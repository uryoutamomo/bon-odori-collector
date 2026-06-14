import unittest

from extract_youtube_setlists import (
    attach_public_event_matches,
    extract_occurrences,
    extract_setlist,
    parse_youtube_event_date,
)


class ExtractYoutubeSetlistsTest(unittest.TestCase):
    def test_extracts_numbered_setlist_with_urls(self):
        text = "\n".join([
            "飛鳥山公園盆踊り（舞ことり）",
            "１東京音頭 https://youtu.be/aaa",
            "２ 荒川音頭 https://www.youtube.com/watch?v=bbb",
        ])
        rows = extract_setlist(text)
        self.assertEqual(
            rows,
            [
                {"number": 1, "title": "東京音頭", "url": "https://www.youtube.com/watch?v=aaa"},
                {"number": 2, "title": "荒川音頭", "url": "https://www.youtube.com/watch?v=bbb"},
            ],
        )

    def test_groups_same_event_series_by_venue_date_and_account(self):
        voices = [
            {
                "source": "youtube",
                "account": "@wadaikoCH",
                "title": "東京音頭　飛鳥山公園輪踊り　2026年5月24日",
                "text": "2026年5月24日行われました。\n飛鳥山公園盆踊り（舞ことり）\n"
                        "1 東京音頭 https://youtu.be/aaa\n2 荒川音頭 https://youtu.be/bbb",
                "url": "https://www.youtube.com/watch?v=main1",
                "date": "2026-06-01T00:00:00+00:00",
            },
            {
                "source": "youtube",
                "account": "@wadaikoCH",
                "title": "荒川音頭　飛鳥山公園輪踊り　2026年5月24日",
                "text": "2026年5月24日行われました。\n飛鳥山公園盆踊り（舞ことり）\n"
                        "1 東京音頭 https://youtu.be/aaa\n2 荒川音頭 https://youtu.be/bbb",
                "url": "https://www.youtube.com/watch?v=main2",
                "date": "2026-06-02T00:00:00+00:00",
            },
        ]
        occurrences, skipped, _ = extract_occurrences(voices, {})
        self.assertEqual(len(occurrences), 1)
        self.assertEqual(skipped, [])
        self.assertEqual(occurrences[0]["venue"], "飛鳥山公園")
        self.assertEqual(occurrences[0]["event_date"], "2026-05-24")
        self.assertEqual(occurrences[0]["song_count"], 2)
        self.assertEqual(occurrences[0]["source_video_count"], 2)
        self.assertEqual(occurrences[0]["accounts"], ["@wadaikoCH"])
        self.assertEqual(occurrences[0]["source_videos"][0]["account"], "@wadaikoCH")

    def test_groups_same_event_across_accounts(self):
        voices = [
            {
                "source": "youtube",
                "account": "@matsuribonodori",
                "title": "東京音頭　横浜開港祭 BON ODORI 20260601",
                "text": "パシフィコ横浜 プラザ広場で開催された横浜開港祭 BON ODORI\n"
                        "1 東京音頭 https://youtu.be/aaa\n2 炭坑節 https://youtu.be/bbb",
                "url": "https://www.youtube.com/watch?v=main1",
                "date": "2026-06-02T00:00:00+00:00",
            },
            {
                "source": "youtube",
                "account": "@wadaikoCH",
                "title": "よこはまアラメヤ音頭　横浜開港祭 BON ODORI 20260601",
                "text": "パシフィコ横浜 プラザ広場で開催された横浜開港祭 BON ODORI\n"
                        "1 東京音頭 https://youtu.be/aaa\n2 よこはまアラメヤ音頭 https://youtu.be/ccc",
                "url": "https://www.youtube.com/watch?v=main2",
                "date": "2026-06-03T00:00:00+00:00",
            },
        ]
        occurrences, skipped, _ = extract_occurrences(voices, {})
        self.assertEqual(skipped, [])
        self.assertEqual(len(occurrences), 1)
        self.assertEqual(occurrences[0]["venue"], "パシフィコ横浜プラザ広場")
        self.assertEqual(occurrences[0]["event_date"], "2026-06-01")
        self.assertEqual(occurrences[0]["song_count"], 3)
        self.assertEqual(occurrences[0]["source_video_count"], 2)
        self.assertEqual(occurrences[0]["accounts"], ["@matsuribonodori", "@wadaikoCH"])

    def test_deduplicates_setlist_by_song_title_across_numbers(self):
        voices = [
            {
                "source": "youtube",
                "account": "@matsuribonodori",
                "title": "横浜開港祭 BON ODORI 20260601",
                "text": "パシフィコ横浜 プラザ広場で開催された横浜開港祭 BON ODORI\n"
                        "1 よこはまアラメヤ音頭 https://youtu.be/aaa\n"
                        "9 よこはまアラメヤ音頭(2部) https://youtu.be/bbb",
                "url": "https://www.youtube.com/watch?v=main1",
                "date": "2026-06-02T00:00:00+00:00",
            },
            {
                "source": "youtube",
                "account": "@wadaikoCH",
                "title": "横浜開港祭 BON ODORI 20260601",
                "text": "パシフィコ横浜 プラザ広場で開催された横浜開港祭 BON ODORI\n"
                        "1 終 よこはまアラメヤ音頭 https://youtu.be/ccc\n"
                        "2 野毛山節 https://youtu.be/ddd",
                "url": "https://www.youtube.com/watch?v=main2",
                "date": "2026-06-03T00:00:00+00:00",
            },
        ]
        occurrences, _, _ = extract_occurrences(voices, {})
        self.assertEqual(occurrences[0]["song_count"], 2)
        self.assertEqual(
            [item["title"] for item in occurrences[0]["setlist"]],
            ["よこはまアラメヤ音頭", "野毛山節"],
        )

    def test_uses_existing_review_hint_for_known_url(self):
        voices = [
            {
                "source": "youtube",
                "account": "@matsuribonodori",
                "title": "東京音頭 2026年6月1日",
                "text": "2026年6月1日\n横浜開港祭盆踊り\n"
                        "1 東京音頭 https://youtu.be/aaa\n2 炭坑節 https://youtu.be/bbb",
                "url": "https://www.youtube.com/watch?v=known",
                "date": "2026-06-02T00:00:00+00:00",
            }
        ]
        review = {
            "events": [
                {
                    "event_key": "yokohama",
                    "event_name": "横浜開港祭 BON ODORI",
                    "venue": "パシフィコ横浜プラザ広場",
                    "songs": [{"urls": ["https://www.youtube.com/watch?v=known"]}],
                }
            ]
        }
        occurrences, _, _ = extract_occurrences(voices, review)
        self.assertEqual(occurrences[0]["event_key_hint"], "yokohama")
        self.assertEqual(occurrences[0]["venue"], "パシフィコ横浜プラザ広場")

    def test_parses_compact_yyyymmdd_date(self):
        self.assertEqual(
            parse_youtube_event_date("マロニエまつり盆踊り大会 20260509"),
            "2026-05-09",
        )

    def test_parses_dot_separated_date(self):
        self.assertEqual(
            parse_youtube_event_date("東京丸の内盆踊り2025.7.25"),
            "2025-07-25",
        )

    def test_skips_numbered_non_bon_odori_video_lists(self):
        voices = [
            {
                "source": "youtube",
                "account": "@wadaikoCH",
                "title": "鳥越神社「鳥越まつり」神輿渡御 2026年6月7日",
                "text": "鳥越神社の神輿渡御\n1 渡御ダイジェスト https://youtu.be/aaa\n"
                        "2 宮入りダイジェスト https://youtu.be/bbb",
                "url": "https://www.youtube.com/watch?v=main",
                "date": "2026-06-08T00:00:00+00:00",
            }
        ]
        occurrences, skipped, _ = extract_occurrences(voices, {})
        self.assertEqual(occurrences, [])
        self.assertEqual(skipped[0]["reason"], "not_bon_odori_setlist")

    def test_matches_public_event_by_date_and_name_when_venue_differs(self):
        occurrences = [
            {
                "event_name_hint": "山王音頭と民踊大会",
                "venue": "赤坂日枝神社",
                "event_date": "2026-06-13",
            }
        ]
        public_events = [
            {
                "name": "山王音頭と民踊大会",
                "venue": "山王パークタワー公開空地",
                "date": "2026-06-13",
                "date_end": "2026-06-15",
            }
        ]
        rows = attach_public_event_matches(occurrences, public_events)
        self.assertEqual(rows[0]["canonical_event_name"], "山王音頭と民踊大会")
        self.assertEqual(rows[0]["canonical_venue"], "山王パークタワー公開空地")
        self.assertIn("event_name_exact", rows[0]["matched_public_event"]["reasons"])


if __name__ == "__main__":
    unittest.main()
