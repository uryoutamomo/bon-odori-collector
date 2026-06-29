import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import collect
from x_official_source_accounts import (
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
            ):
                accounts = collect.load_whitelist_accounts()

        self.assertEqual(accounts[0]["handle"], "@localofficial")
        self.assertEqual(accounts[0]["manual_status"], "優先")


if __name__ == "__main__":
    unittest.main()
