import unittest

from build_event_occurrence_backfill_plan import build_plan, song_hints_from_candidate


class BuildEventOccurrenceBackfillPlanTest(unittest.TestCase):
    def test_song_hints_from_candidate_extracts_quoted_title(self):
        hints = song_hints_from_candidate({
            "title": "「東京音頭」 2024年山王祭 盆踊り",
            "video_url": "https://www.youtube.com/watch?v=a",
            "setlist_sample": [],
        })

        self.assertEqual(hints, [{
            "song_name": "東京音頭",
            "source_url": "https://www.youtube.com/watch?v=a",
        }])

    def test_build_plan_groups_strong_candidates_by_date_cluster(self):
        payload = {
            "candidates": [
                {
                    "status": "strong",
                    "target_year": 2024,
                    "event_name": "山王音頭と民踊大会",
                    "venue": "山王パークタワー公開空地",
                    "area": "千代田区",
                    "detected_event_date": "2024-06-13",
                    "video_id": "a",
                    "video_url": "https://www.youtube.com/watch?v=a",
                    "title": "東京音頭 2024年6月13日 山王音頭と民踊大会 盆踊り",
                    "channel_title": "ch1",
                    "score": 98,
                },
                {
                    "status": "strong",
                    "target_year": 2024,
                    "event_name": "山王音頭と民踊大会",
                    "venue": "山王パークタワー公開空地",
                    "area": "千代田区",
                    "detected_event_date": "2024-06-15",
                    "video_id": "b",
                    "video_url": "https://www.youtube.com/watch?v=b",
                    "title": "山王音頭 2024年6月15日 山王音頭と民踊大会 盆踊り",
                    "channel_title": "ch2",
                    "score": 98,
                },
                {
                    "status": "review",
                    "target_year": 2024,
                    "event_name": "山王音頭と民踊大会",
                    "venue": "山王パークタワー公開空地",
                    "detected_event_date": "2024-06-13",
                },
            ]
        }

        plan = build_plan(payload)

        self.assertEqual(plan["summary"]["observation_count"], 1)
        observation = plan["observations"][0]
        self.assertEqual(observation["date_start"], "2024-06-13")
        self.assertEqual(observation["date_end"], "2024-06-15")
        self.assertEqual(observation["source_video_count"], 2)
        self.assertEqual(observation["source_channels"], ["ch1", "ch2"])

    def test_build_plan_can_manually_accept_low_confidence_observation(self):
        payload = {
            "candidates": [
                {
                    "status": "strong",
                    "target_year": 2023,
                    "event_name": "謝恩納涼盆踊り大会（青山善光寺）",
                    "venue": "青山善光寺",
                    "area": "港区",
                    "detected_event_date": "2023-07-31",
                    "video_id": "a",
                    "video_url": "https://www.youtube.com/watch?v=a",
                    "title": "会津磐梯山 謝恩納涼盆踊り大会（青山・善光寺）20230731",
                    "channel_title": "祭のきせき",
                    "score": 100,
                },
                {
                    "status": "strong",
                    "target_year": 2023,
                    "event_name": "謝恩納涼盆踊り大会（青山善光寺）",
                    "venue": "青山善光寺",
                    "area": "港区",
                    "detected_event_date": "2023-07-31",
                    "video_id": "b",
                    "video_url": "https://www.youtube.com/watch?v=b",
                    "title": "好きになった人 謝恩納涼盆踊り大会（青山・善光寺）20230731",
                    "channel_title": "祭のきせき",
                    "score": 100,
                },
            ]
        }
        initial = build_plan(payload)
        observation_id = initial["excluded_low_observations"][0]["observation_id"]

        plan = build_plan(payload, {"accept": [{"observation_id": observation_id}]})

        self.assertEqual(plan["summary"]["observation_count"], 1)
        self.assertEqual(plan["summary"]["manual_accepted_low_observation_count"], 1)
        self.assertEqual(plan["summary"]["excluded_low_observation_count"], 0)
        self.assertEqual(plan["observations"][0]["confidence"], "manual_accept")
        self.assertEqual(plan["observations"][0]["manual_review"], "accepted_low_confidence")


if __name__ == "__main__":
    unittest.main()
