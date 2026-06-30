import tempfile
import unittest
from pathlib import Path

from classify_public_events_diff import (
    build_classification,
    classify_diff,
    field_family,
    values_differ,
    write_json,
)


class ClassifyPublicEventsDiffTest(unittest.TestCase):
    def test_fixed_date_rule_is_postprocess_rule_not_detail_review(self):
        self.assertEqual(field_family("detail"), "detail")
        self.assertEqual(field_family("fixed_date_rule"), "fixed_date_rule")
        self.assertEqual(field_family("source_urls"), "source")
        self.assertEqual(
            classify_diff("fixed_date_rule", {"rule_type": "fixed_mmdd"}, None),
            "collector_only_postprocess_rule",
        )
        self.assertEqual(
            classify_diff("detail", "public text", None),
            "individual_review",
        )
        self.assertEqual(
            classify_diff("source_urls", [], [{"url": "https://example.com", "kind": "official"}]),
            "individual_review",
        )

    def test_source_url_removal_is_high_risk_individual_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            collector_path = root / "collector.json"
            site_path = root / "site.json"
            base = {
                "name": "丸の内de盆踊り",
                "venue": "行幸通り",
                "date": "2026-07-25",
            }
            write_json(collector_path, [{**base, "source_urls": []}])
            write_json(
                site_path,
                [
                    {
                        **base,
                        "source_urls": [
                            {
                                "label": "公式告知あり",
                                "url": "https://www.marunouchi.com/pickup/event/6763/",
                                "kind": "official",
                            }
                        ],
                    }
                ],
            )

            result = build_classification(collector_path, site_path)

        self.assertEqual(result["summary"]["records_by_family"], {"source": 1})
        self.assertEqual(result["summary"]["events_by_action"], {"individual_review": 1})

    def test_collector_only_fixed_date_rule_does_not_force_individual_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            collector_path = root / "collector.json"
            site_path = root / "site.json"
            base = {
                "name": "山王音頭と民踊大会",
                "venue": "山王パークタワー公開空地",
                "date": "2026-06-13",
            }
            write_json(
                collector_path,
                [
                    {
                        **base,
                        "fixed_date_rule": {
                            "rule_type": "fixed_mmdd",
                            "start_mmdd": "06-13",
                            "end_mmdd": "06-15",
                        },
                    }
                ],
            )
            write_json(site_path, [base])

            result = build_classification(collector_path, site_path)

        self.assertEqual(
            result["summary"]["events_by_action"],
            {"collector_only_postprocess_rule": 1},
        )
        self.assertEqual(result["event_rows"][0]["recommended_action"], "collector_only_postprocess_rule")

    def test_same_weekday_method_metadata_is_not_a_public_diff_by_itself(self):
        collector_value = {
            "date": "2026-08-08",
            "date_end": "2026-08-08",
            "basis": "2025年実績の同月第2土曜を2026年へスライド",
            "method": "same_weekday",
        }
        site_value = {
            "date": "2026-08-08",
            "date_end": "2026-08-08",
            "basis": "2025年実績の同月第2土曜を2026年へスライド",
        }

        self.assertFalse(values_differ("historical_slide", collector_value, site_value))

    def test_recurrence_score_same_display_bucket_is_low_priority(self):
        self.assertEqual(
            classify_diff("recurrence_score", 0.59, 0.55),
            "low_priority_or_unclassified",
        )
        self.assertEqual(
            classify_diff("recurrence_reasons", ["venue_present"], ["venue_present", "recurring_word:毎年"]),
            "low_priority_or_unclassified",
        )
        self.assertEqual(
            classify_diff("recurrence_score", 0.76, 0.54),
            "individual_review",
        )

    def test_matching_rule_prediction_can_replace_legacy_historical_slide(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            collector_path = root / "collector.json"
            site_path = root / "site.json"
            base = {
                "name": "歌舞伎町BON ODORI",
                "venue": "歌舞伎町シネシティ広場",
                "public_category": "recurring_last_year",
                "date": "2025-08-16",
            }
            write_json(
                collector_path,
                [
                    {
                        **base,
                        "display_tier": "rule_predicted",
                        "date_prediction": {
                            "date": "2026-08-15",
                            "date_end": "2026-08-15",
                            "basis": "8月第3土曜",
                            "confidence": "medium",
                        },
                        "prediction_basis": "8月第3土曜",
                        "prediction_evidence_years": [2024, 2025],
                        "historical_reference": {
                            "display_tier": "historical_reference",
                            "label": "2025-08-16実績・今年未確認",
                        },
                        "historical_display_tier": "historical_reference",
                    }
                ],
            )
            write_json(
                site_path,
                [
                    {
                        **base,
                        "display_tier": "historical_slide",
                        "historical_reference": {
                            "display_tier": "historical_slide",
                            "label": "2025-08-16実績・今年未確認",
                        },
                        "historical_display_tier": "historical_slide",
                        "historical_slide": {
                            "date": "2026-08-15",
                            "date_end": "2026-08-15",
                            "basis": "2025年実績の同月第3土曜を2026年へスライド",
                        },
                        "historical_slide_date": "2026-08-15",
                        "historical_slide_date_end": "2026-08-15",
                        "historical_slide_basis": "2025年実績の同月第3土曜を2026年へスライド",
                        "prediction_basis": "2025年実績の同月第3土曜を2026年へスライド",
                    }
                ],
            )

            result = build_classification(collector_path, site_path)

        self.assertEqual(
            result["summary"]["events_by_action"],
            {"rule_prediction_replaces_matching_historical_slide": 1},
        )

    def test_fixed_date_rule_basis_refresh_is_not_individual_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            collector_path = root / "collector.json"
            site_path = root / "site.json"
            base = {
                "name": "花園神社 盆踊り",
                "venue": "花園神社",
                "public_category": "recurring_last_year",
                "display_tier": "historical_slide",
            }
            write_json(
                collector_path,
                [
                    {
                        **base,
                        "historical_reference_score": 0.55,
                        "historical_reference": {
                            "display_tier": "historical_slide",
                            "score": 0.55,
                            "label": "2025-08-01〜2025-08-02実績・今年未確認",
                        },
                        "historical_slide": {
                            "date": "2026-08-01",
                            "date_end": "2026-08-02",
                            "rule_type": "fixed_date_range",
                            "basis": "YOKOSO新宿の告知に「毎年8月1日・2日」と明記",
                        },
                        "historical_slide_basis": "YOKOSO新宿の告知に「毎年8月1日・2日」と明記",
                        "prediction_basis": "YOKOSO新宿の告知に「毎年8月1日・2日」と明記",
                    }
                ],
            )
            write_json(
                site_path,
                [
                    {
                        **base,
                        "historical_reference_score": 0.59,
                        "historical_reference": {
                            "display_tier": "historical_slide",
                            "score": 0.59,
                            "label": "2025-08-01〜2025-08-02実績・今年未確認",
                        },
                        "historical_slide": {
                            "date": "2026-08-01",
                            "date_end": "2026-08-02",
                            "rule_type": "fixed_date_range",
                            "basis": "イベントDBの固定日カラムに記録",
                        },
                        "historical_slide_basis": "イベントDBの固定日カラムに記録",
                        "prediction_basis": "イベントDBの固定日カラムに記録",
                    }
                ],
            )

            result = build_classification(collector_path, site_path)

        self.assertEqual(
            result["summary"]["events_by_action"],
            {"fixed_date_rule_basis_refresh": 1},
        )


if __name__ == "__main__":
    unittest.main()
