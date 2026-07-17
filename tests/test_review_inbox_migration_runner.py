import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from master_db import file_sha256
from review_inbox import inbox_schema_version
from review_inbox_migration_runner import guard_fetch, run_migration


V1_SCHEMA = """
CREATE TABLE schema_migrations (
  version INTEGER NOT NULL,
  name TEXT NOT NULL,
  applied_at TEXT NOT NULL,
  PRIMARY KEY (version, name)
);
INSERT INTO schema_migrations VALUES (1, 'initial', '2026-07-16T00:00:00+00:00');
CREATE TABLE review_inbox_items (
  inbox_id TEXT PRIMARY KEY, kind TEXT NOT NULL, domain TEXT NOT NULL,
  priority_label TEXT, priority_score REAL, title TEXT NOT NULL,
  event_name TEXT, venue TEXT, event_year INTEGER, source_id TEXT NOT NULL,
  source_key TEXT NOT NULL, source_url TEXT, recommended_action TEXT,
  status TEXT NOT NULL DEFAULT 'pending', payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
INSERT INTO review_inbox_items VALUES (
  'legacy-1', 'historical_reference', '過去実績', 'P2', 10, 'legacy',
  'legacy', '会場', 2025, 'legacy', 'legacy|1', 'https://example.com',
  'review', 'accepted', '{"source":"legacy"}',
  '2026-07-16T00:00:00+00:00', '2026-07-17T00:00:00+00:00'
);
"""


def make_v1_db(path: Path) -> None:
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(V1_SCHEMA)
        conn.commit()


class ReviewInboxMigrationRunnerTest(unittest.TestCase):
    def test_guard_fetch_rejects_local_remote_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "master.sqlite"
            make_v1_db(db)

            with self.assertRaises(SystemExit):
                guard_fetch(db, "not-the-local-checksum")

            self.assertEqual(guard_fetch(db, file_sha256(db))["safe_to_fetch_overwrite"], True)

    def test_dry_run_migrates_copy_and_preserves_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "master.sqlite"
            out = root / "dry-run.sqlite"
            make_v1_db(source)
            before_checksum = file_sha256(source)

            report = run_migration(
                master_db=source,
                expected_local_checksum=before_checksum,
                apply=False,
                out_db=out,
                backup_dir=root / "backups",
                report_json=root / "report.json",
                report_md=root / "report.md",
            )

            self.assertEqual(file_sha256(source), before_checksum)
            self.assertTrue(report["audit_passed"])
            self.assertEqual(report["before"]["status_counts"], {"accepted": 1})
            self.assertEqual(report["after"]["status_counts"], {"accepted": 1})
            self.assertEqual(report["after"]["lifecycle_nonnull"]["decision"], 0)
            self.assertEqual(report["after"]["missing_backfill"], {
                "time_scope": 0,
                "source_payload_hash": 0,
                "last_seen_at": 0,
            })
            with closing(sqlite3.connect(out)) as conn:
                self.assertEqual(inbox_schema_version(conn), 2)

    def test_apply_requires_matching_checksum_and_creates_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "master.sqlite"
            make_v1_db(source)
            before_checksum = file_sha256(source)

            with self.assertRaises(SystemExit):
                run_migration(
                    master_db=source,
                    expected_local_checksum="stale",
                    apply=True,
                    out_db=root / "unused.sqlite",
                    backup_dir=root / "backups",
                    report_json=root / "report.json",
                    report_md=root / "report.md",
                )

            report = run_migration(
                master_db=source,
                expected_local_checksum=before_checksum,
                apply=True,
                out_db=root / "unused.sqlite",
                backup_dir=root / "backups",
                report_json=root / "report.json",
                report_md=root / "report.md",
            )

            backup = Path(report["backup_db"])
            self.assertTrue(backup.exists())
            self.assertEqual(file_sha256(backup), before_checksum)
            self.assertNotEqual(file_sha256(source), before_checksum)
            with closing(sqlite3.connect(source)) as conn:
                self.assertEqual(inbox_schema_version(conn), 2)

    def test_apply_rolls_back_transaction_when_migration_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "master.sqlite"
            make_v1_db(source)
            before_checksum = file_sha256(source)

            def fail_after_write(conn):
                conn.execute("UPDATE review_inbox_items SET status = 'rejected'")
                raise RuntimeError("injected migration failure")

            with patch(
                "review_inbox_migration_runner.migrate_inbox_schema_v2",
                side_effect=fail_after_write,
            ):
                with self.assertRaisesRegex(RuntimeError, "injected migration failure"):
                    run_migration(
                        master_db=source,
                        expected_local_checksum=before_checksum,
                        apply=True,
                        out_db=root / "unused.sqlite",
                        backup_dir=root / "backups",
                        report_json=root / "report.json",
                        report_md=root / "report.md",
                    )

            self.assertEqual(file_sha256(source), before_checksum)
            with closing(sqlite3.connect(source)) as conn:
                status = conn.execute("SELECT status FROM review_inbox_items").fetchone()[0]
            self.assertEqual(status, "accepted")

    def test_second_migration_is_idempotent_and_preserves_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "master.sqlite"
            first = root / "first.sqlite"
            second = root / "second.sqlite"
            make_v1_db(source)
            first_report = run_migration(
                master_db=source,
                expected_local_checksum=file_sha256(source),
                apply=False,
                out_db=first,
                backup_dir=root / "backups",
                report_json=root / "first.json",
                report_md=root / "first.md",
            )
            with closing(sqlite3.connect(first)) as conn:
                conn.execute(
                    "UPDATE review_inbox_items SET decision = 'accepted', decided_by = '内田さん'"
                )
                conn.commit()

            second_report = run_migration(
                master_db=first,
                expected_local_checksum=file_sha256(first),
                apply=False,
                out_db=second,
                backup_dir=root / "backups",
                report_json=root / "second.json",
                report_md=root / "second.md",
            )

            self.assertTrue(first_report["migration_changed"])
            self.assertFalse(second_report["migration_changed"])
            self.assertEqual(second_report["after"]["lifecycle_nonnull"]["decision"], 1)
            with closing(sqlite3.connect(second)) as conn:
                row = conn.execute(
                    "SELECT decision, decided_by FROM review_inbox_items"
                ).fetchone()
            self.assertEqual(row, ("accepted", "内田さん"))


if __name__ == "__main__":
    unittest.main()
