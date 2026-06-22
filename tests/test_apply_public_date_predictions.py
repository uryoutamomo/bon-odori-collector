import unittest

from apply_public_date_predictions import apply_predictions


def prediction_row(name="丸の内de盆踊り", venue="行幸通り"):
    return {
        "event_name": name,
        "venue": venue,
        "target_year": 2026,
        "prediction": {
            "predicted_date_start": "2026-07-31",
            "predicted_date_end": "2026-07-31",
            "predicted_weekday_start": "金",
            "predicted_weekday_end": "金",
            "confidence": "medium",
            "score": 0.74,
            "rule_type": "weekday_last",
            "basis": "7月の最終金曜",
            "evidence_years": [2024, 2025],
            "evidence_count": 2,
        },
        "actual_observations": [],
    }


class ApplyPublicDatePredictionsTest(unittest.TestCase):
    def test_apply_predictions_adds_date_prediction_without_overwriting_date(self):
        events = [{
            "name": "丸の内de盆踊り",
            "venue": "行幸通り",
            "date": "2025-07-25",
            "date_end": "2025-07-26",
        }]

        result = apply_predictions(events, {"predictions": [prediction_row()]})

        self.assertEqual(result["report"]["applied_count"], 1)
        self.assertEqual(result["events"][0]["date"], "2025-07-25")
        self.assertEqual(result["events"][0]["date_prediction"]["date"], "2026-07-31")
        self.assertEqual(result["events"][0]["date_prediction"]["rule_type"], "weekday_last")
        self.assertEqual(result["events"][0]["display_tier"], "rule_predicted")
        self.assertEqual(result["events"][0]["predicted_date"], "2026-07-31")
        self.assertEqual(result["events"][0]["predicted_date_end"], "2026-07-31")
        self.assertEqual(result["events"][0]["prediction_basis"], "7月の最終金曜")
        self.assertEqual(result["events"][0]["prediction_confidence"], "medium")
        self.assertEqual(result["events"][0]["prediction_evidence_years"], [2024, 2025])
        self.assertEqual(result["report"]["applied"][0]["before"]["date"], "2025-07-25")
        self.assertEqual(result["report"]["applied"][0]["after"]["display_tier"], "rule_predicted")

    def test_apply_predictions_skips_when_target_year_date_exists(self):
        events = [{
            "name": "山王音頭と民踊大会",
            "venue": "山王パークタワー公開空地",
            "date": "2026-06-13",
            "date_prediction": {"date": "old"},
            "display_tier": "rule_predicted",
            "predicted_date": "old",
            "predicted_date_end": "old",
            "prediction_basis": "old",
            "prediction_confidence": "low",
            "prediction_evidence_years": [2025],
        }]

        result = apply_predictions(events, {"predictions": [prediction_row("山王音頭と民踊大会", "山王パークタワー公開空地")]})

        self.assertEqual(result["report"]["applied_count"], 0)
        self.assertEqual(result["report"]["skipped_count"], 1)
        self.assertNotIn("date_prediction", result["events"][0])
        self.assertNotIn("display_tier", result["events"][0])
        self.assertNotIn("predicted_date", result["events"][0])

    def test_apply_predictions_skips_low_confidence_public_prediction(self):
        events = [{
            "name": "赤坂浄土寺盆踊り大会",
            "venue": "浄土寺",
            "date": "2025-07-24",
            "date_prediction": {"date": "old"},
            "display_tier": "rule_predicted",
            "predicted_date": "old",
            "predicted_date_end": "old",
            "prediction_basis": "old",
            "prediction_confidence": "low",
            "prediction_evidence_years": [2024],
        }]
        low = prediction_row("赤坂浄土寺盆踊り大会", "浄土寺")
        low["prediction"]["confidence"] = "low"

        result = apply_predictions(events, {"predictions": [low]})

        self.assertEqual(result["report"]["applied_count"], 0)
        self.assertEqual(result["report"]["skipped_count"], 1)
        self.assertEqual(result["report"]["skipped"][0]["reason"], "low_confidence_public_prediction")
        self.assertNotIn("date_prediction", result["events"][0])
        self.assertNotIn("display_tier", result["events"][0])
        self.assertNotIn("predicted_date", result["events"][0])

    def test_apply_predictions_reports_unmatched(self):
        result = apply_predictions([], {"predictions": [prediction_row()]})

        self.assertEqual(result["report"]["unmatched_count"], 1)


if __name__ == "__main__":
    unittest.main()
