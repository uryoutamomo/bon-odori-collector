"""E0b: レビューコンソール由来の変更提案を候補器へ付け替える。

受け入れ条件の一覧は docs/local-judgment-e0b-bridge-v1.md §6 にある。
"""
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from event_model.local_judgment_migration import migrate_event_inbox_candidate, migrate_local_judgment_contract
from master_rdb.master_db import init_db, normalize_text
from public_export_support.build_public_historical_reference_change_requests import build_payload, build_request
from report_apply.apply_change_requests import validate_apply_allowed, validate_payload
from review_inbox_adapters.build_change_requests_from_review_inbox import (
    build_candidate_reports,
    build_requests,
    main as bridge_main,
)
from review_inbox_adapters.build_event_inbox_candidates import CANONICAL_TABLES, _proposal, run
from review_inbox_adapters.local_judgment_contract import sha256_hex

ROOT = Path(__file__).resolve().parents[1]
PROMOTE = importlib.util.spec_from_file_location(
    "promote_change_requests_for_review", ROOT / "scripts" / "promote_change_requests_for_review.py"
)
PROMOTE_MODULE = importlib.util.module_from_spec(PROMOTE)
PROMOTE.loader.exec_module(PROMOTE_MODULE)

STAMP = "2026-01-01T00:00:00+00:00"
APPLY_CONFIRMATION = "APPLY EVENT INBOX CANDIDATES"


def _seed_db(path, *, occurrence_id="occ_probe", name="試験盆踊り", venue="試験公園", year=2099, date_start="2099-08-01"):
    """会場・系列・開催回を1件だけ置く。E0 の候補検索と公開historical referenceの両方で使う。"""
    conn = init_db(path)
    migrate_local_judgment_contract(conn)
    migrate_event_inbox_candidate(conn)
    conn.execute("INSERT INTO venues (venue_id, origin, canonical_name, normalized_name, area, address, review_status, created_at, updated_at) VALUES ('ven_probe','curated',?,?,'千代田区','','active',?,?)", (venue, normalize_text(venue), STAMP, STAMP))
    conn.execute("INSERT INTO event_series (series_id, origin, series_key, canonical_name, normalized_name, usual_venue_id, status, created_at, updated_at) VALUES ('ser_probe','curated',?,?,?, 'ven_probe','active',?,?)", (name, name, normalize_text(name), STAMP, STAMP))
    conn.execute("INSERT INTO event_occurrences (occurrence_id, origin, series_id, event_year, occurrence_sequence, display_name, venue_id, date_start, date_status, lifecycle_status, created_at, updated_at) VALUES (?, 'curated','ser_probe',?,1,?, 'ven_probe',?, 'confirmed','published',?,?)", (occurrence_id, year, name, date_start, STAMP, STAMP))
    conn.commit()
    conn.close()


def _console_entry(action, *, occurrence_id="occ_probe", inbox_id="inbox_1", **extra):
    entry = {"action": action, "occurrence_id": occurrence_id, "inbox_id": inbox_id,
             "event_name_hint": "試験盆踊り", "event_year": 2099, "date_start": None, "date_end": None,
             "historical_year": None, "historical_date": None, "venue": {}, "detail_addendum": "",
             "source_url": "https://example.test/e"}
    entry.update(extra)
    return entry


def _console_report(*entries, report_id="inbox_1"):
    return {"report_type": "review_console_change_request",
            "source": {"report_id": report_id, "raw_text": "コンソールのメモ", "source_url": "https://example.test/e", "title": "試験盆踊り"},
            "events": list(entries)}


def _write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _args(root, db, reports, **overrides):
    fields = dict(report=list(reports), report_dir=[], db=db, out_db=root / "dry.sqlite",
                  out_json=root / "report.json", out_md=root / "report.md", max_candidates=200,
                  apply=False, confirm="", no_auto_migrate=False, include_expired=False)
    fields.update(overrides)
    return type("Args", (), fields)()


def _staged_item(inbox_id="inbox_1", occurrence_id="occ_probe", event_year=2026, event_date_text="2026 [X1]\n7/19"):
    item = {"inbox_id": inbox_id, "kind": "official_source", "title": "町会「試験盆踊り」",
            "event_name": "町会「試験盆踊り」", "venue": "試験公園", "event_year": event_year,
            "source_url": "https://example.test/e",
            "payload": {"event_date_text": event_date_text, "source_url": "https://example.test/e", "memo": "メモ"}}
    if occurrence_id:
        item["payload"]["observed_candidate"] = {"candidate_key": f"{occurrence_id}|{event_date_text}||"}
    return item


def _staged_row(item, change_type, note=""):
    return {"inbox_update": {"inbox_id": item["inbox_id"], "decision_route": "change_request"},
            "apply_value": "confirm_current_date", "note": note, "source_item": item, "change_type": change_type}


class ConsoleCandidateTest(unittest.TestCase):
    """§6-1〜9：新しいレポート形式が候補器で受理される。"""

    def test_console_report_becomes_event_update_candidate(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = root / "master.sqlite"; _seed_db(db)
            report = _write(root / "console.json", _console_report(_console_entry("confirm_current_year_date", date_start="2099-08-01", date_end="2099-08-01")))
            result = run(_args(root, db, [report]))
            self.assertEqual(result["summary"]["created"], 1, result["issues"])
            row = sqlite3.connect(root / "dry.sqlite").execute(
                "SELECT contract_domain, contract_lane, status, source_id, domain FROM review_inbox_items"
            ).fetchone()
            self.assertEqual(row, ("event", "event_update", "candidate", "review_console:inbox_1", "イベント"))

    def test_all_three_console_actions_become_candidates(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = root / "master.sqlite"; _seed_db(db)
            report = _write(root / "console.json", _console_report(
                _console_entry("confirm_current_year_date", date_start="2099-08-01"),
                _console_entry("add_historical_reference", historical_year=2098, historical_date="2098-08-01"),
                _console_entry("update_venue", venue={"name": "別会場"}),
            ))
            result = run(_args(root, db, [report]))
            self.assertEqual(result["summary"]["created"], 3, result["issues"])
            lanes = {row[0] for row in sqlite3.connect(root / "dry.sqlite").execute("SELECT contract_lane FROM review_inbox_items")}
            self.assertEqual(lanes, {"event_update"})

    def test_entry_without_occurrence_id_writes_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = root / "master.sqlite"; _seed_db(db)
            entry = _console_entry("confirm_current_year_date", date_start="2099-08-01")
            entry.pop("occurrence_id")
            report = _write(root / "console.json", _console_report(entry))
            result = run(_args(root, db, [report]))
            self.assertTrue(any(issue["issue_type"] == "invalid_report" and issue["severity"] == "high" for issue in result["issues"]), result["issues"])
            self.assertEqual(sqlite3.connect(root / "dry.sqlite").execute("SELECT COUNT(*) FROM review_inbox_items").fetchone()[0], 0)

    def test_unsupported_console_action_writes_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = root / "master.sqlite"; _seed_db(db)
            report = _write(root / "console.json", _console_report(_console_entry("register_new")))
            result = run(_args(root, db, [report]))
            self.assertTrue(any(issue["issue_type"] == "invalid_report" for issue in result["issues"]))
            self.assertEqual(sqlite3.connect(root / "dry.sqlite").execute("SELECT COUNT(*) FROM review_inbox_items").fetchone()[0], 0)

    def test_two_actions_on_same_occurrence_are_separate_families(self):
        """同じ開催回への日付確定と会場補完が1つの family に潰れると、片方が改訂として消える。"""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = root / "master.sqlite"; _seed_db(db)
            report = _write(root / "console.json", _console_report(
                _console_entry("confirm_current_year_date", date_start="2099-08-01"),
                _console_entry("update_venue", venue={"name": "別会場"}),
            ))
            result = run(_args(root, db, [report]))
            self.assertFalse([issue for issue in result["issues"] if issue["issue_type"] == "entry_key_collision"])
            families = [row[0] for row in sqlite3.connect(root / "dry.sqlite").execute("SELECT revision_family_key FROM review_inbox_items ORDER BY revision_family_key")]
            self.assertEqual(len(set(families)), 2, families)
            self.assertTrue(all(key.startswith("review_console:inbox_1#") for key in families))

    def test_identical_second_run_is_noop(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = root / "master.sqlite"; _seed_db(db)
            report = _write(root / "console.json", _console_report(_console_entry("confirm_current_year_date", date_start="2099-08-01")))
            args = _args(root, db, [report], apply=True, confirm=APPLY_CONFIRMATION, out_db=db)
            self.assertEqual(run(args)["summary"]["created"], 1)
            second = run(args)
            self.assertEqual(second["summary"]["noop"], 1)
            self.assertEqual(sqlite3.connect(db).execute("SELECT COUNT(*), MAX(revision) FROM review_inbox_items").fetchone(), (1, 0))

    def test_unknown_occurrence_id_is_not_candidated(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = root / "master.sqlite"; _seed_db(db)
            report = _write(root / "console.json", _console_report(_console_entry("confirm_current_year_date", occurrence_id="occ_missing", date_start="2099-08-01")))
            result = run(_args(root, db, [report]))
            self.assertTrue(any(issue["issue_type"] == "occurrence_id_not_found" for issue in result["issues"]), result["issues"])
            self.assertEqual(sqlite3.connect(root / "dry.sqlite").execute("SELECT COUNT(*) FROM review_inbox_items").fetchone()[0], 0)

    def test_dry_run_keeps_canonical_tables_unchanged(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = root / "master.sqlite"; _seed_db(db)
            report = _write(root / "console.json", _console_report(_console_entry("confirm_current_year_date", date_start="2099-08-01")))
            run(_args(root, db, [report]))
            original = sqlite3.connect(db); dry = sqlite3.connect(root / "dry.sqlite")
            for table in CANONICAL_TABLES:
                self.assertEqual(original.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
                                 dry.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], table)

    def test_existing_report_types_keep_their_payload_hash(self):
        """E0b で `_proposal` にキーを足すと、既存 family が一斉に改訂される。

        既知値は origin/main（aaeecb7）で同じ入力を流して得たもの。ここが動いたら、
        公式お知らせ・現地報告の候補が中身は同じまま revision だけ増える。
        """
        official = _proposal(
            {"report_type": "official_notice", "report_id": "notice", "source": {"report_id": "notice", "raw_text": "text"}, "path": "notice.json"},
            {"action": "register_new", "event_name_hint": "試験盆踊り", "event_year": 2099, "date_start": "2099-08-01", "venue": {"name": "試験公園"}},
            "register_new",
        )
        firsthand = _proposal(
            {"report_type": "new_event", "report_id": "firsthand", "source": {"raw_note": "note"}, "path": "firsthand.json"},
            {"event_name_hint": "現地盆踊り", "event_year": 2099, "event_date": "2099-08-02", "raw_note": "note"},
            "new_event",
        )
        self.assertEqual(sha256_hex(official), "88466a9d082eda3f25119ab02f86a3fbd177cb296369c8c7659223953cc8db2b")
        self.assertEqual(sha256_hex(firsthand), "6af5e85157dfcf04751028ac8730e6d883e9b5ba06386678eccc590e114f3a13")


class BridgeOutputTest(unittest.TestCase):
    """§6-10〜14：橋渡しは候補レポートを既定で書き、旧出力は人の昇格なしに適用できない。"""

    def test_every_built_request_is_dry_run_only(self):
        """INV-RVW-011。コンソールの選択が判断台帳を通らずに適用されるのを防ぐ。"""
        requests, unresolved = build_requests(
            [_staged_row(_staged_item(), "confirm_current_year_date"),
             _staged_row(_staged_item(inbox_id="inbox_2", event_year=2025), "add_historical_reference"),
             _staged_row(_staged_item(inbox_id="inbox_3"), "update_venue")],
            current_year=2026,
        )
        self.assertEqual(unresolved, [])
        self.assertEqual(len(requests), 3)
        self.assertTrue(all(request.get("dry_run_only") is True for request in requests), requests)

    def test_apply_layer_refuses_bridge_output(self):
        requests, _ = build_requests([_staged_row(_staged_item(), "confirm_current_year_date")], current_year=2026)
        payload = {"request_type": "rdb_change_requests", "requests": requests}
        validate_payload(payload)
        with self.assertRaises(ValueError) as caught:
            validate_apply_allowed(payload)
        self.assertIn("refusing --apply", str(caught.exception))

    def test_promotion_clears_dry_run_only_and_keeps_the_route_open(self):
        """旧経路は消さない（strangler）。人が昇格させれば従来どおり適用できる。"""
        requests, _ = build_requests([_staged_row(_staged_item(), "confirm_current_year_date")], current_year=2026)
        payload = {"request_type": "rdb_change_requests", "requests": requests}
        promoted, _report = PROMOTE_MODULE.promote_payload(payload, ["inbox_1"], reviewed_by="uchida")
        validate_apply_allowed(promoted)
        self.assertNotIn("dry_run_only", promoted["requests"][0])
        self.assertEqual(promoted["requests"][0]["reviewed_by"], "uchida")

    def test_candidate_report_carries_venue_only_for_update_venue(self):
        """会場テキストを他の経路に載せると ensure_venue() が会場を二重に作る。"""
        requests, _ = build_requests(
            [_staged_row(_staged_item(), "confirm_current_year_date"),
             _staged_row(_staged_item(inbox_id="inbox_3"), "update_venue")],
            current_year=2026,
        )
        rows = [_staged_row(_staged_item(), "confirm_current_year_date"),
                _staged_row(_staged_item(inbox_id="inbox_3"), "update_venue")]
        by_action = {report["events"][0]["action"]: report["events"][0] for report in build_candidate_reports(requests, rows)}
        self.assertEqual(by_action["confirm_current_year_date"]["venue"], {})
        self.assertEqual(by_action["update_venue"]["venue"], {"name": "試験公園"})

    def test_candidate_report_uses_cleaned_event_name(self):
        rows = [_staged_row(_staged_item(), "confirm_current_year_date")]
        requests, _ = build_requests(rows, current_year=2026)
        entry = build_candidate_reports(requests, rows)[0]["events"][0]
        self.assertEqual(entry["event_name_hint"], "試験盆踊り")
        self.assertEqual(entry["occurrence_id"], "occ_probe")

    def test_unresolved_row_is_absent_from_candidate_reports(self):
        rows = [_staged_row(_staged_item(occurrence_id=None), "confirm_current_year_date")]
        requests, unresolved = build_requests(rows, current_year=2026)
        self.assertEqual([item["reason"] for item in unresolved], ["missing_occurrence_id"])
        self.assertEqual(build_candidate_reports(requests, rows), [])

    def test_cli_writes_candidate_reports_by_default(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            staged = _write(root / "staged.json", {"rows": [_staged_row(_staged_item(), "confirm_current_year_date")]})
            reports = root / "event_inbox_reports"
            argv = ["build_change_requests_from_review_inbox.py", "--staged", str(staged), "--out", str(root / "out.json"),
                    "--unresolved-out", str(root / "unresolved.json"), "--candidate-report-dir", str(reports)]
            with patch("sys.argv", argv):
                self.assertEqual(bridge_main(), 0)
            written = sorted(reports.glob("*.json"))
            self.assertEqual([path.name for path in written], ["inbox_1.json"])
            report = json.loads(written[0].read_text(encoding="utf-8"))
            self.assertEqual(report["report_type"], "review_console_change_request")
            self.assertEqual(report["events"][0]["action"], "confirm_current_year_date")

    def test_no_candidate_report_flag_skips_them(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            staged = _write(root / "staged.json", {"rows": [_staged_row(_staged_item(), "confirm_current_year_date")]})
            reports = root / "event_inbox_reports"
            argv = ["build_change_requests_from_review_inbox.py", "--staged", str(staged), "--out", str(root / "out.json"),
                    "--unresolved-out", str(root / "unresolved.json"), "--candidate-report-dir", str(reports),
                    "--no-candidate-report"]
            with patch("sys.argv", argv):
                self.assertEqual(bridge_main(), 0)
            self.assertFalse(reports.exists())
            self.assertTrue((root / "out.json").exists())

    def test_bridge_output_round_trips_into_a_candidate(self):
        """橋渡しが書いたレポートを候補器がそのまま読めること（経路がつながっている証拠）。"""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = root / "master.sqlite"
            _seed_db(db, name="試験盆踊り", year=2026, date_start="2026-07-19")
            staged = _write(root / "staged.json", {"rows": [_staged_row(_staged_item(), "confirm_current_year_date")]})
            reports = root / "event_inbox_reports"
            argv = ["build_change_requests_from_review_inbox.py", "--staged", str(staged), "--out", str(root / "out.json"),
                    "--unresolved-out", str(root / "unresolved.json"), "--candidate-report-dir", str(reports)]
            with patch("sys.argv", argv):
                bridge_main()
            result = run(_args(root, db, [], report_dir=[reports], include_expired=True))
            self.assertEqual(result["summary"]["created"], 1, result["issues"])
            row = sqlite3.connect(root / "dry.sqlite").execute(
                "SELECT contract_lane, event_name, source_id FROM review_inbox_items"
            ).fetchone()
            self.assertEqual(row, ("event_update", "試験盆踊り", "review_console:inbox_1"))


class HistoricalReferenceRequestTest(unittest.TestCase):
    """§6-15〜17：公開historical reference は対象IDなしのリクエストを作らない。"""

    def _public_event(self, name="試験盆踊り", venue="試験公園"):
        return {"name": name, "venue": venue, "date": "", "date_end": "",
                "historical_reference": {"last_seen_year": 2025, "last_seen_dates": ["2025-07-25"], "confidence": "medium"},
                "source_urls": [{"label": "公式告知あり", "url": "https://example.test/event", "kind": "official"}]}

    def test_build_request_requires_occurrence_id(self):
        with self.assertRaises(ValueError) as caught:
            build_request(self._public_event(), None, {"url": "https://example.test/event"}, "2025-07-25", "", 2025)
        self.assertIn("occurrence_id is required", str(caught.exception))

    def test_source_has_no_match_hint_branch_left(self):
        """キー名としての `"match_hint"` が消えていること（説明文中の言及は対象外）。"""
        source = (ROOT / "public_export_support" / "build_public_historical_reference_change_requests.py").read_text(encoding="utf-8")
        self.assertNotIn('"match_hint"', source)

    def test_unresolved_event_produces_no_request(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "master.sqlite"
            _seed_db(db, year=2026, date_start="2026-07-19")
            payload, report = build_payload([self._public_event(name="まったく別の行事", venue="別会場")], db)
            self.assertEqual(payload["requests"], [])
            self.assertNotIn("match_hint", json.dumps(payload, ensure_ascii=False))
            self.assertEqual(report["request_count"], 0)

    def test_resolved_event_still_produces_the_same_request(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "master.sqlite"
            _seed_db(db, year=2026, date_start="2026-07-19")
            payload, _report = build_payload([self._public_event()], db)
            self.assertEqual(len(payload["requests"]), 1)
            request = payload["requests"][0]
            self.assertEqual(request["occurrence_id"], "occ_probe")
            self.assertEqual(request["change_type"], "add_historical_reference")
            self.assertEqual(request["historical_date"], "2025-07-25")
            self.assertTrue(request["dry_run_only"])


if __name__ == "__main__":
    unittest.main()
