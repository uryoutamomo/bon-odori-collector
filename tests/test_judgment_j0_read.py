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
    def test_structure_does_not_import_canonical_fact_writers(self):
        sources = "\n".join(Path(name).read_text() for name in (
            "review_inbox_adapters/build_judgment_packets.py",
            "review_inbox_adapters/apply_judgment_results.py",
            "review_inbox_adapters/judgment_ledger_writer.py",
        ))
        for name in ("ensure_venue", "ensure_series_and_occurrence", "confirm_occurrence_schedule_venue", "upsert_occurrence_song", "link_occurrence_evidence"):
            self.assertNotIn(name, sources)
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
            before=sqlite3.connect(root/"packets.sqlite"); tables=("venues","venue_aliases","event_series","event_series_aliases","event_occurrences","occurrence_dates","occurrence_evidence_links","songs","occurrence_songs","occurrence_song_evidence_links")
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

    # --- §9 の未カバー分（こと、2026-08-14）。対応表 docs/local-judgment-j0-read-test-coverage.md を同時に更新すること ---

    def _inject_occurrence_candidate(self, db, occurrence_id="occ-test"):
        """候補集合だけ差し替える。targets は source_payload_hash の材料ではないので改訂にはならない（E0 §3.4）。"""
        conn=sqlite3.connect(db); conn.row_factory=sqlite3.Row
        row=conn.execute("SELECT inbox_id,payload_json FROM review_inbox_items WHERE kind='event_candidate'").fetchone()
        payload=json.loads(row["payload_json"])
        payload["targets"]["occurrence_candidates"]=[{"occurrence_id":occurrence_id,"series_id":"ser-test","display_name":"試験盆踊り","match_score":0.5}]
        conn.execute("UPDATE review_inbox_items SET payload_json=? WHERE inbox_id=?",(json.dumps(payload,ensure_ascii=False),row["inbox_id"]))
        conn.commit(); inbox_id=row["inbox_id"]; conn.close(); return inbox_id

    def _set_queue_state(self, db, inbox_id, state):
        conn=sqlite3.connect(db)
        conn.execute("INSERT INTO review_queue_state_ledger(inbox_id,domain,lane,queue_state,decision_id,updated_at) VALUES (?,?,?,?,?,?)",(inbox_id,"event","event_create",state,"decision:seed","2026-08-14T00:00:00+00:00"))
        conn.commit(); conn.close()

    def _retryable_packet(self, root, db):
        """defer_for_retry を選べる packet を1件作る（occurrence 候補が要る。仕様 §3.4）。"""
        self._inject_occurrence_candidate(db)
        build=build_packets(self._packet_args(root,db))
        return json.loads(Path(build["batches"][0]).read_text())["packets"][0]

    def test_closed_or_held_candidates_are_not_packetized(self):
        """§9-1,2: closed からの再判断と、hold 中の候補の横取りを禁じる。"""
        for state in ("closed","deferred_retry","awaiting_user"):
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp); db=self._seed(root); inbox_id=self._inject_occurrence_candidate(db)
                self._set_queue_state(db,inbox_id,state)
                report=build_packets(self._packet_args(root,db))
                self.assertEqual(report["generated"],0,state)
                self.assertEqual([x["reason"] for x in report["excluded"]],["not_eligible"],state)

    def test_superseded_candidate_is_not_packetized(self):
        """§9-3: 改訂された古い行を判断させない。"""
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=self._seed(root); inbox_id=self._inject_occurrence_candidate(db)
            conn=sqlite3.connect(db); conn.execute("UPDATE review_inbox_items SET superseded_by_inbox_id=? WHERE inbox_id=?",("inbox_newer",inbox_id)); conn.commit(); conn.close()
            report=build_packets(self._packet_args(root,db))
            self.assertEqual(report["generated"],0)
            self.assertEqual([x["reason"] for x in report["excluded"]],["superseded"])

    def test_expired_candidate_is_not_packetized(self):
        """§9-4: 8/15 の行事を 8/20 に判断しても無意味なので出さない。"""
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=self._seed(root); inbox_id=self._inject_occurrence_candidate(db)
            conn=sqlite3.connect(db); conn.execute("UPDATE review_inbox_items SET expires_at=? WHERE inbox_id=?",("2020-01-01T23:59:59+09:00",inbox_id)); conn.commit(); conn.close()
            report=build_packets(self._packet_args(root,db))
            self.assertEqual(report["generated"],0)
            self.assertEqual([x["reason"] for x in report["excluded"]],["expired"])

    def test_candidate_without_queue_row_is_eligible(self):
        """§9-5: 「台帳に行が無い＝eligible」は E0 §8 から J0-read が引き継いだ規則。"""
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=self._seed(root)
            conn=sqlite3.connect(db)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM review_queue_state_ledger").fetchone()[0],0)
            conn.close()
            self.assertEqual(build_packets(self._packet_args(root,db))["generated"],1)

    def test_hold_for_user_writes_three_ledgers_with_serialized_json(self):
        """§9-22,28,29: raw の hold_for_user が registry の hold へ正規化され、3表が整合し、JSON 列が文字列で入る。"""
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=self._seed(root); packet=self._retryable_packet(root,db)
            args=self._result_args(root,packet,requested_action="hold_for_user",reason_code="requires_policy_judgment")
            self.assertEqual(apply_results(args)["held_for_user"],1)
            conn=sqlite3.connect(args.out_db); conn.row_factory=sqlite3.Row
            decision=conn.execute("SELECT * FROM canonical_decision_ledger").fetchone()
            self.assertEqual((decision["action"],decision["hold_mode"],decision["queue_state_after"]),("hold","awaiting_user","awaiting_user"))
            self.assertIsNone(decision["next_eligible_at"])
            queue=conn.execute("SELECT queue_state,decision_id FROM review_queue_state_ledger").fetchone()
            self.assertEqual((queue["queue_state"],queue["decision_id"]),("awaiting_user",decision["decision_id"]))
            hold=conn.execute("SELECT * FROM review_hold_ledger").fetchone()
            self.assertEqual(hold["decision_id"],decision["decision_id"])
            self.assertEqual(json.loads(hold["allowed_actions"]),["accept","reject"])
            self.assertEqual(json.loads(hold["candidate_ids"]),["occ-test"])
            conn.close()

    def test_declared_hold_mode_conflicting_with_reason_code_is_rejected(self):
        """§9-23: 申告と reason_code 由来の mode が食い違ったら、黙って直さず捨てる。"""
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=self._seed(root); packet=self._retryable_packet(root,db)
            # 再試行候補を渡しておく。渡さないと「deferred_retry なのに候補が無い」で契約が先に弾いてしまい、
            # mode 照合を外しても同じ結果になってテストが素通りする（変異チェックで実測）。
            args=self._result_args(root,packet,requested_action="hold_for_user",reason_code="packet_stale",selected_retry_candidate_id=packet["retry_candidates"][0]["candidate_id"])
            report=apply_results(args)
            self.assertEqual((report["rejected_result"],report["held_for_user"],report["deferred_for_retry"]),(1,0,0))
            conn=sqlite3.connect(args.out_db)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM canonical_decision_ledger").fetchone()[0],0)
            conn.close()

    def test_retry_candidate_outside_the_machine_list_is_rejected(self):
        """§9-24: 機械が提示していない再試行候補を選ばせない。"""
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=self._seed(root); packet=self._retryable_packet(root,db)
            args=self._result_args(root,packet,requested_action="defer_for_retry",reason_code="awaiting_official_announcement",selected_retry_candidate_id="retry-not-offered")
            self.assertEqual(apply_results(args)["rejected_result"],1)

    def test_next_eligible_at_comes_from_the_machine_candidate(self):
        """§9-25: LLM が書いた日付は読まず、凍結された候補の値を使う。"""
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=self._seed(root); packet=self._retryable_packet(root,db)
            candidate=packet["retry_candidates"][0]
            args=self._result_args(root,packet,requested_action="defer_for_retry",reason_code="awaiting_official_announcement",selected_retry_candidate_id=candidate["candidate_id"],next_eligible_at="2099-01-01T00:00:00+09:00")
            self.assertEqual(apply_results(args)["deferred_for_retry"],1)
            conn=sqlite3.connect(args.out_db)
            stored=conn.execute("SELECT next_eligible_at FROM canonical_decision_ledger").fetchone()[0]
            conn.close()
            self.assertEqual(stored,candidate["next_eligible_at"])
            self.assertNotEqual(stored,"2099-01-01T00:00:00+09:00")

    def test_defer_for_retry_passes_end_to_end_for_a_candidate_expiring_soon(self):
        """§9-51 の通し: 期限が10日後でも defer_for_retry が契約を通って台帳へ入る（窓計算だけでなく取り込みまで）。"""
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=self._seed(root); inbox_id=self._inject_occurrence_candidate(db)
            near=(datetime.now(timezone.utc)+timedelta(days=10)).isoformat()
            conn=sqlite3.connect(db); conn.execute("UPDATE review_inbox_items SET expires_at=? WHERE inbox_id=?",(near,inbox_id)); conn.commit(); conn.close()
            build=build_packets(self._packet_args(root,db))
            packet=json.loads(Path(build["batches"][0]).read_text())["packets"][0]
            candidate=packet["retry_candidates"][0]
            args=self._result_args(root,packet,requested_action="defer_for_retry",reason_code="awaiting_official_announcement",selected_retry_candidate_id=candidate["candidate_id"])
            self.assertEqual(apply_results(args)["deferred_for_retry"],1)
            conn=sqlite3.connect(args.out_db); conn.row_factory=sqlite3.Row
            self.assertEqual(conn.execute("SELECT queue_state FROM review_queue_state_ledger").fetchone()["queue_state"],"deferred_retry")
            hold=conn.execute("SELECT hold_mode,next_eligible_at,hold_packet_json FROM review_hold_ledger").fetchone()
            self.assertEqual(hold["hold_mode"],"deferred_retry")
            self.assertEqual(json.loads(hold["hold_packet_json"])["next_eligible_at"],hold["next_eligible_at"])
            conn.close()

    def test_unknown_reason_code_is_rejected(self):
        """§9-26: 対応表に無い reason_code を作文させない。"""
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=self._seed(root); packet=self._retryable_packet(root,db)
            args=self._result_args(root,packet,requested_action="hold_for_user",reason_code="なんとなく保留")
            self.assertEqual(apply_results(args)["rejected_result"],1)

    def test_accept_closes_the_queue_state(self):
        """§9-27: terminal decision で queue が closed になる。"""
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=self._seed(root); build=build_packets(self._packet_args(root,db))
            packet=json.loads(Path(build["batches"][0]).read_text())["packets"][0]
            args=self._result_args(root,packet)
            apply_results(args)
            conn=sqlite3.connect(args.out_db); conn.row_factory=sqlite3.Row
            queue=conn.execute("SELECT queue_state FROM review_queue_state_ledger WHERE inbox_id=?",(packet["inbox_id"],)).fetchone()
            self.assertEqual(queue["queue_state"],"closed")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM review_hold_ledger").fetchone()[0],0)
            conn.close()

    def test_ledger_write_rolls_back_completely_on_failure(self):
        """§9-30: 3表のどれかで失敗したら1行も残さない。hold 表への書き込みは canonical の後なので、ここで壊すと巻き戻りが効くか分かる。"""
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=self._seed(root); packet=self._retryable_packet(root,db)
            args=self._result_args(root,packet,requested_action="hold_for_user",reason_code="requires_policy_judgment")
            with patch("review_inbox_adapters.judgment_ledger_writer.build_hold_ledger_entry",side_effect=sqlite3.OperationalError("boom")):
                with self.assertRaises(sqlite3.OperationalError):
                    apply_results(args)
            conn=sqlite3.connect(args.out_db)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM canonical_decision_ledger").fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM review_queue_state_ledger").fetchone()[0],0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM review_hold_ledger").fetchone()[0],0)
            conn.close()

    def test_reapplying_the_same_result_is_a_noop(self):
        """§9-31: 二重取り込みで台帳が増えない（決定的な packet_id が効いている証拠）。"""
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=self._seed(root); build=build_packets(self._packet_args(root,db))
            packet=json.loads(Path(build["batches"][0]).read_text())["packets"][0]
            first=self._result_args(root,packet); self.assertEqual(apply_results(first)["accepted"],1)
            second=self._result_args(root,packet); second.db=first.out_db; second.out_db=root/"results2.sqlite"
            report=apply_results(second)
            self.assertEqual((report["noop"],report["accepted"]),(1,0))
            conn=sqlite3.connect(second.out_db)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM canonical_decision_ledger").fetchone()[0],1)
            conn.close()

    def test_same_decision_id_with_different_content_stops(self):
        """§9-32: decision_id は同じでも中身が違うものを黙って上書きしない（payload は decision_id の材料ではない）。"""
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=self._seed(root); build=build_packets(self._packet_args(root,db))
            packet=json.loads(Path(build["batches"][0]).read_text())["packets"][0]
            first=self._result_args(root,packet); apply_results(first)
            second=self._result_args(root,packet,payload={"reason_detail":"あとから足した"}); second.db=first.out_db; second.out_db=root/"results2.sqlite"
            with self.assertRaisesRegex(ValueError,"decision_id_conflict"):
                apply_results(second)

    def test_legacy_pending_rows_are_untouched(self):
        """§9-35: 判断待ち561件の器（既存レビュー画面）へ手を出さない。"""
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); db=self._seed(root)
            conn=sqlite3.connect(db)
            conn.execute("INSERT INTO review_inbox_items(inbox_id,kind,domain,time_scope,title,source_id,source_key,status,source_payload_hash,last_seen_at,payload_json,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",("inbox_legacy","song_candidate","曲・用語・低緊急度","reference","古い判断待ち","legacy","legacy#1","pending","f"*64,"2026-07-01T00:00:00+09:00","{}","2026-07-01T00:00:00+09:00","2026-07-01T00:00:00+09:00"))
            conn.commit(); before=conn.execute("SELECT * FROM review_inbox_items WHERE inbox_id='inbox_legacy'").fetchone(); conn.close()
            build=build_packets(self._packet_args(root,db))
            packet=json.loads(Path(build["batches"][0]).read_text())["packets"][0]
            args=self._result_args(root,packet); apply_results(args)
            conn=sqlite3.connect(args.out_db)
            self.assertEqual(conn.execute("SELECT * FROM review_inbox_items WHERE inbox_id='inbox_legacy'").fetchone(),before)
            conn.close()
