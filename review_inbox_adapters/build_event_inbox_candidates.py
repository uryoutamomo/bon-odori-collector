#!/usr/bin/env python3
"""Build non-canonical event candidates from notice and firsthand reports."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import operation_safety.manual_apply_guards as guards
from event_model.local_judgment_migration import migrate_event_inbox_candidate, migrate_local_judgment_contract
from master_rdb.master_db import MASTER_DB, connect_existing, normalize_text, stable_id
from report_apply.event_report_helpers import find_occurrence_candidates, find_venue_candidates, upsert_evidence_item
from report_apply.rdb_apply_support import copy_db, write_json
from review_inbox import ensure_inbox_schema
from review_inbox_adapters.event_inbox_writer import insert_candidate, supersede, update_candidate
from review_inbox_adapters.local_judgment_contract import canonical_json, sha256_hex

DATA = Path("data")
OUT_DB = DATA / "event_inbox_candidates_dry_run.sqlite"
OUT_JSON = DATA / "event_inbox_candidates_report.json"
OUT_MD = DATA / "event_inbox_candidates_report.md"
EVENT_INBOX_CANDIDATE_CONFIRMATION = "APPLY EVENT INBOX CANDIDATES"

CANONICAL_TABLES = ("venues", "venue_aliases", "event_series", "event_series_aliases", "event_occurrences", "occurrence_dates", "occurrence_evidence_links", "songs", "occurrence_songs", "occurrence_song_evidence_links", "canonical_decision_ledger", "review_queue_state_ledger", "review_hold_ledger")


def now_iso(): return datetime.now(timezone.utc).isoformat()
def table_counts(conn): return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in CANONICAL_TABLES}
def _issue(issues, severity, issue_type, **extra): issues.append({"severity": severity, "issue_type": issue_type, **extra})


def _report_entries(path):
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    if report.get("report_type") == "official_notice":
        source = report.get("source") or {}
        if not source.get("report_id") or not source.get("raw_text") or not isinstance(report.get("events"), list):
            raise ValueError("official report missing source.report_id, source.raw_text, or events")
        base = {"report_type": "official_notice", "report_id": source["report_id"], "source": source, "path": str(path)}
        return [(base, event) for event in report["events"]]
    if report.get("report_type") in {"new_event", "existing_event_songs"}:
        base = {"report_type": report["report_type"], "report_id": Path(path).stem, "source": report, "path": str(path)}
        return [(base, report)]
    raise ValueError(f"unsupported report_type: {report.get('report_type')!r}")


def _proposal(base, entry, action, suffix=""):
    official = base["report_type"] == "official_notice"
    hint = entry.get("match_hint") or {}
    name = entry.get("event_name_hint") or hint.get("event_name_hint")
    year = entry.get("event_year") or hint.get("event_year")
    if not official:
        name, year = entry.get("event_name_hint"), entry.get("event_year")
    date = entry.get("date_start") if official else entry.get("event_date")
    date_end = entry.get("date_end") if official else entry.get("event_date_end")
    venue = entry.get("venue") or ({"name": hint.get("venue_name_hint")} if hint.get("venue_name_hint") else {})
    return {"legacy_action": action, "event_name_hint": name, "series_name_hint": entry.get("series_name") if not official else None,
            "event_year": year, "date_start": date, "date_end": date_end, "venue": venue,
            "detail_addendum": entry.get("detail_addendum") if official else entry.get("raw_note"),
            "songs": entry.get("songs", []), "uncertain": bool(entry.get("uncertain", False)),
            "explicit_occurrence_id": entry.get("occurrence_id") if action == "confirm_existing" else None,
            "explicit_series_id": None, "explicit_source_occurrence_id": entry.get("source_occurrence_id"),
            "depends_on_family_key": None, "_suffix": suffix}


def _entry_key(entry, proposal):
    if entry.get("entry_id"): return entry["entry_id"]
    if entry.get("occurrence_id"): return stable_id("entry", entry["occurrence_id"], length=12)
    if proposal.get("event_name_hint") and proposal.get("event_year"):
        return stable_id("entry", normalize_text(proposal["event_name_hint"]), str(proposal["event_year"]), length=12)
    hint = entry.get("match_hint") or {}
    if hint.get("event_name_hint") and hint.get("event_year"):
        return stable_id("entry", normalize_text(hint["event_name_hint"]), str(hint["event_year"]), hint.get("venue_name_hint") or "", length=12)
    raise ValueError("entry identity requires entry_id, occurrence_id, name/year, or complete match_hint")


def _expires(proposal, now):
    date = proposal.get("date_end") or proposal.get("date_start")
    if not date: return now + timedelta(days=90)
    return datetime.fromisoformat(date).replace(hour=23, minute=59, second=59, tzinfo=timezone(timedelta(hours=9)))


def _targets(conn, proposal, lane, now):
    name, venue, year = proposal["event_name_hint"], (proposal.get("venue") or {}).get("name"), proposal.get("event_year")
    first = find_occurrence_candidates(conn, name, venue, year, limit=8)
    if lane == "event_create":
        merged = {row["occurrence_id"]: row for row in first}
        for row in find_occurrence_candidates(conn, name, venue, None, limit=8):
            if row["occurrence_id"] not in merged or row["match_score"] > merged[row["occurrence_id"]]["match_score"]: merged[row["occurrence_id"]] = row
        first = sorted(merged.values(), key=lambda x: -x["match_score"])
    return {"occurrence_candidates": first, "venue_candidates": find_venue_candidates(conn, venue, (proposal.get("venue") or {}).get("area"), limit=8),
            "retrieved_at": now.isoformat(), "calculation_version": "e0-candidate-search/v1",
            "input_hash": sha256_hex({"event_name_hint": name, "venue_name": venue, "event_year": year, "limit": 8})}


def _family(conn, key):
    return [dict(r) for r in conn.execute("SELECT * FROM review_inbox_items WHERE revision_family_key = ? ORDER BY revision", (key,))]
def _has_decision(conn, inbox_id): return bool(conn.execute("SELECT 1 FROM canonical_decision_ledger WHERE inbox_id = ?", (inbox_id,)).fetchone())


def _validate_family(rows):
    if not rows: return
    if [r["revision"] for r in rows] != list(range(len(rows))) or len({r["contract_lane"] for r in rows}) != 1:
        raise ValueError("revision_family_invalid")


def _candidate(conn, base, entry, proposal, lane, family, revision, now, depends=None):
    source_id = ("official_notice:" if base["report_type"] == "official_notice" else "firsthand:") + base["report_id"]
    key = _entry_key(entry, proposal) + proposal.pop("_suffix", "")
    family_key = f"{source_id}#{key}"
    source_key = family_key if revision == 0 else f"{family_key}@r{revision}"
    payload_hash = sha256_hex(proposal)
    raw = (base["source"].get("raw_text") or base["source"].get("raw_note") or "")[:1000]
    report = {"report_type": "official_notice" if base["report_type"] == "official_notice" else "firsthand_new_event", "report_id": base["report_id"], "report_path": base["path"], "reported_at": None, "notice_kind": base["source"].get("notice_kind"), "source_title": base["source"].get("title"), "source_url": base["source"].get("source_url") or base["source"].get("url")}
    resolved_target = None
    display = {"event_name_hint": proposal.get("event_name_hint"), "event_year": proposal.get("event_year"), "date_start": proposal.get("date_start"), "venue": proposal.get("venue")}
    if proposal.get("explicit_occurrence_id"):
        row = conn.execute("SELECT o.occurrence_id, o.display_name, o.event_year, o.date_start, v.canonical_name AS venue_name FROM event_occurrences o LEFT JOIN venues v ON v.venue_id=o.venue_id WHERE o.occurrence_id=?", (proposal["explicit_occurrence_id"],)).fetchone()
        if row:
            resolved_target = dict(row)
            display.update({"event_name_hint": display["event_name_hint"] or row["display_name"], "event_year": display["event_year"] or row["event_year"], "date_start": display["date_start"] or row["date_start"], "venue": display["venue"] or {"name": row["venue_name"]}})
    payload = {"candidate_version": 1, "report": report, "proposal": proposal, "resolved_target": resolved_target, "targets": _targets(conn, proposal, lane, now), "evidence_ids": [stable_id("evidence", source_id)], "raw_excerpt": raw}
    expires = _expires(proposal, now)
    return {"inbox_id": stable_id("inbox", "event_candidate", source_id, source_key), "kind": "event_candidate", "domain": "イベント", "contract_domain": "event", "contract_lane": lane, "time_scope": "future" if display.get("date_start") and datetime.fromisoformat(display["date_start"]).date() >= now.date() else ("historical" if display.get("date_start") else "reference"), "priority_label": None, "priority_score": None, "title": f"{display['event_name_hint']}（{(display.get('venue') or {}).get('name')}／{display.get('date_start')}）", "event_name": display["event_name_hint"], "venue": (display.get("venue") or {}).get("name"), "event_year": display["event_year"], "source_id": source_id, "source_key": source_key, "source_url": report["source_url"], "recommended_action": None, "status": "candidate", "source_payload_hash": payload_hash, "last_seen_at": now.isoformat(), "payload_json": payload, "created_at": now.isoformat(), "updated_at": now.isoformat(), "first_eligible_at": now.isoformat(), "expires_at": expires.isoformat(), "superseded_by_inbox_id": None, "depends_on_inbox_id": depends, "revision_family_key": family_key, "revision": revision}


def run(args):
    if args.apply: guards.require_confirmation(True, args.confirm, EVENT_INBOX_CANDIDATE_CONFIRMATION, "build_event_inbox_candidates.py --apply")
    reports = list(args.report or []) + [p for directory in (args.report_dir or []) for p in sorted(Path(directory).glob("*.json"))]
    if not reports: raise ValueError("at least one --report or --report-dir is required")
    db, applied = Path(args.db), []
    target = db if args.apply else Path(args.out_db)
    if not args.apply:
        if target.resolve() == db.resolve(): raise ValueError("dry-run target must differ from --db")
        copy_db(db, target)
    issues, changes = [], []
    with connect_existing(target) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON"); ensure_inbox_schema(conn)
        if not args.apply and not args.no_auto_migrate:
            migrate_local_judgment_contract(conn); migrate_event_inbox_candidate(conn); applied = ["local_judgment_contract_v1", "event_inbox_candidate_v1"]
        required = {"canonical_decision_ledger", "local_judgment_schema_migrations"}
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not required <= tables:
            _issue(issues, "high", "canonical_decision_ledger_missing")
        before = table_counts(conn) if not issues else {}
        seen = set()
        jobs = []
        for path in reports:
            try: entries = _report_entries(path)
            except ValueError as exc: _issue(issues, "high", "invalid_report", report=str(path), detail=str(exc)); continue
            for base, entry in entries:
                action = entry.get("action") if base["report_type"] == "official_notice" else base["report_type"]
                if action in {"merge_existing_series", "existing_event_songs"}: changes.append({"outcome":"out_of_scope", "source":str(path), "action":action}); continue
                variants = [(action, "event_update" if action == "confirm_existing" else "event_create", "")]
                if action == "rename_series_and_register_new": variants = [(action, "event_update", ":rename"), (action, "event_create", ":create")]
                for act,lane,suffix in variants:
                    proposal = _proposal(base, entry, act, suffix)
                    if suffix == ":create":
                        source_id = ("official_notice:" if base["report_type"] == "official_notice" else "firsthand:") + base["report_id"]
                        proposal["depends_on_family_key"] = f"{source_id}#{_entry_key(entry, proposal)}:rename"
                    try: key = _entry_key(entry, proposal) + suffix
                    except Exception: _issue(issues,"high","invalid_entry",report=str(path)); continue
                    family_key = (("official_notice:" if base["report_type"] == "official_notice" else "firsthand:") + base["report_id"] + "#" + key)
                    if family_key in seen: _issue(issues,"high","entry_key_collision",family_key=family_key); continue
                    seen.add(family_key); jobs.append((base,entry,proposal,lane,family_key))
        new_needed = sum(not _family(conn, fam) for *_, fam in jobs)
        if new_needed > args.max_candidates: _issue(issues,"high","max_candidates_exceeded",needed=new_needed)
        if not any(i["severity"] == "high" for i in issues):
            for base,entry,proposal,lane,family_key in jobs:
                expires = _expires(proposal, datetime.now(timezone.utc))
                if datetime.now(timezone.utc) > expires.astimezone(timezone.utc): changes.append({"outcome":"expired","source_key":family_key}); continue
                fam = _family(conn, family_key); _validate_family(fam)
                revision = len(fam)
                dependency = proposal.get("depends_on_family_key")
                depends_on = _family(conn, dependency)[-1]["inbox_id"] if dependency and _family(conn, dependency) else None
                candidate = _candidate(conn, base, entry, proposal, lane, fam, revision, datetime.now(timezone.utc), depends=depends_on)
                latest = fam[-1] if fam else None
                if latest and latest["source_payload_hash"] == candidate["source_payload_hash"]:
                    if dependency and latest["depends_on_inbox_id"] != depends_on:
                        if _has_decision(conn, latest["inbox_id"]):
                            _issue(issues, "medium", "dependency_superseded_after_decision", inbox_id=latest["inbox_id"])
                        else:
                            conn.execute("UPDATE review_inbox_items SET depends_on_inbox_id = ? WHERE inbox_id = ?", (depends_on, latest["inbox_id"]))
                    update_candidate(conn, {**candidate, "inbox_id": latest["inbox_id"]}, last_seen_only=True); changes.append({"outcome":"noop","inbox_id":latest["inbox_id"]}); continue
                if latest and not _has_decision(conn, latest["inbox_id"]):
                    candidate.update({"inbox_id":latest["inbox_id"], "source_key":latest["source_key"], "revision":latest["revision"]}); update_candidate(conn,candidate); changes.append({"outcome":"updated","inbox_id":latest["inbox_id"]}); continue
                insert_candidate(conn,candidate)
                if latest: supersede(conn, latest["inbox_id"], candidate["inbox_id"]); changes.append({"outcome":"superseded","inbox_id":candidate["inbox_id"]})
                else: changes.append({"outcome":"created","inbox_id":candidate["inbox_id"]})
                source_id = candidate["source_id"]; upsert_evidence_item(conn, stable_id("evidence", source_id), platform="web", evidence_type="poster_post", source_key=source_id, title=candidate["title"], text_excerpt=candidate["payload_json"]["raw_excerpt"], url=candidate["source_url"], now=candidate["created_at"])
        after = table_counts(conn) if before else {}
        if before and before != after: _issue(issues,"high","canonical_table_mutated")
        if any(i["severity"] == "high" for i in issues): conn.rollback()
        else: conn.commit()
    summary = {key: sum(c["outcome"] == key for c in changes) for key in ("created","updated","noop","superseded","expired","out_of_scope")}
    result = {"mode":"apply" if args.apply else "dry_run", "migrations_applied":applied, "summary":summary, "issues":issues, "changes":changes, "target_db":str(target)}
    write_json(args.out_json,result); Path(args.out_md).write_text("# Event inbox candidates\n\n```json\n"+json.dumps(result,ensure_ascii=False,indent=2)+"\n```\n",encoding="utf-8")
    return result


def main():
    p=argparse.ArgumentParser(); p.add_argument("--report",type=Path,action="append"); p.add_argument("--report-dir",type=Path,action="append"); p.add_argument("--db",type=Path,default=MASTER_DB); p.add_argument("--out-db",type=Path,default=OUT_DB); p.add_argument("--out-json",type=Path,default=OUT_JSON); p.add_argument("--out-md",type=Path,default=OUT_MD); p.add_argument("--max-candidates",type=int,default=200); p.add_argument("--apply",action="store_true"); p.add_argument("--confirm",default=""); p.add_argument("--no-auto-migrate",action="store_true")
    args=p.parse_args()
    try: result=run(args)
    except ValueError as e: p.error(str(e))
    print(json.dumps(result["summary"],ensure_ascii=False)); return 1 if any(i["severity"] == "high" for i in result["issues"]) else 0
if __name__ == "__main__": raise SystemExit(main())
