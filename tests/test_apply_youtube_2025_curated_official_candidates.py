import unittest

from legacy.notion_writes.apply_youtube_2025_curated_official_candidates import evidence_note


class ApplyYoutube2025CuratedOfficialCandidatesTest(unittest.TestCase):
    def test_evidence_note_includes_all_video_urls(self):
        item = {
            "event_name": "六本木ヒルズ盆踊り",
            "primary_url": "https://www.roppongihills.com/events/2025/08/0478.html",
            "reason": "official confirmed",
        }
        row = {
            "detected_dates": ["2025-08-23"],
            "video_count": 3,
            "videos": [
                {"video_url": f"https://www.youtube.com/watch?v={idx}", "detected_event_date": "2025-08-23", "title": f"title {idx}"}
                for idx in range(3)
            ],
        }

        note = evidence_note(item, row)

        for idx in range(3):
            self.assertIn(f"https://www.youtube.com/watch?v={idx}", note)

    def test_evidence_note_can_use_item_level_videos(self):
        item = {
            "event_name": "SHIBUYA MIYASHITA PARK BON DANCE 2025",
            "primary_url": "https://miyashita-bondance.jp/2025/",
            "reason": "official archive confirmed",
            "detected_dates": ["2025-09-27", "2025-09-28"],
            "video_count": 1,
            "videos": [
                {
                    "video_url": "https://www.youtube.com/watch?v=dZp8xUrphEE",
                    "detected_event_date": "2025-09-27",
                    "title": "Miyashita Park Bon Dance",
                }
            ],
        }

        note = evidence_note(item, {})

        self.assertIn("2025-09-27, 2025-09-28", note)
        self.assertIn("https://www.youtube.com/watch?v=dZp8xUrphEE", note)


if __name__ == "__main__":
    unittest.main()
