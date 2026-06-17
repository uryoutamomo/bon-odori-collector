import unittest

from apply_event_occurrence_backfill_plan import apply_plan


class ApplyEventOccurrenceBackfillPlanTest(unittest.TestCase):
    def test_apply_plan_adds_observation_and_rebuilds_summary(self):
        payload = {
            "generated_by": "build_event_occurrence_observations.py",
            "summary": {
                "active_review_skipped": {"missing": 1},
                "setlist_attach": {"attached_occurrences": 1},
            },
            "series": [],
            "observations": [],
        }
        plan = {
            "observations": [{
                "observation_id": "obs1",
                "series_key": "series1",
                "event_name": "郡上おどり in 青山 2025",
                "venue": "秩父宮ラグビー場駐車場",
                "area": "港区",
                "year": 2024,
                "date_start": "2024-06-14",
                "date_end": "2024-06-14",
                "observed_dates": ["2024-06-14"],
                "weekday_start": "金",
                "weekday_end": "金",
                "source_type": "youtube_backfill_observed",
                "source_video_count": 3,
                "source_channels": ["ch1", "ch2"],
                "confidence": "medium",
                "source_videos": [],
                "songs": [{"song_name": "かわさき"}],
            }]
        }

        data = apply_plan(payload, plan)

        self.assertEqual(data["summary"]["observation_count"], 1)
        self.assertEqual(data["summary"]["source_video_count"], 3)
        self.assertEqual(data["summary"]["observations_by_year"], {"2024": 1})
        self.assertEqual(data["summary"]["backfill_apply"]["added"], 1)
        self.assertEqual(data["summary"]["backfill_apply"]["updated"], 0)
        self.assertEqual(data["summary"]["active_review_skipped"], {"missing": 1})

    def test_apply_plan_updates_same_observation_id(self):
        observation = {
            "observation_id": "obs1",
            "series_key": "series1",
            "event_name": "山王音頭と民踊大会",
            "venue": "山王パークタワー公開空地",
            "year": 2024,
            "date_start": "2024-06-13",
            "date_end": "2024-06-13",
            "observed_dates": ["2024-06-13"],
            "source_video_count": 1,
            "source_channels": ["ch1"],
            "songs": [],
        }
        payload = {"summary": {}, "series": [], "observations": [observation]}
        plan = {"observations": [{**observation, "source_video_count": 2}]}

        data = apply_plan(payload, plan)

        self.assertEqual(data["summary"]["observation_count"], 1)
        self.assertEqual(data["summary"]["source_video_count"], 2)
        self.assertEqual(data["summary"]["backfill_apply"]["added"], 0)
        self.assertEqual(data["summary"]["backfill_apply"]["updated"], 1)


if __name__ == "__main__":
    unittest.main()
