import json
import sqlite3
import unittest
from pathlib import Path

import build_song_catalog_shadow_report as shadow


def make_db(path):
    conn = sqlite3.connect(path)
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
    conn.execute(
        "INSERT INTO songs VALUES ('song_1','東京音頭','東京音頭','active')"
    )
    conn.execute(
        "INSERT INTO songs VALUES ('song_2','大人の部','大人の部','候補')"
    )
    conn.execute(
        "INSERT INTO songs VALUES ('song_3','夜の踊り子','夜の踊り子','無効')"
    )
    conn.execute(
        "INSERT INTO songs VALUES ('song_4','曲A','曲A','active')"
    )
    conn.execute(
        "INSERT INTO songs VALUES ('song_5','曲B','曲B','active')"
    )
    conn.execute(
        # RDB-only verified song: not in either static file, so this row
        # must surface as rdb_verified_only, not same_verified.
        "INSERT INTO songs VALUES ('song_6','RDB専用音頭','RDB専用音頭','active')"
    )
    conn.execute(
        # A row whose status is neither active/有効/候補/無効: SongCatalog
        # resolves this to UNKNOWN. Even though the same string is also in
        # the static provider, an RDB match with UNKNOWN status must be
        # reported as unresolved, not static_only or same_verified.
        "INSERT INTO songs VALUES ('song_7','謎ステータス曲','謎ステータス曲','draft')"
    )
    conn.execute(
        # Lowercase in the RDB; the static file registers the uppercase
        # form (see setUp). Legacy static membership (whitespace removal +
        # casefold) must treat these as the same value even though they are
        # not the same literal string -- this reproduces the real
        # discrepancy oto found in production (One Love / Runner /
        # ultra soul all differ from their RDB form only by case).
        "INSERT INTO songs VALUES ('song_8','one love','one love','active')"
    )
    conn.execute(
        "INSERT INTO song_aliases VALUES "
        "('song_4','共有別名','共有別名','manual','manual')"
    )
    conn.execute(
        "INSERT INTO song_aliases VALUES "
        "('song_5','共有別名','共有別名','manual','manual')"
    )
    conn.commit()
    conn.close()


class TestShadowReport(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmpdir = Path(tempfile.mkdtemp())
        self.db_path = self.tmpdir / "master.sqlite"
        make_db(self.db_path)

        self.registration_path = self.tmpdir / "song_master_initial_registration.json"
        self.registration_path.write_text(
            json.dumps(
                {
                    "created": [
                        {"song_name": "東京音頭"},
                        {"song_name": "静的専用曲"},
                        # Registered uppercase in static; the RDB has the
                        # same song lowercase (song_8 "one love"). Legacy
                        # static membership normalizes via whitespace
                        # removal + casefold only (bon_odori_songs.
                        # _norm_song), so these must be treated as the same
                        # value despite not being the same literal string.
                        {"song_name": "ONE LOVE"},
                    ],
                    "skipped": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        self.review_source_path = self.tmpdir / "rdb_song_review_source.json"
        self.review_source_path.write_text(
            json.dumps(
                {
                    "rows": [
                        {"canonical_song_name": "大人の部", "status": "needs_song_master_review"},
                        {"canonical_song_name": "謎ステータス曲", "status": "needs_song_master_review"},
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        self.weekly_path = self.tmpdir / "weekly_harvest_candidates.json"
        self.weekly_path.write_text(
            json.dumps(
                {
                    "rows": [
                        {"term": "東京音頭", "category": "曲候補"},
                        {"term": "夜の踊り子", "category": "曲候補"},
                        {"term": "未知の候補", "category": "曲候補"},
                        # Non-song-candidate categories exist in the same
                        # file (曲×会場共起, 用語候補) and must be excluded --
                        # their `term` values are not song-name candidates.
                        {"term": "築地本願寺 × 何か", "category": "曲×会場共起"},
                        {"term": "用語その他", "category": "用語候補"},
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        self.public_path = self.tmpdir / "events_public.json"
        self.public_path.write_text(
            json.dumps(
                {"events": [{"songs": [{"name": "東京音頭"}, {"name": "共有別名"}]}]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def build(self):
        return shadow.build_report(
            db_path=self.db_path,
            registration_path=self.registration_path,
            review_source_path=self.review_source_path,
            weekly_path=self.weekly_path,
            public_path=self.public_path,
        )

    def test_all_divergence_codes_present_in_fixture(self):
        report = self.build()
        by_value = {row["value"]: row for row in report["rows"]}

        # same_verified: 東京音頭 is in both static and RDB (verified).
        self.assertEqual(by_value["東京音頭"]["divergence"], shadow.DIVERGENCE_SAME_VERIFIED)

        # static_only: 静的専用曲 is only in the static registration file.
        self.assertEqual(by_value["静的専用曲"]["divergence"], shadow.DIVERGENCE_STATIC_ONLY)

        # rdb_verified_only: RDB専用音頭 is a verified RDB song absent from
        # either static file.
        self.assertEqual(by_value["RDB専用音頭"]["divergence"], shadow.DIVERGENCE_RDB_VERIFIED_ONLY)
        self.assertFalse(by_value["RDB専用音頭"]["static_is_master"])

        # rdb_candidate_only: 大人の部 is "known" per static (via the
        # unreviewed rdb_song_review_source.json) but is only a candidate
        # in the RDB -- this is the exact 2026-08-04 bug shape.
        self.assertEqual(by_value["大人の部"]["divergence"], shadow.DIVERGENCE_RDB_CANDIDATE_ONLY)
        self.assertTrue(by_value["大人の部"]["static_is_master"])
        self.assertEqual(by_value["大人の部"]["rdb_review_state"], "candidate")

        # rdb_rejected_only: 夜の踊り子 is rejected in the RDB, absent from static.
        self.assertEqual(by_value["夜の踊り子"]["divergence"], shadow.DIVERGENCE_RDB_REJECTED_ONLY)

        # ambiguous_alias: 共有別名 points at two different songs.
        self.assertEqual(by_value["共有別名"]["divergence"], shadow.DIVERGENCE_AMBIGUOUS_ALIAS)

        # unresolved: 未知の候補 is a weekly term with no match anywhere.
        self.assertEqual(by_value["未知の候補"]["divergence"], shadow.DIVERGENCE_UNRESOLVED)

    def test_unknown_status_rdb_hit_is_unresolved_even_when_static_hit(self):
        # 謎ステータス曲 matches an RDB row (canonical exact) but that row's
        # status doesn't map to verified/candidate/rejected -> UNKNOWN. It
        # is ALSO present in the static provider. This must classify as
        # unresolved (RDB matched something untrustworthy), not static_only.
        report = self.build()
        by_value = {row["value"]: row for row in report["rows"]}
        row = by_value["謎ステータス曲"]
        self.assertTrue(row["static_is_master"])
        self.assertEqual(row["rdb_review_state"], "unknown")
        self.assertEqual(row["divergence"], shadow.DIVERGENCE_UNRESOLVED)

    def test_weekly_only_includes_song_candidate_category(self):
        report = self.build()
        values = {row["value"] for row in report["rows"]}
        self.assertNotIn("築地本願寺 × 何か", values)
        self.assertNotIn("用語その他", values)
        self.assertEqual(report["source_counts"]["weekly"], 3)

    def test_static_membership_uses_legacy_normalization(self):
        # "one love" only appears literally via the RDB (song_8); the
        # static file only has "ONE LOVE" (see setUp). A naive exact-string
        # membership check (`value in static_known`) would report
        # static_is_master=False for "one love" and misclassify this as
        # rdb_verified_only. With legacy-normalized comparison the case
        # difference is irrelevant and this must be same_verified.
        report = self.build()
        by_value = {row["value"]: row for row in report["rows"]}
        self.assertIn("one love", by_value)
        self.assertTrue(by_value["one love"]["static_is_master"])
        self.assertEqual(by_value["one love"]["divergence"], shadow.DIVERGENCE_SAME_VERIFIED)

    def test_candidate_and_rejected_never_reported_as_verified(self):
        report = self.build()
        by_value = {row["value"]: row for row in report["rows"]}
        self.assertNotEqual(by_value["大人の部"]["divergence"], shadow.DIVERGENCE_SAME_VERIFIED)
        self.assertNotEqual(by_value["大人の部"]["divergence"], shadow.DIVERGENCE_RDB_VERIFIED_ONLY)
        self.assertNotEqual(by_value["夜の踊り子"]["divergence"], shadow.DIVERGENCE_SAME_VERIFIED)
        self.assertNotEqual(by_value["夜の踊り子"]["divergence"], shadow.DIVERGENCE_RDB_VERIFIED_ONLY)

    def test_source_aggregation_across_static_weekly_public_rdb(self):
        report = self.build()
        by_value = {row["value"]: row for row in report["rows"]}
        # 東京音頭 comes from static, weekly, public, and rdb all at once.
        self.assertEqual(
            set(by_value["東京音頭"]["sources"]), {"static", "weekly", "public", "rdb"}
        )
        # 静的専用曲 only exists in the static file.
        self.assertEqual(set(by_value["静的専用曲"]["sources"]), {"static"})

    def test_source_counts_separate_canonical_and_alias(self):
        report = self.build()
        counts = report["source_counts"]
        # 8 songs registered as canonical_title.
        self.assertEqual(counts["rdb_canonical"], 8)
        # 1 distinct alias string ("共有別名", shared by two songs but
        # counted once as a raw value).
        self.assertEqual(counts["rdb_alias"], 1)
        self.assertEqual(
            counts["rdb_unique_values"], counts["rdb_canonical"] + counts["rdb_alias"]
        )

    def test_deterministic_ordering_and_repeatable_output(self):
        report_a = self.build()
        report_b = self.build()
        report_a.pop("generated_at")
        report_b.pop("generated_at")
        self.assertEqual(report_a, report_b)

        values = [row["value"] for row in report_a["rows"]]
        self.assertEqual(values, sorted(values))

    def test_all_divergence_codes_have_fixed_keys_in_summary(self):
        report = self.build()
        self.assertEqual(set(report["divergence_counts"]), set(shadow.ALL_DIVERGENCE_CODES))


if __name__ == "__main__":
    unittest.main()
