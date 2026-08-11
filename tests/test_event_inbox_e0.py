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

    @staticmethod
    def _seed_occurrence(conn, *, occurrence_id="occ_probe", display_name="試験盆踊り", year=2099, date_start="2099-08-01"):
        """会場・系列・開催回を1件だけ置く最小 fixture。E0 の候補検索が当たる状態を作る。"""
        stamp = "2026-01-01T00:00:00+00:00"
        conn.execute("INSERT INTO venues (venue_id, origin, canonical_name, normalized_name, area, address, review_status, created_at, updated_at) VALUES ('ven_probe','curated','試験公園','試験公園','千代田区','',?,?,?)", ("active", stamp, stamp))
        conn.execute("INSERT INTO event_series (series_id, origin, series_key, canonical_name, normalized_name, usual_venue_id, status, created_at, updated_at) VALUES ('ser_probe','curated',?,?,?, 'ven_probe','active',?,?)", (display_name, display_name, display_name, stamp, stamp))
        conn.execute("INSERT INTO event_occurrences (occurrence_id, origin, series_id, event_year, occurrence_sequence, display_name, venue_id, date_start, date_status, lifecycle_status, created_at, updated_at) VALUES (?, 'curated','ser_probe',?,1,?, 'ven_probe',?, 'confirmed','published',?,?)", (occurrence_id, year, display_name, date_start, stamp, stamp))
        conn.commit()

    def test_strong_fuzzy_match_is_not_promoted_to_explicit_id(self):
        """既存と完全同名でも、レポートがIDを書いていない限り対象は確定しない（仕様 §6 / §11-1）。"""
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=root/"master.sqlite"
            conn=init_db(db); migrate_local_judgment_contract(conn); migrate_event_inbox_candidate(conn); self._seed_occurrence(conn); conn.close()
            report=root/"notice.json"; report.write_text(json.dumps({"report_type":"official_notice","source":{"report_id":"notice","raw_text":"text"},"events":[{"action":"register_new","event_name_hint":"試験盆踊り","event_year":2099,"date_start":"2099-08-01","venue":{"name":"試験公園"}}]},ensure_ascii=False),encoding="utf-8")
            args=type("Args",(),{"report":[report],"report_dir":[],"db":db,"out_db":root/"dry.sqlite","out_json":root/"report.json","out_md":root/"report.md","max_candidates":200,"apply":False,"confirm":"","no_auto_migrate":False,"include_expired":False})()
            self.assertEqual(run(args)["summary"]["created"],1)
            dry=sqlite3.connect(root/"dry.sqlite")
            payload=json.loads(dry.execute("SELECT payload_json FROM review_inbox_items WHERE kind='event_candidate'").fetchone()[0])
            best=max(row["match_score"] for row in payload["targets"]["occurrence_candidates"])
            self.assertGreaterEqual(best,0.92,"完全同名の候補が検索に出ていないと、この検査は無意味になる")
            self.assertIsNone(payload["proposal"]["explicit_occurrence_id"],"閾値超えの候補があってもIDを確定してはいけない")
            self.assertIsNone(payload["resolved_target"],"名寄せ結果を resolved_target に書いてはいけない")

    def test_display_name_change_does_not_create_revision(self):
        """DB側の表示名が変わっても、レポートが同じなら hash も revision も動かない（仕様 §3.4 / §11-39）。"""
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=root/"master.sqlite"
            conn=init_db(db); migrate_local_judgment_contract(conn); migrate_event_inbox_candidate(conn); self._seed_occurrence(conn); conn.close()
            report=root/"notice.json"; report.write_text(json.dumps({"report_type":"official_notice","source":{"report_id":"notice","raw_text":"text"},"events":[{"action":"confirm_existing","occurrence_id":"occ_probe","detail_addendum":"掲示物で確認"}]},ensure_ascii=False),encoding="utf-8")
            def invoke():
                return run(type("Args",(),{"report":[report],"report_dir":[],"db":db,"out_db":db,"out_json":root/"report.json","out_md":root/"report.md","max_candidates":200,"apply":True,"confirm":"APPLY EVENT INBOX CANDIDATES","no_auto_migrate":False,"include_expired":False})())
            self.assertEqual(invoke()["summary"]["created"],1)
            conn=sqlite3.connect(db)
            before=conn.execute("SELECT source_payload_hash, revision FROM review_inbox_items WHERE kind='event_candidate'").fetchone()
            conn.execute("UPDATE event_occurrences SET display_name = '書き換えた表示名' WHERE occurrence_id = 'occ_probe'"); conn.commit(); conn.close()
            self.assertEqual(invoke()["summary"]["noop"],1,"レポートが同じなら再実行は no-op でなければならない")
            conn=sqlite3.connect(db)
            self.assertEqual(conn.execute("SELECT source_payload_hash, revision FROM review_inbox_items WHERE kind='event_candidate'").fetchone(),before)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM review_inbox_items WHERE kind='event_candidate'").fetchone()[0],1)
