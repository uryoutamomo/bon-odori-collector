import unittest

from build_youtube_channel_review import build_review, review_channel


class BuildYoutubeChannelReviewTest(unittest.TestCase):
    def test_marks_known_channel_as_already_registered(self):
        review = review_channel({
            "already_known": True,
            "candidate_score": 86,
            "channel_title": "祭のきせき　盆踊り",
        })

        self.assertEqual(review["decision"], "already_registered")
        self.assertEqual(review["priority"], "high")

    def test_applies_manual_adopt_review(self):
        review = review_channel({
            "channel_id": "UCKCspf_NrY16rUnODmBqOWA",
            "channel_title": "Tokyo Lonely Walker",
            "candidate_score": 90,
        })

        self.assertEqual(review["decision"], "adopt")
        self.assertEqual(review["priority"], "high")
        self.assertIn("日付検証", review["reason"])

    def test_holds_single_walk_channel(self):
        review = review_channel({
            "channel_id": "UCLGUldYbdjEFLjwzFm70qgw",
            "channel_title": "VioletVik",
            "candidate_score": 12,
        })

        self.assertEqual(review["decision"], "hold")
        self.assertEqual(review["priority"], "low")

    def test_build_review_counts_and_order(self):
        output = build_review({
            "channels": [
                {
                    "channel_id": "UCLGUldYbdjEFLjwzFm70qgw",
                    "channel_title": "VioletVik",
                    "candidate_score": 12,
                    "sample_videos": [],
                },
                {
                    "channel_id": "UCKCspf_NrY16rUnODmBqOWA",
                    "channel_title": "Tokyo Lonely Walker",
                    "candidate_score": 90,
                    "sample_videos": [{"title": "渋谷盆踊り", "url": "https://youtu.be/x"}],
                },
                {
                    "channel_id": "UCLSZK_q5ma6aeIrVRUEpkNw",
                    "channel_title": "祭のきせき　盆踊り",
                    "already_known": True,
                    "candidate_score": 86,
                    "sample_videos": [],
                },
            ]
        })

        self.assertEqual(output["counts"], {"adopt": 1, "already_registered": 1, "hold": 1})
        self.assertEqual(output["rows"][0]["decision"], "adopt")
        self.assertEqual(output["rows"][1]["decision"], "already_registered")


if __name__ == "__main__":
    unittest.main()
