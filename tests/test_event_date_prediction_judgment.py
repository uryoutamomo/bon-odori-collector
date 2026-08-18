import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from event_model.event_date_prediction_judgment import (
    EventDateJudgmentError,
    apply_judgment_set_to_copy,
    certainty_label,
    validate_llm_judgment,
)
from master_rdb.master_db import init_db


def kameari_judgment():
    return {
        "schema": "llm_event_date_judgment_v1",
        "judgment_id": "llmdate_kameari_2026",
        "predicted_date_id": "preddate_kameari",
        "target_series_id": "ser_kameari",
        "target_event_name": "亀有銀座商店街納涼盆踊り大会",
        "venue": "亀有ゆうろーど（亀有銀座商店街）",
        "target_year": 2026,
        "predicted_date_start": "2026-08-29",
        "predicted_date_end": "2026-08-30",
        "calendar_rule": {"type": "last_full_weekend", "month": 8, "duration_days": 2},
        "organizer_rule": {
            "source_kind": "organizer_primary",
            "source_url": "https://www.youroad.com/event.html",
            "rule_text": "毎年8月の最後の土曜・日曜に開催",
        },
        "historical_matches": [
            {
                "year": 2023,
                "date_start": "2023-08-26",
                "date_end": "2023-08-27",
                "source_kind": "organizer_archive",
                "source_url": "https://www.youroad.com/event.html",
            },
            {
                "year": 2024,
                "date_start": "2024-08-24",
                "date_end": "2024-08-25",
                "source_kind": "organizer_archive",
                "source_url": "https://www.youroad.com/event-bonodori-2024.html",
            },
            {
                "year": 2025,
                "date_start": "2025-08-30",
                "date_end": "2025-08-31",
                "source_kind": "organizer_archive",
                "source_url": "https://www.youroad.com/event.html",
            },
        ],
        "current_year_signals": [
            {
                "source_kind": "community_organization",
                "source_url": "https://nakanodaipta.com/local-information/3042/",
                "date_start": "2026-08-29",
                "date_end": "2026-08-30",
                "description": "地域PTAの2026年行事案内が同名・同会場・同日程を掲載",
            }
        ],
        "conflicts": [],
        "official_current_year_confirmation": False,
        "joint_probability": 0.95,
        "certainty_label": "ほぼ確実",
        "reason_summary": "主催者の明示規則、3年連続の一致、当年の地域団体情報が一致",
    }


class EventDatePredictionJudgmentTest(unittest.TestCase):
    def test_japanese_labels_have_explicit_ninety_percent_boundary(self):
        self.assertEqual(certainty_label(0.90), "ほぼ確実")
        self.assertEqual(certainty_label(0.8999), "可能性が高い")
        self.assertEqual(certainty_label(0.75), "可能性が高い")
        self.assertEqual(certainty_label(0.55), "可能性あり")
        self.assertEqual(certainty_label(0.30), "参考予測")
        self.assertEqual(certainty_label(0.29), "可能性は低い")

    def test_kameari_is_validated_as_joint_ninety_five_percent(self):
        row = validate_llm_judgment(kameari_judgment())

        self.assertEqual(row["predicted_date_start"], "2026-08-29")
        self.assertEqual(row["predicted_date_end"], "2026-08-30")
        self.assertEqual(row["joint_probability"], 0.95)
        self.assertEqual(row["probability_percent"], 95)
        self.assertEqual(row["certainty_label"], "ほぼ確実")
        self.assertEqual(row["machine_checks"]["evidence_cap"], 0.97)
        self.assertEqual(row["date_certainty_tier"], "rule_predicted")

    def test_llm_cannot_claim_almost_certain_from_pattern_only(self):
        row = kameari_judgment()
        row["organizer_rule"] = None
        row["joint_probability"] = 0.95

        with self.assertRaisesRegex(EventDateJudgmentError, "exceeds evidence cap 0.89"):
            validate_llm_judgment(row)

    def test_conflict_caps_probability(self):
        row = kameari_judgment()
        row["conflicts"] = ["自治体一覧が別日を掲載"]

        with self.assertRaisesRegex(EventDateJudgmentError, "exceeds evidence cap 0.49"):
            validate_llm_judgment(row)

    def test_current_year_official_confirmation_must_use_confirmed_path(self):
        row = kameari_judgment()
        row["official_current_year_confirmation"] = True

        with self.assertRaisesRegex(EventDateJudgmentError, "confirmed-date path"):
            validate_llm_judgment(row)

    def test_calendar_rule_is_machine_checked_for_every_year(self):
        row = kameari_judgment()
        row["historical_matches"][1]["date_start"] = "2024-08-31"

        with self.assertRaisesRegex(EventDateJudgmentError, "does not match calendar_rule"):
            validate_llm_judgment(row)

    def test_applies_to_copy_and_promotes_tier_without_setting_confirmed_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.sqlite"
            output = Path(tmp) / "output.sqlite"
            conn = init_db(source)
            conn.execute(
                """
                INSERT INTO venues(
                  venue_id, canonical_name, normalized_name, area, review_status, created_at, updated_at
                ) VALUES ('ven_kameari', ?, ?, '葛飾区', 'active', 'now', 'now')
                """,
                ("亀有ゆうろーど（亀有銀座商店街）", "亀有ゆうろーど亀有銀座商店街"),
            )
            conn.execute(
                """
                INSERT INTO event_series(
                  series_id, series_key, canonical_name, normalized_name, status, created_at, updated_at
                ) VALUES ('ser_kameari', 'kameari-ginza-bonodori', ?, ?, 'active', 'now', 'now')
                """,
                ("亀有銀座商店街納涼盆踊り大会", "亀有銀座商店街納涼盆踊り大会"),
            )
            conn.execute(
                """
                INSERT INTO event_occurrences(
                  occurrence_id, series_id, event_year, occurrence_sequence, display_name,
                  venue_id, date_status, lifecycle_status, current_event_state,
                  date_certainty_tier, created_at, updated_at
                ) VALUES (
                  'occ_kameari', 'ser_kameari', 2026, 1, ?, 'ven_kameari',
                  'predicted', 'active', 'predicted', 'historical_slide', 'now', 'now'
                )
                """,
                ("亀有銀座商店街納涼盆踊り大会",),
            )
            conn.execute(
                """
                INSERT INTO historical_promotion_candidates(
                  candidate_id, target_series_id, target_occurrence_id, target_event_name,
                  historical_years_json, promotion_confidence, recommended_action, created_at, updated_at
                ) VALUES (
                  'cand_kameari', 'ser_kameari', 'occ_kameari', ?, '[2024,2025]',
                  'medium', 'manual_predicted_date_review', 'now', 'now'
                )
                """,
                ("亀有銀座商店街納涼盆踊り大会",),
            )
            conn.execute(
                """
                INSERT INTO predicted_occurrence_dates(
                  predicted_date_id, historical_candidate_id, target_series_id,
                  target_occurrence_id, target_event_name, predicted_year, date_start,
                  date_end, date_status, basis_type, basis_type_label, rule_type,
                  basis, confidence, score, application_status, source,
                  source_payload_json, created_at, updated_at
                ) VALUES (
                  'preddate_kameari', 'cand_kameari', 'ser_kameari', 'occ_kameari', ?,
                  2026, '2026-08-29', '2026-08-30', 'predicted', 'weekday_based',
                  '曜日基準', 'weekday_last', 'old', 'medium', 0.66,
                  'candidate_for_2026_occurrence', 'manual', '{}', 'now', 'now'
                )
                """,
                ("亀有銀座商店街納涼盆踊り大会",),
            )
            conn.commit()
            conn.close()

            report = apply_judgment_set_to_copy(
                source,
                output,
                {"schema": "llm_event_date_judgment_set_v1", "judgments": [kameari_judgment()]},
                now="2026-08-18T00:00:00+00:00",
            )

            self.assertEqual(report["applied_count"], 1)
            conn = sqlite3.connect(output)
            prediction = conn.execute(
                """
                SELECT date_start, date_end, confidence, score, source, source_payload_json
                FROM predicted_occurrence_dates WHERE predicted_date_id='preddate_kameari'
                """
            ).fetchone()
            occurrence = conn.execute(
                """
                SELECT date_start, date_end, current_event_state, date_certainty_tier
                FROM event_occurrences WHERE occurrence_id='occ_kameari'
                """
            ).fetchone()
            conn.close()

        self.assertEqual(prediction[:5], ("2026-08-29", "2026-08-30", "high", 0.95, "llm_event_date_judgment_v1"))
        payload = json.loads(prediction[5])
        self.assertEqual(payload["certainty_label"], "ほぼ確実")
        self.assertEqual(payload["venue"], "亀有ゆうろーど（亀有銀座商店街）")
        self.assertEqual(occurrence, (None, None, "predicted", "rule_predicted"))


if __name__ == "__main__":
    unittest.main()
