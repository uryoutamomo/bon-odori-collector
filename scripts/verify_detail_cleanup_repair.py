#!/usr/bin/env python3
"""Fail closed unless the temporary 14-detail repair changes exactly its scope."""

import argparse
from contextlib import closing
import hashlib
import json
import sqlite3
from pathlib import Path



def tables(path):
    with closing(sqlite3.connect(path)) as conn:
        return {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        }


def columns(path, table):
    with closing(sqlite3.connect(path)) as conn:
        return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def rows(path, table):
    names = columns(path, table)
    order = ", ".join(names)
    with closing(sqlite3.connect(path)) as conn:
        return [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY {order}")]


def row_map(path, table, key):
    names = columns(path, table)
    key_index = names.index(key)
    return {row[key_index]: dict(zip(names, row)) for row in rows(path, table)}


def report_expectations(path):
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    if report.get("report_type") != "detail_cleanup_repair":
        raise ValueError("invalid repair report type")
    events = report["events"]
    expected = {event["occurrence_id"]: event["detail_replacement"] for event in events}
    if len(expected) != 14 or len(expected) != len(events):
        raise ValueError("repair report must contain exactly 14 unique occurrence_ids")
    if any(not detail for detail in expected.values()):
        raise ValueError("every repair event must provide detail_replacement")
    if set(report.get("expected_current_detail_sha256", {})) != set(expected):
        raise ValueError("repair report must pin every expected current detail")
    payload = {key: value for key, value in report.items() if key != "report_sha256"}
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if report.get("report_sha256") != digest:
        raise ValueError("repair report digest mismatch")
    return report, expected


def check_apply_report(path):
    result = json.loads(Path(path).read_text(encoding="utf-8"))
    summary = result.get("summary", {})
    audit = result.get("audit", {})
    applied = result.get("applied", {})
    guard = result.get("write_guard", {})
    if summary.get("issues_count") != 0 or audit.get("issue_count") != 0:
        raise ValueError("apply report contains issues or audit findings")
    if summary.get("issues_by_severity") or audit.get("issues_by_severity"):
        raise ValueError("apply report contains issue severities")
    if len(applied.get("events_applied", [])) != 14 or applied.get("events_unresolved"):
        raise ValueError("apply report did not apply exactly 14 events")
    if not guard.get("db_committed") or guard.get("rolled_back"):
        raise ValueError("apply report was not committed cleanly")


def check_audit_report(path):
    report = json.loads(Path(path).read_text(encoding="utf-8"))
    if report.get("issue_count") != 0 or report.get("issues_by_severity"):
        raise ValueError("post-fetch audit contains findings")


def verify_occurrences(before, after, expected):
    before_rows = row_map(before, "event_occurrences", "occurrence_id")
    after_rows = row_map(after, "event_occurrences", "occurrence_id")
    if before_rows.keys() != after_rows.keys():
        raise ValueError("event_occurrences row set changed")
    changed = {key for key in before_rows if before_rows[key] != after_rows[key]}
    if changed != set(expected):
        raise ValueError(f"unexpected occurrence changes: expected={sorted(expected)} actual={sorted(changed)}")
    for occurrence_id, expected_detail in expected.items():
        differences = {
            key: (before_rows[occurrence_id][key], after_rows[occurrence_id][key])
            for key in before_rows[occurrence_id]
            if before_rows[occurrence_id][key] != after_rows[occurrence_id][key]
        }
        if set(differences) - {"detail", "updated_at"}:
            raise ValueError(f"non-detail occurrence field changed: {occurrence_id}: {sorted(differences)}")
        if after_rows[occurrence_id]["detail"] != expected_detail:
            raise ValueError(f"replacement detail mismatch: {occurrence_id}")
    return changed


def verify_tables(before, after):
    before_tables, after_tables = tables(before), tables(after)
    if before_tables != after_tables:
        raise ValueError("database table set changed")
    for table in sorted(before_tables - {"event_occurrences"}):
        if rows(before, table) != rows(after, table):
            raise ValueError(f"out-of-scope table changed: {table}")


def public_source_index(path):
    source_map = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = source_map.get("rows", [])
    indexed = {row.get("public_event_key"): row.get("occurrence_id") for row in rows}
    if len(indexed) != len(rows) or len(set(indexed.values())) != len(rows) or not all(indexed.values()):
        raise ValueError("public source map lacks unique event keys/occurrence ids")
    return indexed


def verify_public(before, after, before_map, after_map, expected):
    before_rows = json.loads(Path(before).read_text(encoding="utf-8"))
    after_rows = json.loads(Path(after).read_text(encoding="utf-8"))
    before_source, after_source = public_source_index(before_map), public_source_index(after_map)
    if before_source != after_source:
        raise ValueError("public source map changed")
    def index(items, source):
        indexed = {}
        for item in items:
            key = "|".join(str(item.get(field) or "") for field in ("name", "venue", "date", "date_end"))
            if key not in source or key in indexed:
                raise ValueError("public events do not match the source map exactly")
            indexed[source[key]] = item
        if set(indexed) != set(source.values()):
            raise ValueError("public event key/count changed")
        return indexed
    before_index, after_index = index(before_rows, before_source), index(after_rows, after_source)
    if before_index.keys() != after_index.keys():
        raise ValueError("public event key/count changed")
    changed = {key for key in before_index if before_index[key] != after_index[key]}
    if changed != set(expected):
        raise ValueError(f"unexpected public event changes: {sorted(changed)}")
    for key in expected:
        differences = {field for field in before_index[key] | after_index[key] if before_index[key].get(field) != after_index[key].get(field)}
        if differences != {"detail"} or after_index[key].get("detail") != expected[key]:
            raise ValueError(f"public event changed outside detail: {key}: {sorted(differences)}")


def verify(before, after, report, apply_report=None, audit_report=None, public_before=None, public_after=None, public_before_source_map=None, public_after_source_map=None):
    _, expected = report_expectations(report)
    changed = verify_occurrences(before, after, expected)
    verify_tables(before, after)
    with closing(sqlite3.connect(after)) as conn:
        foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    if foreign_keys or integrity != "ok":
        raise ValueError(f"database integrity failed: fk={foreign_keys[:10]} integrity={integrity}")
    if apply_report:
        check_apply_report(apply_report)
    if audit_report:
        check_audit_report(audit_report)
    public_paths = (public_before, public_after, public_before_source_map, public_after_source_map)
    if any(public_paths):
        if not all(public_paths):
            raise ValueError("both public exports and source maps are required")
        verify_public(public_before, public_after, public_before_source_map, public_after_source_map, expected)
    return {"verified": True, "changed_occurrence_ids": sorted(changed), "count": len(changed)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", type=Path, required=True)
    parser.add_argument("--after", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--apply-report", type=Path)
    parser.add_argument("--audit-report", type=Path)
    parser.add_argument("--public-before", type=Path)
    parser.add_argument("--public-after", type=Path)
    parser.add_argument("--public-before-source-map", type=Path)
    parser.add_argument("--public-after-source-map", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    result = verify(**vars(args))
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text, end="")


if __name__ == "__main__":
    main()
