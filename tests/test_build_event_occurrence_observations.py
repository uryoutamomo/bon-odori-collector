import unittest

from build_event_occurrence_observations import attach_songs, build_active_observations, date_clusters


class BuildEventOccurrenceObservationsTest(unittest.TestCase):
    def test_date_clusters_split_distant_dates(self):
        self.assertEqual(
            date_clusters(["2025-05-30", "2025-06-01", "2025-09-28"]),
            [["2025-05-30", "2025-06-01"], ["2025-09-28"]],
        )

    def test_build_active_observations_groups_matched_videos(self):
        rows = [
            {
                "video_id": "a",
                "video_url": "https://www.youtube.com/watch?v=a",
                "title": "sample",
                "channel_title": "ch1",
                "published_at": "2025-07-20T00:00:00Z",
                "detected_event_date": "2025-07-20",
                "matched_public_event": {
                    "name": "自由が丘納涼盆踊り大会",
                    "venue": "自由が丘駅前ロータリー 特設会場",
                    "area": "目黒区",
                },
            },
            {
                "video_id": "b",
                "video_url": "https://www.youtube.com/watch?v=b",
                "title": "sample",
                "channel_title": "ch2",
                "published_at": "2025-07-21T00:00:00Z",
                "detected_event_date": "2025-07-21",
                "matched_public_event": {
                    "name": "自由が丘納涼盆踊り大会",
                    "venue": "自由が丘駅前ロータリー 特設会場",
                    "area": "目黒区",
                },
            },
        ]

        observations, skipped = build_active_observations(rows)

        self.assertEqual(skipped, {})
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]["date_start"], "2025-07-20")
        self.assertEqual(observations[0]["date_end"], "2025-07-21")
        self.assertEqual(observations[0]["source_video_count"], 2)
        self.assertEqual(observations[0]["source_channels"], ["ch1", "ch2"])

    def test_build_active_observations_splits_distant_same_series_dates(self):
        base = {
            "video_url": "https://www.youtube.com/watch?v=a",
            "title": "sample",
            "channel_title": "ch",
            "published_at": "2025-01-01T00:00:00Z",
            "matched_public_event": {"name": "飛鳥山盆踊り", "venue": "飛鳥山公園"},
        }
        rows = [
            {**base, "video_id": "a", "detected_event_date": "2025-07-05"},
            {**base, "video_id": "b", "detected_event_date": "2025-12-20"},
        ]

        observations, skipped = build_active_observations(rows)

        self.assertEqual(skipped, {})
        self.assertEqual(len(observations), 2)
        self.assertEqual([row["date_start"] for row in observations], ["2025-07-05", "2025-12-20"])

    def test_attach_songs_uses_matching_observation_date(self):
        rows = []
        for video_id, date in [("a", "2025-07-05"), ("b", "2025-12-20")]:
            rows.append({
                "video_id": video_id,
                "video_url": f"https://www.youtube.com/watch?v={video_id}",
                "title": "sample",
                "channel_title": "ch",
                "published_at": "2025-01-01T00:00:00Z",
                "detected_event_date": date,
                "matched_public_event": {"name": "飛鳥山盆踊り", "venue": "飛鳥山公園"},
            })
        observations, _skipped = build_active_observations(rows)

        summary = attach_songs(observations, [{
            "event_date": "2025-12-20",
            "matched_public_event": {"name": "飛鳥山盆踊り", "venue": "飛鳥山公園"},
            "setlist": [{"title": "東京音頭", "url": "https://www.youtube.com/watch?v=b"}],
        }])

        self.assertEqual(summary["attached_occurrences"], 1)
        songs_by_date = {row["date_start"]: [song["song_name"] for song in row["songs"]] for row in observations}
        self.assertEqual(songs_by_date["2025-07-05"], [])
        self.assertEqual(songs_by_date["2025-12-20"], ["東京音頭"])


if __name__ == "__main__":
    unittest.main()
