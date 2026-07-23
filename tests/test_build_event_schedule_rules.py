import unittest

from youtube_backfill.build_event_schedule_rules import build_rules
from tests.test_build_event_date_predictions import observation, payload


class BuildEventScheduleRulesTest(unittest.TestCase):
    def test_classifies_fixed_date_axis(self):
        rows = [
            observation("s1", "山王音頭と民踊大会", "山王パークタワー公開空地", 2023, "2023-06-13"),
            observation("s1", "山王音頭と民踊大会", "山王パークタワー公開空地", 2024, "2024-06-13", "2024-06-15"),
        ]

        data = build_rules(payload(rows), target_year=2026)
        rule = data["rules"][0]["rule"]

        self.assertEqual(rule["rule_type"], "fixed_date")
        self.assertEqual(rule["primary_axis"], "date")
        self.assertEqual(rule["axis_label"], "同一日タイプ")
        self.assertEqual(rule["rule_confidence"], "medium")

    def test_classifies_weekday_axis(self):
        rows = [
            observation("s1", "丸の内de盆踊り", "行幸通り", 2024, "2024-07-26"),
            observation("s1", "丸の内de盆踊り", "行幸通り", 2025, "2025-07-25"),
        ]

        data = build_rules(payload(rows), target_year=2026)
        rule = data["rules"][0]["rule"]

        self.assertEqual(rule["rule_type"], "weekday_last")
        self.assertEqual(rule["primary_axis"], "weekday")
        self.assertEqual(rule["axis_label"], "同一曜日タイプ")
        self.assertEqual(rule["rule_confidence"], "medium")

    def test_keeps_candidate_rules_for_review(self):
        rows = [
            observation("s1", "西久保八幡神社 盆踊り", "西久保八幡神社", 2023, "2023-08-10", "2023-08-12"),
            observation("s1", "西久保八幡神社 盆踊り", "西久保八幡神社", 2024, "2024-08-09"),
            observation("s1", "西久保八幡神社 盆踊り", "西久保八幡神社", 2025, "2025-08-09"),
        ]

        data = build_rules(payload(rows), target_year=2026)
        row = data["rules"][0]

        self.assertEqual(row["rule"]["rule_type"], "weekend_near_day")
        self.assertIn("fixed_date", {candidate["rule_type"] for candidate in row["candidate_rules"]})
        self.assertEqual(row["rule"]["rule_confidence"], "high")

    def test_rule_payload_records_explicit_2027_target(self):
        rows = [
            observation("s1", "丸の内de盆踊り", "行幸通り", 2025, "2025-07-25"),
            observation("s1", "丸の内de盆踊り", "行幸通り", 2026, "2026-07-31"),
        ]

        data = build_rules(payload(rows), target_year=2027)

        self.assertEqual(data["target_year"], 2027)
        self.assertEqual(data["rules"][0]["rule"]["predicted_date_start"], "2027-07-30")


if __name__ == "__main__":
    unittest.main()
