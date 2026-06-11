import unittest
import json
import os
import tempfile
from unittest.mock import patch

import collect


def title_prop(value):
    return {"title": [{"plain_text": value}]}


def rich_text_prop(value):
    return {"rich_text": [{"plain_text": value}]}


def select_prop(value):
    return {"select": {"name": value}}


def multi_select_prop(*values):
    return {"multi_select": [{"name": value} for value in values]}


def checkbox_prop(value):
    return {"checkbox": value}


class GlossaryRegistrationTest(unittest.TestCase):
    def row(self, confidence="公式確認", aliases="旧名"):
        return {
            "id": "page-1",
            "properties": {
                "正規名称": title_prop("晴海ふ頭公園"),
                "表記ゆれ": rich_text_prop(aliases),
                "確度": select_prop(confidence),
            },
        }

    def test_skips_low_confidence_alias_for_confident_legacy_row(self):
        with (
            patch.object(collect, "NOTION_TOKEN", "token"),
            patch.object(collect, "GLOSSARY_DB_ID", "glossary"),
            patch.object(
                collect,
                "_notion_query_database",
                return_value={"results": [self.row(confidence="公式確認")]},
            ),
            patch.object(collect, "_notion_request") as request,
        ):
            collect.register_glossary_alias(
                "晴盆",
                "晴海ふ頭公園",
                source_url="https://example.com",
                confidence="推察",
            )

        request.assert_not_called()

    def test_keeps_existing_behavior_for_confident_alias(self):
        with (
            patch.object(collect, "NOTION_TOKEN", "token"),
            patch.object(collect, "GLOSSARY_DB_ID", "glossary"),
            patch.object(
                collect,
                "_notion_query_database",
                return_value={"results": [self.row(confidence="公式確認")]},
            ),
            patch.object(collect, "_notion_request") as request,
        ):
            collect.register_glossary_alias(
                "晴海ふ頭",
                "晴海ふ頭公園",
                confidence="複数一致",
            )

        request.assert_called_once()
        payload = request.call_args.args[2]
        aliases = payload["properties"]["表記ゆれ"]["rich_text"][0]["text"]["content"]
        self.assertIn("旧名", aliases)
        self.assertIn("晴海ふ頭", aliases)


class GlossaryV2RuntimeTest(unittest.TestCase):
    def v2_row(
        self,
        term,
        interpretation,
        kind,
        confidence="複数一致",
        state="有効",
        auto_apply=True,
        roles=(),
        song="",
    ):
        return {
            "id": f"page-{term}",
            "properties": {
                "使用語": title_prop(term),
                "解釈": rich_text_prop(interpretation),
                "種別": select_prop(kind),
                "シグナル役割": multi_select_prop(*roles),
                "確度": select_prop(confidence),
                "状態": select_prop(state),
                "自動適用可": checkbox_prop(auto_apply),
                "曲名": rich_text_prop(song),
            },
        }

    def test_loads_only_active_auto_apply_v2_rows(self):
        rows = [
            self.v2_row("晴盆", "晴海ふ頭公園の盆踊り", "イベント別名", roles=("会場ヒント",)),
            self.v2_row("悪口盆踊り", "悪口盆踊り", "除外語", confidence="除外確定", roles=("除外語",)),
            self.v2_row("行ってきた", "行ってきた", "行動語", roles=("参加報告",)),
            self.v2_row("ボラちゃん音頭", "ボラちゃん音頭", "曲名", roles=("曲目ヒント",)),
            self.v2_row("候補語", "候補語", "会場別名", state="候補"),
            self.v2_row("手動待ち", "手動待ち", "会場別名", auto_apply=False),
        ]
        with (
            patch.object(collect, "NOTION_TOKEN", "token"),
            patch.object(collect, "GLOSSARY_V2_DB_ID", "glossary-v2"),
            patch.object(
                collect,
                "_notion_query_database",
                return_value={"results": rows, "has_more": False},
            ),
        ):
            runtime = collect.load_glossary_v2()

        self.assertEqual(runtime["alias_map"]["晴盆"], "晴海ふ頭公園の盆踊り")
        self.assertIn("悪口盆踊り", runtime["exclude_keywords"])
        self.assertIn("行ってきた", runtime["experience_keywords"])
        self.assertIn("ボラちゃん音頭", runtime["song_terms"])
        self.assertNotIn("候補語", runtime["alias_map"])
        self.assertNotIn("手動待ち", runtime["alias_map"])

    def test_x_config_merges_runtime_terms_without_duplicates(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_path = os.path.join(tmpdir, "glossary_runtime.json")
            with open(runtime_path, "w", encoding="utf-8") as f:
                json.dump({
                    "generated_by": "test",
                    "alias_map": {"晴盆": "晴海ふ頭公園の盆踊り"},
                    "exclude_keywords": ["悪口盆踊り", "ライブ"],
                    "experience_keywords": ["行ってきた", "踊った"],
                    "song_terms": ["ボラちゃん音頭"],
                }, f)
            with patch.object(collect, "GLOSSARY_RUNTIME_FILE", runtime_path):
                cfg = collect._apply_glossary_runtime_to_x_config({
                    "exclude_keywords": ["ライブ"],
                    "experience_keywords": ["踊った"],
                })

        self.assertEqual(cfg["exclude_keywords"], ["ライブ", "悪口盆踊り"])
        self.assertEqual(cfg["experience_keywords"], ["踊った", "行ってきた"])
        self.assertEqual(cfg["glossary_runtime"]["alias_count"], 1)
        self.assertEqual(cfg["glossary_runtime"]["song_count"], 1)


if __name__ == "__main__":
    unittest.main()
