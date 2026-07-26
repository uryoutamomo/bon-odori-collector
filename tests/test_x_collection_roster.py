import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import collect


class XCollectionRosterTest(unittest.TestCase):
    """収集名簿のローカル正本化と、スコアtrustedの自動編入。

    背景: 2026-07-26 まで、実際にタイムラインを読む名簿は Notion「Xメンバーリスト」
    だけが供給源で69件に固定されていた。一方スコア台帳では383件が trusted と
    判定済みで、その大半を一度も読みに行っていなかった。
    """

    def _no_other_sources(self, tmpdir):
        return (
            patch.object(collect, "NOTION_TOKEN", None),
            patch.object(
                collect, "X_OFFICIAL_SOURCE_ACCOUNTS_FILE", str(Path(tmpdir) / "no-official.json")
            ),
            patch.object(
                collect, "X_IMPORTANT_INFORMANTS_FILE", str(Path(tmpdir) / "no-informants.json")
            ),
        )

    def test_local_roster_is_read_without_notion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            roster = Path(tmpdir) / "x_collection_roster.json"
            roster.write_text(
                json.dumps({
                    "accounts": [
                        {"handle": "@RosterOne", "manual_status": "優先", "notion_page_id": "p1"},
                        {"handle": "@rostertwo", "manual_status": "休止"},
                    ]
                }, ensure_ascii=False),
                encoding="utf-8",
            )
            patches = self._no_other_sources(tmpdir) + (
                patch.object(collect, "X_COLLECTION_ROSTER_FILE", str(roster)),
            )
            for p in patches:
                p.start()
            try:
                accounts = collect.load_whitelist_accounts(
                    {"auto_trusted_roster": {"enabled": False}}
                )
            finally:
                for p in patches:
                    p.stop()

        by_handle = {row["handle"]: row for row in accounts}
        self.assertEqual(set(by_handle), {"@rosterone", "@rostertwo"})
        self.assertEqual(by_handle["@rosterone"]["manual_status"], "優先")
        self.assertEqual(by_handle["@rosterone"]["page_id"], "p1")
        self.assertEqual(by_handle["@rostertwo"]["manual_status"], "休止")

    def test_trusted_accounts_are_auto_enrolled(self):
        scores = {
            "accounts": {
                "goodone": {
                    "handle": "@goodone", "status": "trusted",
                    "posts_seen": 40, "usefulness_score": 90,
                },
                "thin": {
                    # trusted だが観測数が少なく judgement が薄いので編入しない
                    "handle": "@thin", "status": "trusted",
                    "posts_seen": 1, "usefulness_score": 95,
                },
                "ordinary": {
                    "handle": "@ordinary", "status": "active",
                    "posts_seen": 50, "usefulness_score": 80,
                },
            }
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            patches = self._no_other_sources(tmpdir) + (
                patch.object(collect, "X_COLLECTION_ROSTER_FILE", str(Path(tmpdir) / "none.json")),
                patch.object(collect, "_load_x_account_scores", lambda cfg=None: scores),
            )
            for p in patches:
                p.start()
            try:
                accounts = collect.load_whitelist_accounts({
                    "auto_trusted_roster": {"enabled": True, "min_posts_seen": 3, "min_score": 6.0}
                })
            finally:
                for p in patches:
                    p.stop()

        handles = {row["handle"] for row in accounts}
        self.assertIn("@goodone", handles)
        self.assertNotIn("@thin", handles)
        self.assertNotIn("@ordinary", handles)

    def test_auto_enrollment_respects_max_accounts(self):
        scores = {
            "accounts": {
                f"acct{i}": {
                    "handle": f"@acct{i}", "status": "trusted",
                    "posts_seen": 10, "usefulness_score": 50 + i,
                }
                for i in range(10)
            }
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            patches = self._no_other_sources(tmpdir) + (
                patch.object(collect, "X_COLLECTION_ROSTER_FILE", str(Path(tmpdir) / "none.json")),
                patch.object(collect, "_load_x_account_scores", lambda cfg=None: scores),
            )
            for p in patches:
                p.start()
            try:
                accounts = collect.load_whitelist_accounts({
                    "auto_trusted_roster": {"enabled": True, "max_accounts": 3, "min_posts_seen": 1}
                })
            finally:
                for p in patches:
                    p.stop()

        # スコアの高い順に上限件数だけ編入する
        self.assertEqual(len(accounts), 3)
        self.assertEqual(
            {row["handle"] for row in accounts},
            {"@acct9", "@acct8", "@acct7"},
        )


if __name__ == "__main__":
    unittest.main()
