"""J0-adjudication: the user lane that decides agent-opened awaiting_user holds.

Each test targets one numbered acceptance condition of
`docs/local-judgment-j0-adjudication-v1.md` §9.  The mapping is kept in
`docs/local-judgment-j0-adjudication-test-coverage.md`.
"""
import hashlib
import inspect
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from io import StringIO
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from event_model.local_judgment_migration import (
    migrate_event_inbox_candidate, migrate_local_judgment_contract, migrate_review_claim_ledger,
)
from master_rdb.master_db import connect_existing, init_db
from review_console import data as console_data
from review_inbox_adapters import apply_user_adjudications as apply_module
from review_inbox_adapters.apply_user_adjudications import main as apply_main, run as apply_adjudications
from review_inbox_adapters.event_inbox_writer import insert_candidate
from review_inbox_adapters.judgment_ledger_writer import write_decision
from review_inbox_adapters.local_judgment_contract import (
    ContractError, build_canonical_hold, build_user_decision, canonicalize_raw_judgment,
)

HASH = "a" * 64
CANONICAL_FACT_TABLES = (
    "venues", "venue_aliases", "event_series", "event_series_aliases", "event_occurrences",
    "occurrence_dates", "occurrence_evidence_links", "songs", "occurrence_songs",
    "occurrence_song_evidence_links",
)


def _now():
    return datetime.now(timezone.utc)


class JudgmentJ0AdjudicationTest(unittest.TestCase):
    # ------------------------------------------------------------------ setup
    def _db(self, root, *, migrate=True):
        db = root / "master.sqlite"
        conn = init_db(db)
        if migrate:
            migrate_local_judgment_contract(conn)
            migrate_event_inbox_candidate(conn)
            migrate_review_claim_ledger(conn)
        conn.commit()
        conn.close()
        return db

    def _inbox_row(self, inbox_id, *, status="candidate", source_key="key-1"):
        stamp = _now().isoformat()
        return {
            "inbox_id": inbox_id, "kind": "event_candidate", "domain": "曲・用語・低緊急度",
            "contract_domain": "event", "contract_lane": "event_update", "time_scope": "future",
            "priority_label": "中", "priority_score": 50, "title": "試験盆踊り 2099",
            "event_name": "試験盆踊り", "venue": "試験公園", "event_year": 2099,
            "source_id": "source-1", "source_key": source_key, "source_url": "https://example.test",
            "recommended_action": "review", "status": status, "source_payload_hash": HASH,
            "last_seen_at": stamp, "payload_json": {"proposal": {}, "targets": {}},
            "created_at": stamp, "updated_at": stamp, "first_eligible_at": None, "expires_at": None,
            "superseded_by_inbox_id": None, "depends_on_inbox_id": None,
            "revision_family_key": "family-1", "revision": 0,
        }

    def _open_hold(self, db, root, *, inbox_id="inbox-adj", packet_id="packet-adj",
                   candidate_ids=None, reason_code="requires_policy_judgment",
                   source_key="key-1", write_packet=True, actor_id="oto-test"):
        """Open a real awaiting_user hold through the contract and the J0-read writer."""
        conn = connect_existing(db)
        conn.row_factory = sqlite3.Row
        if not conn.execute("SELECT 1 FROM review_inbox_items WHERE inbox_id=?", (inbox_id,)).fetchone():
            insert_candidate(conn, self._inbox_row(inbox_id, source_key=source_key))
        raw = {
            "packet_id": packet_id, "inbox_id": inbox_id, "domain": "event", "lane": "event_update",
            "source_id": "source-1", "source_key": source_key, "source_payload_hash": HASH,
            "requested_action": "hold", "payload": {"reason_detail": "人の判断が要る"},
        }
        normalized = canonicalize_raw_judgment(raw, trusted_actor={
            "actor_type": "agent", "actor_id": actor_id, "decision_channel": "llm",
            "decided_at": _now().isoformat(),
        })
        decision = build_canonical_hold(normalized, reason_code=reason_code)
        conn.commit()
        conn.execute("BEGIN")
        write_decision(conn, decision, candidate_ids=candidate_ids)
        conn.commit()
        hold = conn.execute(
            "SELECT * FROM review_hold_ledger WHERE inbox_id=? ORDER BY opened_at DESC", (inbox_id,)
        ).fetchone()
        conn.close()
        if write_packet:
            self._write_packet(root, packet_id, inbox_id, candidate_ids)
        return dict(hold)

    def _write_packet(self, root, packet_id, inbox_id, candidate_ids=None):
        directory = root / "packets"
        directory.mkdir(parents=True, exist_ok=True)
        packet = {
            "packet_id": packet_id, "inbox_id": inbox_id,
            "proposal": {"event_name_hint": "試験盆踊り"},
            "targets": {"occurrence_candidates": [
                {"occurrence_id": candidate_id, "display_name": f"試験盆踊り {index}", "venue_name": "試験公園"}
                for index, candidate_id in enumerate(candidate_ids or [])
            ]},
        }
        (directory / f"batch_{packet_id}.json").write_text(
            json.dumps({"packets": [packet]}, ensure_ascii=False), encoding="utf-8"
        )
        return directory

    def _adj_path(self, root):
        path = root / "adjudications.json"
        if not path.exists():
            path.write_text(json.dumps({"schema_version": 1, "adjudications": []}), encoding="utf-8")
        return path

    def _args(self, root, db, **extra):
        args = SimpleNamespace(
            db=db, out_db=root / "applied.sqlite", adjudications=self._adj_path(root),
            report_json=root / "report.json", actor_id="uchida", apply=False, confirm="",
            no_auto_migrate=False,
        )
        for key, value in extra.items():
            setattr(args, key, value)
        return args

    def _rows(self, path):
        return json.loads(Path(path).read_text())["adjudications"]

    def _set_rows(self, path, rows):
        Path(path).write_text(json.dumps({"schema_version": 1, "adjudications": rows}, ensure_ascii=False))

    def _checksum(self, path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def _holds(self, db, root, **extra):
        return console_data.load_adjudication_holds(db_path=db, packets_dir=root / "packets", **extra)

    # ------------------------------------------------------------- 読み出し 1-6
    def test_01_deferred_retry_hold_is_not_listed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            conn = connect_existing(db)
            conn.execute("UPDATE review_hold_ledger SET hold_mode='deferred_retry' WHERE hold_id=?", (hold["hold_id"],))
            conn.commit(); conn.close()
            self.assertEqual(self._holds(db, root), [])

    def test_02_closed_hold_is_not_listed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            self.assertEqual(len(self._holds(db, root)), 1)
            conn = connect_existing(db)
            conn.execute("UPDATE review_hold_ledger SET status='resolved' WHERE hold_id=?", (hold["hold_id"],))
            conn.commit(); conn.close()
            self.assertEqual(self._holds(db, root), [])

    def test_03_expired_hold_is_shown_but_not_actionable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            conn = connect_existing(db)
            conn.execute("UPDATE review_hold_ledger SET expires_at=? WHERE hold_id=?",
                         ((_now() - timedelta(days=1)).isoformat(), hold["hold_id"]))
            conn.commit(); conn.close()
            listed = self._holds(db, root)
            self.assertEqual(len(listed), 1)
            self.assertTrue(listed[0]["expired"])
            self.assertFalse(listed[0]["actionable"])
            self.assertEqual(listed[0]["action_disabled_reason"], "期限切れ")

    def test_04_hold_without_packet_file_is_shown_as_undecidable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root)
            self._open_hold(db, root, write_packet=False)
            (root / "packets").mkdir(parents=True, exist_ok=True)
            listed = self._holds(db, root)
            self.assertEqual(len(listed), 1)
            self.assertFalse(listed[0]["packet_available"])
            self.assertFalse(listed[0]["actionable"])
            self.assertIn("packet", listed[0]["action_disabled_reason"])

    def test_05_hold_claimed_by_another_user_cannot_be_opened(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            console_data.claim_adjudication_hold(hold["hold_id"], "other-console", db_path=db)
            listed = self._holds(db, root)
            self.assertTrue(listed[0]["claim_other"])
            self.assertFalse(listed[0]["actionable"])
            with self.assertRaises(ValueError):
                console_data.claim_adjudication_hold(hold["hold_id"], "uchida", db_path=db)

    def test_06_agent_claim_does_not_block_the_user(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            conn = connect_existing(db)
            conn.execute(
                "INSERT INTO review_claim_ledger(inbox_id,claimed_by,claim_kind,claimed_at,expires_at,batch_id)"
                " VALUES (?,?,?,?,?,NULL)",
                (hold["inbox_id"], "oto-test", "agent", _now().isoformat(), (_now() + timedelta(minutes=30)).isoformat()),
            )
            conn.commit(); conn.close()
            listed = self._holds(db, root)
            self.assertFalse(listed[0]["claim_other"])
            self.assertTrue(listed[0]["actionable"])
            self.assertTrue(console_data.claim_adjudication_hold(hold["hold_id"], "uchida", db_path=db)["claimed"])

    def test_06a_a_database_without_the_ledgers_shows_an_empty_lane(self):
        """本番RDBはJ0 migration未適用。開いた瞬間に落ちないこと。"""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root, migrate=False)
            (root / "packets").mkdir(parents=True, exist_ok=True)
            self.assertEqual(self._holds(db, root), [])

    def test_06b_opening_the_lane_never_creates_a_master_database(self):
        """sqlite3.connect は無いパスを作る。master RDB の場所に0バイト版を残さない。"""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            missing = root / "master.sqlite"
            (root / "packets").mkdir(parents=True, exist_ok=True)
            self.assertEqual(console_data.load_adjudication_holds(db_path=missing, packets_dir=root / "packets"), [])
            self.assertFalse(missing.exists())
            with self.assertRaises(FileNotFoundError):
                console_data.claim_adjudication_hold("hold-x", "uchida", db_path=missing)
            self.assertFalse(missing.exists())

    def test_06c_exact_llm_duplicate_overlay_removes_only_the_matching_hold(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root)
            hold = self._open_hold(db, root, reason_code="insufficient_evidence")
            stamp = _now().isoformat()
            title = "試験盆踊り（試験公園／2099-08-01）"
            conn = connect_existing(db)
            conn.execute("INSERT INTO venues (venue_id,origin,canonical_name,normalized_name,area,address,review_status,created_at,updated_at) VALUES ('ven_existing','curated','試験公園','試験公園','','','active',?,?)", (stamp, stamp))
            conn.execute("INSERT INTO event_series (series_id,origin,series_key,canonical_name,normalized_name,usual_venue_id,status,created_at,updated_at) VALUES ('ser_existing','curated','試験盆踊り','試験盆踊り','試験盆踊り','ven_existing','active',?,?)", (stamp, stamp))
            conn.execute("INSERT INTO event_occurrences (occurrence_id,origin,series_id,event_year,occurrence_sequence,display_name,venue_id,date_start,date_status,lifecycle_status,created_at,updated_at) VALUES ('occ_existing','curated','ser_existing',2099,1,'試験盆踊り','ven_existing','2099-08-01','confirmed','published',?,?)", (stamp, stamp))
            conn.execute(
                "UPDATE review_inbox_items SET title=?,event_name='試験盆踊り',venue='試験公園',event_year=2099,payload_json=? WHERE inbox_id=?",
                (title, json.dumps({"proposal": {"explicit_occurrence_id": "occ_existing"}, "resolved_target": {"occurrence_id": "occ_existing"}}), hold["inbox_id"]),
            )
            conn.execute(
                "UPDATE canonical_decision_ledger SET payload_json=? WHERE decision_id=?",
                (json.dumps({"occurrence_match": "occ_existing", "series_match": "ser_existing", "venue_match": "none"}), hold["prior_agent_attempt_id"]),
            )
            conn.commit(); conn.close()
            decision = {
                "hold_id": hold["hold_id"], "inbox_id": hold["inbox_id"], "title": title,
                "classification": "duplicate_or_alias", "confidence": "high", "recommended_action": "merge",
                "reason_detail": "既存開催回と一致", "source_payload_hash": HASH,
                "prior_agent_attempt_id": hold["prior_agent_attempt_id"],
                "duplicate_target_occurrence_id": "occ_existing", "target_series_id": "ser_existing",
                "target_venue_id": "ven_existing", "target_date_start": "2099-08-01",
                "checked_at": stamp,
            }
            overlay = root / "hold-overlay.json"
            overlay.write_text(json.dumps({
                "schema_version": 1, "generated_by": "おと（Codex）/Terra",
                "generated_at": stamp, "decisions": [decision],
            }, ensure_ascii=False))

            self.assertEqual(self._holds(db, root, decision_overlay_path=overlay), [])
            audited = self._holds(db, root, decision_overlay_path=overlay, include_auto_resolved=True)
            self.assertEqual(audited[0]["auto_resolution"]["target_occurrence_id"], "occ_existing")
            self.assertFalse(audited[0]["actionable"])

            decision["target_date_start"] = "2099-08-02"
            overlay.write_text(json.dumps({
                "schema_version": 1, "generated_by": "おと（Codex）/Terra",
                "generated_at": stamp, "decisions": [decision],
            }, ensure_ascii=False))
            self.assertEqual(len(self._holds(db, root, decision_overlay_path=overlay)), 1)

    # -------------------------------------------------------- 裁定の記録 7-10
    def test_07_recording_a_decision_does_not_touch_the_master_rdb(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            before = self._checksum(db)
            console_data.save_adjudication(hold["hold_id"], "accept", db_path=db, path=self._adj_path(root))
            self.assertEqual(self._checksum(db), before)
            self.assertEqual(len(self._rows(self._adj_path(root))), 1)

    def test_07_claim_writes_only_the_claim_lease_row(self):
        """The claim lease is the single console write; no ledger row may move."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            # 件数だけ見ると UPDATE を見逃すので、行の中身ごと比べる。
            def ledgers():
                conn = connect_existing(db)
                snapshot = {name: [tuple(row) for row in conn.execute(f"SELECT * FROM {name} ORDER BY 1")]
                            for name in ("canonical_decision_ledger", "review_queue_state_ledger", "review_hold_ledger")}
                conn.close()
                return snapshot

            before = ledgers()
            console_data.claim_adjudication_hold(hold["hold_id"], "uchida", db_path=db)
            self.assertEqual(ledgers(), before)
            conn = connect_existing(db)
            self.assertEqual(conn.execute("SELECT claim_kind FROM review_claim_ledger").fetchone()[0], "user")
            conn.close()

    def test_07a_no_http_path_can_apply_to_the_ledger(self):
        source = Path("review_console/server.py").read_text()
        self.assertNotIn("/api/adjudication/apply", source)
        self.assertIn("/api/adjudication/decide", source)

    def test_07b_status_reports_pending_count_and_command(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            path = self._adj_path(root)
            console_data.save_adjudication(hold["hold_id"], "accept", db_path=db, path=path)
            status = console_data.adjudication_status(path)
            self.assertEqual(status["pending_count"], 1)
            self.assertIn("--confirm", status["apply_command"])
            self.assertIn("apply_user_adjudications.py", status["apply_command"])

    def test_08_adjudications_are_stored_apart_from_the_legacy_decisions(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            path = self._adj_path(root)
            console_data.save_adjudication(hold["hold_id"], "accept", db_path=db, path=path)
            self.assertNotEqual(console_data.ADJUDICATIONS_PATH, console_data.DECISIONS_PATH)
            # 既存の判断待ち561件の器（decisions.json）と関数を共用していないこと。
            adjudication_source = "\n".join(inspect.getsource(function) for function in (
                console_data.load_adjudications, console_data.save_adjudication,
                console_data.save_adjudication_batch, console_data._record_adjudication,
                console_data.adjudication_status, console_data.load_adjudication_holds,
            ))
            for legacy in ("save_decision(", "load_decisions(", "export_decisions(", "DECISIONS_PATH"):
                self.assertNotIn(legacy, adjudication_source)
            self.assertEqual(console_data.load_decisions(root / "decisions.json").get("decisions"), {})

    def test_09_action_outside_allowed_actions_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            with self.assertRaises(ValueError) as caught:
                console_data.save_adjudication(hold["hold_id"], "requeue", db_path=db, path=self._adj_path(root))
            self.assertIn("not allowed", str(caught.exception))

    def test_09a_target_outside_the_frozen_candidate_set_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root)
            hold = self._open_hold(db, root, candidate_ids=["occ_1", "occ_2"])
            with self.assertRaises(ValueError) as caught:
                console_data.save_adjudication(hold["hold_id"], "accept", target_id="occ_9",
                                               db_path=db, path=self._adj_path(root))
            self.assertIn("candidate set", str(caught.exception))
            with self.assertRaises(ValueError):
                console_data.save_adjudication(hold["hold_id"], "accept", db_path=db, path=self._adj_path(root))

    def test_10_holds_with_a_frozen_candidate_set_cannot_be_batched(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root)
            first = self._open_hold(db, root, candidate_ids=["occ_1"])
            second = self._open_hold(db, root, inbox_id="inbox-adj-2", packet_id="packet-adj-2",
                                     candidate_ids=["occ_2"], source_key="key-2")
            self.assertEqual(first["grouping_fingerprint"], second["grouping_fingerprint"])
            with self.assertRaises(ValueError) as caught:
                console_data.save_adjudication_batch([first["hold_id"], second["hold_id"]], "accept",
                                                     db_path=db, path=self._adj_path(root))
            # 「対象IDが無い」で弾かれても通ってしまうので、一括対象から外れた理由まで見る。
            self.assertIn("not eligible for batch", str(caught.exception))

    # ------------------------------------------------------------- 反映 11-18
    def _record(self, db, root, hold, action="accept", **extra):
        return console_data.save_adjudication(hold["hold_id"], action, db_path=db,
                                              path=self._adj_path(root), **extra)

    def test_11_changed_candidate_set_is_invalidated(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root)
            hold = self._open_hold(db, root, candidate_ids=["occ_1"])
            self._record(db, root, hold, target_id="occ_1")
            rows = self._rows(self._adj_path(root)); rows[0]["candidate_set_sha256"] = "b" * 64
            self._set_rows(self._adj_path(root), rows)
            report = apply_adjudications(self._args(root, db))
            self.assertEqual(report["invalidated"], 1)
            self.assertEqual(report["issues"][0]["issue_type"], "candidate_set_changed")
            self.assertEqual(report["issues"][0]["severity"], "medium")

    def test_11a_target_outside_the_candidate_set_is_invalidated_at_apply(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root)
            hold = self._open_hold(db, root, candidate_ids=["occ_1"])
            self._record(db, root, hold, target_id="occ_1")
            rows = self._rows(self._adj_path(root)); rows[0]["target_id"] = "occ_typed_by_hand"
            self._set_rows(self._adj_path(root), rows)
            report = apply_adjudications(self._args(root, db))
            self.assertEqual(report["issues"][0]["issue_type"], "target_not_in_candidate_set")

    def test_12_decision_on_a_closed_hold_is_invalidated(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            self._record(db, root, hold)
            conn = connect_existing(db)
            conn.execute("UPDATE review_hold_ledger SET status='resolved' WHERE hold_id=?", (hold["hold_id"],))
            conn.commit(); conn.close()
            report = apply_adjudications(self._args(root, db))
            self.assertEqual(report["issues"][0]["issue_type"], "hold_not_open")
            self.assertEqual(report["applied"], 0)

    def test_13_decision_on_an_expired_hold_is_invalidated(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            self._record(db, root, hold)
            conn = connect_existing(db)
            conn.execute("UPDATE review_hold_ledger SET expires_at=? WHERE hold_id=?",
                         ((_now() - timedelta(minutes=1)).isoformat(), hold["hold_id"]))
            conn.commit(); conn.close()
            report = apply_adjudications(self._args(root, db))
            self.assertEqual(report["issues"][0]["issue_type"], "hold_expired")

    def test_13a_invalidated_rows_keep_their_reason(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            self._record(db, root, hold)
            conn = connect_existing(db)
            conn.execute("UPDATE review_hold_ledger SET status='resolved' WHERE hold_id=?", (hold["hold_id"],))
            conn.commit(); conn.close()
            apply_adjudications(self._args(root, db))
            rows = self._rows(self._adj_path(root))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "invalidated")
            self.assertEqual(rows[0]["invalid_reason"], "hold_not_open")
            self.assertTrue(rows[0]["invalidated_at"])

    def test_13b_invalidated_rows_are_not_processed_again(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            self._record(db, root, hold)
            conn = connect_existing(db)
            conn.execute("UPDATE review_hold_ledger SET status='resolved' WHERE hold_id=?", (hold["hold_id"],))
            conn.commit(); conn.close()
            apply_adjudications(self._args(root, db))
            second = apply_adjudications(self._args(root, db, out_db=root / "applied2.sqlite"))
            self.assertEqual(second["invalidated"], 0)
            self.assertEqual(second["issues"], [])

    def test_13c_an_invalidated_hold_can_be_adjudicated_again_as_a_new_row(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            self._record(db, root, hold)
            rows = self._rows(self._adj_path(root)); rows[0]["candidate_set_sha256"] = "b" * 64
            self._set_rows(self._adj_path(root), rows)
            args = self._args(root, db)
            apply_adjudications(args)
            # 反映先（dry-run のコピー）でも hold は閉じない。閉じると裁き直せなくなる。
            self.assertEqual(sqlite3.connect(args.out_db).execute(
                "SELECT status FROM review_hold_ledger WHERE hold_id=?", (hold["hold_id"],)).fetchone()[0], "open")
            self.assertEqual(len(self._holds(db, root)), 1)  # 画面にも残る
            self._record(db, root, hold, action="reject")
            rows = self._rows(self._adj_path(root))
            self.assertEqual([row["status"] for row in rows], ["invalidated", "pending"])
            report = apply_adjudications(self._args(root, db, out_db=root / "applied2.sqlite"))
            self.assertEqual(report["applied"], 1)

    def test_13d_a_hold_without_its_prior_attempt_uses_one_reason_code(self):
        """保存する理由と report の理由を割らない（おとの独立レビュー指摘）。"""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            self._record(db, root, hold)
            conn = connect_existing(db)
            conn.execute("DELETE FROM canonical_decision_ledger WHERE decision_id=?", (hold["prior_agent_attempt_id"],))
            conn.commit(); conn.close()
            report = apply_adjudications(self._args(root, db))
            self.assertEqual(report["issues"][0]["issue_type"], "prior_attempt_missing")
            self.assertEqual(self._rows(self._adj_path(root))[0]["invalid_reason"], "prior_attempt_missing")

    def test_14_the_three_ledgers_move_together(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            self._record(db, root, hold)
            args = self._args(root, db)
            report = apply_adjudications(args)
            self.assertEqual(report["applied"], 1)
            conn = sqlite3.connect(args.out_db); conn.row_factory = sqlite3.Row
            decision = conn.execute("SELECT * FROM canonical_decision_ledger WHERE actor_type='user'").fetchone()
            self.assertEqual(decision["action"], "accept")
            self.assertEqual(decision["queue_state_before"], "awaiting_user")
            self.assertEqual(decision["queue_state_after"], "closed")
            queue = conn.execute("SELECT queue_state, decision_id FROM review_queue_state_ledger WHERE inbox_id=?",
                                 (hold["inbox_id"],)).fetchone()
            self.assertEqual(queue["queue_state"], "closed")
            self.assertEqual(queue["decision_id"], decision["decision_id"])
            closed = conn.execute("SELECT status, closed_at, resolved_by_decision_id FROM review_hold_ledger WHERE hold_id=?",
                                  (hold["hold_id"],)).fetchone()
            self.assertEqual(closed["status"], "resolved")
            self.assertEqual(closed["resolved_by_decision_id"], decision["decision_id"])
            self.assertTrue(closed["closed_at"])
            conn.close()

    def test_15_apply_goes_through_the_shared_ledger_writer(self):
        source = Path("review_inbox_adapters/apply_user_adjudications.py").read_text()
        self.assertIn("from review_inbox_adapters.judgment_ledger_writer import write_decision", source)
        for forbidden in ("INSERT INTO canonical_decision_ledger", "INSERT INTO review_queue_state_ledger"):
            self.assertNotIn(forbidden, source)
        console = Path("review_console/data.py").read_text()
        for forbidden in ("canonical_decision_ledger", "review_queue_state_ledger"):
            self.assertNotIn(f"INSERT INTO {forbidden}", console)

    def test_16_a_failure_after_the_decision_leaves_no_partial_write(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            self._record(db, root, hold)
            args = self._args(root, db)

            def exploding(conn, decision, **kwargs):
                outcome = write_decision(conn, decision, **kwargs)
                raise sqlite3.OperationalError("disk fell over")

            with patch.object(apply_module, "write_decision", exploding):
                report = apply_adjudications(args)
            self.assertEqual(report["applied"], 0)
            conn = sqlite3.connect(args.out_db)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM canonical_decision_ledger WHERE actor_type='user'").fetchone()[0], 0)
            # agent の hold が残した queue 行は awaiting_user のまま。closed へ動いていないこと。
            self.assertEqual(conn.execute("SELECT queue_state FROM review_queue_state_ledger WHERE inbox_id=?",
                                          (hold["inbox_id"],)).fetchone()[0], "awaiting_user")
            self.assertEqual(conn.execute("SELECT status FROM review_hold_ledger WHERE hold_id=?", (hold["hold_id"],)).fetchone()[0], "open")
            conn.close()

    def test_17_reapplying_the_same_adjudication_adds_no_ledger_row(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            self._record(db, root, hold)
            first = self._args(root, db)
            apply_adjudications(first)
            conn = connect_existing(first.out_db)
            conn.execute("UPDATE review_hold_ledger SET status='open', closed_at=NULL, resolved_by_decision_id=NULL WHERE hold_id=?", (hold["hold_id"],))
            conn.commit(); conn.close()
            rows = self._rows(self._adj_path(root))
            rows[0].update(status="pending", applied_at=None, decision_id=None)
            self._set_rows(self._adj_path(root), rows)
            second = apply_adjudications(self._args(root, first.out_db, out_db=root / "applied2.sqlite"))
            self.assertEqual(second["noop"], 1)
            self.assertEqual(second["invalidated"], 0)
            conn = sqlite3.connect(root / "applied2.sqlite")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM canonical_decision_ledger WHERE actor_type='user'").fetchone()[0], 1)
            conn.close()

    def test_18_applied_rows_carry_the_decision_id_back(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            self._record(db, root, hold)
            args = self._args(root, db)
            report = apply_adjudications(args)
            row = self._rows(self._adj_path(root))[0]
            self.assertEqual(row["status"], "applied")
            self.assertTrue(row["applied_at"])
            self.assertEqual(row["decision_id"], report["entries"][0]["decision_id"])

    # ---------------------------------------------------------- lineage 19-23
    def test_19_the_file_cannot_name_its_own_actor(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            self._record(db, root, hold)
            rows = self._rows(self._adj_path(root)); rows[0]["decided_by"] = "koto"
            self._set_rows(self._adj_path(root), rows)
            args = self._args(root, db)
            apply_adjudications(args)
            actor = sqlite3.connect(args.out_db).execute(
                "SELECT actor_id FROM canonical_decision_ledger WHERE actor_type='user'").fetchone()[0]
            self.assertEqual(actor, "uchida")

    def test_20_actor_type_and_channel_are_fixed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            self._record(db, root, hold)
            args = self._args(root, db)
            apply_adjudications(args)
            row = sqlite3.connect(args.out_db).execute(
                "SELECT actor_type, decision_channel FROM canonical_decision_ledger WHERE open_hold_id=?",
                (hold["hold_id"],)).fetchone()
            self.assertEqual(row, ("user", "console"))

    def test_21_decided_at_is_stamped_by_the_apply_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            self._record(db, root, hold)
            rows = self._rows(self._adj_path(root))
            recorded_at = rows[0]["recorded_at"]
            rows[0]["recorded_at"] = "2000-01-01T00:00:00+00:00"
            self._set_rows(self._adj_path(root), rows)
            args = self._args(root, db)
            apply_adjudications(args)
            decided_at = sqlite3.connect(args.out_db).execute(
                "SELECT decided_at FROM canonical_decision_ledger WHERE actor_type='user'").fetchone()[0]
            self.assertNotEqual(decided_at, "2000-01-01T00:00:00+00:00")
            self.assertGreaterEqual(decided_at, recorded_at)

    def test_22_an_eligible_candidate_cannot_be_decided_by_the_user(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            self._record(db, root, hold)
            conn = connect_existing(db)
            conn.execute("DELETE FROM review_hold_ledger WHERE hold_id=?", (hold["hold_id"],))
            conn.commit(); conn.close()
            args = self._args(root, db)
            report = apply_adjudications(args)
            self.assertEqual(report["applied"], 0)
            self.assertEqual(report["issues"][0]["issue_type"], "hold_not_open")
            self.assertEqual(sqlite3.connect(args.out_db).execute(
                "SELECT COUNT(*) FROM canonical_decision_ledger WHERE actor_type='user'").fetchone()[0], 0)
            with self.assertRaises(ContractError):
                build_user_decision({"actor_type": "user", "requested_action": "accept"}, open_hold={"status": "closed"})

    def test_23_a_deferred_retry_hold_cannot_be_decided_by_the_user(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            self._record(db, root, hold)
            conn = connect_existing(db)
            conn.execute("UPDATE review_hold_ledger SET hold_mode='deferred_retry' WHERE hold_id=?", (hold["hold_id"],))
            conn.commit(); conn.close()
            report = apply_adjudications(self._args(root, db))
            self.assertEqual(report["issues"][0]["issue_type"], "hold_not_open")
            self.assertEqual(report["applied"], 0)

    # ------------------------------------------------------------- 一括 24-27
    def test_24_batches_never_cross_a_grouping_fingerprint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root)
            first = self._open_hold(db, root)
            second = self._open_hold(db, root, inbox_id="inbox-adj-2", packet_id="packet-adj-2",
                                     source_key="key-2", reason_code="conflicting_sources")
            self.assertNotEqual(first["grouping_fingerprint"], second["grouping_fingerprint"])
            with self.assertRaises(ValueError):
                console_data.save_adjudication_batch([first["hold_id"], second["hold_id"]], "accept",
                                                     db_path=db, path=self._adj_path(root))

    def test_25_each_batch_item_is_validated_on_its_own(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root)
            first = self._open_hold(db, root)
            second = self._open_hold(db, root, inbox_id="inbox-adj-2", packet_id="packet-adj-2", source_key="key-2")
            recorded = console_data.save_adjudication_batch([first["hold_id"], second["hold_id"]], "accept",
                                                            db_path=db, path=self._adj_path(root))
            self.assertEqual(len(recorded), 2)
            conn = connect_existing(db)
            conn.execute("UPDATE review_hold_ledger SET status='resolved' WHERE hold_id=?", (second["hold_id"],))
            conn.commit(); conn.close()
            report = apply_adjudications(self._args(root, db))
            self.assertEqual((report["applied"], report["invalidated"]), (1, 1))

    def test_26_the_batch_id_reaches_the_canonical_decision(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root)
            first = self._open_hold(db, root)
            second = self._open_hold(db, root, inbox_id="inbox-adj-2", packet_id="packet-adj-2", source_key="key-2")
            recorded = console_data.save_adjudication_batch([first["hold_id"], second["hold_id"]], "accept",
                                                            db_path=db, path=self._adj_path(root))
            args = self._args(root, db)
            apply_adjudications(args)
            stored = {row[0] for row in sqlite3.connect(args.out_db).execute(
                "SELECT adjudication_batch_id FROM canonical_decision_ledger WHERE actor_type='user'")}
            self.assertEqual(stored, {recorded[0]["batch_id"]})
            self.assertTrue(recorded[0]["batch_id"].startswith("adjbatch_"))

    def test_27_a_single_adjudication_has_no_batch_id(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            self._record(db, root, hold)
            args = self._args(root, db)
            apply_adjudications(args)
            self.assertIsNone(sqlite3.connect(args.out_db).execute(
                "SELECT adjudication_batch_id FROM canonical_decision_ledger WHERE actor_type='user'").fetchone()[0])

    # -------------------------------------------------- canonical 不変 28-31
    def test_28_canonical_fact_tables_do_not_move(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            self._record(db, root, hold)
            before = sqlite3.connect(db)
            counts = {name: before.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in CANONICAL_FACT_TABLES}
            before.close()
            args = self._args(root, db)
            apply_adjudications(args)
            conn = sqlite3.connect(args.out_db)
            self.assertEqual({name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in CANONICAL_FACT_TABLES}, counts)
            conn.close()

    def test_29_the_user_lane_imports_no_canonical_fact_writer(self):
        sources = "\n".join(Path(name).read_text() for name in (
            "review_inbox_adapters/apply_user_adjudications.py",
            "review_console/data.py",
            "review_console/server.py",
        ))
        for name in ("ensure_venue", "ensure_series_and_occurrence", "confirm_occurrence_schedule_venue",
                     "upsert_occurrence_song", "link_occurrence_evidence"):
            self.assertNotIn(name, sources)

    def test_30_the_inbox_status_stays_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            self._record(db, root, hold)
            args = self._args(root, db)
            apply_adjudications(args)
            self.assertEqual(sqlite3.connect(args.out_db).execute(
                "SELECT status FROM review_inbox_items WHERE inbox_id=?", (hold["inbox_id"],)).fetchone()[0], "candidate")

    def test_31_legacy_pending_rows_are_untouched(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            conn = connect_existing(db)
            stamp = _now().isoformat()
            conn.execute(
                "INSERT INTO review_inbox_items(inbox_id,kind,domain,title,status,source_id,source_key,"
                "source_payload_hash,last_seen_at,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                ("legacy-1", "song_candidate", "曲・用語・低緊急度", "旧レビュー行", "pending",
                 "legacy", "legacy-key", "b" * 64, stamp, stamp, stamp),
            )
            conn.commit(); conn.close()
            self._record(db, root, hold)
            args = self._args(root, db)
            apply_adjudications(args)
            row = sqlite3.connect(args.out_db).execute(
                "SELECT status, updated_at FROM review_inbox_items WHERE inbox_id='legacy-1'").fetchone()
            self.assertEqual(row, ("pending", stamp))

    # -------------------------------------------------------- 安全装置 32-36
    def test_32_dry_run_leaves_the_production_database_byte_identical(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            self._record(db, root, hold)
            before = self._checksum(db)
            apply_adjudications(self._args(root, db))
            self.assertEqual(self._checksum(db), before)

    def test_33_apply_without_the_confirmation_phrase_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); self._open_hold(db, root)
            with self.assertRaises(ValueError):
                apply_adjudications(self._args(root, db, apply=True, confirm=""))
            with self.assertRaises(ValueError):
                apply_adjudications(self._args(root, db, apply=True, confirm="APPLY USER ADJUDICATIONS "))

    def test_34_apply_never_migrates_and_stops_without_the_ledgers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root, migrate=False)
            with self.assertRaises(ValueError) as caught:
                apply_adjudications(self._args(root, db, apply=True, confirm="APPLY USER ADJUDICATIONS"))
            self.assertEqual(str(caught.exception), "judgment_ledger_missing")
            conn = sqlite3.connect(db)
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            conn.close()
            self.assertNotIn("canonical_decision_ledger", tables)

    def test_34a_dry_run_migrates_only_its_own_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root, migrate=False)
            args = self._args(root, db)
            report = apply_adjudications(args)
            self.assertEqual(report["migrations_applied"],
                             ["local_judgment_contract_v1", "event_inbox_candidate_v1", "review_claim_ledger_v1"])
            copy_tables = {row[0] for row in sqlite3.connect(args.out_db).execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            source_tables = {row[0] for row in sqlite3.connect(db).execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("review_hold_ledger", copy_tables)
            self.assertNotIn("review_hold_ledger", source_tables)

    def test_34b_no_auto_migrate_stops_a_dry_run_without_the_ledgers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root, migrate=False)
            with self.assertRaises(ValueError):
                apply_adjudications(self._args(root, db, no_auto_migrate=True))

    def test_35_a_dry_run_pointed_at_production_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); self._open_hold(db, root)
            with self.assertRaises(ValueError) as caught:
                apply_adjudications(self._args(root, db, out_db=db))
            self.assertIn("must differ", str(caught.exception))

    def test_36_the_real_command_line_drives_every_option(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._db(root); hold = self._open_hold(db, root)
            self._record(db, root, hold)
            argv = ["apply_user_adjudications.py", "--db", str(db), "--out-db", str(root / "cli.sqlite"),
                    "--adjudications", str(self._adj_path(root)), "--report-json", str(root / "cli-report.json"),
                    "--actor-id", "uchida"]
            with patch.object(sys, "argv", argv), redirect_stdout(StringIO()) as out:
                self.assertEqual(apply_main(), 0)
            self.assertEqual(json.loads(out.getvalue())["applied"], 1)
            self.assertTrue((root / "cli-report.json").exists())


if __name__ == "__main__":
    unittest.main()
