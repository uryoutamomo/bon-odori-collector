import sqlite3
import unittest
from contextlib import closing

import apply_youtube_setlist_occurrences_rdb as apply_setlists
from master_rdb.master_db import normalize_text, stable_id


SONGS_SCHEMA = """
CREATE TABLE songs (
  song_id TEXT PRIMARY KEY,
  canonical_title TEXT NOT NULL,
  normalized_title TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL,
  memo TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""

NOW = "2026-07-26T00:00:00+00:00"

# 2026-07-24 GMOシブヤエンタメ祭 の実データ。9曲すべてに配信側のラベルが付いている。
JAME_SETLIST = [
    "JAME盆踊り BOY MEETS GIRL (TRF)",
    "JAME盆踊り EZ DO DANCE (TRF)",
    "JAME盆踊り GET WILD (TM NETWORK)",
    "JAME盆踊り Y.M.C.A.",
    "JAME盆踊り survival dAnce (TRF)",
    "JAME盆踊り とっとこハム太郎",
]


def songs_db(rows=()):
    conn = sqlite3.connect(":memory:")
    conn.executescript(SONGS_SCHEMA)
    for canonical, normalized, status, song_id in rows:
        conn.execute(
            "INSERT INTO songs(song_id, canonical_title, normalized_title, status, memo,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
            (song_id, canonical, normalized, status, "", NOW, NOW),
        )
    return conn


class SharedSetlistLabelTest(unittest.TestCase):
    def test_strips_label_shared_by_every_title(self):
        label = apply_setlists.shared_setlist_label(JAME_SETLIST, set())

        self.assertEqual(label, "JAME盆踊り")
        self.assertEqual(
            apply_setlists.strip_shared_label(JAME_SETLIST[0], label),
            "BOY MEETS GIRL (TRF)",
        )

    def test_keeps_titles_when_the_leading_token_differs(self):
        titles = ["東京音頭", "炭坑節", "きよしのズンドコ節"]

        self.assertEqual(apply_setlists.shared_setlist_label(titles, set()), "")

    def test_keeps_a_shared_leading_token_that_is_itself_a_known_song(self):
        # "東京音頭 一番" 形式の設定表。ラベルではなく曲名なので削ってはいけない。
        titles = ["東京音頭 一番", "東京音頭 二番", "東京音頭 三番"]
        known = {normalize_text("東京音頭")}

        self.assertEqual(apply_setlists.shared_setlist_label(titles, known), "")

    def test_ignores_a_setlist_too_short_to_trust(self):
        titles = ["JAME盆踊り GET WILD", "JAME盆踊り Y.M.C.A."]

        self.assertEqual(apply_setlists.shared_setlist_label(titles, set()), "")

    def test_does_not_strip_when_a_title_is_only_the_label(self):
        titles = ["JAME盆踊り", "JAME盆踊り GET WILD", "JAME盆踊り Y.M.C.A."]

        self.assertEqual(apply_setlists.shared_setlist_label(titles, set()), "")

    def test_strip_shared_label_leaves_titles_without_the_label(self):
        self.assertEqual(apply_setlists.strip_shared_label("東京音頭", "JAME盆踊り"), "東京音頭")
        self.assertEqual(apply_setlists.strip_shared_label("東京音頭", ""), "東京音頭")


class NonSongShapeCheckTest(unittest.TestCase):
    # occurrence_songs は公開層なので、ここを抜けたものは公開サイトに曲として出る。
    def test_rejects_titles_that_are_not_song_names(self):
        for title in (
            "花園直道 with JPN dancers",  # 出演者クレジット
            "半浦青年団",  # 団体名
            "3回分マルチ編集",  # 動画側のメモ
            "DJタイム",  # 進行の見出し
            "DJ「俚謡山脈」",
            "大森日雅",  # アニソン盆踊りの出演者（声優）
            "The Police",  # バンド名
            "Traditional Japanese",  # 英語のジャンル表記
            "Awaodori",  # 2026-07-26 内田さん判定
            "カワサキ",  # 同上
        ):
            with self.subTest(title=title):
                self.assertFalse(apply_setlists.song_title_passes_shape_check(title))

    def test_keeps_real_song_titles(self):
        for title in (
            "東京音頭",
            "邪神ちゃん音頭",
            "マツケンサンバ",
            "ダンシングヒーロー",
            "会津磐梯山",
            "Let's ONDO Again",
            "嵐",  # 2026-07-26 内田さん判定「嵐だけ曲」
        ):
            with self.subTest(title=title):
                self.assertTrue(apply_setlists.song_title_passes_shape_check(title))


class ResolveSongTest(unittest.TestCase):
    def test_label_stripped_title_matches_the_curated_master(self):
        with closing(
            songs_db([("GET WILD", normalize_text("GET WILD"), "有効", "song_0001")])
        ) as conn:
            label = apply_setlists.shared_setlist_label(JAME_SETLIST, set())

            song_id, display_title, verdict = apply_setlists.resolve_song(
                conn,
                apply_setlists.strip_shared_label("JAME盆踊り GET WILD (TM NETWORK)", label),
                "GMOシブヤエンタメ祭",
                NOW,
            )

            self.assertEqual((song_id, display_title, verdict), ("song_0001", "GET WILD", "matched"))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0], 1)

    def test_reuses_a_row_whose_song_id_predates_a_manual_title_repair(self):
        # 2026-07-24 の手作業修正の再現。song_id は汚れた表記由来のまま、
        # canonical/normalized だけ整形済みになっている行。
        dirty_normalized = normalize_text("JAME盆踊り BOY MEETS GIRL")
        repaired_id = stable_id("song_cand", dirty_normalized)
        with closing(
            songs_db([("BOY MEETS GIRL", normalize_text("BOY MEETS GIRL"), "候補", repaired_id)])
        ) as conn:
            song_id, display_title, verdict = apply_setlists.resolve_song(
                conn, "JAME盆踊り BOY MEETS GIRL", "GMOシブヤエンタメ祭", NOW
            )

            self.assertEqual(song_id, repaired_id)
            self.assertEqual(display_title, "BOY MEETS GIRL")
            self.assertEqual(verdict, "candidate_existing")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0], 1)

    def test_registers_an_unseen_plausible_title_as_a_candidate(self):
        with closing(songs_db()) as conn:
            song_id, display_title, verdict = apply_setlists.resolve_song(
                conn, "邪神ちゃん音頭", "", NOW
            )

            self.assertEqual(verdict, "candidate_new")
            self.assertEqual(display_title, "邪神ちゃん音頭")
            row = conn.execute(
                "SELECT canonical_title, normalized_title, status FROM songs WHERE song_id = ?",
                (song_id,),
            ).fetchone()
            self.assertEqual(row, ("邪神ちゃん音頭", normalize_text("邪神ちゃん音頭"), "候補"))


if __name__ == "__main__":
    unittest.main()
