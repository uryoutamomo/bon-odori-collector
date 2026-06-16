import unittest

from export_youtube_2025_second_pass_event_groups import classify_group, title_years


class ExportYoutube2025SecondPassEventGroupsTest(unittest.TestCase):
    def test_classifies_prior_year_video_uploaded_in_2025(self):
        group = {
            "start_date": "2025-09-27",
            "end_date": "",
            "detected_dates": [],
            "sample_videos": [
                {"title": "2024年デコトラ盆踊り"},
                {"title": "品川区民まつり 2024 盆踊り"},
            ],
        }

        classification = classify_group(group)

        self.assertEqual(title_years(group), ["2024"])
        self.assertEqual(classification["category"], "prior_year_video_uploaded_in_2025")

    def test_classifies_prior_year_video_without_notion_date(self):
        group = {
            "start_date": "",
            "end_date": "",
            "detected_dates": [],
            "sample_videos": [{"title": "2024年 京橋盆踊り"}],
        }

        classification = classify_group(group)

        self.assertEqual(classification["category"], "prior_year_video_uploaded_in_2025")

    def test_keeps_2025_title_with_missing_detected_date_in_extraction_bucket(self):
        group = {
            "start_date": "2025-09-27",
            "end_date": "",
            "detected_dates": [],
            "sample_videos": [{"title": "2025年 品川区民まつり 盆踊り"}],
        }

        classification = classify_group(group)

        self.assertEqual(title_years(group), ["2025"])
        self.assertEqual(classification["category"], "notion_date_present_missing_detected_date")


if __name__ == "__main__":
    unittest.main()
