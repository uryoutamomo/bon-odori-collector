#!/usr/bin/env python3
"""Apply an official/third-party notice-board flyer report to the master RDB.

Default mode writes only to a copied SQLite DB (dry run). Production writes require
--apply and the confirmation phrase (manual_apply_guards.OFFICIAL_NOTICE_FIELD_REPORT_CONFIRMATION).

Report input is a JSON file (see docs/official-notice-field-report-operations.md
for the schema), written by koto from a photo of a notice board / flyer /
回覧板 that Uchida-san shared. One report = one physical notice, which
commonly lists several bon-odori events at once (e.g. a 連合町会 summer flyer).
Each entry in "events" is either:

- "confirm_existing": confirm date/venue for an occurrence already in the RDB
  (by explicit occurrence_id or a fuzzy match_hint), or just append a detail note.
- "register_new": register an event that isn't in the RDB yet.

Partial-apply policy: if some events in the report can't be resolved
unambiguously, those are recorded as medium-severity issues and skipped --
the events that CAN be resolved are still applied and committed. This report
is idempotent, so re-running the same JSON after fixing the ambiguous entries
(e.g. adding an explicit occurrence_id) only adds what wasn't applied yet.
True data-integrity problems (foreign key violations, a row missing right
after we wrote it) remain high-severity and roll back the whole transaction.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import operation_safety.manual_apply_guards as manual_apply_guards
from master_rdb.master_db import MASTER_DB, connect_existing, normalize_text, refresh_manifest_database_state, stable_id, table_counts
from report_apply.official_notice_report_helpers import (
    SOURCE_KIND_OFFICIAL_CURRENT_YEAR,
    confirm_occurrence_schedule_venue,
    ensure_series_and_occurrence,
    ensure_venue,
    find_occurrence_candidates,
    link_notice_evidence,
    upsert_announced_song,
    upsert_notice_evidence,
)
from report_apply.rdb_apply_support import audit_db, backup_db, copy_db, has_high_issue, issue_summary, rows, scalar, write_json


DATA = Path("data")
OUT_DB = DATA / "official_notice_report_apply_dry_run.sqlite"
OUT_JSON = DATA / "official_notice_report_apply_report.json"
OUT_MD = DATA / "official_notice_report_apply_report.md"
BACKUP_DIR = DATA / "backups"
PREFLIGHT_DB = DATA / "official_notice_report_apply_preflight.sqlite"
SCRIPT_NAME = "apply_official_notice_report.py"

STRONG_MATCH_SCORE = 0.92
REQUIRED_SOURCE_FIELDS = ("report_id", "raw_text")


def validate_report(report):
    errors = []
    if report.get("report_type") != "official_notice":
        errors.append(f"invalid report_type: {report.get('report_type')!r}")
    source = report.get("source") or {}
    for field in REQUIRED_SOURCE_FIELDS:
        if not source.get(field):
            errors.append(f"missing required source field: {field}")
    events = report.get("events", [])
    if not isinstance(events, list) or not events:
        errors.append("events must be a non-empty list")
    for index, event in enumerate(events):
        action = event.get("action")
        if action not in ("confirm_existing", "register_new"):
            errors.append(f"event[{index}]: invalid action {action!r}")
            continue
        if action == "confirm_existing":
            if not event.get("occurrence_id") and not event.get("match_hint"):
                errors.append(f"event[{index}]: confirm_existing requires occurrence_id or match_hint")
        else:
            for field in ("event_name_hint", "event_year", "date_start"):
                if not event.get(field):
                    errors.append(f"event[{index}]: register_new missing required field: {field}")
            if not (event.get("venue") or {}).get("name"):
                errors.append(f"event[{index}]: register_new requires venue.name")
        songs = event.get("songs", [])
        if not isinstance(songs, list) or any(not isinstance(s, dict) or not s.get("title") for s in songs):
            errors.append(f"event[{index}]: songs must be a list of {{title: str, uncertain?: bool}}")
    if errors:
        raise ValueError("invalid report: " + "; ".join(errors))


def _apply_songs(conn, occurrence_id, event, evidence_id, now):
    applied = []
    for song in event.get("songs", []):
        applied.append(
            upsert_announced_song(
                conn, occurrence_id, song["title"], evidence_id, uncertain=bool(song.get("uncertain", False)), now=now
            )
        )
    return applied


def _resolve_confirm_target(conn, index, event):
    occurrence_id = event.get("occurrence_id")
    if occurrence_id:
        found = rows(conn, "SELECT occurrence_id FROM event_occurrences WHERE occurrence_id = ?", (occurrence_id,))
        if not found:
            return None, [{"severity": "medium", "issue_type": "occurrence_id_not_found", "event_index": index, "occurrence_id": occurrence_id}]
        return occurrence_id, []

    hint = event.get("match_hint") or {}
    candidates = find_occurrence_candidates(conn, hint.get("event_name_hint"), hint.get("venue_name_hint"), hint.get("event_year"))
    strong = [c for c in candidates if c["match_score"] >= STRONG_MATCH_SCORE]
    if len(strong) == 1:
        return strong[0]["occurrence_id"], []
    issue_type = "ambiguous_occurrence" if candidates else "no_occurrence_candidates"
    return None, [{"severity": "medium", "issue_type": issue_type, "event_index": index, "candidates": candidates}]


def apply_one_event(conn, index, event, shared_evidence_id, default_notice_kind, now):
    """Returns (applied_dict_or_None, issues). issues use severity="medium" for
    unresolved matches (skippable, doesn't block other events) and "high" only
    for a malformed action (should have been caught by validate_report)."""
    action = event["action"]
    notice_kind = event.get("notice_kind_override") or default_notice_kind

    if action == "confirm_existing":
        occurrence_id, issues = _resolve_confirm_target(conn, index, event)
        if occurrence_id is None:
            return None, issues

        venue_info = event.get("venue")
        venue_id = None
        if venue_info:
            venue_result = ensure_venue(
                conn,
                venue_info["name"],
                area=venue_info.get("area"),
                address=venue_info.get("address"),
                access=venue_info.get("access"),
                now=now,
            )
            if venue_result["status"] == "ambiguous":
                return None, [{"severity": "medium", "issue_type": "ambiguous_venue", "event_index": index, "candidates": venue_result["candidates"]}]
            venue_id = venue_result["venue_id"]

        confirm_result = confirm_occurrence_schedule_venue(
            conn,
            occurrence_id,
            venue_id=venue_id,
            date_start=event.get("date_start"),
            date_end=event.get("date_end"),
            source_kind=notice_kind,
            detail_addendum=event.get("detail_addendum"),
            date_basis_note="公式掲示物・チラシで確認。",
            now=now,
        )
        link_notice_evidence(conn, occurrence_id, shared_evidence_id, notes=event.get("detail_addendum") or "日程・会場の確認根拠。")
        songs_applied = _apply_songs(conn, occurrence_id, event, shared_evidence_id, now)
        return {
            "action": "confirm_existing",
            "occurrence_id": occurrence_id,
            "changed_fields": confirm_result["changed_fields"],
            "songs_applied": songs_applied,
        }, []

    # register_new
    venue_hint = (event.get("venue") or {}).get("name")
    own_series_key = normalize_text(event.get("series_name") or event["event_name_hint"])
    near_dupes = find_occurrence_candidates(conn, event["event_name_hint"], venue_hint, event.get("event_year"))
    strong_dupes = [c for c in near_dupes if c["match_score"] >= STRONG_MATCH_SCORE and c["series_normalized_name"] != own_series_key]
    if strong_dupes:
        return None, [{"severity": "medium", "issue_type": "possible_duplicate_of_existing_occurrence", "event_index": index, "candidates": strong_dupes}]

    venue = event["venue"]
    venue_result = ensure_venue(conn, venue["name"], area=venue.get("area"), address=venue.get("address"), access=venue.get("access"), now=now)
    if venue_result["status"] == "ambiguous":
        return None, [{"severity": "medium", "issue_type": "ambiguous_venue", "event_index": index, "candidates": venue_result["candidates"]}]

    series_result = ensure_series_and_occurrence(
        conn,
        event.get("series_name") or event["event_name_hint"],
        venue_result["venue_id"],
        event["event_year"],
        event["date_start"],
        event.get("date_end"),
        source_kind=notice_kind,
        detail=event.get("detail_addendum"),
        now=now,
    )
    link_notice_evidence(conn, series_result["occurrence_id"], shared_evidence_id, notes="新規イベント登録の根拠。")
    songs_applied = _apply_songs(conn, series_result["occurrence_id"], event, shared_evidence_id, now)
    return {
        "action": "register_new",
        "occurrence_id": series_result["occurrence_id"],
        "venue_id": venue_result["venue_id"],
        "venue_status": venue_result["status"],
        "occurrence_created": series_result["occurrence_created"],
        "songs_applied": songs_applied,
    }, []


def apply_report(conn, report, now):
    source = report["source"]
    evidence_id = stable_id("ev", "official_notice", source["report_id"], source.get("account_key") or "")
    upsert_notice_evidence(
        conn,
        evidence_id,
        title=source.get("title") or source["report_id"],
        text_excerpt=source["raw_text"],
        account_key=source.get("account_key"),
        url=source.get("url"),
        now=now,
    )

    default_notice_kind = source.get("notice_kind") or SOURCE_KIND_OFFICIAL_CURRENT_YEAR
    events_applied = []
    events_unresolved = []
    all_issues = []
    for index, event in enumerate(report.get("events", [])):
        applied_event, issues = apply_one_event(conn, index, event, evidence_id, default_notice_kind, now)
        all_issues.extend(issues)
        if applied_event is not None:
            events_applied.append(applied_event)
        else:
            events_unresolved.append(index)

    applied = {
        "resolved": bool(events_applied),
        "evidence_id": evidence_id,
        "events_applied": events_applied,
        "events_unresolved": events_unresolved,
        "skipped_events": report.get("skipped_events", []),
    }
    return applied, all_issues


def consistency_checks(conn, applied):
    issues = []
    fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_rows:
        issues.append(
            {"severity": "high", "issue_type": "foreign_key_check_failed", "count": len(fk_rows), "sample": [tuple(row) for row in fk_rows[:10]]}
        )
    evidence_id = applied.get("evidence_id")
    if evidence_id:
        ev_row = rows(conn, "SELECT evidence_id FROM evidence_items WHERE evidence_id = ?", (evidence_id,))
        if not ev_row:
            issues.append({"severity": "high", "issue_type": "evidence_missing_after_apply", "evidence_id": evidence_id})
    for entry in applied.get("events_applied", []):
        occ_id = entry["occurrence_id"]
        occ_row = rows(conn, "SELECT occurrence_id FROM event_occurrences WHERE occurrence_id = ?", (occ_id,))
        if not occ_row:
            issues.append({"severity": "high", "issue_type": "occurrence_missing_after_apply", "occurrence_id": occ_id})
        for song in entry.get("songs_applied", []):
            song_row = rows(conn, "SELECT occurrence_song_id FROM occurrence_songs WHERE occurrence_song_id = ?", (song["occurrence_song_id"],))
            if not song_row:
                issues.append({"severity": "high", "issue_type": "occurrence_song_missing_after_apply", "occurrence_song_id": song["occurrence_song_id"]})
    return issues


def render_markdown(result):
    applied = result["applied"]
    lines = [
        "# Official notice report apply result",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- resolved: {applied.get('resolved')}",
        f"- events_applied: {len(applied.get('events_applied', []))}",
        f"- events_unresolved: {len(applied.get('events_unresolved', []))}",
        f"- target_db: `{result['outputs']['target_db']}`",
        f"- dry_run_db: `{result['outputs']['dry_run_db']}`",
        f"- backup_db: `{result['outputs']['backup_db']}`",
        f"- db_committed: {result['write_guard']['db_committed']}",
        f"- rolled_back: {result['write_guard']['rolled_back']}",
        f"- issues_by_severity: {result['summary']['issues_by_severity']}",
        f"- audit_issues_by_severity: {result['summary']['audit_issues_by_severity']}",
        "",
        f"- evidence_id: `{applied.get('evidence_id')}`",
        "",
        "## Applied events",
        "",
    ]
    for entry in applied.get("events_applied", []):
        lines.append(f"- {entry['action']} {entry['occurrence_id']} (songs: {len(entry.get('songs_applied', []))})")
    if applied.get("events_unresolved"):
        lines += ["", "## Unresolved events (not written; see issues below)", ""]
        for index in applied["events_unresolved"]:
            lines.append(f"- event index {index}")
    if applied.get("skipped_events"):
        lines += ["", "## Out of scope (from report.skipped_events)", ""]
        for skipped in applied["skipped_events"]:
            lines.append(f"- {skipped.get('name')}: {skipped.get('reason')}")
    if result["issues"]:
        lines += ["", "## Issues", ""]
        for issue in result["issues"]:
            lines.append(f"- {issue['severity']} {issue['issue_type']}: {issue}")
    lines += [
        "",
        "## Next step",
        "",
        "- After a successful --apply, publish the RDB to S3 (see docs/official-notice-field-report-operations.md Step 3):",
        "  `python3 master_db_s3_artifact.py publish --expect-remote-checksum <checksum from `status`>`",
        "- If any events are unresolved, fix the report JSON (e.g. add an explicit occurrence_id) and re-run --apply;",
        "  already-applied events are idempotent no-ops on re-run.",
        "- Commit only data/official_notice_reports/*.json, the manifest, and this report — never the .sqlite file.",
        "",
    ]
    return "\n".join(lines)


def run(args):
    if args.apply:
        manual_apply_guards.require_confirmation(
            args.apply,
            args.confirm,
            manual_apply_guards.OFFICIAL_NOTICE_FIELD_REPORT_CONFIRMATION,
            "apply_official_notice_report.py --apply",
        )
        if Path(args.out_db) == Path(args.master_db):
            raise ValueError("--out-db must not equal --master-db")

    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    validate_report(report)

    now = datetime.now(timezone.utc).isoformat()
    target_db = Path(args.master_db if args.apply else args.out_db)
    backup_path = ""

    if args.apply:
        copy_db(args.master_db, PREFLIGHT_DB)
        with connect_existing(PREFLIGHT_DB) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            preflight_applied, preflight_change_issues = apply_report(conn, report, now)
            preflight_issues = preflight_change_issues + consistency_checks(conn, preflight_applied)
            conn.commit()
        preflight_audit = audit_db(PREFLIGHT_DB, PREFLIGHT_DB.with_suffix(".audit.json"), PREFLIGHT_DB.with_suffix(".audit.md"))
        if has_high_issue(preflight_issues, preflight_audit["issues"]):
            raise ValueError(
                f"preflight refused high severity issues: checks={issue_summary(preflight_issues)} audit={preflight_audit['issues_by_severity']}"
            )
        backup_path = str(backup_db(args.master_db, now, BACKUP_DIR))
    else:
        copy_db(args.master_db, args.out_db)

    committed = False
    rolled_back = False
    with connect_existing(target_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        applied, change_issues = apply_report(conn, report, now)
        issues = change_issues + consistency_checks(conn, applied)
        if has_high_issue(issues):
            conn.rollback()
            rolled_back = True
        else:
            conn.commit()
            committed = True
        counts = table_counts(conn)

    audit_result = audit_db(target_db, args.out_json.with_suffix(".audit.json"), args.out_md.with_suffix(".audit.md"))
    if args.apply and audit_result["issues_by_severity"].get("high"):
        raise ValueError(f"post-apply audit has high issues: {audit_result['issues_by_severity']}")
    if args.apply and committed:
        refresh_manifest_database_state(args.master_db, updated_at=now)

    result = {
        "generated_by": SCRIPT_NAME,
        "generated_at": now,
        "mode": "apply" if args.apply else "dry_run",
        "sources": {"master_db": str(args.master_db), "report": str(args.report)},
        "outputs": {
            "target_db": str(target_db),
            "dry_run_db": "" if args.apply else str(args.out_db),
            "backup_db": backup_path,
            "json": str(args.out_json),
            "markdown": str(args.out_md),
        },
        "options": {"apply": bool(args.apply)},
        "write_guard": {
            "db_committed": committed,
            "rolled_back": rolled_back,
            "rollback_reason": "high_severity_issue" if rolled_back else "",
        },
        "summary": {
            "issues_count": len(issues),
            "issues_by_severity": issue_summary(issues),
            "audit_issues_by_severity": audit_result["issues_by_severity"],
            "table_counts": counts,
        },
        "report": report,
        "applied": applied,
        "issues": issues,
        "audit": {
            "issue_count": audit_result["issue_count"],
            "issues_by_severity": audit_result["issues_by_severity"],
            "issues_by_type": audit_result["issues_by_type"],
        },
        "public_json_write": {
            "enabled": False,
            "policy": "Run export_public_events.py and the site deploy separately, on Uchida-san's schedule.",
        },
    }
    write_json(args.out_json, result)
    Path(args.out_md).write_text(render_markdown(result), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--master-db", type=Path, default=MASTER_DB)
    parser.add_argument("--out-db", type=Path, default=OUT_DB)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        result = run(args)
    except ValueError as exc:
        parser.error(str(exc))
    print(
        "official notice report apply: "
        f"mode={result['mode']} "
        f"resolved={result['applied'].get('resolved')} "
        f"events_applied={len(result['applied'].get('events_applied', []))} "
        f"events_unresolved={len(result['applied'].get('events_unresolved', []))} "
        f"committed={result['write_guard']['db_committed']} "
        f"issues={result['summary']['issues_by_severity']} "
        f"audit={result['summary']['audit_issues_by_severity']} "
        f"target_db={result['outputs']['target_db']}"
    )
    return 1 if result["summary"]["issues_by_severity"].get("high") else 0


if __name__ == "__main__":
    raise SystemExit(main())
