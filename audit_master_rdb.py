"""Audit the Ph0 dry-run master SQLite database."""

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from master_db import MASTER_DB, MASTER_MANIFEST, file_sha256, table_counts


DATA = Path("data")
NOTION_DB = DATA / "notion_snapshot.sqlite"
SONG_OCCURRENCES = DATA / "song_occurrences.json"
OUT_JSON = DATA / "master_rdb_audit.json"
OUT_MD = DATA / "master_rdb_audit.md"


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def scalar(conn, query, params=()):
    return conn.execute(query, params).fetchone()[0]


def issue(severity, issue_type, description, payload=None):
    return {
        "severity": severity,
        "issue_type": issue_type,
        "description": description,
        "payload": payload or {},
    }


def count_table(path, table):
    with sqlite3.connect(path) as conn:
        return scalar(conn, f"SELECT COUNT(*) FROM {table}")


def source_checksum(path):
    path = Path(path)
    return file_sha256(path) if path.exists() else ""


def linked_source_gap(conn, notion_db, source_key, master_table, source_table):
    conn.execute("ATTACH DATABASE ? AS notion_source", (str(notion_db),))
    try:
        return scalar(
            conn,
            f"""
            SELECT COUNT(*)
            FROM notion_source.{source_table} s
            LEFT JOIN external_record_links l
              ON l.system = 'notion'
             AND l.source_key = ?
             AND l.master_table = ?
             AND l.external_id = s.page_id
            WHERE l.external_id IS NULL
            """,
            (source_key, master_table),
        )
    finally:
        conn.execute("DETACH DATABASE notion_source")


def audit(args):
    db_path = Path(args.db)
    issues = []
    if not db_path.exists():
        issues.append(issue("high", "master_db_missing", "Master DB is missing.", {"path": str(db_path)}))
        return build_result(args, {}, issues)

    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        counts = table_counts(conn)
        fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
        if fk_rows:
            issues.append(issue("high", "foreign_key_check_failed", "Foreign key check failed.", {"rows": fk_rows[:20], "count": len(fk_rows)}))

        duplicate_checks = {
            "duplicate_series_year_sequence": """
                SELECT COUNT(*) FROM (
                  SELECT series_id, event_year, occurrence_sequence, COUNT(*) c
                  FROM event_occurrences
                  GROUP BY series_id, event_year, occurrence_sequence
                  HAVING c > 1
                )
            """,
            "duplicate_occurrence_song_role": """
                SELECT COUNT(*) FROM (
                  SELECT occurrence_id, normalized_title, role, COUNT(*) c
                  FROM occurrence_songs
                  GROUP BY occurrence_id, normalized_title, role
                  HAVING c > 1
                )
            """,
            "empty_venue_name": "SELECT COUNT(*) FROM venues WHERE canonical_name = ''",
            "empty_song_title": "SELECT COUNT(*) FROM songs WHERE canonical_title = ''",
            "empty_series_name": "SELECT COUNT(*) FROM event_series WHERE canonical_name = ''",
            "non_curated_venues": "SELECT COUNT(*) FROM venues WHERE origin != 'curated'",
            "non_curated_series": "SELECT COUNT(*) FROM event_series WHERE origin != 'curated'",
            "non_curated_occurrences": "SELECT COUNT(*) FROM event_occurrences WHERE origin != 'curated'",
        }
        check_counts = {}
        for key, query in duplicate_checks.items():
            count = scalar(conn, query)
            check_counts[key] = count
            if count:
                severity = "high" if key.startswith("duplicate") else "medium"
                issues.append(issue(severity, key, f"Audit check failed: {key}.", {"count": count}))

        cache_mismatch = scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM occurrence_dates d
            JOIN event_occurrences o ON o.occurrence_id = d.occurrence_id
            WHERE d.date_type IN ('confirmed', 'ended', 'predicted')
              AND (o.date_start != d.date_start OR COALESCE(o.date_end, '') != COALESCE(d.date_end, ''))
            """,
        )
        check_counts["date_cache_mismatch"] = cache_mismatch
        if cache_mismatch:
            issues.append(issue("high", "date_cache_mismatch", "Occurrence date cache differs from occurrence_dates.", {"count": cache_mismatch}))
        check_counts["historical_reference_dates"] = scalar(
            conn,
            "SELECT COUNT(*) FROM occurrence_dates WHERE date_type = 'historical_reference'",
        )

        source_counts = {
            "notion_venues": count_table(args.notion_db, "notion_venues"),
            "notion_events": count_table(args.notion_db, "notion_events"),
            "notion_songs": count_table(args.notion_db, "notion_songs"),
            "song_occurrence_input": len(load_json(args.song_occurrences, {}).get("occurrences") or []),
            "song_relation_input": sum(
                len(row.get("songs") or [])
                for row in load_json(args.song_occurrences, {}).get("occurrences") or []
            ),
        }
        source_counts["notion_venues_unlinked_from_master"] = linked_source_gap(
            conn, args.notion_db, "venues", "venues", "notion_venues"
        )
        source_counts["notion_events_unlinked_from_master"] = linked_source_gap(
            conn, args.notion_db, "events", "event_occurrences", "notion_events"
        )
        manifest = load_json(args.manifest, {})
        manifest_checksums = manifest.get("source_checksums") or {}
        current_checksums = {
            "notion_db": source_checksum(args.notion_db),
            "song_occurrences": source_checksum(args.song_occurrences),
        }
        source_drift = {
            key: bool(manifest_checksums.get(key) and manifest_checksums.get(key) != value)
            for key, value in current_checksums.items()
        }
        if any(source_drift.values()):
            issues.append(
                issue(
                    "medium",
                    "source_snapshot_drift",
                    "Current source snapshot differs from the master DB build manifest.",
                    {
                        "manifest_source_checksums": manifest_checksums,
                        "current_source_checksums": current_checksums,
                        "source_drift": source_drift,
                        "resolution": "Rebuild the master DB from the current source snapshots during Ph2 cutover to clear benign source drift.",
                    },
                )
            )
        expected_minimums = {
            "venues": (source_counts["notion_venues"], "notion_db"),
            "songs": (source_counts["notion_songs"], "notion_db"),
            "event_occurrences": (source_counts["notion_events"], "notion_db"),
        }
        for table, (minimum, source_key) in expected_minimums.items():
            actual = counts.get(table, 0)
            if actual < minimum:
                severity = "medium" if source_drift.get(source_key) else "high"
                issue_type = "source_count_drift" if source_drift.get(source_key) else "source_count_regression"
                issues.append(
                    issue(
                        severity,
                        issue_type,
                        f"{table} has fewer rows than the current source snapshot.",
                        {"actual": actual, "minimum": minimum, "source": source_key},
                    )
                )

        unresolved = scalar(conn, "SELECT COUNT(*) FROM occurrence_songs WHERE song_id IS NULL")
        check_counts["unresolved_occurrence_songs"] = unresolved
        observed_unmatched = scalar(conn, "SELECT COUNT(*) FROM observed_occurrences WHERE match_status != 'matched_curated'")
        observed_discard = scalar(conn, "SELECT COUNT(*) FROM observed_occurrences WHERE quality_status = 'discard_candidate'")
        observed_out_of_scope = scalar(conn, "SELECT COUNT(*) FROM observed_occurrences WHERE quality_status = 'out_of_scope'")
        observed_song_unmatched = scalar(conn, "SELECT COUNT(*) FROM observed_occurrence_songs WHERE match_status != 'matched_song'")
        historical_candidates = scalar(conn, "SELECT COUNT(*) FROM historical_promotion_candidates")
        historical_auto = scalar(conn, "SELECT COUNT(*) FROM historical_promotion_candidates WHERE auto_promote_eligible = 1")
        predicted_dates = scalar(conn, "SELECT COUNT(*) FROM predicted_occurrence_dates")
        predicted_date_based = scalar(conn, "SELECT COUNT(*) FROM predicted_occurrence_dates WHERE basis_type = 'date_based'")
        predicted_weekday_based = scalar(conn, "SELECT COUNT(*) FROM predicted_occurrence_dates WHERE basis_type = 'weekday_based'")
        predicted_year_mismatch = scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM predicted_occurrence_dates p
            JOIN event_occurrences o ON o.occurrence_id = p.target_occurrence_id
            WHERE o.event_year != p.predicted_year
            """,
        )
        predicted_detached = scalar(conn, "SELECT COUNT(*) FROM predicted_occurrence_dates WHERE target_occurrence_id IS NULL")
        predicted_superseded = scalar(conn, "SELECT COUNT(*) FROM predicted_occurrence_dates WHERE application_status = 'superseded_by_curated'")
        predicted_matches_curated = scalar(conn, "SELECT COUNT(*) FROM predicted_occurrence_dates WHERE application_status = 'matches_curated'")
        predicted_sync_jobs = scalar(
            conn,
            """
            SELECT COUNT(*)
            FROM notion_sync_jobs
            WHERE target_table = 'predicted_occurrence_dates'
              AND requested_by = 'build_historical_promotion_candidates.py'
            """,
        )
        check_counts["observed_unmatched_occurrences"] = observed_unmatched
        check_counts["observed_discard_candidate_occurrences"] = observed_discard
        check_counts["observed_out_of_scope_occurrences"] = observed_out_of_scope
        check_counts["observed_unmatched_songs"] = observed_song_unmatched
        check_counts["historical_promotion_candidates"] = historical_candidates
        check_counts["historical_auto_promote_eligible"] = historical_auto
        check_counts["predicted_occurrence_dates"] = predicted_dates
        check_counts["predicted_occurrence_dates_date_based"] = predicted_date_based
        check_counts["predicted_occurrence_dates_weekday_based"] = predicted_weekday_based
        check_counts["predicted_occurrence_dates_year_mismatch"] = predicted_year_mismatch
        check_counts["predicted_occurrence_dates_detached_series_only"] = predicted_detached
        check_counts["predicted_occurrence_dates_superseded_by_curated"] = predicted_superseded
        check_counts["predicted_occurrence_dates_matches_curated"] = predicted_matches_curated
        check_counts["predicted_occurrence_date_sync_jobs"] = predicted_sync_jobs
        if predicted_year_mismatch:
            issues.append(issue("high", "predicted_date_year_mismatch", "Predicted date is linked to a different occurrence year.", {"count": predicted_year_mismatch}))

    return build_result(
        args,
        counts,
        issues,
        source_counts=source_counts,
        check_counts=check_counts,
    )


def build_result(args, counts, issues, source_counts=None, check_counts=None):
    return {
        "generated_by": "audit_master_rdb.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": str(args.db),
        "table_counts": counts,
        "source_counts": source_counts or {},
        "check_counts": check_counts or {},
        "issue_count": len(issues),
        "issues_by_severity": dict(Counter(row["severity"] for row in issues)),
        "issues_by_type": dict(Counter(row["issue_type"] for row in issues)),
        "issues": issues,
    }


def render_markdown(result):
    lines = [
        "# Master RDB audit",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- database: {result['database']}",
        f"- issue_count: {result['issue_count']}",
        f"- issues_by_severity: {result['issues_by_severity']}",
        "",
        "## Table counts",
        "",
    ]
    for key, value in result["table_counts"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Check counts", ""])
    for key, value in result["check_counts"].items():
        lines.append(f"- {key}: {value}")
    if result["issues"]:
        lines.extend(["", "## Issues", ""])
        for row in result["issues"][:50]:
            lines.append(f"- {row['severity']} {row['issue_type']}: {row['description']} {row['payload']}")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(MASTER_DB))
    parser.add_argument("--notion-db", default=str(NOTION_DB))
    parser.add_argument("--song-occurrences", default=str(SONG_OCCURRENCES))
    parser.add_argument("--manifest", default=str(MASTER_MANIFEST))
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    args = parser.parse_args()
    result = audit(args)
    write_json(args.out_json, result)
    Path(args.out_md).write_text(render_markdown(result), encoding="utf-8")
    print(
        "master rdb audit: "
        f"issues={result['issue_count']} "
        f"severity={result['issues_by_severity']} "
        f"checks={result['check_counts']}"
    )
    return 1 if result["issues_by_severity"].get("high") else 0


if __name__ == "__main__":
    raise SystemExit(main())
