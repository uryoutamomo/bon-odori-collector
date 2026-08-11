import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from event_model.local_judgment_migration import migrate_event_inbox_candidate, migrate_local_judgment_contract
from master_rdb.master_db import init_db
from review_inbox_adapters.build_event_inbox_candidates import main as cli_main, run
from review_inbox_adapters.event_inbox_writer import insert_candidate


class EventInboxE0Test(unittest.TestCase):
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
            root = Path(temp); db=root/"master.sqlite"; init_db(db).close()
            report=root/"notice.json"; report.write_text(json.dumps({"report_type":"official_notice","source":{"report_id":"notice","raw_text":"text","source_url":"https://example.test"},"events":[{"action":"register_new","event_name_hint":"試験盆踊り","event_year":2099,"date_start":"2099-08-01","venue":{"name":"試験公園"}}]},ensure_ascii=False),encoding="utf-8")
            args=type("Args",(),{"report":[report],"report_dir":[],"db":db,"out_db":root/"dry.sqlite","out_json":root/"report.json","out_md":root/"report.md","max_candidates":200,"apply":False,"confirm":"","no_auto_migrate":False})()
            result=run(args)
            self.assertEqual(result["summary"]["created"],1)
            self.assertEqual(result["migrations_applied"],["local_judgment_contract_v1","event_inbox_candidate_v1"])
            original=sqlite3.connect(db); dry=sqlite3.connect(root/"dry.sqlite")
            self.assertEqual(original.execute("SELECT COUNT(*) FROM review_inbox_items").fetchone()[0],0)
            row=dry.execute("SELECT domain, contract_domain, status, revision FROM review_inbox_items").fetchone()
            self.assertEqual(row,("イベント","event","candidate",0))

    def test_no_auto_migrate_refuses_missing_ledger(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=root/"master.sqlite"; init_db(db).close()
            report=root/"notice.json"; report.write_text(json.dumps({"report_type":"official_notice","source":{"report_id":"notice","raw_text":"text"},"events":[]}),encoding="utf-8")
            args=type("Args",(),{"report":[report],"report_dir":[],"db":db,"out_db":root/"dry.sqlite","out_json":root/"report.json","out_md":root/"report.md","max_candidates":200,"apply":False,"confirm":"","no_auto_migrate":True})()
            self.assertTrue(any(x["issue_type"]=="canonical_decision_ledger_missing" for x in run(args)["issues"]))
