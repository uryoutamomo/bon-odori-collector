import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import collect
from collection_support.x_official_source_accounts import (
    handle_from_social_url,
    is_official_social_url,
    load_official_source_accounts,
)


class XOfficialSourceAccountsTest(unittest.TestCase):
    def test_loads_and_normalizes_registry(self):
        accounts = load_official_source_accounts()

        iri2 = [row for row in accounts if row["handle"] == "@iri2choukai"][0]

        self.assertEqual(iri2["manual_status"], "優先")
        self.assertEqual(iri2["source_type"], "official_or_organizer_social")

    def test_matches_registered_social_url(self):
        self.assertEqual(
            handle_from_social_url("https://x.com/iri2choukai/status/2069959259895496872"),
            "iri2choukai",
        )
        self.assertTrue(
            is_official_social_url("https://x.com/iri2choukai/status/2069959259895496872")
        )
        self.assertFalse(is_official_social_url("https://x.com/example/status/1"))

    def test_collect_loads_local_accounts_without_notion_token(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = Path(tmpdir) / "x_official_source_accounts.json"
            registry.write_text(
                json.dumps(
                    {
                        "accounts": [
                            {
                                "handle": "@LocalOfficial",
                                "name": "Local Official",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with patch.object(collect, "NOTION_TOKEN", None), patch.object(
                collect, "X_OFFICIAL_SOURCE_ACCOUNTS_FILE", str(registry)
            ), patch.object(
                collect, "X_IMPORTANT_INFORMANTS_FILE", str(Path(tmpdir) / "missing-informants.json")
            ), patch.object(
                collect, "X_COLLECTION_ROSTER_FILE", str(Path(tmpdir) / "missing-roster.json")
            ):
                accounts = collect.load_whitelist_accounts(
                    {"auto_trusted_roster": {"enabled": False}}
                )

        self.assertEqual(accounts[0]["handle"], "@localofficial")
        self.assertEqual(accounts[0]["manual_status"], "優先")

    def test_collect_loads_current_important_informants_without_notion_token(self):
        # 他の供給源（収集名簿・スコア自動編入）を切り、重要情報提供者台帳だけが
        # Notionトークン無しでも読めることを確認する。
        with patch.object(collect, "NOTION_TOKEN", None), patch.object(
            collect, "X_OFFICIAL_SOURCE_ACCOUNTS_FILE", "missing-official-accounts.json"
        ), patch.object(
            collect, "X_COLLECTION_ROSTER_FILE", "missing-collection-roster.json"
        ):
            accounts = collect.load_whitelist_accounts({"auto_trusted_roster": {"enabled": False}})

        by_handle = {row["handle"]: row for row in accounts}
        self.assertEqual(
            set(by_handle),
            {"@natsutr_bon", "@gpveqead9u10257"},
        )
        self.assertEqual(by_handle["@natsutr_bon"]["manual_status"], "優先")
        self.assertEqual(by_handle["@gpveqead9u10257"]["source_type"], "important_informant")

    def test_important_informants_are_annotated_without_inflating_observed_score(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            informants = Path(tmpdir) / "x_important_informants.json"
            informants.write_text(
                json.dumps(
                    {
                        "accounts": [
                            {
                                "handle": "@thin_history",
                                "manual_status": "優先",
                                "source_type": "important_informant",
                                "collection_enabled": True,
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with patch.object(collect, "X_IMPORTANT_INFORMANTS_FILE", str(informants)):
                scores = collect._build_x_account_scores(
                    [
                        {
                            "source": "x_whitelist",
                            "account": "@thin_history",
                            "text": "盆踊りに行ってきた。写真も楽しかった。",
                            "date": collect.datetime.now(collect.timezone.utc).isoformat(),
                        }
                    ],
                    {},
                )

        row = scores["accounts"]["thin_history"]
        self.assertEqual(row["manual_status"], "優先")
        self.assertEqual(row["source_type"], "important_informant")
        # A single ordinary post must not be pushed into "trusted"/"S" by the
        # manual annotation: the observed score/status/rank stay honest so
        # they remain trustworthy once persisted into the evidence RDB.
        # trusted_min_values defaults to 3, so one post can't cross it.
        self.assertNotEqual(row["status"], "trusted")
        self.assertNotEqual(row["usefulness_rank"], "S")

    def test_annotate_important_informants_ignores_accounts_with_no_observed_posts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            informants = Path(tmpdir) / "x_important_informants.json"
            informants.write_text(
                json.dumps(
                    {
                        "accounts": [
                            {"handle": "@never_posted", "collection_enabled": True}
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with patch.object(collect, "X_IMPORTANT_INFORMANTS_FILE", str(informants)):
                scores = collect._build_x_account_scores([], {})

        self.assertNotIn("never_posted", scores["accounts"])


if __name__ == "__main__":
    unittest.main()
