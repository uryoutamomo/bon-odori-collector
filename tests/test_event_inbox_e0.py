import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from event_model.local_judgment_migration import migrate_event_inbox_candidate, migrate_local_judgment_contract
from master_rdb.master_db import init_db
from review_inbox_adapters.build_event_inbox_candidates import main as cli_main, run
from review_inbox_adapters.event_inbox_writer import insert_candidate


class EventInboxE0Test(unittest.TestCase):
    def test_structure_does_not_import_canonical_writers(self):
        source = Path("review_inbox_adapters/build_event_inbox_candidates.py").read_text()
        for name in ("ensure_venue", "ensure_series_and_occurrence", "confirm_occurrence_schedule_venue", "upsert_occurrence_song", "link_occurrence_evidence"):
            self.assertNotIn(name, source)

    def test_main_parses_real_argv_and_runs(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=root/"master.sqlite"; init_db(db).close()
            report=root/"notice.json"; report.write_text(json.dumps({"report_type":"official_notice","source":{"report_id":"notice","raw_text":"text"},"events":[{"action":"register_new","event_name_hint":"試験盆踊り","event_year":2099,"date_start":"2099-08-01","venue":{"name":"試験公園"}}]},ensure_ascii=False),encoding="utf-8")
            argv=["build_event_inbox_candidates.py","--report",str(report),"--db",str(db),"--out-db",str(root/"dry.sqlite"),"--out-json",str(root/"report.json"),"--out-md",str(root/"report.md")]
            with patch("sys.argv", argv): self.assertEqual(cli_main(),0)
            self.assertEqual(json.loads((root/"report.json").read_text())["summary"]["created"],1)

    def test_apply_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=root/"master.sqlite"; init_db(db).close()
            args=type("Args",(),{"report":[root/"missing.json"],"report_dir":[],"db":db,"out_db":root/"out.sqlite","out_json":root/"x.json","out_md":root/"x.md","max_candidates":200,"apply":True,"confirm":"","no_auto_migrate":False,"include_expired":False})()
            with self.assertRaises(ValueError, msg="confirmation guard must run before report IO"):
                run(args)
    def test_migration_is_additive_and_idempotent(self):
        conn = init_db(":memory:")
        migrate_local_judgment_contract(conn)
        first = migrate_event_inbox_candidate(conn)
        second = migrate_event_inbox_candidate(conn)
        self.assertIn("revision", first["columns_added"])
        self.assertEqual(second["columns_added"], [])
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM local_judgment_schema_migrations WHERE version=2").fetchone()[0], 1)

    def test_dry_run_creates_candidate_and_keeps_source_db_unmodified(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db=root/"master.sqlite"; source=init_db(db); migrate_local_judgment_contract(source); migrate_event_inbox_candidate(source); source.commit(); source.close()
            report=root/"notice.json"; report.write_text(json.dumps({"report_type":"official_notice","source":{"report_id":"notice","raw_text":"text","source_url":"https://example.test"},"events":[{"action":"register_new","event_name_hint":"試験盆踊り","event_year":2099,"date_start":"2099-08-01","venue":{"name":"試験公園"}}]},ensure_ascii=False),encoding="utf-8")
            args=type("Args",(),{"report":[report],"report_dir":[],"db":db,"out_db":root/"dry.sqlite","out_json":root/"report.json","out_md":root/"report.md","max_candidates":200,"apply":False,"confirm":"","no_auto_migrate":False,"include_expired":False})()
            result=run(args)
            self.assertEqual(result["summary"]["created"],1)
            self.assertEqual(result["migrations_applied"],["local_judgment_contract_v1","event_inbox_candidate_v1"])
            original=sqlite3.connect(db); dry=sqlite3.connect(root/"dry.sqlite")
            self.assertEqual(original.execute("SELECT COUNT(*) FROM review_inbox_items").fetchone()[0],0)
            row=dry.execute("SELECT domain, contract_domain, status, revision FROM review_inbox_items").fetchone()
            self.assertEqual(row,("イベント","event","candidate",0))
            from review_inbox_adapters.build_event_inbox_candidates import CANONICAL_TABLES
            for table in CANONICAL_TABLES:
                self.assertEqual(original.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], dry.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], table)

    def test_no_auto_migrate_refuses_missing_ledger(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=root/"master.sqlite"; init_db(db).close()
            report=root/"notice.json"; report.write_text(json.dumps({"report_type":"official_notice","source":{"report_id":"notice","raw_text":"text"},"events":[]}),encoding="utf-8")
            args=type("Args",(),{"report":[report],"report_dir":[],"db":db,"out_db":root/"dry.sqlite","out_json":root/"report.json","out_md":root/"report.md","max_candidates":200,"apply":False,"confirm":"","no_auto_migrate":True,"include_expired":False})()
            self.assertTrue(any(x["issue_type"]=="canonical_decision_ledger_missing" for x in run(args)["issues"]))

    def test_decided_revision_is_idempotent_on_third_run(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=root/"master.sqlite"; conn=init_db(db); migrate_local_judgment_contract(conn); migrate_event_inbox_candidate(conn); conn.commit(); conn.close()
            report=root/"notice.json"
            def invoke(detail):
                report.write_text(json.dumps({"report_type":"official_notice","source":{"report_id":"notice","raw_text":"text"},"events":[{"action":"register_new","event_name_hint":"試験盆踊り","event_year":2099,"date_start":"2099-08-01","detail_addendum":detail,"venue":{"name":"試験公園"}}]},ensure_ascii=False),encoding="utf-8")
                return run(type("Args",(),{"report":[report],"report_dir":[],"db":db,"out_db":db,"out_json":root/"report.json","out_md":root/"report.md","max_candidates":200,"apply":True,"confirm":"APPLY EVENT INBOX CANDIDATES","no_auto_migrate":False,"include_expired":False})())
            invoke("初版")
            conn=sqlite3.connect(db); old=conn.execute("SELECT inbox_id FROM review_inbox_items").fetchone()[0]
            conn.execute("INSERT INTO canonical_decision_ledger(decision_id,schema_version,packet_id,packet_sha256,inbox_id,domain,lane,source_id,source_key,source_payload_hash,action,queue_state_before,queue_state_after,payload_json,actor_type,actor_id,decision_channel,decided_at,created_at) VALUES ('d',1,'p','x',?,'event','event_create','s','k','h','accept','eligible','closed','{}','agent','a','llm','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00')",(old,)); conn.commit(); conn.close()
            invoke("改訂"); third=invoke("改訂")
            conn=sqlite3.connect(db); self.assertEqual(conn.execute("SELECT COUNT(*) FROM review_inbox_items").fetchone()[0],2)
            self.assertEqual(conn.execute("SELECT COUNT(DISTINCT revision_family_key), MAX(revision) FROM review_inbox_items").fetchone(),(1,1))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM review_inbox_items WHERE superseded_by_inbox_id IS NOT NULL").fetchone()[0],1)
            self.assertEqual(third["summary"]["noop"],1)
