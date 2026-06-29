import unittest
from datetime import date

from apply_public_historical_references import apply_historical_references


class ApplyPublicHistoricalReferencesTest(unittest.TestCase):
    def test_applies_historical_reference_to_recurring_event(self):
        events = [{
            "name": "神田明神納涼祭り アニソン盆踊り",
            "venue": "神田明神境内",
            "public_category": "recurring_last_year",
            "public_status": "expected_medium",
            "public_status_label": "昨年開催",
            "recurrence_label": "昨年開催・継続性 中",
            "recurrence_score": 0.62,
            "recurrence_reasons": ["recurring_word:神社"],
            "recurrence_cautions": [],
            "last_seen_year": 2025,
            "last_seen_dates": ["2025-08-08"],
            "date": "2025-08-08",
        }]

        result = apply_historical_references(events)

        self.assertEqual(result["report"]["target_count"], 1)
        self.assertEqual(result["report"]["applied_count"], 1)
        self.assertEqual(result["events"][0]["historical_display_tier"], "historical_slide")
        self.assertEqual(result["events"][0]["historical_reference_confidence"], "medium")
        self.assertEqual(result["events"][0]["historical_last_seen_year"], 2025)
        self.assertEqual(result["events"][0]["display_tier"], "historical_slide")
        self.assertEqual(result["events"][0]["predicted_date"], "2026-08-14")
        self.assertEqual(result["report"]["slide_count"], 1)

    def test_preserves_rule_prediction_display_tier(self):
        events = [{
            "name": "丸の内de盆踊り",
            "venue": "行幸通り",
            "public_category": "recurring_last_year",
            "public_status": "expected_medium",
            "recurrence_score": 0.6,
            "last_seen_year": 2025,
            "last_seen_dates": ["2025-07-25", "2025-07-26"],
            "date_prediction": {"date": "2026-07-31"},
            "display_tier": "rule_predicted",
            "predicted_date": "2026-07-31",
        }]

        result = apply_historical_references(events)

        self.assertEqual(result["report"]["with_rule_prediction_count"], 1)
        self.assertEqual(result["events"][0]["display_tier"], "rule_predicted")
        self.assertEqual(result["events"][0]["historical_reference"]["has_rule_prediction"], True)
        self.assertEqual(result["report"]["slide_count"], 0)

    def test_fixed_date_rule_overrides_weekday_slide(self):
        events = [{
            "name": "花園神社 盆踊り",
            "venue": "花園神社",
            "public_category": "recurring_last_year",
            "public_status": "expected_medium",
            "recurrence_score": 0.55,
            "last_seen_year": 2025,
            "last_seen_dates": ["2025-08-01", "2025-08-02"],
            "date": "2025-08-01",
            "date_end": "2025-08-02",
        }]
        fixed_rules = {
            ("花園神社盆踊り", "花園神社"): {
                "month": 8,
                "day": 1,
                "end_month": 8,
                "end_day": 2,
                "basis": "YOKOSO新宿の告知に「毎年8月1日・2日」と明記",
            }
        }

        result = apply_historical_references(events, fixed_date_rules=fixed_rules)

        self.assertEqual(result["events"][0]["predicted_date"], "2026-08-01")
        self.assertEqual(result["events"][0]["predicted_date_end"], "2026-08-02")
        self.assertEqual(result["events"][0]["historical_slide_method"], "fixed_date")
        self.assertEqual(result["report"]["fixed_date_rule_count"], 1)

    def test_embedded_fixed_date_rule_overrides_external_rule(self):
        events = [{
            "name": "山王音頭と民踊大会",
            "venue": "山王パークタワー公開空地",
            "public_category": "recurring_last_year",
            "public_status": "expected_medium",
            "recurrence_score": 0.58,
            "last_seen_year": 2025,
            "last_seen_dates": ["2025-06-13", "2025-06-15"],
            "date": "2025-06-13",
            "date_end": "2025-06-15",
            "fixed_date_rule": {
                "month": 6,
                "day": 13,
                "end_month": 6,
                "end_day": 15,
                "basis": "イベントDBの固定日カラムに記録",
            },
        }]
        stale_external_rules = {
            ("山王音頭と民踊大会", "山王パークタワー公開空地"): {
                "month": 6,
                "day": 20,
                "end_month": 6,
                "end_day": 22,
            }
        }

        result = apply_historical_references(
            events,
            today=date(2026, 1, 1),
            fixed_date_rules=stale_external_rules,
        )

        self.assertEqual(result["events"][0]["predicted_date"], "2026-06-13")
        self.assertEqual(result["events"][0]["predicted_date_end"], "2026-06-15")
        self.assertEqual(result["events"][0]["prediction_basis"], "イベントDBの固定日カラムに記録")

    def test_low_confidence_stays_reference_only(self):
        events = [{
            "name": "大銀座盆踊り",
            "venue": "中央通り",
            "public_category": "recurring_last_year",
            "public_status": "expected_low",
            "recurrence_score": 0.51,
            "last_seen_year": 2025,
            "last_seen_dates": ["2025-08-02"],
            "date": "2025-08-02",
        }]

        result = apply_historical_references(events)

        self.assertEqual(result["report"]["slide_count"], 0)
        self.assertEqual(result["report"]["reference_only_count"], 1)
        self.assertEqual(result["events"][0]["display_tier"], "historical_reference")
        self.assertNotIn("predicted_date", result["events"][0])

    def test_past_slide_clears_stale_slide_and_prediction_fields(self):
        events = [{
            "name": "西綾瀬町会 夏祭り盆踊り大会",
            "venue": "五反野コミュニティ公園",
            "public_category": "recurring_last_year",
            "public_status": "expected_medium",
            "recurrence_score": 0.67,
            "last_seen_year": 2025,
            "last_seen_dates": ["2025-06-21"],
            "date": "2025-06-21",
            "historical_display_tier": "historical_slide",
            "historical_slide": {"date": "2026-06-20"},
            "predicted_date": "2026-06-20",
            "prediction_basis": "stale slide",
            "display_tier": "historical_slide",
        }]

        result = apply_historical_references(events, today=date(2026, 6, 26))

        self.assertEqual(result["events"][0]["historical_display_tier"], "historical_reference")
        self.assertEqual(result["events"][0]["display_tier"], "historical_reference")
        self.assertNotIn("historical_slide", result["events"][0])
        self.assertNotIn("predicted_date", result["events"][0])
        self.assertNotIn("prediction_basis", result["events"][0])
        self.assertEqual(result["report"]["past_slide_downgrade_count"], 1)

    def test_clears_existing_reference_from_non_target_event(self):
        events = [{
            "name": "確定イベント",
            "public_category": "upcoming",
            "historical_reference": {"old": True},
            "historical_last_seen_year": 2025,
        }]

        result = apply_historical_references(events)

        self.assertEqual(result["report"]["target_count"], 0)
        self.assertNotIn("historical_reference", result["events"][0])
        self.assertNotIn("historical_last_seen_year", result["events"][0])


if __name__ == "__main__":
    unittest.main()
