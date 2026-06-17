import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

from proactive_search import (
    build_queries,
    build_report,
    extract_dates,
    extract_links,
    load_targets,
    parse_months,
    select_due_targets,
    select_targets_for_run,
    target_key,
    update_state_from_report,
)
from sync_venue_master import _prop


class ProactiveSearchTest(unittest.TestCase):
    def test_parse_months_accepts_notion_shapes(self):
        self.assertEqual(parse_months(6), [6])
        self.assertEqual(parse_months("6月、7月"), [6, 7])
        self.assertEqual(parse_months(["6月", "7"]), [6, 7])

    def test_notion_month_property_shapes_are_exported(self):
        self.assertEqual(_prop({
            "例年開催月": {"type": "number", "number": 6}
        }, "例年開催月"), 6)
        self.assertEqual(_prop({
            "例年開催月": {
                "type": "multi_select",
                "multi_select": [{"name": "6月"}, {"name": "7月"}],
            }
        }, "例年開催月"), ["6月", "7月"])

    def test_config_overrides_venue_master(self):
        venue_master = [{"venue": "山王日枝神社", "month": None}]
        config = {
            "events": [{
                "venue": "山王日枝神社",
                "event_name": "山王音頭と民踊大会",
                "months": [6],
                "aliases": ["日枝神社"],
            }]
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "events.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False)
            targets, _ = load_targets(venue_master, path)
        self.assertEqual(targets[0]["months"], [6])
        self.assertIn("日枝神社", targets[0]["aliases"])

    def test_due_targets_include_next_month(self):
        targets = [
            {"venue": "六月", "months": [6]},
            {"venue": "七月", "months": [7]},
            {"venue": "八月", "months": [8]},
        ]
        now = datetime(2026, 6, 7, tzinfo=timezone.utc)
        selected = select_due_targets(targets, now=now, lead_months=1)
        self.assertEqual([item["venue"] for item in selected], ["六月", "七月"])

    def test_targets_rotate_by_unchecked_and_oldest_unconfirmed(self):
        targets = [
            {"venue": "確認済み", "event_name": "確認済み", "months": [6]},
            {"venue": "未確認古い", "event_name": "未確認古い", "months": [6]},
            {"venue": "未確認新しい", "event_name": "未確認新しい", "months": [6]},
            {"venue": "未チェック", "event_name": "未チェック", "months": [6]},
        ]
        state = {"targets": {
            target_key(targets[0]): {
                "last_status": "confirmed",
                "last_checked_at": "2026-06-10T00:00:00+00:00",
            },
            target_key(targets[1]): {
                "last_status": "unconfirmed",
                "last_checked_at": "2026-06-01T00:00:00+00:00",
            },
            target_key(targets[2]): {
                "last_status": "unconfirmed",
                "last_checked_at": "2026-06-12T00:00:00+00:00",
            },
        }}

        selected = select_targets_for_run(targets, state, limit=3)

        self.assertEqual(
            [item["venue"] for item in selected],
            ["未チェック", "未確認古い", "未確認新しい"],
        )

    def test_updates_proactive_state_from_report(self):
        targets = [{
            "venue": "山王日枝神社",
            "event_name": "山王音頭と民踊大会",
            "months": [6],
        }]
        report = [{
            "venue": "山王日枝神社",
            "event_name": "山王音頭と民踊大会",
            "status": "confirmed",
        }]
        state = update_state_from_report(
            {},
            targets,
            report,
            now=datetime(2026, 6, 13, tzinfo=timezone.utc),
        )
        record = state["targets"][target_key(targets[0])]

        self.assertEqual(record["last_status"], "confirmed")
        self.assertEqual(record["checked_count"], 1)
        self.assertEqual(record["confirmed_count"], 1)
        self.assertEqual(record["last_checked_at"], "2026-06-13T00:00:00+00:00")

    def test_query_contains_alias_and_year(self):
        query = build_queries({
            "venue": "山王日枝神社",
            "event_name": "山王音頭と民踊大会",
            "aliases": ["日枝神社"],
        }, 2026)
        self.assertIn('"日枝神社"', query["news"])
        self.assertIn("2026", query["x"])

    def test_report_marks_current_year_confirmation(self):
        target = {
            "venue": "山王日枝神社",
            "event_name": "山王音頭と民踊大会",
            "aliases": ["日枝神社"],
            "confirmation_terms": ["山王音頭と民踊大会", "民踊大会"],
            "months": [6],
        }
        items = [{
            "source": "news_proactive",
            "title": "日枝神社 山王音頭と民踊大会を2026年6月に開催",
            "url": "https://example.com/event",
        }]
        report = build_report([target], items, 2026)
        self.assertEqual(report[0]["status"], "confirmed")

    def test_report_keeps_old_year_unconfirmed(self):
        target = {
            "venue": "山王日枝神社",
            "event_name": "山王音頭と民踊大会",
            "aliases": ["日枝神社"],
            "confirmation_terms": ["山王音頭と民踊大会", "民踊大会"],
            "months": [6],
        }
        items = [{
            "title": "日枝神社 山王音頭と民踊大会を2025年6月に開催",
            "url": "https://example.com/old",
        }]
        report = build_report([target], items, 2026)
        self.assertEqual(report[0]["status"], "unconfirmed")

    def test_report_uses_publication_year(self):
        target = {
            "venue": "山王日枝神社",
            "event_name": "山王音頭と民踊大会",
            "aliases": ["日枝神社"],
            "confirmation_terms": ["山王音頭と民踊大会", "民踊大会"],
            "months": [6],
        }
        items = [{
            "text": "6/14は日枝神社で山王音頭と民踊大会を開催",
            "date": "2026-06-07T01:00:00+00:00",
            "url": "https://x.com/example/status/1",
        }]
        report = build_report([target], items, 2026)
        self.assertEqual(report[0]["status"], "confirmed")

    def test_general_festival_news_does_not_confirm_specific_dance(self):
        target = {
            "venue": "山王日枝神社",
            "event_name": "山王音頭と民踊大会",
            "aliases": ["日枝神社", "山王祭"],
            "confirmation_terms": ["山王音頭と民踊大会", "民踊大会"],
            "months": [6],
        }
        items = [{
            "title": "2026年 日枝神社の山王祭を6月7日から開催",
            "url": "https://example.com/sanno",
        }]
        report = build_report([target], items, 2026)
        self.assertEqual(report[0]["status"], "unconfirmed")

    def test_report_accepts_odori_event_without_bon_word(self):
        target = {
            "venue": "秩父宮ラグビー場駐車場",
            "event_name": "郡上おどり in 青山",
            "confirmation_terms": ["郡上おどり"],
            "months": [6],
        }
        items = [{
            "title": "郡上おどり2026開催決定!!",
            "text": "郡上おどりの日程がきまりました。6月26日（金）17:00～20:30",
            "url": "https://aoyama-gaienmae.or.jp/news/20260326/",
        }]

        report = build_report([target], items, 2026)

        self.assertEqual(report[0]["status"], "confirmed")

    def test_extract_links_normalizes_same_site_article_urls(self):
        raw = '<a href="/news/20260326/">郡上おどり2026開催決定!!</a>'

        links = extract_links(raw, "https://aoyama-gaienmae.or.jp/news/")

        self.assertEqual(links, [{
            "url": "https://aoyama-gaienmae.or.jp/news/20260326/",
            "label": "郡上おどり2026開催決定!!",
        }])

    def test_extract_dates_from_japanese_text(self):
        text = "6月26日（金）17:00～20:30 6月27日（土）17:00～20:00"

        self.assertEqual(extract_dates(text, 2026), ["2026-06-26", "2026-06-27"])


if __name__ == "__main__":
    unittest.main()
