import unittest
from datetime import date

from public_export_support.score_event_recurrence import build_rows, enrich_public_events, parse_edition_number, public_status_for_event


TARGET_YEAR = 2026
TODAY = date(2026, 6, 17)


class ScoreEventRecurrenceTest(unittest.TestCase):
    def test_future_2026_confirmed_is_upcoming(self):
        event = {
            "name": "西綾瀬町会 夏祭り盆踊り大会",
            "venue": "五反野コミュニティ公園",
            "area": "足立区",
            "date": "2026-06-20",
            "status": "確認済み",
        }
        result = public_status_for_event(event, target_year=TARGET_YEAR, today=TODAY)
        self.assertEqual(result["public_status"], "upcoming_confirmed")
        self.assertEqual(result["public_category"], "upcoming")
        self.assertEqual(result["public_status_label"], "今後開催")
        self.assertEqual(result["recurrence_score"], 0.95)

    def test_past_2026_confirmed_is_ended_2026(self):
        event = {
            "name": "山王音頭と民踊大会",
            "venue": "山王パークタワー公開空地",
            "area": "千代田区",
            "date": "2026-06-13",
            "status": "終了",
        }
        result = public_status_for_event(event, target_year=TARGET_YEAR, today=TODAY)
        self.assertEqual(result["public_status"], "ended_2026")
        self.assertEqual(result["public_category"], "ended")
        self.assertEqual(result["public_status_label"], "開催終了")

    def test_uses_supplied_today_and_keeps_multi_day_event_upcoming_through_end_date(self):
        event = {
            "name": "二日間盆踊り",
            "venue": "中央公園",
            "area": "中央区",
            "date": "2026-07-20",
            "date_end": "2026-07-21",
            "status": "確認済み",
        }

        on_final_day = public_status_for_event(
            event, target_year=TARGET_YEAR, today=date(2026, 7, 21)
        )
        after_final_day = public_status_for_event(
            event, target_year=TARGET_YEAR, today=date(2026, 7, 22)
        )

        self.assertEqual(on_final_day["public_category"], "upcoming")
        self.assertEqual(after_final_day["public_category"], "ended")

    def test_2025_recurring_event_gets_expected_label(self):
        event = {
            "name": "第70回 恵比寿駅前盆踊り大会",
            "venue": "JR恵比寿駅西口広場",
            "area": "渋谷区",
            "date": "2025-07-25",
            "date_end": "2025-07-26",
            "status": "終了",
            "detail": "公式確認URLあり。第70回、2025-07-25〜2025-07-26、納涼盆踊り大会。",
        }
        result = public_status_for_event(event, target_year=TARGET_YEAR, today=TODAY)
        self.assertEqual(result["public_status"], "expected_high")
        self.assertEqual(result["public_category"], "recurring_last_year")
        self.assertEqual(result["public_status_label"], "昨年開催")
        self.assertEqual(result["edition_number"], 70)
        self.assertIn("edition_number:70", result["reasons"])
        self.assertGreaterEqual(result["recurrence_score"], 0.75)

    def test_2025_one_shot_style_event_is_demoted(self):
        event = {
            "name": "SHIBUYA MIYASHITA PARK BON DANCE 2025",
            "venue": "宮下公園",
            "area": "渋谷区",
            "date": "2025-09-27",
            "date_end": "2025-09-28",
            "status": "終了",
            "detail": "公式確認URLあり。Festival / BON DANCE / シブヤエンタメ祭系の2025企画。",
        }
        result = public_status_for_event(event, target_year=TARGET_YEAR, today=TODAY)
        self.assertEqual(result["public_status"], "expected_low")
        self.assertEqual(result["public_category"], "recurring_last_year")
        self.assertIn("イベント名に2025明記", result["cautions"])

    def test_no_date_event_is_date_unknown(self):
        event = {
            "name": "名称未確認の盆踊り",
            "venue": "公園",
            "area": "世田谷区",
            "months": [7],
            "status": "未確認",
        }
        result = public_status_for_event(event, target_year=TARGET_YEAR, today=TODAY)
        self.assertEqual(result["public_status"], "date_unknown")
        self.assertEqual(result["public_category"], "date_unknown")
        self.assertEqual(result["public_status_label"], "日程未確認")

    def test_enrich_public_events_adds_public_fields(self):
        events = [
            {
                "name": "西綾瀬町会 夏祭り盆踊り大会",
                "venue": "五反野コミュニティ公園",
                "area": "足立区",
                "date": "2026-06-20",
                "status": "確認済み",
            }
        ]
        rows = build_rows(events, target_year=TARGET_YEAR, today=TODAY)
        enriched = enrich_public_events(events, rows)
        self.assertEqual(enriched[0]["public_status"], "upcoming_confirmed")
        self.assertEqual(enriched[0]["public_category"], "upcoming")
        self.assertIn("public_note", enriched[0])

    def test_2027_context_uses_2026_as_previous_year(self):
        event = {
            "name": "第71回 恵比寿駅前盆踊り大会",
            "venue": "JR恵比寿駅西口広場",
            "area": "渋谷区",
            "date": "2026-07-24",
            "status": "終了",
            "detail": "2026年に公式開催。恒例の盆踊り大会。",
        }

        result = public_status_for_event(
            event, target_year=2027, today=date(2027, 6, 17)
        )

        self.assertEqual(result["public_category"], "recurring_last_year")
        self.assertEqual(result["last_seen_year"], 2026)
        self.assertIn("held_2026", result["reasons"])

    def test_parse_edition_number_handles_fullwidth_digits_and_ordinal(self):
        self.assertEqual(parse_edition_number("第３４回ふるさと千川まつり"), 34)
        self.assertEqual(parse_edition_number("盆踊り 12回目"), 12)


if __name__ == "__main__":
    unittest.main()
