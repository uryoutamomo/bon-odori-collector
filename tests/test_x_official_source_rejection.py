"""人が「このアカウントは公式ソースとして対象外」と決めたことを覚えておく検査。

覚えていないと、同じアカウントが翌日もまた確認待ちに現れる。人が決めたことを
機械が毎日巻き戻す構図で、ゐの市のときと同じ問題になる。
"""

import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import collect
import review_x_official_sources as review
from collection_support.x_official_source_accounts import load_official_source_accounts
from collection_support.x_source_registry import REJECTED, tier_for_account


EVENTS = [{"series_id": "s1", "series_name": "鉄砲洲納涼盆踊り", "venue": "鉄砲洲公園",
           "ward": "中央区", "latest_occurrence_end": str(date.today() - timedelta(days=400))}]
# 会場が1回だけ当たった準公式（議員）。possible 止まりなので pending_review になる。
# 実測では、盆踊りに触れる政治家の投稿の大半が地域あいさつだった。
VOICES = [{"source": "x", "account": "@giin", "name": "山田太郎 区議会議員",
           "text": "中央区の鉄砲洲公園で盆踊りがありました", "url": "https://x.com/giin/status/1"}]


def refresh(tmp: str, accounts: list[dict], voices=VOICES) -> list[dict]:
    path = Path(tmp) / "x_official_source_accounts.json"
    path.write_text(json.dumps({"accounts": accounts}, ensure_ascii=False), encoding="utf-8")
    with patch.object(collect, "X_OFFICIAL_SOURCE_ACCOUNTS_FILE", str(path)), \
         patch.object(collect, "load_events_from_master_db", lambda db_path: EVENTS):
        collect._refresh_official_source_registry(voices)
    return json.loads(path.read_text(encoding="utf-8"))["accounts"]


class RejectionIsRememberedTest(unittest.TestCase):
    def test_rejection_holds_even_without_a_decided_by_marker(self):
        """印を要求すると、手で書いた行が降格して同じ問題が戻る。"""
        self.assertEqual(tier_for_account({"tier": REJECTED}), REJECTED)
        self.assertEqual(
            tier_for_account({"tier": REJECTED, "linked_events": [{"confidence": "confirmed"},
                                                                  {"confidence": "confirmed"}]}),
            REJECTED,
        )

    def test_daily_refresh_does_not_put_a_rejected_account_back_in_the_queue(self):
        # decided_by をわざと落としてある。台帳は手で編集できるので、印が無い
        # 行でも判断が消えないことを確かめる必要がある（印を必須にしたせいで
        # @iri2choukai が降格した前例がある）。
        rejected = [{
            "handle": "@giin", "name": "山田太郎 区議会議員", "tier": REJECTED,
            "decided_at": "2026-08-13",
            "decision_reason": "地域あいさつばかりで行事の一次情報を出していない",
        }]
        with tempfile.TemporaryDirectory() as tmp:
            saved = refresh(tmp, rejected)
        row = [r for r in saved if r["handle"] == "@giin"][0]
        self.assertEqual(row["tier"], REJECTED)
        self.assertEqual(row["decision_reason"], "地域あいさつばかりで行事の一次情報を出していない")
        self.assertNotEqual(row.get("decided_by"), "machine")

    def test_rejection_survives_on_a_row_the_machine_had_created(self):
        """機械が作った行の tier だけを人が書き換えた場合も巻き戻さない。

        既存の保護は `decided_by` が machine 以外であることを条件にしているので、
        この形の行だけは日次更新に上書きされて確認待ちへ戻ってしまう。
        """
        rejected = [{
            "handle": "@giin", "name": "山田太郎 区議会議員", "tier": REJECTED,
            "decided_by": "machine",
            "decision_reason": "地域あいさつばかりで行事の一次情報を出していない",
        }]
        with tempfile.TemporaryDirectory() as tmp:
            saved = refresh(tmp, rejected)
        self.assertEqual([r for r in saved if r["handle"] == "@giin"][0]["tier"], REJECTED)

    def test_rejected_account_is_not_read_and_does_not_shadow_the_bonodorer_roster(self):
        """公式として対象外にしても、盆踊ラーとして読む判断までは奪わない。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "registry.json"
            path.write_text(json.dumps({"accounts": [
                {"handle": "@giin", "tier": REJECTED, "decided_by": "user"},
                {"handle": "@iri2choukai", "tier": "active", "decided_by": "user"},
            ]}, ensure_ascii=False), encoding="utf-8")
            loaded = load_official_source_accounts(path)
        handles = [row["handle"] for row in loaded]
        # 休止として返すと、この一覧は盆踊ラー名簿より先に組まれるため
        # 同じハンドルを覆い隠して直読みから消してしまう。
        self.assertEqual(handles, ["@iri2choukai"])

    def test_pending_rows_keep_the_date_they_first_needed_a_person(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = refresh(tmp, [])
            row = [r for r in first if r["handle"] == "@giin"][0]
            self.assertEqual(row["tier"], "pending_review")
            self.assertTrue(row.get("pending_since"))

            aged = dict(row, pending_since="2026-07-01")
            again = refresh(tmp, [aged])
        self.assertEqual([r for r in again if r["handle"] == "@giin"][0]["pending_since"],
                         "2026-07-01")


class ReviewCommandTest(unittest.TestCase):
    def _registry(self, tmp: str) -> Path:
        path = Path(tmp) / "registry.json"
        path.write_text(json.dumps({"accounts": [
            {"handle": "@giin", "name": "山田太郎 区議会議員", "tier": "pending_review",
             "pending_since": "2026-08-13", "linked_events": [
                 {"series_id": "s1", "series_name": "鉄砲洲納涼盆踊り",
                  "ward": "中央区", "confidence": "possible"}]},
        ]}, ensure_ascii=False), encoding="utf-8")
        return path

    def test_reject_records_who_decided_and_why(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._registry(tmp)
            review.main(["--registry", str(path), "reject", "@giin",
                         "--reason", "地域あいさつばかりで一次情報を出していない"])
            row = json.loads(path.read_text(encoding="utf-8"))["accounts"][0]
        self.assertEqual(row["tier"], REJECTED)
        self.assertEqual(row["decided_by"], "user")
        self.assertEqual(row["decision_reason"], "地域あいさつばかりで一次情報を出していない")
        # 判断が済んだので、確認待ちの日数は消える。
        self.assertNotIn("pending_since", row)

    def test_reject_requires_a_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._registry(tmp)
            with self.assertRaises(SystemExit):
                review.main(["--registry", str(path), "reject", "@giin"])

    def test_accept_promotes_and_reopen_hands_it_back_to_the_machine(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._registry(tmp)
            review.main(["--registry", str(path), "accept", "@giin", "--reason", "毎年告知している"])
            row = json.loads(path.read_text(encoding="utf-8"))["accounts"][0]
            self.assertEqual(row["tier"], "active")
            self.assertEqual(row["decided_by"], "user")

            review.main(["--registry", str(path), "reopen", "@giin"])
            row = json.loads(path.read_text(encoding="utf-8"))["accounts"][0]
        self.assertEqual(row["tier"], "pending_review")
        self.assertNotIn("decided_by", row)
        self.assertNotIn("decision_reason", row)

    def test_unknown_handle_stops_instead_of_creating_a_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self._registry(tmp)
            with self.assertRaises(SystemExit):
                review.main(["--registry", str(path), "reject", "@nobody", "--reason", "x"])
            self.assertEqual(len(json.loads(path.read_text(encoding="utf-8"))["accounts"]), 1)


if __name__ == "__main__":
    unittest.main()
