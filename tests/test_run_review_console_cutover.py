import json
import tempfile
import unittest
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from master_rdb.master_db import file_sha256, init_db
from review_console import data
from review_inbox import export_inbox_json, inbox_rows, upsert_inbox_items
from review_inbox_adapters.source_adapter import input_sha256
from review_inbox_adapters.source_writer import SourceWriterError
from run_review_console_cutover import (
    CONFIRM_BY_MODE,
    EXPECTED_INBOX_COUNTS,
    run_cutover,
)


JST = ZoneInfo("Asia/Tokyo")
PUBLIC_SHA = "b" * 64
ENABLED_ENV = {
    "REVIEW_INBOX_DUAL_WRITE_MODE": "bulk",
    "REVIEW_INBOX_CAS_PUBLISH_ENABLED": "true",
    "REVIEW_INBOX_READER_MODE": "legacy",
    "REVIEW_INBOX_LEGACY_WRITER_ENABLED": "true",
    "REVIEW_CONSOLE_READER_MODE": "canary",
}


def _write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _prepared_fixture(tmp):
    root = Path(tmp) / "root"
    (root / "data").mkdir(parents=True)
    database = Path(tmp) / "fetched.sqlite"
    conn = init_db(database)
    items = []
    for source_id, count in EXPECTED_INBOX_COUNTS.items():
        for index in range(count):
            items.append(
                {
                    "inbox_id": f"inbox_{source_id}_{index}",
                    "kind": "fixture",
                    "domain": "fixture",
                    "time_scope": "future",
                    "priority_label": "P1",
                    "priority_score": index,
                    "title": f"{source_id} {index}",
                    "event_name": f"Event {index}",
                    "venue": "Venue",
                    "event_year": 2026,
                    "source_id": source_id,
                    "source_key": f"{source_id}-{index}",
                    "source_url": "https://example.com",
                    "recommended_action": "review_fixture",
                    "status": "pending",
                    "payload": {"index": index},
                }
            )
    upsert_inbox_items(conn, items, ensure_schema=False)
    conn.commit()
    rows = inbox_rows(conn, status="pending", ensure_schema=False)
    conn.close()
    export_inbox_json(database, root / "data/review_inbox.json")

    source_by_id = {source.id: source for source in data.SOURCES}
    snapshot_paths = []
    for legacy_source_id, inbox_source_id in data.B1_LEGACY_TO_INBOX_SOURCE_IDS.items():
        source = source_by_id[legacy_source_id]
        legacy_path = root / source.path
        legacy_rows = [
            {
                "fixture_id": f"{legacy_source_id}-{index}",
                "title": f"{legacy_source_id} {index}",
            }
            for index in range(EXPECTED_INBOX_COUNTS[inbox_source_id])
        ]
        _write_json(legacy_path, {source.rows_path: legacy_rows})
        source_rows = [row for row in rows if row["source_id"] == inbox_source_id]
        snapshot_path = Path(tmp) / f"{inbox_source_id}.json"
        _write_json(
            snapshot_path,
            {
                "source_id": inbox_source_id,
                "input_path": str(legacy_path),
                "input_sha256": input_sha256(legacy_path.read_bytes()),
                "input_size_bytes": legacy_path.stat().st_size,
                "item_count": len(source_rows),
                "items": source_rows,
            },
        )
        snapshot_paths.append(snapshot_path)

    checksum = file_sha256(database)
    manifest = Path(tmp) / "fetched.manifest.json"
    _write_json(
        manifest,
        {
            "database_checksum": checksum,
            "artifact": {"snapshot_id": "Rstart-snapshot"},
        },
    )
    return root, database, manifest, snapshot_paths, checksum


def _args(tmp, root, database, manifest, snapshots, checksum, **overrides):
    values = {
        "input_root": root,
        "master_db": database,
        "artifact_manifest": manifest,
        "adapted_snapshot": snapshots,
        "expect_rstart_checksum": checksum,
        "expect_snapshot_id": "Rstart-snapshot",
        "expect_public_sha256": PUBLIC_SHA,
        "public_target_year": 2026,
        "public_today": "2026-07-18",
        "reader_mode": "canary",
        "evidence_out": Path(tmp) / "evidence.json",
        "execute": True,
        "confirm": CONFIRM_BY_MODE["canary"],
    }
    values.update(overrides)
    return Namespace(**values)


class RunReviewConsoleCutoverTest(unittest.TestCase):
    def test_default_off_confirm_environment_and_cron_fail_before_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing"
            base = _args(tmp, missing, missing, missing, [], "a" * 64)
            cases = (
                (_args(tmp, missing, missing, missing, [], "a" * 64, execute=False), ENABLED_ENV, datetime(2026, 7, 18, 12, tzinfo=JST), "is off"),
                (_args(tmp, missing, missing, missing, [], "a" * 64, confirm="wrong"), ENABLED_ENV, datetime(2026, 7, 18, 12, tzinfo=JST), "--confirm must be exactly"),
                (base, {key: value for key, value in ENABLED_ENV.items() if key != "REVIEW_INBOX_READER_MODE"}, datetime(2026, 7, 18, 12, tzinfo=JST), "explicit environment gates"),
                (base, {**ENABLED_ENV, "REVIEW_CONSOLE_READER_MODE": "inbox"}, datetime(2026, 7, 18, 12, tzinfo=JST), "must be explicitly set to canary"),
                (base, ENABLED_ENV, datetime(2026, 7, 18, 17, 30, tzinfo=JST), "17:20-18:00"),
            )
            for args, environ, now, message in cases:
                with self.subTest(message=message), self.assertRaisesRegex(SourceWriterError, message):
                    run_cutover(args, environ=environ, now=now, activate=lambda _mode: self.fail("must not activate"))

    def test_validates_s3_lineage_parity_preview_and_activates_only_requested_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, database, manifest, snapshots, checksum = _prepared_fixture(tmp)
            activated = []
            report = run_cutover(
                _args(tmp, root, database, manifest, snapshots, checksum),
                environ=ENABLED_ENV,
                now=datetime(2026, 7, 18, 12, tzinfo=JST),
                digest_function=lambda _database, *, target_year, today: PUBLIC_SHA,
                activate=activated.append,
            )

            self.assertEqual(activated, ["canary"])
            self.assertTrue(report["read_only"])
            self.assertEqual(report["artifact"]["database_sha256"], checksum)
            self.assertEqual(report["database_audit"]["pending_item_count"], 170)
            self.assertTrue(report["prepared_inputs"]["parity"]["summary"]["parity"])
            self.assertTrue(report["prepared_inputs"]["reader_preview"]["ok"])
            self.assertEqual(file_sha256(database), checksum)
            self.assertTrue(Path(tmp, "evidence.json").is_file())

    def test_rejects_repo_inbox_or_legacy_input_not_bound_to_fetched_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, database, manifest, snapshots, checksum = _prepared_fixture(tmp)
            inbox_path = root / "data/review_inbox.json"
            payload = json.loads(inbox_path.read_text(encoding="utf-8"))
            payload["items"].pop()
            _write_json(inbox_path, payload)
            with self.assertRaisesRegex(SourceWriterError, "does not match"):
                run_cutover(
                    _args(tmp, root, database, manifest, snapshots, checksum),
                    environ=ENABLED_ENV,
                    now=datetime(2026, 7, 18, 12, tzinfo=JST),
                    digest_function=lambda _database, *, target_year, today: PUBLIC_SHA,
                    activate=lambda _mode: self.fail("must not activate"),
                )

    def test_rejects_operator_rstart_not_matching_fetched_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, database, manifest, snapshots, checksum = _prepared_fixture(tmp)
            self.assertNotEqual(checksum, "f" * 64)
            with self.assertRaisesRegex(SourceWriterError, "S3 fetch lineage checksum mismatch"):
                run_cutover(
                    _args(
                        tmp,
                        root,
                        database,
                        manifest,
                        snapshots,
                        "f" * 64,
                    ),
                    environ=ENABLED_ENV,
                    now=datetime(2026, 7, 18, 12, tzinfo=JST),
                    digest_function=lambda _database, *, target_year, today: PUBLIC_SHA,
                    activate=lambda _mode: self.fail("must not activate"),
                )

    def test_rejects_adapter_input_sha_not_matching_adapter_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, database, manifest, snapshots, checksum = _prepared_fixture(tmp)
            source_by_id = {source.id: source for source in data.SOURCES}
            legacy_path = root / source_by_id["official_source"].path
            legacy_payload = json.loads(legacy_path.read_text(encoding="utf-8"))
            legacy_payload[source_by_id["official_source"].rows_path][0]["title"] = "tampered"
            _write_json(legacy_path, legacy_payload)

            with self.assertRaisesRegex(SourceWriterError, "adapter input lineage mismatch"):
                run_cutover(
                    _args(tmp, root, database, manifest, snapshots, checksum),
                    environ=ENABLED_ENV,
                    now=datetime(2026, 7, 18, 12, tzinfo=JST),
                    digest_function=lambda _database, *, target_year, today: PUBLIC_SHA,
                    activate=lambda _mode: self.fail("must not activate"),
                )

    def test_canary_does_not_require_full_replacement_but_inbox_does(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, database, manifest, snapshots, checksum = _prepared_fixture(tmp)
            source_by_id = {source.id: source for source in data.SOURCES}
            historical_legacy = root / source_by_id["historical_promotion_candidate"].path
            historical_snapshot = next(
                path
                for path in snapshots
                if json.loads(path.read_text(encoding="utf-8"))["source_id"]
                == "historical_reference"
            )

            distinct_adapter_input = Path(tmp) / "historical-adapter-input.json"
            distinct_adapter_input.write_bytes(historical_legacy.read_bytes())
            snapshot_payload = json.loads(historical_snapshot.read_text(encoding="utf-8"))
            snapshot_payload["input_path"] = str(distinct_adapter_input)
            snapshot_payload["input_sha256"] = input_sha256(distinct_adapter_input.read_bytes())
            _write_json(historical_snapshot, snapshot_payload)

            legacy_payload = json.loads(historical_legacy.read_text(encoding="utf-8"))
            legacy_payload[source_by_id["historical_promotion_candidate"].rows_path].pop()
            _write_json(historical_legacy, legacy_payload)

            activated = []
            report = run_cutover(
                _args(tmp, root, database, manifest, snapshots, checksum),
                environ=ENABLED_ENV,
                now=datetime(2026, 7, 18, 12, tzinfo=JST),
                digest_function=lambda _database, *, target_year, today: PUBLIC_SHA,
                activate=activated.append,
            )
            self.assertEqual(activated, ["canary"])
            self.assertTrue(report["prepared_inputs"]["reader_mode_gate"]["ok"])
            self.assertFalse(report["prepared_inputs"]["reader_mode_gate"]["full_readiness"])

            with self.assertRaisesRegex(SourceWriterError, "B1 inbox reader preview failed"):
                run_cutover(
                    _args(
                        tmp,
                        root,
                        database,
                        manifest,
                        snapshots,
                        checksum,
                        reader_mode="inbox",
                        confirm=CONFIRM_BY_MODE["inbox"],
                        evidence_out=Path(tmp) / "inbox-evidence.json",
                    ),
                    environ={**ENABLED_ENV, "REVIEW_CONSOLE_READER_MODE": "inbox"},
                    now=datetime(2026, 7, 18, 12, tzinfo=JST),
                    digest_function=lambda _database, *, target_year, today: PUBLIC_SHA,
                    activate=lambda _mode: self.fail("must not activate"),
                )


if __name__ == "__main__":
    unittest.main()
