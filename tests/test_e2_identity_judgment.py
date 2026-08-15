"""E2: LLMは同一性だけを答え、機械が変更要求へ変換する。

受け入れ条件の一覧は docs/local-judgment-e2-identity-to-change-request-v1.md §7 にある。
"""
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from event_model.local_judgment_migration import migrate_event_inbox_candidate, migrate_local_judgment_contract, migrate_review_claim_ledger
from master_rdb.master_db import init_db, normalize_text, stable_id
from report_apply.apply_change_requests import apply_one_request, validate_payload
from review_inbox_adapters.apply_judgment_results import run as apply_results
from review_inbox_adapters.build_change_requests_from_judgment import build_payload, main as convert_main, run as convert_run
from review_inbox_adapters.build_event_inbox_candidates import run as build_candidates
from review_inbox_adapters.build_judgment_packets import run as build_packets
from review_inbox_adapters.local_judgment_contract import ACTION_REGISTRY, IDENTITY_MATCH_NONE, TRANSITIONS
import review_console.data as console_data

ROOT = Path(__file__).resolve().parents[1]
STAMP = "2026-01-01T00:00:00+00:00"
NONE = IDENTITY_MATCH_NONE


def _seed(root, *, existing=True, venue_name="試験公園", series_name="試験盆踊り"):
    db = root / "master.sqlite"
    conn = init_db(db)
    migrate_local_judgment_contract(conn)
    migrate_event_inbox_candidate(conn)
    migrate_review_claim_ledger(conn)
    if existing:
        conn.execute("INSERT INTO venues (venue_id, origin, canonical_name, normalized_name, area, address, review_status, created_at, updated_at) VALUES ('ven_seed','curated',?,?,'千代田区','','active',?,?)", (venue_name, normalize_text(venue_name), STAMP, STAMP))
        conn.execute("INSERT INTO event_series (series_id, origin, series_key, canonical_name, normalized_name, usual_venue_id, status, created_at, updated_at) VALUES ('ser_seed','curated',?,?,?, 'ven_seed','active',?,?)", (normalize_text(series_name), series_name, normalize_text(series_name), STAMP, STAMP))
        conn.execute("INSERT INTO event_occurrences (occurrence_id, origin, series_id, event_year, occurrence_sequence, display_name, venue_id, date_start, date_status, lifecycle_status, created_at, updated_at) VALUES ('occ_seed','curated','ser_seed',2099,1,?, 'ven_seed','2099-08-01','confirmed','published',?,?)", (series_name, STAMP, STAMP))
    conn.commit()
    conn.close()
    notice = root / "notice.json"
    notice.write_text(json.dumps({"report_type": "official_notice", "source": {"report_id": "notice", "raw_text": "text", "source_url": "https://example.test/notice"}, "events": [{"action": "register_new", "event_name_hint": "試験盆踊り", "event_year": 2099, "date_start": "2099-08-01", "venue": {"name": "試験公園"}}]}, ensure_ascii=False), encoding="utf-8")
    build_candidates(SimpleNamespace(report=[notice], report_dir=[], db=db, out_db=db, out_json=root / "c.json", out_md=root / "c.md", max_candidates=10, apply=True, confirm="APPLY EVENT INBOX CANDIDATES", no_auto_migrate=False, include_expired=False))
    return db


def _packet(root, db):
    report = build_packets(SimpleNamespace(db=db, out_db=root / "packets.sqlite", out_dir=root / "packets", report_json=root / "p.json", actor_id="oto-test", batch_size=20, max_packets=100, lease_minutes=30, force_claim=False, domain="event", apply=False, confirm="", no_auto_migrate=False))
    return json.loads(Path(report["batches"][0]).read_text())["packets"][0]


def _identity(packet, **extra):
    occurrence = (packet["targets"].get("occurrence_candidates") or [{}])[0]
    venue = (packet["targets"].get("venue_candidates") or [{}])[0]
    payload = {"occurrence_match": occurrence.get("occurrence_id") or NONE,
               "series_match": occurrence.get("series_id") or NONE,
               "venue_match": venue.get("venue_id") or NONE}
    payload.update(extra)
    return payload


def _apply(root, packet, payload, name="result"):
    result = {key: packet[key] for key in ("packet_id", "inbox_id", "domain", "lane", "source_id", "source_key", "source_payload_hash")}
    result.update({"requested_action": "accept", "payload": payload})
    path = root / f"{name}.json"
    path.write_text(json.dumps({"results": [result]}, ensure_ascii=False), encoding="utf-8")
    args = SimpleNamespace(db=root / "packets.sqlite", out_db=root / f"{name}s.sqlite", results=[path], packets_dir=root / "packets", report_json=root / f"{name}-r.json", report_md=root / f"{name}-r.md", actor_id="oto-test", apply=False, confirm="", no_auto_migrate=False)
    return apply_results(args), args


def _convert(root, db, name="conv"):
    args = SimpleNamespace(db=db, out_json=root / f"{name}.json", out_md=root / f"{name}.md")
    report = convert_run(args)
    return report, json.loads((root / f"{name}.json").read_text())


class RegistryContractTest(unittest.TestCase):
    """§7-1〜7：同一性の payload は event レーンにだけ足し、行為の語彙は動かさない。"""

    def test_identity_fields_are_allowed_on_event_lanes(self):
        for lane in ("event_create", "event_update"):
            allowed = ACTION_REGISTRY[("event", lane, "accept")]["allowed_payload_fields"]
            self.assertTrue({"occurrence_match", "series_match", "venue_match"} <= allowed, lane)

    def test_song_and_term_payload_fields_are_unchanged(self):
        """他ドメインを巻き込んでいないこと。"""
        for key in (("song", "song"), ("term", "term")):
            for action in ("accept", "reject", "hold"):
                self.assertEqual(ACTION_REGISTRY[(*key, action)]["allowed_payload_fields"],
                                 frozenset({"target_id", "reason_detail", "evidence_class"}), (key, action))
            self.assertEqual(ACTION_REGISTRY[(*key, "requeue")]["allowed_payload_fields"],
                             frozenset({"hold_id", "released_at", "next_eligible_at"}))

    def test_event_reject_does_not_take_identity_fields(self):
        self.assertEqual(ACTION_REGISTRY[("event", "event_create", "reject")]["allowed_payload_fields"],
                         frozenset({"target_id", "reason_detail", "evidence_class"}))

    def test_transitions_are_unchanged(self):
        """行為の語彙を増やしていない＝契約の遷移表に手を入れていない証明。"""
        self.assertEqual(TRANSITIONS, frozenset({
            ("eligible", "closed", "agent", "accept"),
            ("eligible", "closed", "agent", "reject"),
            ("eligible", "deferred_retry", "agent", "hold"),
            ("eligible", "awaiting_user", "agent", "hold"),
            ("deferred_retry", "eligible", "system", "requeue"),
            ("awaiting_user", "closed", "user", "accept"),
            ("awaiting_user", "closed", "user", "reject"),
        }))
        self.assertEqual({action for (_d, _l, action) in ACTION_REGISTRY}, {"accept", "reject", "hold", "requeue"})

    def test_identity_outside_the_candidate_set_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = _seed(root); packet = _packet(root, db)
            report, _ = _apply(root, packet, _identity(packet, occurrence_match="occ_ghost"))
            self.assertEqual(report["rejected_result"], 1)
            self.assertEqual(report["issues"][0]["issue_type"], "occurrence_match_not_a_candidate")

    def test_series_match_conflicting_with_occurrence_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = _seed(root); packet = _packet(root, db)
            report, _ = _apply(root, packet, _identity(packet, series_match=NONE))
            self.assertEqual(report["rejected_result"], 1)
            self.assertEqual(report["issues"][0]["issue_type"], "series_match_conflicts_with_occurrence")

    def test_empty_identity_value_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = _seed(root); packet = _packet(root, db)
            report, _ = _apply(root, packet, _identity(packet, venue_match=""))
            self.assertEqual(report["rejected_result"], 1)
            self.assertEqual(report["issues"][0]["issue_type"], "venue_match_missing")

    def test_event_facts_in_the_payload_are_rejected(self):
        """名前や日付を言い直させない。E0 が抽出した事実と食い違う写しを作らないため。"""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = _seed(root); packet = _packet(root, db)
            report, _ = _apply(root, packet, _identity(packet, event_name_hint="べつの名前"))
            self.assertEqual(report["rejected_result"], 1)
            self.assertEqual(report["issues"][0]["issue_type"], "invalid_result")


class NonePolicyTest(unittest.TestCase):
    """§7-8〜15：新しい系列・会場になる答えは人の確認へ回す。"""

    def test_new_series_answer_becomes_an_awaiting_user_hold(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = _seed(root, existing=False); packet = _packet(root, db)
            report, args = _apply(root, packet, _identity(packet))
            self.assertEqual((report["accepted"], report["held_for_user"]), (0, 1))
            hold = sqlite3.connect(args.out_db).execute("SELECT reason_code, hold_mode, candidate_ids, candidate_set_sha256 FROM review_hold_ledger").fetchone()
            self.assertEqual(hold[:2], ("new_series_requires_confirmation", "awaiting_user"))
            self.assertIsNone(hold[2])
            self.assertIsNone(hold[3])

    def test_new_venue_answer_becomes_an_awaiting_user_hold(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = _seed(root); packet = _packet(root, db)
            report, args = _apply(root, packet, _identity(packet, venue_match=NONE))
            self.assertEqual(report["held_for_user"], 1)
            self.assertEqual(sqlite3.connect(args.out_db).execute("SELECT reason_code FROM review_hold_ledger").fetchone()[0],
                             "new_venue_requires_confirmation")

    def test_both_none_reports_the_series_reason(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = _seed(root, existing=False); packet = _packet(root, db)
            _report, args = _apply(root, packet, {"occurrence_match": NONE, "series_match": NONE, "venue_match": NONE})
            self.assertEqual(sqlite3.connect(args.out_db).execute("SELECT reason_code FROM review_hold_ledger").fetchone()[0],
                             "new_series_requires_confirmation")

    def test_existing_series_without_occurrence_stays_accepted(self):
        """開催回だけ none なら止めない。occurrence_id で後から直せるので回復できる。"""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = _seed(root); packet = _packet(root, db)
            identity = _identity(packet)
            report, args = _apply(root, packet, {**identity, "occurrence_match": NONE})
            self.assertEqual((report["accepted"], report["held_for_user"]), (1, 0))
            self.assertEqual(sqlite3.connect(args.out_db).execute("SELECT COUNT(*) FROM review_hold_ledger").fetchone()[0], 0)

    def test_new_confirmation_hold_needs_no_target_and_can_be_batched(self):
        """候補が実在する状況でも凍結しない。凍結すると対象を要求され、一括で裁けなくなる。"""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = _seed(root); packet = _packet(root, db)
            self.assertTrue(packet["targets"]["occurrence_candidates"], "候補が無いと凍結の有無を区別できない")
            _report, args = _apply(root, packet, _identity(packet, venue_match=NONE))
            conn = sqlite3.connect(args.out_db); conn.row_factory = sqlite3.Row
            hold = dict(conn.execute("SELECT * FROM review_hold_ledger").fetchone())
            self.assertIsNone(hold["candidate_ids"])
            self.assertIsNone(hold["candidate_set_sha256"])
            self.assertFalse(console_data.adjudication_target_required(hold, "accept"))
            recorded = console_data.save_adjudication_batch([hold["hold_id"]], "accept", db_path=args.out_db, path=root / "adj.json")
            self.assertEqual(len(recorded), 1)
            self.assertTrue(recorded[0]["batch_id"])
            self.assertIsNone(recorded[0]["target_id"])

    def test_hold_keeps_the_raw_identity_answer(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = _seed(root, existing=False); packet = _packet(root, db)
            _report, args = _apply(root, packet, _identity(packet))
            payload = json.loads(sqlite3.connect(args.out_db).execute("SELECT payload_json FROM canonical_decision_ledger").fetchone()[0])
            self.assertEqual(payload["series_match"], NONE)
            self.assertEqual(payload["venue_match"], NONE)


class ConversionTest(unittest.TestCase):
    """§7-16〜22：機械が変更型を決める。"""

    def _accepted(self, root, **identity_extra):
        db = _seed(root); packet = _packet(root, db)
        report, args = _apply(root, packet, _identity(packet, **identity_extra))
        self.assertEqual(report["accepted"], 1, report["issues"])
        return args.out_db

    def test_existing_occurrence_becomes_confirm_current_year_date(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _report, payload = _convert(root, self._accepted(root))
            self.assertEqual(len(payload["requests"]), 1)
            request = payload["requests"][0]
            self.assertEqual(request["change_type"], "confirm_current_year_date")
            self.assertEqual(request["occurrence_id"], "occ_seed")
            self.assertNotIn("venue", request)
            validate_payload(payload)

    def test_existing_series_becomes_create_current_year_occurrence(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _report, payload = _convert(root, self._accepted(root, occurrence_match=NONE))
            request = payload["requests"][0]
            self.assertEqual(request["change_type"], "create_current_year_occurrence")
            self.assertEqual(request["series_id"], "ser_seed")
            self.assertEqual(request["venue"], {"venue_id": "ven_seed"})
            validate_payload(payload)

    def test_existing_venue_travels_as_venue_id(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _report, payload = _convert(root, self._accepted(root, occurrence_match=NONE))
            self.assertEqual(payload["requests"][0]["venue"], {"venue_id": "ven_seed"})

    def test_output_carries_no_dry_run_only(self):
        """判断台帳を通っているので、コンソール直通の経路と違い昇格を二重に求めない。"""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _report, payload = _convert(root, self._accepted(root))
            self.assertNotIn("dry_run_only", payload["requests"][0])

    def test_conversion_is_deterministic_and_not_duplicated(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = self._accepted(root)
            first_report, first = _convert(root, db, name="a")
            _second_report, second = _convert(root, db, name="b")
            self.assertEqual(first, second)
            self.assertEqual(first_report["request_count"], 1)
            self.assertEqual(len({r["request_id"] for r in first["requests"]}), 1)

    def test_unadjudicated_none_is_not_converted(self):
        """人の裁定を経ていない new series は変更要求にならない。"""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = _seed(root, existing=False); packet = _packet(root, db)
            report, args = _apply(root, packet, _identity(packet))
            self.assertEqual(report["held_for_user"], 1)
            convert_report, payload = _convert(root, args.out_db)
            self.assertEqual(payload["requests"], [])
            self.assertEqual(convert_report["decisions_read"], 0)

    def test_user_acceptance_of_a_new_series_becomes_create_event_series(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = _seed(root, existing=False); packet = _packet(root, db)
            _report, args = _apply(root, packet, _identity(packet))
            conn = sqlite3.connect(args.out_db); conn.row_factory = sqlite3.Row
            agent = dict(conn.execute("SELECT * FROM canonical_decision_ledger").fetchone())
            # 内田さんの裁定（agent hold を経た user の accept）を台帳へ置く。
            columns = [key for key in agent if key != "created_at"]
            values = [agent[key] for key in columns]
            row = dict(zip(columns, values))
            row.update({"decision_id": "decision:user-accept", "action": "accept", "actor_type": "user",
                        "decision_channel": "console", "actor_id": "uchida", "queue_state_before": "awaiting_user",
                        "queue_state_after": "closed", "reason_code": None, "hold_mode": None,
                        "payload_json": json.dumps({"reason_detail": "新規で登録する"}, ensure_ascii=False),
                        "prior_agent_attempt_id": agent["decision_id"]})
            conn.execute(f"INSERT INTO canonical_decision_ledger ({','.join(row)},created_at) VALUES ({','.join('?' for _ in row)},?)",
                         [*row.values(), STAMP])
            conn.commit(); conn.close()
            _convert_report, payload = _convert(root, args.out_db)
            request = payload["requests"][0]
            self.assertEqual(request["change_type"], "create_event_series")
            self.assertEqual(request["series_name"], "試験盆踊り")
            self.assertEqual(request["venue"], {"name": "試験公園"})
            validate_payload(payload)


class CreateEventSeriesTest(unittest.TestCase):
    """§7-23〜26：新しい系列は INSERT だけで作り、既存を黙って再利用しない。"""

    def _request(self, **extra):
        request = {"request_id": "req-1", "change_type": "create_event_series", "series_name": "新設盆踊り",
                   "display_name": "新設盆踊り", "event_year": 2099, "date_start": "2099-08-05",
                   "date_end": "2099-08-05", "venue": {"name": "新設公園"},
                   "source": {"url": "https://example.test/n", "kind": "official_current_year", "platform": "web"}}
        request.update(extra)
        return request

    def _db(self, root):
        db = root / "master.sqlite"
        conn = init_db(db)
        conn.execute("INSERT INTO venues (venue_id, origin, canonical_name, normalized_name, area, address, review_status, created_at, updated_at) VALUES ('ven_seed','curated','試験公園',?,'千代田区','','active',?,?)", (normalize_text("試験公園"), STAMP, STAMP))
        conn.execute("INSERT INTO event_series (series_id, origin, series_key, canonical_name, normalized_name, usual_venue_id, status, created_at, updated_at) VALUES ('ser_seed','curated',?,'試験盆踊り',?, 'ven_seed','active',?,?)", (normalize_text("試験盆踊り"), normalize_text("試験盆踊り"), STAMP, STAMP))
        conn.commit()
        return conn

    def test_create_event_series_inserts_series_and_occurrence(self):
        with tempfile.TemporaryDirectory() as temp:
            conn = self._db(Path(temp)); conn.row_factory = sqlite3.Row
            applied, issues = apply_one_request(conn, self._request(), 0, STAMP)
            self.assertEqual(issues, [])
            self.assertTrue(applied["series_created"])
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM event_series").fetchone()[0], 2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM event_occurrences").fetchone()[0], 1)

    def test_create_event_series_never_touches_an_existing_series(self):
        """既存 series が1行も書き換わらない（register_new の暗黙上書きとの決定的な違い）。"""
        with tempfile.TemporaryDirectory() as temp:
            conn = self._db(Path(temp)); conn.row_factory = sqlite3.Row
            before = dict(conn.execute("SELECT * FROM event_series WHERE series_id='ser_seed'").fetchone())
            apply_one_request(conn, self._request(), 0, STAMP)
            after = dict(conn.execute("SELECT * FROM event_series WHERE series_id='ser_seed'").fetchone())
            self.assertEqual(before, after)

    def test_duplicate_series_key_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            conn = self._db(Path(temp)); conn.row_factory = sqlite3.Row
            applied, issues = apply_one_request(conn, self._request(series_name="試験盆踊り"), 0, STAMP)
            self.assertIsNone(applied)
            self.assertEqual(issues[0]["issue_type"], "series_key_already_exists")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM event_occurrences").fetchone()[0], 0)

    def test_create_event_series_needs_no_occurrence_id(self):
        """作る側の変更型なので、指す対象を要求しない。"""
        validate_payload({"request_type": "rdb_change_requests", "requests": [self._request()]})

    def test_year_mismatch_is_refused_by_validation(self):
        payload = {"request_type": "rdb_change_requests", "requests": [self._request(date_start="2100-08-05")]}
        with self.assertRaisesRegex(ValueError, "date_start must be in event_year"):
            validate_payload(payload)

    def test_series_id_is_refused_on_create_event_series(self):
        payload = {"request_type": "rdb_change_requests", "requests": [self._request(series_id="ser_seed")]}
        with self.assertRaisesRegex(ValueError, "must not carry series_id"):
            validate_payload(payload)

    def test_apply_layer_does_not_import_ensure_series_and_occurrence(self):
        """暗黙の再利用・上書きをする関数を、反映層へ持ち込まないこと（説明文中の言及は対象外）。"""
        import report_apply.apply_change_requests as module
        self.assertFalse(hasattr(module, "ensure_series_and_occurrence"))


class VenueIdTest(unittest.TestCase):
    """venue_id で会場を指せる＝同一性の答えを反映時に名前で開き直さない。"""

    def _db(self, root):
        db = root / "master.sqlite"
        conn = init_db(db)
        conn.execute("INSERT INTO venues (venue_id, origin, canonical_name, normalized_name, area, address, review_status, created_at, updated_at) VALUES ('ven_seed','curated','試験公園',?,'千代田区','','active',?,?)", (normalize_text("試験公園"), STAMP, STAMP))
        conn.execute("INSERT INTO event_series (series_id, origin, series_key, canonical_name, normalized_name, usual_venue_id, status, created_at, updated_at) VALUES ('ser_seed','curated',?,'試験盆踊り',?, 'ven_seed','active',?,?)", (normalize_text("試験盆踊り"), normalize_text("試験盆踊り"), STAMP, STAMP))
        conn.execute("INSERT INTO event_occurrences (occurrence_id, origin, series_id, event_year, occurrence_sequence, display_name, venue_id, date_start, date_status, lifecycle_status, created_at, updated_at) VALUES ('occ_seed','curated','ser_seed',2099,1,'試験盆踊り',NULL,'2099-08-01','confirmed','published',?,?)", (STAMP, STAMP))
        conn.commit()
        return conn

    def test_update_venue_by_id_creates_no_venue_row(self):
        with tempfile.TemporaryDirectory() as temp:
            conn = self._db(Path(temp)); conn.row_factory = sqlite3.Row
            request = {"request_id": "req-v", "change_type": "update_venue", "occurrence_id": "occ_seed",
                       "venue": {"venue_id": "ven_seed"}, "source": {"url": "https://example.test/v", "kind": "official_current_year"}}
            applied, issues = apply_one_request(conn, request, 0, STAMP)
            self.assertEqual(issues, [])
            self.assertEqual(applied["venue_status"], "resolved")
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM venues").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT venue_id FROM event_occurrences WHERE occurrence_id='occ_seed'").fetchone()[0], "ven_seed")

    def test_unknown_venue_id_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            conn = self._db(Path(temp)); conn.row_factory = sqlite3.Row
            request = {"request_id": "req-v", "change_type": "update_venue", "occurrence_id": "occ_seed",
                       "venue": {"venue_id": "ven_ghost"}, "source": {"url": "https://example.test/v", "kind": "official_current_year"}}
            applied, issues = apply_one_request(conn, request, 0, STAMP)
            self.assertIsNone(applied)
            self.assertEqual(issues[0]["issue_type"], "venue_id_not_found")

    def test_venue_reference_may_be_id_or_name(self):
        base = {"request_id": "req-v", "change_type": "update_venue", "occurrence_id": "occ_seed",
                "source": {"url": "https://example.test/v", "kind": "official_current_year"}}
        validate_payload({"request_type": "rdb_change_requests", "requests": [{**base, "venue": {"venue_id": "ven_seed"}}]})
        validate_payload({"request_type": "rdb_change_requests", "requests": [{**base, "venue": {"name": "試験公園"}}]})
        with self.assertRaisesRegex(ValueError, "requires venue_id or name"):
            validate_payload({"request_type": "rdb_change_requests", "requests": [{**base, "venue": {}}]})


class ConversionSafetyTest(unittest.TestCase):
    """§7-27〜29：変換層は読むだけ。"""

    def test_main_parses_real_argv(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = _seed(root)
            argv = ["build_change_requests_from_judgment.py", "--db", str(db), "--out-json", str(root / "o.json"), "--out-md", str(root / "o.md")]
            with patch("sys.argv", argv):
                self.assertEqual(convert_main(), 0)
            self.assertTrue((root / "o.json").exists())

    def test_conversion_leaves_the_database_byte_identical(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = _seed(root)
            before = hashlib.sha256(db.read_bytes()).hexdigest()
            _convert(root, db)
            self.assertEqual(hashlib.sha256(db.read_bytes()).hexdigest(), before)

    def test_conversion_module_has_no_write_statements(self):
        source = (ROOT / "review_inbox_adapters" / "build_change_requests_from_judgment.py").read_text(encoding="utf-8")
        for statement in ("INSERT INTO", "UPDATE ", "DELETE FROM", ".commit()"):
            self.assertNotIn(statement, source, statement)

    def test_read_only_connection_refuses_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = _seed(root)
            conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("DELETE FROM review_inbox_items")
            conn.close()

    def test_missing_identity_answer_is_reported_not_guessed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = _seed(root); packet = _packet(root, db)
            _report, args = _apply(root, packet, _identity(packet))
            conn = sqlite3.connect(args.out_db)
            conn.execute("UPDATE canonical_decision_ledger SET payload_json = '{}'")
            conn.commit(); conn.close()
            report, payload = _convert(root, args.out_db)
            self.assertEqual(payload["requests"], [])
            self.assertEqual(report["skipped"][0]["reason"], "identity_answer_missing")


if __name__ == "__main__":
    unittest.main()
