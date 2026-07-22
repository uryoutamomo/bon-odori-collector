#!/usr/bin/env python3
"""Apply one of Uchida-san's firsthand bon-odori attendance reports to the master RDB.

Default mode writes only to a copied SQLite DB (dry run). Production writes require
--apply and the confirmation phrase (manual_apply_guards.FIRSTHAND_FIELD_REPORT_CONFIRMATION).

Report input is a JSON file (see docs/firsthand-field-report-operations.md for the schema),
written by koto from a conversation with Uchida-san about a bon-odori event he attended.
Two report_type values are supported:

- "existing_event_songs": add songs Uchida-san heard at an event already in the RDB.
- "new_event": register an event that isn't in the RDB yet (with venue), plus any songs.

If the target occurrence/venue can't be resolved unambiguously, nothing is written; the
dry-run report lists the candidates so koto can ask Uchida-san to disambiguate and re-run.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import operation_safety.manual_apply_guards as manual_apply_guards
from report_apply.firsthand_report_helpers import (
    add_firsthand_evidence,
    ensure_series_and_occurrence,
    ensure_venue,
    find_occurrence_candidates,
    upsert_occurrence_song,
)
from master_rdb.master_db import MASTER_DB, connect_existing, normalize_text, refresh_manifest_database_state, table_counts
from report_apply.rdb_apply_support import audit_db, backup_db, copy_db, has_high_issue, issue_summary, rows, scalar, write_json


DATA = Path("data")
OUT_DB = DATA / "firsthand_field_report_apply_dry_run.sqlite"
OUT_JSON = DATA / "firsthand_field_report_apply_report.json"
OUT_MD = DATA / "firsthand_field_report_apply_report.md"
BACKUP_DIR = DATA / "backups"
PREFLIGHT_DB = DATA / "firsthand_field_report_apply_preflight.sqlite"
SCRIPT_NAME = "apply_firsthand_field_report.py"

STRONG_MATCH_SCORE = 0.92
REQUIRED_FIELDS = ("report_type", "raw_note", "event_name_hint", "event_year", "event_date")


def validate_report(report):
    errors = []
    if report.get("report_type") not in ("existing_event_songs", "new_event"):
        errors.append(f"invalid report_type: {report.get('report_type')!r}")
    for field in REQUIRED_FIELDS:
        if not report.get(field):
            errors.append(f"missing required field: {field}")
    if report.get("report_type") == "new_event" and not (report.get("venue") or {}).get("name"):
        errors.append("new_event report requires venue.name")
    songs = report.get("songs", [])
    if not isinstance(songs, list) or any(not isinstance(s, dict) or not s.get("title") for s in songs):
        errors.append("songs must be a list of {title: str, uncertain?: bool}")
    if errors:
        raise ValueError("invalid report: " + "; ".join(errors))


def _apply_songs(conn, occurrence_id, report, evidence_id, now):
    applied = []
    default_uncertain = bool(report.get("uncertain", False))
    for song in report.get("songs", []):
        applied.append(
            upsert_occurrence_song(
                conn,
                occurrence_id,
                song["title"],
                evidence_id,
                uncertain=bool(song.get("uncertain", default_uncertain)),
                now=now,
            )
        )
    return applied


def apply_existing_event_songs(conn, report, now):
    issues = []
    occurrence_id = report.get("occurrence_id")
    candidates = []
    if occurrence_id:
        found = rows(conn, "SELECT occurrence_id FROM event_occurrences WHERE occurrence_id = ?", (occurrence_id,))
        if not found:
            issues.append({"severity": "high", "issue_type": "occurrence_id_not_found", "occurrence_id": occurrence_id})
            occurrence_id = None
    else:
        candidates = find_occurrence_candidates(
            conn, report["event_name_hint"], report.get("venue_name_hint"), report.get("event_year")
        )
        strong = [c for c in candidates if c["match_score"] >= STRONG_MATCH_SCORE]
        if len(strong) == 1:
            occurrence_id = strong[0]["occurrence_id"]
        else:
            issue_type = "ambiguous_occurrence" if candidates else "no_occurrence_candidates"
            issues.append({"severity": "high", "issue_type": issue_type, "candidates": candidates})
            occurrence_id = None

    if occurrence_id is None:
        return {"resolved": False, "report_type": "existing_event_songs"}, issues

    evidence_id = add_firsthand_evidence(
        conn,
        occurrence_id,
        report["raw_note"],
        url=report.get("source_url"),
        event_date=report.get("event_date"),
        uncertain=bool(report.get("uncertain", False)),
        now=now,
    )
    songs_applied = _apply_songs(conn, occurrence_id, report, evidence_id, now)
    return {
        "resolved": True,
        "report_type": "existing_event_songs",
        "occurrence_id": occurrence_id,
        "evidence_id": evidence_id,
        "songs_applied": songs_applied,
    }, issues


def apply_new_event(conn, report, now):
    issues = []
    venue_hint = (report.get("venue") or {}).get("name")
    # A candidate whose series_key exactly matches this report's series key is not a
    # "duplicate to warn about" -- it's the same series ensure_series_and_occurrence()
    # will idempotently reuse below (e.g. re-applying the same report, or a later year
    # of a series already registered from a firsthand report).
    own_series_key = normalize_text(report.get("series_name") or report["event_name_hint"])
    near_dupes = find_occurrence_candidates(conn, report["event_name_hint"], venue_hint, report.get("event_year"))
    strong_dupes = [
        c
        for c in near_dupes
        if c["match_score"] >= STRONG_MATCH_SCORE and c["series_normalized_name"] != own_series_key
    ]
    if strong_dupes:
        issues.append(
            {"severity": "high", "issue_type": "possible_duplicate_of_existing_occurrence", "candidates": strong_dupes}
        )
        return {"resolved": False, "report_type": "new_event"}, issues

    venue = report["venue"]
    venue_result = ensure_venue(
        conn,
        venue["name"],
        area=venue.get("area"),
        address=venue.get("address"),
        access=venue.get("access"),
        source_url=report.get("source_url"),
        now=now,
    )
    if venue_result["status"] == "ambiguous":
        issues.append({"severity": "high", "issue_type": "ambiguous_venue", "candidates": venue_result["candidates"]})
        return {"resolved": False, "report_type": "new_event"}, issues

    series_result = ensure_series_and_occurrence(
        conn,
        report.get("series_name") or report["event_name_hint"],
        venue_result["venue_id"],
        report["event_year"],
        report["event_date"],
        report.get("event_date_end"),
        source_url=report.get("source_url"),
        detail=report["raw_note"],
        now=now,
    )
    evidence_id = add_firsthand_evidence(
        conn,
        series_result["occurrence_id"],
        report["raw_note"],
        url=report.get("source_url"),
        event_date=report.get("event_date"),
        uncertain=bool(report.get("uncertain", False)),
        now=now,
    )
    songs_applied = _apply_songs(conn, series_result["occurrence_id"], report, evidence_id, now)
    return {
        "resolved": True,
        "report_type": "new_event",
        "venue_id": venue_result["venue_id"],
        "venue_status": venue_result["status"],
        "series_id": series_result["series_id"],
        "occurrence_id": series_result["occurrence_id"],
        "occurrence_created": series_result["occurrence_created"],
        "evidence_id": evidence_id,
        "songs_applied": songs_applied,
    }, issues


def apply_change(conn, report, now):
    if report["report_type"] == "existing_event_songs":
        return apply_existing_event_songs(conn, report, now)
    return apply_new_event(conn, report, now)


def consistency_checks(conn, applied):
    if not applied.get("resolved"):
        return []
    issues = []
    fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_rows:
        issues.append(
            {
                "severity": "high",
                "issue_type": "foreign_key_check_failed",
                "count": len(fk_rows),
                "sample": [tuple(row) for row in fk_rows[:10]],
            }
        )
    occurrence_id = applied["occurrence_id"]
    occ_count = scalar(conn, "SELECT COUNT(*) FROM event_occurrences WHERE occurrence_id = ?", (occurrence_id,))
    if occ_count != 1:
        issues.append({"severity": "high", "issue_type": "occurrence_missing_after_apply", "occurrence_id": occurrence_id})
    songs_applied = applied.get("songs_applied", [])
    if songs_applied:
        placeholders = ",".join("?" for _ in songs_applied)
        actual_song_count = scalar(
            conn,
            f"SELECT COUNT(*) FROM occurrence_songs WHERE occurrence_song_id IN ({placeholders})",
            tuple(song["occurrence_song_id"] for song in songs_applied),
        )
        if actual_song_count != len(songs_applied):
            issues.append(
                {
                    "severity": "high",
                    "issue_type": "occurrence_song_count_mismatch",
                    "expected": len(songs_applied),
                    "actual": actual_song_count,
                }
            )
    return issues


def render_markdown(result):
    applied = result["applied"]
    lines = [
        "# Firsthand field report apply result",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- report_type: {applied.get('report_type')}",
        f"- resolved: {applied.get('resolved')}",
        f"- target_db: `{result['outputs']['target_db']}`",
        f"- dry_run_db: `{result['outputs']['dry_run_db']}`",
        f"- backup_db: `{result['outputs']['backup_db']}`",
        f"- db_committed: {result['write_guard']['db_committed']}",
        f"- rolled_back: {result['write_guard']['rolled_back']}",
        f"- issues_by_severity: {result['summary']['issues_by_severity']}",
        f"- audit_issues_by_severity: {result['summary']['audit_issues_by_severity']}",
        "",
    ]
    if applied.get("resolved"):
        lines += [
            "## Applied",
            "",
            f"- occurrence_id: `{applied.get('occurrence_id')}`",
        ]
        if applied.get("report_type") == "new_event":
            lines += [
                f"- venue_id: `{applied.get('venue_id')}` ({applied.get('venue_status')})",
                f"- series_id: `{applied.get('series_id')}`",
                f"- occurrence_created: {applied.get('occurrence_created')}",
            ]
        lines += [f"- evidence_id: `{applied.get('evidence_id')}`", "", "### Songs", ""]
        for song in applied.get("songs_applied", []):
            lines.append(f"- {song['occurrence_song_id']} (song_id={song['song_id']})")
        lines.append("")
    if result["issues"]:
        lines += ["## Issues (nothing written when any issue is 'high')", ""]
        for issue in result["issues"]:
            lines.append(f"- {issue['severity']} {issue['issue_type']}: {issue}")
        lines.append("")
    lines += [
        "## Next step",
        "",
        "- After a successful --apply, publish the RDB to S3 (see docs/firsthand-field-report-operations.md Step 3):",
        "  `python3 master_db_s3_artifact.py publish --expect-remote-checksum <checksum from `status`>`",
        "- Commit only data/firsthand_reports/*.json, the manifest, and this report — never the .sqlite file.",
        "",
    ]
    return "\n".join(lines)


def run(args):
    if args.apply:
        manual_apply_guards.require_confirmation(
            args.apply,
            args.confirm,
            manual_apply_guards.FIRSTHAND_FIELD_REPORT_CONFIRMATION,
            "apply_firsthand_field_report.py --apply",
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
            preflight_applied, preflight_change_issues = apply_change(conn, report, now)
            preflight_issues = preflight_change_issues + consistency_checks(conn, preflight_applied)
            conn.commit()
        preflight_audit = audit_db(
            PREFLIGHT_DB, PREFLIGHT_DB.with_suffix(".audit.json"), PREFLIGHT_DB.with_suffix(".audit.md")
        )
        if has_high_issue(preflight_issues, preflight_audit["issues"]):
            raise ValueError(
                "preflight refused high severity issues: "
                f"checks={issue_summary(preflight_issues)} "
                f"audit={preflight_audit['issues_by_severity']}"
            )
        backup_path = str(backup_db(args.master_db, now, BACKUP_DIR))
    else:
        copy_db(args.master_db, args.out_db)

    committed = False
    rolled_back = False
    with connect_existing(target_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        applied, change_issues = apply_change(conn, report, now)
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
        "firsthand field report apply: "
        f"mode={result['mode']} "
        f"resolved={result['applied'].get('resolved')} "
        f"committed={result['write_guard']['db_committed']} "
        f"issues={result['summary']['issues_by_severity']} "
        f"audit={result['summary']['audit_issues_by_severity']} "
        f"target_db={result['outputs']['target_db']}"
    )
    return 1 if result["summary"]["issues_by_severity"].get("high") else 0


if __name__ == "__main__":
    raise SystemExit(main())
