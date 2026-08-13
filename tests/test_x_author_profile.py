import unittest

import collect
from collection_support.x_author_profile import (
    ProfileBioProbe,
    author_profile_description,
)
from collection_support.x_raw_archive import _record


class AuthorProfileTest(unittest.TestCase):
    def test_reads_bio_from_top_level_description(self):
        probe = ProfileBioProbe()
        author = {"userName": "bonsuke", "description": "中央区の町会です"}
        self.assertEqual(author_profile_description(author, probe), "中央区の町会です")
        self.assertEqual(probe.found_by_path, {"description": 1})

    def test_reads_bio_nested_under_profile_bio(self):
        """Reading ``description`` alone returned "" for every account."""
        probe = ProfileBioProbe()
        author = {"userName": "bonsuke", "profile_bio": {"description": "盆オドラーです"}}
        self.assertEqual(author_profile_description(author, probe), "盆オドラーです")
        self.assertEqual(probe.found_by_path, {"profile_bio.description": 1})

    def test_empty_top_level_description_falls_back_to_nested(self):
        probe = ProfileBioProbe()
        author = {"description": "", "profile_bio": {"description": "町会の広報です"}}
        self.assertEqual(author_profile_description(author, probe), "町会の広報です")

    def test_missing_bio_reports_author_keys_without_bio_text(self):
        probe = ProfileBioProbe()
        author = {"userName": "bonsuke", "name": "盆助", "followers": 10}
        self.assertEqual(author_profile_description(author, probe), "")
        report = probe.report()
        self.assertIn("自己紹介文あり 0件", report)
        # The provider's key names are what tells us whether the bio was
        # omitted or merely nested somewhere we do not read yet.
        self.assertIn("followers", report)
        self.assertIn("userName", report)

    def test_report_never_contains_the_bio_itself(self):
        """CI logs of this repository are public."""
        probe = ProfileBioProbe()
        author_profile_description({"description": "個人の自己紹介文"}, probe)
        self.assertNotIn("個人の自己紹介文", probe.report())

    def test_voice_mapping_keeps_a_nested_bio(self):
        tweet = {
            "id": "1",
            "text": "盆踊りに行ってきました",
            "createdAt": "2026-08-13T00:00:00Z",
            "author": {"userName": "bonsuke", "name": "盆助",
                       "profile_bio": {"description": "中央区の盆踊り好き"}},
        }
        voice = collect._x_map_to_voice(tweet)
        self.assertEqual(voice["profile_description"], "中央区の盆踊り好き")

    def test_raw_archive_keeps_a_nested_bio(self):
        tweet = {
            "id": "1",
            "text": "盆踊り",
            "createdAt": "2026-08-13T00:00:00Z",
            "author": {"userName": "bonsuke", "name": "盆助",
                       "profile_bio": {"description": "町会の公式です"}},
        }
        record = _record(tweet, {"route": "query"}, "2026-08-13T00:00:00+00:00")
        self.assertEqual(record["profile_description"], "町会の公式です")

    def test_account_scores_pick_up_a_nested_bio_end_to_end(self):
        """The bio has to survive as far as the account ledger to be usable."""
        voices = [{
            "source": "x", "account": "@bonsuke", "name": "盆助",
            "text": "盆踊りに行ってきました", "url": "https://x.com/bonsuke/status/1",
            "date": "2026-08-13T00:00:00+00:00",
            "profile_description": collect._x_map_to_voice({
                "id": "1", "text": "盆踊り", "createdAt": "2026-08-13T00:00:00Z",
                "author": {"userName": "bonsuke", "profile_bio": {"description": "町会の公式です"}},
            })["profile_description"],
        }]
        scores = collect._build_x_account_scores(voices, {})
        self.assertEqual(scores["accounts"]["bonsuke"]["profile_description"], "町会の公式です")


if __name__ == "__main__":
    unittest.main()
