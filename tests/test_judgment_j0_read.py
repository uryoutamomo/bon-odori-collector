import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from event_model.local_judgment_migration import migrate_event_inbox_candidate, migrate_local_judgment_contract, migrate_review_claim_ledger
from master_rdb.master_db import init_db
from review_inbox_adapters.apply_judgment_results import main as apply_main, run as apply_results
from review_inbox_adapters.build_event_inbox_candidates import run as build_candidates
from review_inbox_adapters.build_judgment_packets import main as packet_main, run as build_packets
from review_inbox_adapters.build_judgment_packets import make_packet
import review_inbox_adapters.build_judgment_packets as packet_builder


class JudgmentJ0ReadTest(unittest.TestCase):
    def _seed(self, root):
        db = root / "master.sqlite"
        conn = init_db(db)
        migrate_local_judgment_contract(conn)
        migrate_event_inbox_candidate(conn)
        migrate_review_claim_ledger(conn)
        conn.commit(); conn.close()
        notice = root / "notice.json"
        notice.write_text(json.dumps({"report_type":"official_notice","source":{"report_id":"notice","raw_text":"text","source_url":"https://example.test"},"events":[{"action":"register_new","event_name_hint":"試験盆踊り","event_year":2099,"date_start":"2099-08-01","venue":{"name":"試験公園"}}]}, ensure_ascii=False))
        build_candidates(SimpleNamespace(report=[notice],report_dir=[],db=db,out_db=db,out_json=root/"candidate.json",out_md=root/"candidate.md",max_candidates=10,apply=True,confirm="APPLY EVENT INBOX CANDIDATES",no_auto_migrate=False,include_expired=False))
        return db

    def _packet_args(self, root, db):
        return SimpleNamespace(db=db,out_db=root/"packets.sqlite",out_dir=root/"packets",report_json=root/"packets-report.json",actor_id="oto-test",batch_size=20,max_packets=100,lease_minutes=30,force_claim=False,domain="event",apply=False,confirm="",no_auto_migrate=False)

    def _result_args(self, root, packet, **extra):
        result={key:packet[key] for key in ("packet_id","inbox_id","domain","lane","source_id","source_key","source_payload_hash")}
        result.update({"requested_action":"accept","payload":{}}); result.update(extra)
        result_path=root/"result.json"; result_path.write_text(json.dumps({"results":[result]}))
        return SimpleNamespace(db=root/"packets.sqlite",out_db=root/"results.sqlite",results=[result_path],packets_dir=root/"packets",report_json=root/"results-report.json",report_md=root/"results-report.md",actor_id="oto-test",apply=False,confirm="",no_auto_migrate=False)

    def test_packet_dry_run_writes_report_and_disables_retry_without_occurrence(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=self._seed(root)
            report=build_packets(self._packet_args(root,db))
            self.assertEqual(report["generated"],1)
            self.assertEqual(report["migrations_applied"], ["local_judgment_contract_v1","event_inbox_candidate_v1","review_claim_ledger_v1"])
            self.assertTrue((root/"packets-report.json").exists())
            packet=json.loads(Path(report["batches"][0]).read_text())["packets"][0]
            self.assertEqual(packet["retry_unavailable_reason"], "no_occurrence_candidates")
            self.assertNotIn("defer_for_retry", packet["allowed_actions"])
            self.assertIn("hold_for_user", packet["allowed_actions"])

    def test_apply_result_writes_ledgers_releases_claim_and_reports(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=self._seed(root); build=build_packets(self._packet_args(root,db))
            packet=json.loads(Path(build["batches"][0]).read_text())["packets"][0]
            result={key:packet[key] for key in ("packet_id","inbox_id","domain","lane","source_id","source_key","source_payload_hash")}
            result.update({"requested_action":"accept","payload":{}})
            result_path=root/"result.json"; result_path.write_text(json.dumps({"results":[result]}))
            args=SimpleNamespace(db=root/"packets.sqlite",out_db=root/"results.sqlite",results=[result_path],packets_dir=root/"packets",report_json=root/"results-report.json",report_md=root/"results-report.md",actor_id="oto-test",apply=False,confirm="",no_auto_migrate=False)
            report=apply_results(args)
            self.assertEqual(report["accepted"],1)
            self.assertTrue(args.report_json.exists()); self.assertTrue(args.report_md.exists())
            conn=sqlite3.connect(args.out_db)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM canonical_decision_ledger").fetchone()[0],1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM review_claim_ledger").fetchone()[0],0)
            conn.close()

    def test_untrusted_actor_identity_and_timestamp_are_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=self._seed(root); build=build_packets(self._packet_args(root,db)); packet=json.loads(Path(build["batches"][0]).read_text())["packets"][0]
            args=self._result_args(root,packet,actor_id="uchida",actor_type="user",decision_channel="console",decided_at="2000-01-01T00:00:00+00:00")
            self.assertEqual(apply_results(args)["accepted"],1)
            row=sqlite3.connect(args.out_db).execute("SELECT actor_id,actor_type,decision_channel,decided_at FROM canonical_decision_ledger").fetchone()
            self.assertEqual(row[:3],("oto-test","agent","llm")); self.assertNotEqual(row[3],"2000-01-01T00:00:00+00:00")

    def test_untrusted_payload_extra_field_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=self._seed(root); build=build_packets(self._packet_args(root,db)); packet=json.loads(Path(build["batches"][0]).read_text())["packets"][0]
            self.assertEqual(apply_results(self._result_args(root,packet,payload={"rationale":"LLM text"}))["rejected_result"],1)

    def test_apply_keeps_canonical_facts_and_candidate_status_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=self._seed(root); build=build_packets(self._packet_args(root,db)); packet=json.loads(Path(build["batches"][0]).read_text())["packets"][0]
            before=sqlite3.connect(root/"packets.sqlite"); tables=("venues","event_series","event_occurrences","occurrence_dates","songs","occurrence_songs")
            counts={t:before.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}; before.close()
            args=self._result_args(root,packet); apply_results(args); conn=sqlite3.connect(args.out_db)
            self.assertEqual({t:conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables},counts)
            self.assertEqual(conn.execute("SELECT status FROM review_inbox_items WHERE inbox_id=?",(packet["inbox_id"],)).fetchone()[0],"candidate")
            conn.close()

    def test_ten_day_expiry_retry_window_is_contract_valid(self):
        """v1.2 #51: +14 days must be clipped to the packet's window end."""
        when=datetime(2026, 8, 14, tzinfo=timezone.utc)
        row={"inbox_id":"inbox-test","contract_domain":"event","contract_lane":"event_update","source_id":"source","source_key":"key","source_payload_hash":"hash","expires_at":(when+timedelta(days=10)).isoformat(),"source_url":"https://example.test","payload_json":json.dumps({"proposal":{},"targets":{"retrieved_at":when.isoformat(),"occurrence_candidates":[{"occurrence_id":"occ-test"}]},"evidence_ids":["evidence-test"]})}
        packet=make_packet(row,when)
        candidate=packet["retry_candidates"][0]
        self.assertEqual(candidate["window_end"], (when+timedelta(days=10)).isoformat())
        self.assertEqual(candidate["next_eligible_at"], candidate["window_end"])

    def test_packet_apply_requires_its_own_confirmation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=self._seed(root); args=self._packet_args(root,db); args.apply=True; args.confirm=""
            with self.assertRaises(ValueError): build_packets(args)

    def test_result_apply_requires_its_own_confirmation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=self._seed(root)
            args=SimpleNamespace(db=db,out_db=root/"unused.sqlite",results=[],packets_dir=root/"missing",report_json=root/"report.json",report_md=root/"report.md",actor_id="oto-test",apply=True,confirm="",no_auto_migrate=False)
            with self.assertRaises(ValueError): apply_results(args)

    def test_packet_ids_are_deterministic_for_identical_row(self):
        when=datetime(2026, 8, 14, tzinfo=timezone.utc)
        row={"inbox_id":"inbox-test","contract_domain":"event","contract_lane":"event_update","source_id":"source","source_key":"key","source_payload_hash":"hash","expires_at":None,"source_url":"https://example.test","payload_json":json.dumps({"proposal":{},"targets":{"retrieved_at":when.isoformat(),"occurrence_candidates":[]},"evidence_ids":[]})}
        self.assertEqual(make_packet(row,when)["packet_id"], make_packet(row,when+timedelta(days=1))["packet_id"])

    def test_allowed_actions_follow_registry(self):
        with patch.dict(packet_builder.ACTION_REGISTRY, {}, clear=True):
            self.assertEqual(packet_builder.allowed("event", "event_update"), [])

    def test_no_auto_migrate_refuses_missing_claim_ledger(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=root/"master.sqlite"; init_db(db).close(); args=self._packet_args(root,db); args.no_auto_migrate=True
            with self.assertRaisesRegex(ValueError, "judgment_ledger_missing"): build_packets(args)

    def test_both_clis_parse_real_argv(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=self._seed(root)
            with patch("sys.argv", ["build_judgment_packets.py","--db",str(db),"--out-db",str(root/"packets.sqlite"),"--out-dir",str(root/"packets"),"--report-json",str(root/"packets-report.json"),"--actor-id","oto-test"]):
                self.assertEqual(packet_main(),0)
            packet=json.loads(next((root/"packets").glob("batch_*.json")).read_text())["packets"][0]
            result={key:packet[key] for key in ("packet_id","inbox_id","domain","lane","source_id","source_key","source_payload_hash")}; result.update({"requested_action":"accept","payload":{}})
            result_path=root/"result.json"; result_path.write_text(json.dumps({"results":[result]}))
            with patch("sys.argv", ["apply_judgment_results.py","--db",str(root/"packets.sqlite"),"--out-db",str(root/"results.sqlite"),"--packets-dir",str(root/"packets"),"--results",str(result_path),"--report-json",str(root/"results-report.json"),"--report-md",str(root/"results-report.md"),"--actor-id","oto-test"]):
                self.assertEqual(apply_main(),0)
