import unittest

from public_export_support.date_predictions import apply_predictions


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
            "joint_probability": 0.95,
            "probability_percent": 95,
            "certainty_label": "ほぼ確実",
            "certainty_meaning": "このイベントが、この予測日に開催される確からしさ",
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
        self.assertEqual(result["events"][0]["current_event_state"], "predicted")
        self.assertEqual(result["events"][0]["date_certainty_tier"], "rule_predicted")
        self.assertEqual(result["events"][0]["prediction_probability"], 0.95)
        self.assertEqual(result["events"][0]["prediction_probability_percent"], 95)
        self.assertEqual(result["events"][0]["prediction_certainty_label"], "ほぼ確実")
        self.assertEqual(
            result["events"][0]["date_prediction"]["certainty_meaning"],
            "このイベントが、この予測日に開催される確からしさ",
        )
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

    def test_apply_predictions_never_attaches_to_confirmed_state(self):
        event = {
            "name": "丸の内de盆踊り",
            "venue": "行幸通り",
            "date": "2025-07-25",
            "current_event_state": "confirmed",
            "date_certainty_tier": "confirmed",
        }

        result = apply_predictions([event], {"predictions": [prediction_row()]})

        self.assertEqual(result["report"]["applied_count"], 0)
        self.assertNotIn("date_prediction", result["events"][0])
        self.assertEqual(result["events"][0]["date_certainty_tier"], "confirmed")

    def test_explicit_occurrence_id_selects_only_its_matching_event(self):
        events = [
            {"occurrence_id": "occ_first", "name": "同名盆踊り", "venue": "同じ会場", "date": "2025-08-01"},
            {"occurrence_id": "occ_second", "name": "同名盆踊り", "venue": "同じ会場", "date": "2025-08-02"},
        ]
        prediction = prediction_row("同名盆踊り", "同じ会場")
        prediction["target_occurrence_id"] = "occ_second"
        result = apply_predictions(events, {"predictions": [prediction]})
        self.assertEqual(result["report"]["applied_count"], 1)
        self.assertNotIn("date_prediction", result["events"][0])
        self.assertEqual(result["events"][1]["date_prediction"]["date"], "2026-07-31")
        self.assertEqual(result["report"]["applied"][0]["resolution"], "target_occurrence_id")

    def test_unknown_explicit_occurrence_id_does_not_fall_back_to_name(self):
        event = {"occurrence_id": "occ_actual", "name": "丸の内de盆踊り", "venue": "行幸通り", "date": "2025-07-25"}
        prediction = prediction_row()
        prediction["target_occurrence_id"] = "occ_missing"
        result = apply_predictions([event], {"predictions": [prediction]})
        self.assertEqual(result["report"]["unmatched_count"], 1)
        self.assertEqual(result["report"]["unmatched"][0]["reason"], "target_occurrence_id_not_found")
        self.assertNotIn("date_prediction", result["events"][0])

    def test_ambiguous_legacy_name_and_venue_is_not_applied(self):
        events = [
            {"occurrence_id": "occ_one", "name": "同名盆踊り", "venue": "同じ会場", "date": "2025-08-01"},
            {"occurrence_id": "occ_two", "name": "同名盆踊り", "venue": "同じ会場", "date": "2025-08-02"},
        ]
        result = apply_predictions(events, {"predictions": [prediction_row("同名盆踊り", "同じ会場")]})
        self.assertEqual(result["report"]["applied_count"], 0)
        self.assertEqual(result["report"]["skipped_count"], 1)
        self.assertEqual(result["report"]["skipped"][0]["reason"], "ambiguous_legacy_identity")
        self.assertNotIn("date_prediction", result["events"][0])
        self.assertNotIn("date_prediction", result["events"][1])


if __name__ == "__main__":
    unittest.main()
