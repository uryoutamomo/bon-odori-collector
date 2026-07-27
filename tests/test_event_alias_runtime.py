import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import build_event_alias_runtime as builder
import master_rdb.master_db as master_db
from youtube_backfill import event_aliases


def normalize(value):
    return master_db.normalize_text(value)


class EventAliasRuntimeBuilderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmp_path = Path(self.tmp.name)
        self.db_path = self.tmp_path / "master.sqlite"
        conn = master_db.init_db(self.db_path)
        conn.close()
        self._seed()

    def _seed(self):
        now = master_db.now_utc()
        self.venue_id = master_db.stable_id("venue", "渋谷109前")
        self.series_id = master_db.stable_id("series", "渋谷盆踊り")
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO venues(
                  venue_id, origin, canonical_name, normalized_name,
                  review_status, created_at, updated_at
                ) VALUES (?, 'curated', '渋谷109前', ?, 'active', ?, ?)
                """,
                (self.venue_id, normalize("渋谷109前"), now, now),
            )
            conn.execute(
                """
                INSERT INTO event_series(
                  series_id, origin, series_key, canonical_name, normalized_name,
                  status, created_at, updated_at
                ) VALUES (?, 'curated', '渋谷盆踊り', '渋谷盆踊り', ?, 'active', ?, ?)
                """,
                (self.series_id, normalize("渋谷盆踊り"), now, now),
            )
            for alias in ("Shibuya Bon Odori", "渋谷盆踊り"):
                conn.execute(
                    """
                    INSERT INTO event_series_aliases(
                      series_id, alias, normalized_alias, source, confidence
                    ) VALUES (?, ?, ?, 'test', 'manual')
                    """,
                    (self.series_id, alias, normalize(alias)),
                )
            for alias in ("Shibuya 109", "SHIBUYA109前"):
                conn.execute(
                    """
                    INSERT INTO venue_aliases(
                      venue_id, alias, normalized_alias, source, confidence
                    ) VALUES (?, ?, ?, 'test', 'manual')
                    """,
                    (self.venue_id, alias, normalize(alias)),
                )

    def test_groups_aliases_by_canonical_name(self):
        runtime = builder.build_runtime(self.db_path)
        self.assertEqual(
            runtime["event_aliases"]["渋谷盆踊り"], ["Shibuya Bon Odori", "渋谷盆踊り"]
        )
        self.assertEqual(runtime["venue_aliases"]["渋谷109前"], ["SHIBUYA109前", "Shibuya 109"])
        self.assertEqual(runtime["event_alias_count"], 2)
        self.assertEqual(runtime["venue_alias_count"], 2)

    def test_keeps_an_alias_equal_to_the_canonical_name(self):
        # Dropping it silently removed matches the previous code-owned table made.
        runtime = builder.build_runtime(self.db_path)
        self.assertIn("渋谷盆踊り", runtime["event_aliases"]["渋谷盆踊り"])

    def test_missing_alias_table_yields_an_empty_section(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DROP TABLE event_series_aliases")
        runtime = builder.build_runtime(self.db_path)
        self.assertEqual(runtime["event_aliases"], {})
        self.assertTrue(runtime["venue_aliases"])

    def test_missing_alias_table_keeps_the_previous_section(self):
        # An RDB that predates the migration must not blank out the committed
        # runtime file, or every matcher silently loses its aliases.
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DROP TABLE event_series_aliases")
        previous = {"event_aliases": {"渋谷盆踊り": ["Shibuya Bon Odori"]}}
        runtime = builder.build_runtime(self.db_path, previous=previous)
        self.assertEqual(runtime["event_aliases"], previous["event_aliases"])
        self.assertEqual(runtime["carried_over_sections"], ["event_aliases"])

    def test_main_keeps_aliases_when_the_rdb_predates_the_migration(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DROP TABLE event_series_aliases")
        out = self.tmp_path / "event_alias_runtime.json"
        builder.atomic_write_json(out, {"event_aliases": {"渋谷盆踊り": ["Shibuya Bon Odori"]}})
        self.assertEqual(builder.main(["--db", str(self.db_path), "--out", str(out)]), 0)
        payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(payload["event_aliases"], {"渋谷盆踊り": ["Shibuya Bon Odori"]})

    def test_main_keeps_the_existing_file_when_the_rdb_is_absent(self):
        out = self.tmp_path / "event_alias_runtime.json"
        out.write_text('{"event_aliases": {"kept": ["x"]}}\n', encoding="utf-8")
        self.assertEqual(builder.main(["--db", str(self.tmp_path / "missing.sqlite"), "--out", str(out)]), 0)
        self.assertIn("kept", json.loads(out.read_text(encoding="utf-8"))["event_aliases"])

    def test_main_writes_the_runtime_file(self):
        out = self.tmp_path / "event_alias_runtime.json"
        self.assertEqual(builder.main(["--db", str(self.db_path), "--out", str(out)]), 0)
        payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(payload["source"], "master_rdb")
        self.assertIn("渋谷盆踊り", payload["event_aliases"])


class EventAliasLookupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.runtime_path = Path(self.tmp.name) / "event_alias_runtime.json"
        self.runtime_path.write_text(
            json.dumps(
                {
                    "event_aliases": {"渋谷盆踊り": ["Shibuya Bon Odori"]},
                    "venue_aliases": {"渋谷109前": ["Shibuya 109"]},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        self.addCleanup(event_aliases.load_alias_runtime, refresh=True)
        event_aliases.load_alias_runtime(self.runtime_path)

    def test_finds_an_event_alias_in_text(self):
        found = event_aliases.find_event_alias(
            "渋谷盆踊り", "Shibuya Bon Odori 2025 highlights", normalize
        )
        self.assertEqual(found, "Shibuya Bon Odori")

    def test_edition_prefix_does_not_break_the_lookup(self):
        found = event_aliases.find_event_alias(
            "第7回 渋谷盆踊り", "Shibuya Bon Odori 2025", normalize
        )
        self.assertEqual(found, "Shibuya Bon Odori")

    def test_finds_a_venue_alias_in_text(self):
        found = event_aliases.find_venue_alias("渋谷109前", "in front of Shibuya 109", normalize)
        self.assertEqual(found, "Shibuya 109")

    def test_unknown_canonical_name_returns_no_alias(self):
        self.assertEqual(event_aliases.find_event_alias("知らない盆踊り", "anything", normalize), "")

    def test_missing_runtime_file_degrades_to_no_aliases(self):
        event_aliases.load_alias_runtime(Path(self.tmp.name) / "absent.json")
        self.assertEqual(event_aliases.public_event_aliases(), {})
        self.assertEqual(event_aliases.find_event_alias("渋谷盆踊り", "Shibuya Bon Odori", normalize), "")

    def test_unreadable_runtime_file_degrades_to_no_aliases(self):
        broken = Path(self.tmp.name) / "broken.json"
        broken.write_text("{ not json", encoding="utf-8")
        event_aliases.load_alias_runtime(broken)
        self.assertEqual(event_aliases.public_venue_aliases(), {})

    def test_environment_override_selects_the_runtime_file(self):
        with mock.patch.dict(
            "os.environ", {event_aliases.RUNTIME_PATH_ENV: str(self.runtime_path)}
        ):
            event_aliases.load_alias_runtime(refresh=True)
            self.assertIn("渋谷盆踊り", event_aliases.public_event_aliases())


if __name__ == "__main__":
    unittest.main()
