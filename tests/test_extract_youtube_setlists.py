import unittest

from youtube_channels.extract_youtube_setlists import (
    attach_public_event_matches,
    extract_occurrences,
    extract_setlist,
    parse_youtube_event_date,
    setlist_from_title,
    split_song_list,
    split_title_event_song,
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

    def test_ignores_related_video_numbered_noise(self):
        text = "\n".join([
            "東京の上野公園で広島ふるさと祭りが開催されました。",
            "ーーー",
            "▽Related Videos",
            "[4K]🇯🇵",
            "20万人で賑わう世田谷のボロ市 2024.",
            "https://youtu.be/IFLlDD8L1Tk",
            "B'z ultra soulで盆踊り 新宿 歌舞伎町 BON ODORI 2部",
            "https://youtu.be/mk72RwvRBz4",
        ])
        self.assertEqual(extract_setlist(text), [])

    def test_ignores_numeric_only_song_titles(self):
        text = "1 24 https://youtu.be/aaa\n2 東京音頭 https://youtu.be/bbb"
        self.assertEqual(
            extract_setlist(text),
            [{"number": 2, "title": "東京音頭", "url": "https://www.youtube.com/watch?v=bbb"}],
        )

    def test_extracts_oedo_matsuri_timestamp_chapters_and_matches_current_event(self):
        video_url = "https://www.youtube.com/watch?v=j0tAIB1dOig"
        voices = [
            {
                "source": "youtube",
                "account": "UCKCspf_NrY16rUnODmBqOWA",
                "title": (
                    "[4K]🇯🇵 中央区大江戸まつり盆おどり大会 2025 "
                    "ダンシングヒーロー｜これがお江戸の盆ダンス 他 / "
                    "Japanese Bon dance in Chuo-ku, Tokyo."
                ),
                "text": "\n".join(
                    [
                        "東京の浜町公園で「第35回中央区大江戸まつり盆おどり大会」が開催されました！",
                        "2025.8.22 Fri",
                        "0:00 OP",
                        "0:13 中央区大江戸まつり盆おどり大会 / Chuo-ku Oedo Matsuri Bon Odori Festival",
                        "1:42 これがお江戸の盆ダンス with 土佐兄弟 / Korega Oedo no Bon Dance",
                        "5:40 大東京音頭 / Dai Tokyo Ondo",
                        "9:08 2000年音頭 / 2000 Nen Ondo",
                        "14:05 チャンチキおけさ / Chanchiki Okesa",
                        "17:25 これがお江戸の盆ダンス② / Korega Oedo no Bon Dance②",
                        "21:05 東京音頭 / Tokyo Ondo",
                        "24:41 大東京音頭② / Dai Tokyo Ondo②",
                        "28:09 炭坑節 / Tanko Bushi",
                        "31:47 銀座カンカン娘 / Ginza Kankan Musume",
                        "35:34 会場雰囲気・屋台・フード / Venue atmosphere, food stalls, and food",
                        "40:59 令和音頭 / Reiwa Ondo",
                        "46:16 きよしの数え唄 / Kiyoshi no Kazoeuta",
                        "49:56 バハマ・ママ / Bahama Mama",
                        "53:46 どだればち・サンバ / Dodarebachi Samba",
                        "1:03:50 2000年音頭② / 2000 Nen Ondo②",
                        "1:08:50 ダンシング・ヒーロー / Eat You Up",
                        "1:13:06 きよしのズンドコ節 / Kiyoshi no Zundoko Bushi",
                        "1:24:32 これがお江戸の盆ダンス③ / Korega Oedo no Bon Dance③",
                        "1:28:05 END",
                    ]
                ),
                "url": video_url,
                "date": "2025-08-23T08:00:46Z",
            }
        ]

        occurrences, skipped, _ = extract_occurrences(voices, {})

        self.assertEqual(skipped, [])
        self.assertEqual(len(occurrences), 1)
        self.assertEqual(occurrences[0]["event_name_hint"], "中央区大江戸まつり盆おどり大会")
        self.assertEqual(occurrences[0]["event_date"], "2025-08-22")
        self.assertEqual(occurrences[0]["song_count"], 13)
        self.assertEqual(
            [item["title"] for item in occurrences[0]["setlist"]],
            [
                "これがお江戸の盆ダンス",
                "大東京音頭",
                "2000年音頭",
                "チャンチキおけさ",
                "東京音頭",
                "炭坑節",
                "銀座カンカン娘",
                "令和音頭",
                "きよしの数え唄",
                "バハマ・ママ",
                "どだればち・サンバ",
                "ダンシング・ヒーロー",
                "きよしのズンドコ節",
            ],
        )
        rows = attach_public_event_matches(
            occurrences,
            [
                {
                    "name": "中央区大江戸まつり盆おどり大会",
                    "venue": "浜町公園",
                    "date": "2026-08-21",
                    "date_end": "2026-08-22",
                }
            ],
        )
        self.assertEqual(rows[0]["canonical_event_name"], "中央区大江戸まつり盆おどり大会")
        self.assertEqual(rows[0]["canonical_venue"], "浜町公園")
        self.assertEqual(
            rows[0]["matched_public_event"]["reasons"],
            ["cross_year_event_name_exact", "event_name_exact", "event_key_hint"],
        )

    def test_splits_bracket_event_and_quoted_song_title(self):
        parsed = split_title_event_song("【鴨台盆踊り2025】「東京音頭」 大正大学盆踊り / 大学生主催盆踊り #盆踊り")

        self.assertEqual(parsed["event_name"], "鴨台盆踊り")
        self.assertEqual(parsed["song_title"], "東京音頭")

    def test_splits_quoted_song_list_in_title_into_each_song(self):
        # 動画タイトルの引用部分に複数曲が並んでいるとき、まるごと1曲名として
        # 取り込むと実在しない曲名になる(公開JSONの曲目欄にもそのまま出た)。
        # 末尾の "..." は「以下略」なので曲名から落とす。
        setlist = setlist_from_title(
            {
                "title": (
                    "【新宿二丁目太宗寺盆踊り大会 2026】J-POP＆洋楽セレクション 全10曲 / "
                    "「ジンギスカン / ズンパ音頭 / ダンシングヒーロ- / ultra soul / マツケンサンバ...」#盆踊り"
                ),
                "url": "https://www.youtube.com/watch?v=C1kwmSecDt8",
            }
        )

        self.assertEqual(
            [item["title"] for item in setlist],
            ["ジンギスカン", "ズンパ音頭", "ダンシングヒーロー", "ultra soul", "マツケンサンバ"],
        )
        self.assertEqual([item["number"] for item in setlist], [1, 2, 3, 4, 5])
        for item in setlist:
            self.assertEqual(item["event_name_hint"], "新宿二丁目太宗寺盆踊り大会")
            self.assertEqual(item["evidence_type"], "title_song_fragment")

    def test_keeps_single_song_title_as_one_entry(self):
        setlist = setlist_from_title(
            {
                "title": "【鴨台盆踊り2025】「東京音頭」 大正大学盆踊り / 大学生主催盆踊り #盆踊り",
                "url": "https://www.youtube.com/watch?v=aaa",
            }
        )

        self.assertEqual([item["title"] for item in setlist], ["東京音頭"])

    def test_split_song_list_keeps_titles_that_are_not_lists(self):
        # 曲名自体に含まれるハイフンやアーティスト名は分解対象にしない。
        self.assertEqual(split_song_list("B'z - ultra soul"), ["B'z - ultra soul"])
        self.assertEqual(split_song_list("東京音頭"), ["東京音頭"])
        self.assertEqual(split_song_list(""), [])

    def test_splits_english_song_at_event_title(self):
        parsed = split_title_event_song(
            '4kHDR👘"Kibou no Wadachi" by Southern All Stars at Jiyugaoka Bon Odori Festival in Tokyo Japan 2025'
        )

        self.assertEqual(parsed["event_name"], "Jiyugaoka Bon Odori Festival")
        self.assertEqual(parsed["song_title"], "Kibou no Wadachi")

    def test_splits_song_before_known_japanese_event_title(self):
        parsed = split_title_event_song("JAME盆踊り Y.M.C.A.  GMOシブヤエンタメ祭　20250601")

        self.assertEqual(parsed["event_name"], "GMOシブヤエンタメ祭")
        self.assertEqual(parsed["song_title"], "JAME盆踊り Y.M.C.A.")

    def test_splits_artist_song_before_event_title(self):
        parsed = split_title_event_song(
            "[4K]🇯🇵 B'z - ultra soul 激盛り上がり！DJ盆踊り｜DJ CELLY a.k.a 盆ジョヴィ｜戸田ふるさと祭り 2025 / Bon dance to B'z songs."
        )

        self.assertEqual(parsed["event_name"], "戸田ふるさと祭り")
        self.assertEqual(parsed["song_title"], "B'z - ultra soul")

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

    def test_groups_single_song_videos_by_title_event_and_date(self):
        voices = [
            {
                "source": "youtube",
                "account": "@urbanwalk",
                "title": "【鴨台盆踊り2025】「東京音頭」 大正大学盆踊り 20250720 / 大学生主催盆踊り #盆踊り",
                "text": "",
                "url": "https://www.youtube.com/watch?v=song1",
                "date": "2025-07-20T00:00:00+00:00",
            },
            {
                "source": "youtube",
                "account": "@urbanwalk",
                "title": "【鴨台盆踊り2025】「炭坑節」 大正大学盆踊り 20250720 / 大学生主催盆踊り #盆踊り",
                "text": "",
                "url": "https://www.youtube.com/watch?v=song2",
                "date": "2025-07-20T00:00:00+00:00",
            },
        ]

        occurrences, skipped, _ = extract_occurrences(voices, {})

        self.assertEqual(skipped, [])
        self.assertEqual(len(occurrences), 1)
        self.assertEqual(occurrences[0]["event_name_hint"], "鴨台盆踊り")
        self.assertEqual(occurrences[0]["event_date"], "2025-07-20")
        self.assertEqual(occurrences[0]["song_count"], 2)
        self.assertEqual(
            [item["title"] for item in occurrences[0]["setlist"]],
            ["東京音頭", "炭坑節"],
        )
        self.assertEqual(occurrences[0]["setlist"][0]["evidence_type"], "title_song_fragment")

    def test_does_not_turn_full_event_overview_title_into_song(self):
        voices = [
            {
                "source": "youtube",
                "account": "@tokyohz",
                "title": "Pt.1 Full of Fun!! Kabukicho Bon Odori 2025 in Shinjuku, Tokyo 4K60",
                "text": "",
                "url": "https://www.youtube.com/watch?v=overview",
                "date": "2025-08-17T00:00:00+00:00",
            }
        ]

        occurrences, skipped, _ = extract_occurrences(voices, {})

        self.assertEqual(occurrences, [])
        self.assertEqual(skipped[0]["reason"], "no_numbered_setlist")

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

    def test_matches_cross_year_occurrence_by_curated_event_alias(self):
        rows = attach_public_event_matches(
            [
                {
                    "event_name_hint": "Marunouchi Bon Odori Dance Festival",
                    "venue": "Gyoko Dori",
                    "event_date": "2025-07-26",
                }
            ],
            [
                {
                    "name": "丸の内de盆踊り",
                    "venue": "行幸通り",
                    "date": "2026-07-24",
                }
            ],
        )

        self.assertEqual(rows[0]["canonical_event_name"], "丸の内de盆踊り")
        self.assertEqual(rows[0]["matched_public_event"]["score"], 115)
        self.assertEqual(
            rows[0]["matched_public_event"]["reasons"],
            ["cross_year_event_alias", "event_name_alias", "venue_alias"],
        )

    def test_infers_sanno_event_from_akasaka_hie_title(self):
        voices = [
            {
                "source": "youtube",
                "account": "@wadaikoCH",
                "title": "「大東京音頭」 赤坂日枝神社山王祭盆踊り3 「山王音頭と民踊大会」の風景 2026年6月13日",
                "text": "「東京音頭」での一体感あふれる盆踊り\n"
                        "1 東京音頭 https://youtu.be/aaa\n"
                        "2 炭坑節 https://youtu.be/bbb\n"
                        "3 大東京音頭 https://youtu.be/ccc",
                "url": "https://www.youtube.com/watch?v=main",
                "date": "2026-06-13T00:00:00+00:00",
            }
        ]

        occurrences, skipped, _ = extract_occurrences(voices, {})

        self.assertEqual(skipped, [])
        self.assertEqual(occurrences[0]["event_name_hint"], "山王音頭と民踊大会")
        self.assertEqual(occurrences[0]["venue"], "赤坂日枝神社")


if __name__ == "__main__":
    unittest.main()
