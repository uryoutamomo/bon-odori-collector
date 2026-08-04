import sqlite3
import unittest

from song_processing.song_catalog import (
    SongCatalog,
    SongMatchType,
    SongReviewState,
)


def make_db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE songs (
          song_id TEXT PRIMARY KEY,
          canonical_title TEXT NOT NULL,
          normalized_title TEXT NOT NULL UNIQUE,
          status TEXT NOT NULL DEFAULT 'active'
        );
        CREATE TABLE song_aliases (
          song_id TEXT NOT NULL,
          alias TEXT NOT NULL,
          normalized_alias TEXT NOT NULL,
          source TEXT NOT NULL,
          confidence TEXT NOT NULL DEFAULT 'manual',
          PRIMARY KEY (song_id, normalized_alias)
        );
        """
    )
    return conn


class TestSongCatalog(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()

    def tearDown(self):
        self.conn.close()

    def insert_song(self, song_id, title, status="active"):
        self.conn.execute(
            "INSERT INTO songs(song_id, canonical_title, normalized_title, status) "
            "VALUES (?, ?, ?, ?)",
            (song_id, title, title, status),
        )

    def insert_alias(self, song_id, alias, source="manual"):
        self.conn.execute(
            "INSERT INTO song_aliases(song_id, alias, normalized_alias, source) "
            "VALUES (?, ?, ?, ?)",
            (song_id, alias, alias, source),
        )

    def test_canonical_verified_active(self):
        self.insert_song("song_1", "東京音頭", status="active")
        catalog = SongCatalog.from_connection(self.conn)
        res = catalog.resolve("東京音頭")
        self.assertEqual(res.match_type, SongMatchType.CANONICAL)
        self.assertEqual(res.review_state, SongReviewState.VERIFIED)
        self.assertEqual(res.song_id, "song_1")
        self.assertTrue(catalog.is_verified("東京音頭"))

    def test_canonical_verified_yuko(self):
        # 有効 (Japanese "valid/effective") must map to VERIFIED, same as active.
        self.insert_song("song_1", "佐竹音頭", status="有効")
        catalog = SongCatalog.from_connection(self.conn)
        res = catalog.resolve("佐竹音頭")
        self.assertEqual(res.review_state, SongReviewState.VERIFIED)
        self.assertTrue(catalog.is_verified("佐竹音頭"))

    def test_alias_verified(self):
        self.insert_song("song_1", "炭鉱節", status="active")
        self.insert_alias("song_1", "炭坑節")
        catalog = SongCatalog.from_connection(self.conn)
        res = catalog.resolve("炭坑節")
        self.assertEqual(res.match_type, SongMatchType.ALIAS)
        self.assertEqual(res.review_state, SongReviewState.VERIFIED)
        self.assertEqual(res.canonical_title, "炭鉱節")

    def test_candidate_is_not_verified(self):
        # This is the exact bug found on 2026-08-04: 大人の部 was treated as
        # a known song via a "候補" (candidate) row. candidate must resolve
        # but must never count as verified.
        self.insert_song("song_1", "大人の部", status="候補")
        catalog = SongCatalog.from_connection(self.conn)
        res = catalog.resolve("大人の部")
        self.assertEqual(res.match_type, SongMatchType.CANONICAL)
        self.assertEqual(res.review_state, SongReviewState.CANDIDATE)
        self.assertFalse(catalog.is_verified("大人の部"))

    def test_rejected_is_not_verified(self):
        self.insert_song("song_1", "夜の踊り子", status="無効")
        catalog = SongCatalog.from_connection(self.conn)
        res = catalog.resolve("夜の踊り子")
        self.assertEqual(res.review_state, SongReviewState.REJECTED)
        self.assertFalse(catalog.is_verified("夜の踊り子"))

    def test_unrecognized_status_is_unknown_not_verified(self):
        # An unrecognized status string must fail closed to UNKNOWN, never
        # be silently promoted to VERIFIED.
        self.insert_song("song_1", "謎の曲", status="draft")
        catalog = SongCatalog.from_connection(self.conn)
        res = catalog.resolve("謎の曲")
        self.assertEqual(res.review_state, SongReviewState.UNKNOWN)
        self.assertFalse(catalog.is_verified("謎の曲"))

    def test_missing_term_resolves_to_none(self):
        self.insert_song("song_1", "東京音頭", status="active")
        catalog = SongCatalog.from_connection(self.conn)
        res = catalog.resolve("周辺で開かれる街なかの踊り")
        self.assertEqual(res.match_type, SongMatchType.NONE)
        self.assertEqual(res.review_state, SongReviewState.UNKNOWN)
        self.assertIsNone(res.song_id)
        self.assertFalse(catalog.is_verified("周辺で開かれる街なかの踊り"))

    def test_ambiguous_alias_is_not_silently_resolved(self):
        self.insert_song("song_1", "曲A", status="active")
        self.insert_song("song_2", "曲B", status="active")
        self.insert_alias("song_1", "共有別名")
        self.insert_alias("song_2", "共有別名")
        catalog = SongCatalog.from_connection(self.conn)
        res = catalog.resolve("共有別名")
        self.assertEqual(res.match_type, SongMatchType.AMBIGUOUS_ALIAS)
        self.assertIsNone(res.song_id)
        self.assertFalse(catalog.is_verified("共有別名"))

    def test_canonical_wins_over_conflicting_alias_of_another_song(self):
        # ふるさと音頭 registers itself as its own alias (self-registration is
        # common in this dataset -- 141 such rows exist in production). This
        # must resolve as a canonical match, not trip ambiguous_alias.
        self.insert_song("song_1", "ふるさと音頭", status="active")
        self.insert_alias("song_1", "ふるさと音頭")
        catalog = SongCatalog.from_connection(self.conn)
        res = catalog.resolve("ふるさと音頭")
        self.assertEqual(res.match_type, SongMatchType.CANONICAL)
        self.assertEqual(res.review_state, SongReviewState.VERIFIED)

    def test_canonical_wins_when_another_songs_alias_collides(self):
        # If song A's canonical title happens to equal song B's alias, the
        # query for that string must resolve to the canonical match (song A),
        # not the alias match (song B).
        self.insert_song("song_a", "東京音頭", status="active")
        self.insert_song("song_b", "大東京音頭", status="active")
        self.insert_alias("song_b", "東京音頭")
        catalog = SongCatalog.from_connection(self.conn)
        res = catalog.resolve("東京音頭")
        self.assertEqual(res.match_type, SongMatchType.CANONICAL)
        self.assertEqual(res.song_id, "song_a")

    def test_reading_does_not_mutate_db(self):
        self.insert_song("song_1", "東京音頭", status="active")
        self.insert_alias("song_1", "とうきょうおんど")
        self.conn.commit()
        before_songs = self.conn.execute("SELECT * FROM songs").fetchall()
        before_aliases = self.conn.execute("SELECT * FROM song_aliases").fetchall()

        catalog = SongCatalog.from_connection(self.conn)
        catalog.resolve("東京音頭")
        catalog.resolve("とうきょうおんど")
        catalog.resolve("存在しない曲")
        catalog.is_verified("東京音頭")

        after_songs = self.conn.execute("SELECT * FROM songs").fetchall()
        after_aliases = self.conn.execute("SELECT * FROM song_aliases").fetchall()
        self.assertEqual(before_songs, after_songs)
        self.assertEqual(before_aliases, after_aliases)

    def test_normalization_ignores_whitespace_and_case(self):
        self.insert_song("song_1", "Bon Dance", status="active")
        catalog = SongCatalog.from_connection(self.conn)
        res = catalog.resolve("bon dance")
        self.assertEqual(res.match_type, SongMatchType.CANONICAL)
        self.assertEqual(res.song_id, "song_1")

    def test_empty_query_resolves_to_none(self):
        catalog = SongCatalog.from_connection(self.conn)
        res = catalog.resolve("")
        self.assertEqual(res.match_type, SongMatchType.NONE)
        self.assertFalse(catalog.is_verified(""))


if __name__ == "__main__":
    unittest.main()
