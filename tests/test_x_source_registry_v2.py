import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

import collect
from collection_support.x_source_registry import link_voice_to_events, registry_candidates, tier_for_account
from unittest.mock import patch


class SourceRegistryV2Test(unittest.TestCase):
    def test_two_axes_not_saturated_usefulness_or_handle_order(self):
        scores = {"accounts": {
            "aaa": {"handle": "@aaa", "posts_seen": 3, "usefulness_score": 100, "announce_score": 1, "record_score": 1, "bon23_count": 1, "distinct_post_days": 1},
            "zzz": {"handle": "@zzz", "posts_seen": 3, "usefulness_score": 100, "announce_score": 9, "record_score": 8, "bon23_count": 2, "distinct_post_days": 2},
        }}
        with patch.object(collect, "_load_x_account_scores", lambda cfg=None: scores), patch.object(collect, "_load_x_roster_exclusions", lambda: {}):
            rows = collect._auto_trusted_roster_accounts({"auto_trusted_roster": {"per_axis_accounts": 1}})
        self.assertEqual([r["handle"] for r in rows], ["@zzz"])

    def test_manual_and_exclusion_and_bot_rules(self):
        scores = {"accounts": {
            "manual": {"handle":"@manual", "posts_seen":3, "announce_score":0, "record_score":0},
            "excluded": {"handle":"@excluded", "posts_seen":3, "announce_score":99, "record_score":99},
            "bot": {"handle":"@bot", "posts_seen":3, "announce_score":98, "record_score":98, "is_area_bot":True},
            "outside": {"handle":"@outside", "posts_seen":3, "announce_score":97, "record_score":1, "outside_ratio":1},
        }}
        with patch.object(collect, "_load_x_account_scores", lambda cfg=None: scores), patch.object(collect, "_load_x_roster_exclusions", lambda: {"excluded": {}}):
            rows = collect._auto_trusted_roster_accounts({"auto_trusted_roster": {"per_axis_accounts": 2}})
        self.assertEqual(set(r["handle"] for r in rows), {"@outside", "@manual"})

    def test_rejects_official_word_without_link_and_outside_same_name(self):
        events = [{"series_id":"s1", "series_name":"浜町盆踊り", "venue":"浜町公園", "ward":"中央区"}]
        self.assertEqual(registry_candidates([{"account":"@shop", "name":"シモジマ【公式】", "text":"新商品です"}], events), [])
        self.assertEqual(link_voice_to_events({"text":"川崎市の浜町公園で盆踊り"}, events), [])
        self.assertEqual(link_voice_to_events({"text":"札幌の中島公園で盆踊り"}, [{"venue":"中島公園", "ward":"中野区"}]), [])

    def test_venue_only_link_and_lifecycle(self):
        events = [{"series_id":"s1", "series_name":"鉄砲洲", "venue":"鉄砲洲公園", "ward":"中央区"}]
        rows = registry_candidates([{"account":"@town", "name":"鉄砲洲町会", "text":"中央区 鉄砲洲公園で盆踊り", "url":"https://x.com/town/status/1"}], events)
        self.assertEqual(rows[0]["tier"], "pending_review")
        self.assertEqual(tier_for_account({"linked_events":[{"confidence":"confirmed", "latest_occurrence_end":str(date.today()-timedelta(days=15))}]}), "dormant")
        self.assertEqual(tier_for_account({"linked_events":[{"confidence":"confirmed"}, {"confidence":"probable"}]}), "active")
        self.assertEqual(tier_for_account({"tier":"dormant", "decided_by":"user", "linked_events":[{}, {}]}), "dormant")

    def test_next_year_wake_is_derived_without_prediction(self):
        prior = date.today().replace(year=date.today().year - 1)
        # sixty days before this year's same-day recurrence is already due.
        self.assertEqual(tier_for_account({"linked_events":[{"confidence":"confirmed", "latest_occurrence_end":str(prior)}]}), "active")


    def test_daily_refresh_never_demotes_a_curated_row(self):
        """検査17。人が手で登録した行を日次更新が降格させない。

        v1 の台帳には decided_by が無い。それを「機械のもの」と見なすと、
        鉄砲洲納涼盆踊りの公式（@iri2choukai）が dormant へ落ち、
        load_official_source_accounts() が manual_status を「休止」に
        書き換えるため、直読み名簿から静かに消える。実際に一度起きた。
        """
        curated = {"accounts": [{
            "handle": "@iri2choukai", "name": "入船二丁目町会", "tier": "active",
            "manual_status": "優先", "related_event_keywords": ["鉄砲洲納涼盆踊り"],
            "notes": "人が確認して登録した行",
        }]}
        events = [{"series_id": "s1", "series_name": "鉄砲洲納涼盆踊り",
                   "venue": "鉄砲洲公園", "ward": "中央区",
                   "latest_occurrence_end": str(date.today() - timedelta(days=400))}]
        # 同じアカウントを機械側も候補として拾う状況を作る（紐付け1件・過去開催）
        voices = [{"source": "x", "account": "@iri2choukai", "name": "入船二丁目町会",
                   "text": "鉄砲洲公園で盆踊りを開催しました", "url": "https://x.com/iri2choukai/status/1"}]

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x_official_source_accounts.json"
            path.write_text(json.dumps(curated, ensure_ascii=False), encoding="utf-8")
            with patch.object(collect, "X_OFFICIAL_SOURCE_ACCOUNTS_FILE", str(path)), \
                 patch.object(collect, "load_events_from_master_db", lambda db_path: events):
                collect._refresh_official_source_registry(voices)
            saved = json.loads(path.read_text(encoding="utf-8"))["accounts"]

        row = [r for r in saved if r["handle"] == "@iri2choukai"][0]
        self.assertEqual(row["tier"], "active")
        self.assertEqual(row["manual_status"], "優先")
        self.assertEqual(row["related_event_keywords"], ["鉄砲洲納涼盆踊り"])
        self.assertNotEqual(row.get("decided_by"), "machine")


if __name__ == "__main__":
    unittest.main()
