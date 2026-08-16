"""公式台帳が、盆踊ラー名簿の選んだ人を黙らせないことの検査。

直読み名簿は 公式台帳 → 重要情報提供者 → 収集名簿 → 2軸名簿 の順に足してから
ハンドルで重複排除する。台帳の行を「休止」として先に置くと、あとから来る
2軸名簿の同じハンドルが捨てられ、読まれなくなる。

2026-08-13 のローカル実測（voices 10,630件・台帳321件・2軸名簿233人）で、
実際に25人がこれで消えていた。内訳は unlinked 23人・pending_review 2人で、
その中には神田観光協会（@kandakankou）のような、検索でしか拾えていない
一次情報源も含まれていた。
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import collect


SCORES = {"accounts": {
    "kandakankou": {"handle": "@kandakankou", "posts_seen": 5, "posts_with_text": 5,
                    "announce_score": 20, "record_score": 20, "bon23_count": 3,
                    "distinct_post_days": 3},
}}


def whitelist_with_ledger(ledger_rows):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "x_official_source_accounts.json"
        path.write_text(json.dumps({"accounts": ledger_rows}, ensure_ascii=False), encoding="utf-8")
        with patch.object(collect, "X_OFFICIAL_SOURCE_ACCOUNTS_FILE", str(path)), \
             patch.object(collect, "_load_x_account_scores", lambda cfg=None: SCORES), \
             patch.object(collect, "_load_x_roster_exclusions", lambda: {}), \
             patch.object(collect, "_load_important_informants", lambda: []), \
             patch.object(collect, "_load_collection_roster", lambda: []), \
             patch.object(collect, "_load_notion_member_list", lambda: []):
            accounts = collect.load_whitelist_accounts({"auto_trusted_roster": {"per_axis_accounts": 5}})
    return {collect._norm_handle(row["handle"]): row for row in accounts}


class LedgerDoesNotMuteRosterTest(unittest.TestCase):
    def test_curated_dormant_account_is_not_auto_enrolled_before_wake(self):
        rows = whitelist_with_ledger([
            {"handle": "@kandakankou", "tier": "dormant", "decided_by": "user",
             "wake_after": "2027-06-01", "linked_events": []},
        ])
        self.assertNotIn("kandakankou", rows)

    def test_rejected_account_is_not_auto_enrolled(self):
        rows = whitelist_with_ledger([
            {"handle": "@kandakankou", "tier": "rejected", "decided_by": "user",
             "linked_events": []},
        ])
        self.assertNotIn("kandakankou", rows)

    def test_unlinked_ledger_row_does_not_mute_a_roster_account(self):
        """紐付けが取れていないことは「読まない」理由にはならない。"""
        rows = whitelist_with_ledger([
            {"handle": "@kandakankou", "name": "神田観光協会", "tier": "unlinked",
             "decided_by": "machine", "linked_events": []},
        ])
        self.assertNotEqual(rows["kandakankou"].get("manual_status"), "休止")

    def test_dormant_ledger_row_does_not_mute_a_roster_account(self):
        rows = whitelist_with_ledger([
            {"handle": "@kandakankou", "name": "神田観光協会", "tier": "dormant",
             "decided_by": "machine", "linked_events": []},
        ])
        self.assertNotEqual(rows["kandakankou"].get("manual_status"), "休止")

    def test_active_ledger_row_is_still_supplied_as_a_priority_source(self):
        rows = whitelist_with_ledger([
            {"handle": "@iri2choukai", "name": "入船二丁目町会", "tier": "active",
             "decided_by": "user"},
        ])
        self.assertEqual(rows["iri2choukai"]["manual_status"], "優先")

    def test_probe_rechecks_machine_muted_accounts_but_never_a_persons_choice(self):
        """休止のためし読みは、点数で黙らせた相手だけを対象にする。

        台帳の行が休止プールを数百件に膨らませていたあいだは、人が休止に
        した相手まで順番が回ってこなかった。プールが小さくなると毎回当たる。
        """
        accounts = [
            {"handle": "@byhand", "manual_status": "休止"},
            {"handle": "@bylowscore", "manual_status": ""},
        ]
        scores = {"accounts": {
            "byhand": {"handle": "@byhand", "usefulness_score": 90},
            "bylowscore": {"handle": "@bylowscore", "usefulness_score": 1, "status": "muted"},
        }}
        with patch.object(collect, "_load_x_account_scores", lambda cfg=None: scores):
            ranked = collect._rank_whitelist_accounts(
                accounts, {"account_ranking": {"probe_muted_accounts_per_run": 5}}
            )
        handles = {collect._norm_handle(row["handle"]) for row in ranked}
        self.assertIn("bylowscore", handles)
        self.assertNotIn("byhand", handles)

    def test_a_hand_written_row_without_a_tier_keeps_its_own_status(self):
        """v1 の行は tier を持たない。人が書いた休止はそのまま尊重する。"""
        rows = whitelist_with_ledger([
            {"handle": "@kandakankou", "name": "神田観光協会", "manual_status": "休止"},
        ])
        self.assertEqual(rows["kandakankou"]["manual_status"], "休止")


if __name__ == "__main__":
    unittest.main()
