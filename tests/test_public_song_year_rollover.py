import inspect
import copy
import unittest
from unittest.mock import patch

import export_public_events as exporter


class PublicSongYearRolloverTest(unittest.TestCase):
    def event(self, year=None, *, date_value=None, songs=None, **overrides):
        event = {
            "name": "年越し曲目テスト盆踊り",
            "venue": "確認公園",
            "area": "新宿区",
            "date": date_value,
            "songs": songs or [],
        }
        if year is not None:
            event["_event_year"] = year
        event.update(overrides)
        return event

    def test_two_year_old_current_hint_is_aged_once_with_full_year_gap(self):
        events = [self.event(2025, songs=[{
            "name": "四谷納涼踊り",
            "probability": 95,
            "confidence": "confirmed",
            "basis": "current_hint",
            "source_count": 1,
        }])]

        projected = exporter.project_retained_historical_songs(events, target_year=2027)

        self.assertEqual(projected[0]["songs"], [{
            "name": "四谷納涼踊り",
            "probability": 43,
            "confidence": "hint",
            "basis": "past_evidence",
            "basis_label": "2025年ヒント",
            "source_count": 1,
        }])
        self.assertEqual(exporter.audit_public_song_projection(projected), [])

    def test_2023_and_2024_direct_songs_use_their_own_year_gaps(self):
        events = [
            self.event(2023, songs=[{
                "name": "2023実測曲",
                "probability": 95,
                "basis": "current_observed",
                "source_count": 2,
            }]),
            self.event(2024, songs=[{
                "name": "2024ヒント曲",
                "probability": 80,
                "basis": "current_hint",
                "source_count": 1,
            }]),
        ]

        projected = exporter.project_retained_historical_songs(events, target_year=2027)

        self.assertEqual(projected[0]["songs"][0]["probability"], 29)
        self.assertEqual(projected[0]["songs"][0]["basis_label"], "2023年実測")
        self.assertEqual(projected[1]["songs"][0]["probability"], 27)
        self.assertEqual(projected[1]["songs"][0]["basis_label"], "2024年ヒント")

    def test_inherited_multiyear_label_is_preserved_without_second_speaker_penalty(self):
        events = [self.event(2026, songs=[{
            "name": "複数年実績曲",
            "probability": 57,
            "confidence": "hint",
            "basis": "past_evidence",
            "basis_label": "2024・2025年実測",
            "source_count": 1,
        }])]

        projected = exporter.project_retained_historical_songs(events, target_year=2027)

        song = projected[0]["songs"][0]
        self.assertEqual(song["probability"], 43)
        self.assertEqual(song["basis"], "past_evidence")
        self.assertEqual(song["basis_label"], "2024・2025年実測")

    def test_target_or_future_occurrence_with_old_display_date_is_not_aged_or_hidden_from_audit(self):
        events = [
            self.event(2027, date_value="2025-07-19", songs=[{
                "name": "今年ヒント曲",
                "probability": 95,
                "basis": "current_hint",
            }]),
            self.event(2028, date_value="2025-07-19", songs=[{
                "name": "翌年ヒント曲",
                "probability": 95,
                "basis": "current_hint",
            }]),
        ]
        before = copy.deepcopy(events)

        projected = exporter.project_retained_historical_songs(events, target_year=2027)

        self.assertEqual(projected, before)
        self.assertEqual(
            exporter.audit_public_song_projection(projected)[0]["type"],
            "indirect_song_above_exact_threshold",
        )

    def test_past_occurrence_without_date_is_aged_from_its_event_year(self):
        events = [self.event(2025, date_value=None, songs=[{
            "name": "日付なし過去曲",
            "probability": 80,
            "basis": "current_announced",
            "source_count": 1,
        }])]

        projected = exporter.project_retained_historical_songs(events, target_year=2027)

        self.assertEqual(projected[0]["songs"][0]["probability"], 36)
        self.assertEqual(projected[0]["songs"][0]["basis_label"], "2025年告知")

    def test_missing_event_year_is_not_inferred_from_an_old_date(self):
        events = [self.event(date_value="2023-07-19", songs=[{
            "name": "推測禁止曲",
            "probability": 95,
            "basis": "current_hint",
        }])]
        before = copy.deepcopy(events)

        projected = exporter.project_retained_historical_songs(events, target_year=2027)

        self.assertEqual(projected, before)
        self.assertEqual(
            exporter.audit_public_song_projection(projected)[0]["basis"], "current_hint"
        )

    def test_invalid_probability_is_rejected_before_public_song_audit(self):
        for probability in (-1, 101):
            with self.subTest(probability=probability):
                events = [self.event(2025, songs=[{
                    "name": "不正確率曲",
                    "probability": probability,
                    "basis": "current_hint",
                }])]
                with self.assertRaisesRegex(ValueError, "between 0 and 100"):
                    exporter.project_retained_historical_songs(events, target_year=2027)

    def test_replacement_merge_is_not_aged_twice_while_another_old_series_is_retained(self):
        current = self.event(
            2026,
            date_value="2026-07-20",
            public_category="upcoming",
            _series_id="ser_current",
            _venue_id="ven_shared",
            songs=[],
        )
        previous = self.event(
            2025,
            date_value="2025-07-20",
            public_category="recurring_last_year",
            _series_id="ser_current",
            _venue_id="ven_shared",
            songs=[{
                "name": "前年ヒント曲",
                "probability": 95,
                "basis": "current_hint",
                "source_count": 1,
            }],
        )
        other_old = self.event(
            2024,
            date_value="2024-07-20",
            public_category="date_unknown",
            _series_id="ser_other",
            _venue_id="ven_other",
            songs=[{
                "name": "別series過去曲",
                "probability": 80,
                "basis": "current_hint",
                "source_count": 1,
            }],
        )

        retained = exporter.suppress_replaced_recurring_events(
            [current, previous, other_old], target_year=2026
        )

        self.assertEqual([event["_series_id"] for event in retained], [
            "ser_current", "ser_other",
        ])
        self.assertEqual(retained[0]["songs"][0]["probability"], 57)
        self.assertEqual(retained[0]["songs"][0]["basis_label"], "2025年ヒント")
        self.assertEqual(retained[1]["songs"][0]["probability"], 36)
        self.assertEqual(retained[1]["songs"][0]["basis_label"], "2024年ヒント")

    def test_project_public_events_ages_retained_song_in_legacy_and_r2_signatures(self):
        raw = self.event(
            2025,
            date_value="2025-07-19",
            name_confirmed=True,
            status="終了",
            months=[7],
            scale="小",
            access="徒歩5分",
            address="東京都新宿区",
            lat=None,
            lng=None,
            description="",
            detail="",
            source_urls=[],
            _source="master_rdb",
            _occurrence_id="occ_rollover_2025",
            _series_id="ser_rollover",
            _venue_id="ven_rollover",
            songs=[{
                "name": "実経路曲",
                "probability": 95,
                "basis": "current_hint",
                "source_count": 1,
            }],
        )
        kwargs = {"target_year": 2027, "today": "2027-01-01"}
        if "inputs" in inspect.signature(exporter.project_public_events).parameters:
            kwargs["inputs"] = exporter.PublicProjectionInputs(
                prediction_payload={"predictions": []},
                overrides={},
                fixed_date_rules={},
            )
            result = exporter.project_public_events([raw], **kwargs)
        else:
            kwargs["db_path"] = "unused.sqlite"
            with patch.object(
                exporter, "load_public_date_predictions_for_export", return_value={"predictions": []}
            ):
                result = exporter.project_public_events([raw], **kwargs)

        song = result["public_events"][0]["songs"][0]
        self.assertEqual(song["probability"], 43)
        self.assertEqual(song["basis"], "past_evidence")
        self.assertEqual(song["basis_label"], "2025年ヒント")


if __name__ == "__main__":
    unittest.main()
