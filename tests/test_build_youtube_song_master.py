import unittest

from build_youtube_song_master import aggregate_occurrences


def occurrence(song_names):
    return {
        "occurrence_id": "occ-1",
        "event_name": "郡上おどり in 青山",
        "venue": "秩父宮ラグビー場駐車場",
        "year": 2025,
        "songs": [
            {
                "song_name": name,
                "evidence": [
                    {
                        "reliability_key": "complete_numbered_video",
                        "source": "youtube_setlist_occurrence",
                        "speaker": "sample",
                        "url": f"https://example.test/{index}",
                    }
                ],
            }
            for index, name in enumerate(song_names)
        ],
    }


class BuildYoutubeSongMasterTest(unittest.TestCase):
    def test_canonicalizes_gujo_kawasaki_variants(self):
        rows, rejected, _ = aggregate_occurrences(
            {"occurrences": [occurrence(["郡上かわさき", "郡上節かわさき", "古調かわさき"])]}
        )

        by_name = {row["song_name"]: row for row in rows}
        self.assertIn("かわさき", by_name)
        self.assertIn("古調かわさき", by_name)
        self.assertNotIn("郡上かわさき", by_name)
        self.assertNotIn("郡上節かわさき", by_name)
        self.assertEqual(by_name["かわさき"]["good_evidence_count"], 2)
        self.assertEqual(rejected, {})

    def test_rejects_kawasaki_event_name_fragments(self):
        rows, rejected, _ = aggregate_occurrences({"occurrences": [occurrence(["川崎おどり", "川崎踊り"])]})

        self.assertEqual(rows, [])
        self.assertEqual(rejected["手動レビューで曲マスター除外"], 2)

    def test_canonicalizes_2000_ondo_digit_loss(self):
        rows, rejected, _ = aggregate_occurrences({"occurrences": [occurrence(["000年音頭", "２０００年音頭"])]})

        by_name = {row["song_name"]: row for row in rows}
        self.assertIn("2000年音頭", by_name)
        self.assertNotIn("000年音頭", by_name)
        self.assertNotIn("２０００年音頭", by_name)
        self.assertEqual(by_name["2000年音頭"]["good_evidence_count"], 2)
        self.assertNotIn("000年音頭", by_name["2000年音頭"]["aliases"])
        self.assertEqual(rejected, {})

    def test_canonicalizes_shonen_yagibushi_into_yagibushi(self):
        rows, rejected, _ = aggregate_occurrences({"occurrences": [occurrence(["少年八木節", "八木節"])]})

        by_name = {row["song_name"]: row for row in rows}
        self.assertIn("八木節", by_name)
        self.assertNotIn("少年八木節", by_name)
        self.assertEqual(by_name["八木節"]["good_evidence_count"], 2)
        self.assertIn("少年八木節", by_name["八木節"]["aliases"])
        self.assertEqual(rejected, {})


if __name__ == "__main__":
    unittest.main()
