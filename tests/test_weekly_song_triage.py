import sqlite3
import unittest
from pathlib import Path

from song_processing.song_catalog import SongCatalog
from song_processing.weekly_song_triage import (
    build_song_catalog,
    classify_candidate,
    is_song_like,
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


def insert_song(conn, song_id, title, status="active"):
    conn.execute(
        "INSERT INTO songs(song_id, canonical_title, normalized_title, status) "
        "VALUES (?, ?, ?, ?)",
        (song_id, title, title, status),
    )


def insert_alias(conn, song_id, alias, source="manual"):
    conn.execute(
        "INSERT INTO song_aliases(song_id, alias, normalized_alias, source) "
        "VALUES (?, ?, ?, ?)",
        (song_id, alias, alias, source),
    )


class WeeklySongTriageTest(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()

    def tearDown(self):
        self.conn.close()

    def catalog(self):
        return SongCatalog.from_connection(self.conn)

    def classify(self, term, catalog=None):
        return classify_candidate({"term": term}, catalog or self.catalog())

    def test_canonicalizes_known_sentence_fragments(self):
        # CANONICAL_MAP must still be checked before SongCatalog, regardless
        # of what (if anything) the RDB knows about this term.
        decision, canonical, reason = self.classify("子供用にドラえもん音頭")

        self.assertEqual(decision, "direct")
        self.assertEqual(canonical, "ドラえもん音頭")
        self.assertIn("正規曲名", reason)

    def test_rejects_sentence_fragments(self):
        decision, canonical, reason = self.classify("またその行事内で行われる踊り")

        self.assertEqual(decision, "reject")
        self.assertEqual(canonical, "またその行事内で行われる踊り")
        self.assertIn("文章断片", reason)

    def test_keeps_ambiguous_terms_for_review(self):
        decision, canonical, reason = self.classify("郡上おどり")

        self.assertEqual(decision, "review")
        self.assertEqual(canonical, "郡上おどり")
        self.assertIn("多義語", reason)

    def test_static_lists_outrank_rdb_verified_match(self):
        # Even if the RDB has verified this exact term as a song in its own
        # right, the hardcoded NOISE_EXACT/AMBIGUOUS_TERMS/CANONICAL_MAP
        # lists must still take priority -- P2 only changes what happens
        # after those checks.
        insert_song(self.conn, "song_1", "郡上おどり", status="active")
        decision, canonical, reason = self.classify("郡上おどり")

        self.assertEqual(decision, "review")
        self.assertIn("多義語", reason)

    def test_accepts_song_like_terms(self):
        self.assertTrue(is_song_like("東京音頭"))
        self.assertTrue(is_song_like("南中ソーラン"))
        self.assertFalse(is_song_like("今日は踊り"))

    def test_rdb_verified_canonical_is_direct(self):
        insert_song(self.conn, "song_1", "夜来香", status="active")
        decision, canonical, reason = self.classify("夜来香")

        self.assertEqual(decision, "direct")
        self.assertEqual(canonical, "夜来香")
        self.assertIn("SongCatalog", reason)
        self.assertIn("検証済み", reason)

    def test_rdb_verified_alias_canonicalizes_to_stored_title(self):
        insert_song(self.conn, "song_1", "炭鉱節", status="active")
        insert_alias(self.conn, "song_1", "炭坑節さのさ")
        decision, canonical, reason = self.classify("炭坑節さのさ")

        self.assertEqual(decision, "direct")
        self.assertEqual(canonical, "炭鉱節")
        self.assertIn("SongCatalog", reason)
        self.assertIn("別名", reason)

    def test_rdb_candidate_is_review_even_if_song_like(self):
        # This is the 大人の部-shaped case generalized: an RDB row that is
        # still 候補 (unreviewed) must never be promoted to direct just
        # because it also happens to look like a title shape.
        insert_song(self.conn, "song_1", "夜の踊り子音頭", status="候補")
        decision, canonical, reason = self.classify("夜の踊り子音頭")

        self.assertEqual(decision, "review")
        self.assertEqual(canonical, "夜の踊り子音頭")
        self.assertIn("SongCatalog", reason)
        self.assertIn("未レビュー候補", reason)

    def test_rdb_rejected_is_reject_even_if_song_like(self):
        insert_song(self.conn, "song_1", "偽物音頭", status="無効")
        decision, canonical, reason = self.classify("偽物音頭")

        self.assertEqual(decision, "reject")
        self.assertEqual(canonical, "偽物音頭")
        self.assertIn("SongCatalog", reason)
        self.assertIn("無効", reason)

    def test_rdb_ambiguous_alias_is_review(self):
        insert_song(self.conn, "song_1", "曲A", status="active")
        insert_song(self.conn, "song_2", "曲B", status="active")
        insert_alias(self.conn, "song_1", "共有別名踊り")
        insert_alias(self.conn, "song_2", "共有別名踊り")
        decision, canonical, reason = self.classify("共有別名踊り")

        self.assertEqual(decision, "review")
        self.assertEqual(canonical, "共有別名踊り")
        self.assertIn("SongCatalog", reason)
        self.assertIn("一意に解決できない", reason)

    def test_rdb_match_with_unrecognized_status_fails_closed_to_review(self):
        insert_song(self.conn, "song_1", "謎音頭", status="draft")
        decision, canonical, reason = self.classify("謎音頭")

        self.assertEqual(decision, "review")
        self.assertEqual(canonical, "謎音頭")
        self.assertIn("SongCatalog", reason)
        self.assertIn("fail closed", reason)

    def test_no_rdb_match_falls_back_to_shape_heuristic_direct(self):
        # 東京音頭 is not in CANONICAL_MAP/NOISE_EXACT/AMBIGUOUS_TERMS and the
        # RDB has nothing for it here, so it must fall back to is_song_like()
        # exactly as before P2.
        decision, canonical, reason = self.classify("東京音頭")

        self.assertEqual(decision, "direct")
        self.assertEqual(canonical, "東京音頭")
        self.assertIn("接尾辞", reason)

    def test_no_rdb_match_falls_back_to_shape_heuristic_reject(self):
        decision, canonical, reason = self.classify("謎の未知語")

        self.assertEqual(decision, "reject")
        self.assertEqual(canonical, "謎の未知語")
        self.assertIn("形が弱い", reason)


class BuildSongCatalogWiringTest(unittest.TestCase):
    def test_opens_db_read_only_and_returns_catalog(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "master.sqlite"
            with sqlite3.connect(db_path) as file_conn:
                file_conn.executescript(
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
                file_conn.execute(
                    "INSERT INTO songs(song_id, canonical_title, normalized_title, status) "
                    "VALUES ('song_1', '東京音頭', '東京音頭', 'active')"
                )
                file_conn.commit()

            catalog = build_song_catalog(db_path)
            self.assertTrue(catalog.is_verified("東京音頭"))

    def test_missing_db_file_fails_explicitly_no_static_fallback(self):
        with self.assertRaises(sqlite3.OperationalError):
            build_song_catalog(Path("/nonexistent/path/does-not-exist.sqlite"))

    def test_schema_drift_fails_explicitly_no_static_fallback(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "bad_schema.sqlite"
            with sqlite3.connect(db_path) as conn:
                conn.execute("CREATE TABLE unrelated (id INTEGER PRIMARY KEY)")
                conn.commit()

            with self.assertRaises(sqlite3.OperationalError):
                build_song_catalog(db_path)


if __name__ == "__main__":
    unittest.main()
