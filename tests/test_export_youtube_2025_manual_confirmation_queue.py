import unittest

from export_youtube_2025_manual_confirmation_queue import official_confirmation_rows


class ExportYoutube2025ManualConfirmationQueueTest(unittest.TestCase):
    def test_keeps_all_videos_for_group(self):
        active_review = {
            "rows": [
                {
                    "action": "needs_official_confirmation",
                    "official_urls": ["https://example.com/event"],
                    "video_url": f"https://www.youtube.com/watch?v={idx}",
                    "title": f"盆踊り {idx}",
                    "detected_event_date": "2025-08-23",
                }
                for idx in range(10)
            ]
        }

        rows = official_confirmation_rows(active_review)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["video_count"], 10)
        self.assertEqual(len(rows[0]["videos"]), 10)


if __name__ == "__main__":
    unittest.main()
