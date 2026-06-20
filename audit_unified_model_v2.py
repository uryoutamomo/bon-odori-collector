"""Audit the staging event-occurrence model and cross-source RDB snapshot.

This is a read-only contract check for the unified model v2 work. It does not
write to Notion, public exports, or source datasets; only JSON/Markdown audit
reports are generated under data/.
"""

import argparse
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from build_event_occurrence_observations import series_key as expected_series_key
from build_event_occurrence_observations import stable_id, year_of


DATA = Path("data")
DEFAULT_OBSERVATIONS = DATA / "event_occurrence_observations.json"
DEFAULT_RDB = DATA / "bon_odori.sqlite"
DEFAULT_OUT_JSON = DATA / "unified_model_v2_audit.json"
DEFAULT_OUT_MD = DATA / "unified_model_v2_audit.md"

OBSERVATION_REQUIRED = {
    "observation_id",
    "series_key",
    "event_name",
    "venue",
    "year",
    "date_start",
    "date_end",
    "observed_dates",
    "source_type",
    "source_video_count",
    "confidence",
}

SERIES_REQUIRED = {
    "series_key",
    "canonical_name",
    "usual_venue",
    "observed_years",
    "observation_count",
}


def read_json(path):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def name_years(text):
    return {int(year) for year in re.findall(r"(20\d{2})", text or "")}


def observation_expected_id(row):
    dates = ",".join(row.get("observed_dates") or [])
    return stable_id(row.get("series_key"), row.get("year"), dates)


def compact_issue(issue_type, severity, description, payload=None):
    return {
        "issue_type": issue_type,
        "severity": severity,
        "description": description,
        "payload": payload or {},
    }


def audit_observations(data):
    observations = data.get("observations") or []
    series_rows = data.get("series") or []
    issues = []
    ids = Counter(row.get("observation_id") for row in observations)
    series_keys = {row.get("series_key") for row in series_rows}
    obs_by_series = Counter(row.get("series_key") for row in observations)

    for row in series_rows:
        missing = sorted(SERIES_REQUIRED - set(row.keys()))
        if missing:
            issues.append(compact_issue(
                "series_missing_required_fields",
                "high",
                "Series row is missing required fields.",
                {"series_key": row.get("series_key"), "missing": missing},
            ))
        expected_count = obs_by_series.get(row.get("series_key"), 0)
        if row.get("observation_count") != expected_count:
            issues.append(compact_issue(
                "series_observation_count_mismatch",
                "medium",
                "Series observation_count does not match observations.",
                {
                    "series_key": row.get("series_key"),
                    "reported": row.get("observation_count"),
                    "actual": expected_count,
                },
            ))

    for observation_id, count in ids.items():
        if observation_id and count > 1:
            issues.append(compact_issue(
                "duplicate_observation_id",
                "high",
                "Observation id is duplicated.",
                {"observation_id": observation_id, "count": count},
            ))

    for row in observations:
        missing = sorted(OBSERVATION_REQUIRED - set(row.keys()))
        if missing:
            issues.append(compact_issue(
                "observation_missing_required_fields",
                "high",
                "Observation row is missing required fields.",
                {"observation_id": row.get("observation_id"), "missing": missing},
            ))
        expected_key = expected_series_key(row.get("event_name"), row.get("venue"))
        if row.get("series_key") != expected_key:
            issues.append(compact_issue(
                "observation_series_key_mismatch",
                "medium",
                "Observation series_key is not derived from event_name and venue.",
                {
                    "observation_id": row.get("observation_id"),
                    "series_key": row.get("series_key"),
                    "expected_series_key": expected_key,
                    "event_name": row.get("event_name"),
                    "venue": row.get("venue"),
                },
            ))
        if row.get("series_key") not in series_keys:
            issues.append(compact_issue(
                "observation_missing_series",
                "high",
                "Observation references a series_key not present in series.",
                {"observation_id": row.get("observation_id"), "series_key": row.get("series_key")},
            ))
        expected_id = observation_expected_id(row)
        if row.get("observation_id") != expected_id:
            issues.append(compact_issue(
                "observation_id_mismatch",
                "medium",
                "Observation id is not derived from series_key, year, and observed_dates.",
                {
                    "observation_id": row.get("observation_id"),
                    "expected_observation_id": expected_id,
                    "series_key": row.get("series_key"),
                    "year": row.get("year"),
                    "observed_dates": row.get("observed_dates"),
                },
            ))
        date_years = {year_of(row.get("date_start")), year_of(row.get("date_end"))}
        date_years.update(year_of(date) for date in row.get("observed_dates") or [])
        date_years.discard(None)
        if date_years and date_years != {row.get("year")}:
            issues.append(compact_issue(
                "observation_year_date_mismatch",
                "high",
                "Observation year does not match date_start/date_end/observed_dates.",
                {
                    "observation_id": row.get("observation_id"),
                    "year": row.get("year"),
                    "date_years": sorted(date_years),
                    "date_start": row.get("date_start"),
                    "date_end": row.get("date_end"),
                },
            ))
        embedded_years = name_years(row.get("event_name"))
        if embedded_years and row.get("year") not in embedded_years:
            issues.append(compact_issue(
                "event_name_year_mismatch",
                "review",
                "Event name contains a year that differs from the observed occurrence year.",
                {
                    "observation_id": row.get("observation_id"),
                    "event_name": row.get("event_name"),
                    "year": row.get("year"),
                    "name_years": sorted(embedded_years),
                    "date_start": row.get("date_start"),
                },
            ))

    summary = {
        "observation_count": len(observations),
        "series_count": len(series_rows),
        "issue_count": len(issues),
        "issues_by_type": dict(Counter(issue["issue_type"] for issue in issues)),
        "issues_by_severity": dict(Counter(issue["severity"] for issue in issues)),
    }
    return summary, issues


def table_count(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def scalar(conn, query):
    return conn.execute(query).fetchone()[0]


def grouped_counts(conn, query):
    return {str(key): count for key, count in conn.execute(query).fetchall()}


def audit_rdb(path):
    path = Path(path)
    if not path.exists():
        return {
            "database": str(path),
            "table_counts": {},
            "issue_count": 1,
            "issues_by_type": {"rdb_missing": 1},
            "issues_by_severity": {"high": 1},
        }, [compact_issue("rdb_missing", "high", "RDB sqlite snapshot is missing.", {"database": str(path)})]

    issues = []
    with sqlite3.connect(path) as conn:
        counts = {
            table: table_count(conn, table)
            for table in [
                "events",
                "venues",
                "event_venues",
                "songs",
                "dance_variants",
                "event_song_links",
                "evidence_items",
                "event_evidence_links",
                "song_evidence_links",
                "review_queue",
                "rdb_issues",
            ]
        }
        checks = {
            "event_venues_missing_event": scalar(conn, "SELECT COUNT(*) FROM event_venues ev LEFT JOIN events e ON e.event_id = ev.event_id WHERE e.event_id IS NULL"),
            "event_venues_missing_venue": scalar(conn, "SELECT COUNT(*) FROM event_venues ev LEFT JOIN venues v ON v.venue_id = ev.venue_id WHERE v.venue_id IS NULL"),
            "event_evidence_missing_event": scalar(conn, "SELECT COUNT(*) FROM event_evidence_links l LEFT JOIN events e ON e.event_id = l.event_id WHERE e.event_id IS NULL"),
            "event_evidence_missing_evidence": scalar(conn, "SELECT COUNT(*) FROM event_evidence_links l LEFT JOIN evidence_items i ON i.evidence_id = l.evidence_id WHERE i.evidence_id IS NULL"),
            "event_song_missing_event": scalar(conn, "SELECT COUNT(*) FROM event_song_links l LEFT JOIN events e ON e.event_id = l.event_id WHERE e.event_id IS NULL"),
            "song_evidence_missing_evidence": scalar(conn, "SELECT COUNT(*) FROM song_evidence_links l LEFT JOIN evidence_items i ON i.evidence_id = l.evidence_id WHERE i.evidence_id IS NULL"),
            "empty_event_name": scalar(conn, "SELECT COUNT(*) FROM events WHERE event_name = ''"),
            "empty_venue_name": scalar(conn, "SELECT COUNT(*) FROM venues WHERE venue_name = ''"),
            "empty_song_name": scalar(conn, "SELECT COUNT(*) FROM songs WHERE song_name = ''"),
        }
        for check, count in checks.items():
            if count:
                severity = "high" if "missing_" in check else "medium"
                issues.append(compact_issue(
                    check,
                    severity,
                    f"RDB integrity check failed: {check}.",
                    {"count": count},
                ))
        review_statuses = grouped_counts(
            conn,
            "SELECT review_status, COUNT(*) FROM review_queue GROUP BY review_status ORDER BY COUNT(*) DESC",
        )
        event_link_statuses = grouped_counts(
            conn,
            "SELECT link_status, COUNT(*) FROM event_evidence_links GROUP BY link_status ORDER BY COUNT(*) DESC",
        )
        song_link_statuses = grouped_counts(
            conn,
            "SELECT link_status, COUNT(*) FROM song_evidence_links GROUP BY link_status ORDER BY COUNT(*) DESC",
        )

    summary = {
        "database": str(path),
        "table_counts": counts,
        "integrity_checks": checks,
        "review_statuses": review_statuses,
        "event_link_statuses": event_link_statuses,
        "song_link_statuses": song_link_statuses,
        "issue_count": len(issues),
        "issues_by_type": dict(Counter(issue["issue_type"] for issue in issues)),
        "issues_by_severity": dict(Counter(issue["severity"] for issue in issues)),
    }
    return summary, issues


def render_md(report):
    lines = [
        "# 統一モデルv2 監査レポート",
        "",
        f"生成: {report['generated_at']}",
        "",
        "## 概要",
        "",
    ]
    obs = report["observation_audit"]["summary"]
    rdb = report["rdb_audit"]["summary"]
    lines.extend([
        f"- observations: {obs['observation_count']} rows / {obs['series_count']} series / issues={obs['issue_count']}",
        f"- RDB: {rdb.get('database')} / issues={rdb['issue_count']}",
        "",
        "## 観測JSONの論点",
        "",
    ])
    for issue in report["observation_audit"]["issues"][:25]:
        payload = issue.get("payload") or {}
        label = payload.get("event_name") or payload.get("observation_id") or payload.get("series_key") or ""
        lines.append(f"- {issue['severity']} / {issue['issue_type']}: {label} - {issue['description']}")
    if not report["observation_audit"]["issues"]:
        lines.append("- 重大な契約違反は検出なし。")
    lines.extend(["", "## RDBの論点", ""])
    for issue in report["rdb_audit"]["issues"][:25]:
        lines.append(f"- {issue['severity']} / {issue['issue_type']}: {issue['description']} {issue.get('payload') or {}}")
    if not report["rdb_audit"]["issues"]:
        lines.append("- 外部キー相当の欠損・空名称は検出なし。")
    lines.extend(["", "## レビューキュー上位", ""])
    for status, count in list((rdb.get("review_statuses") or {}).items())[:12]:
        lines.append(f"- {status}: {count}")
    lines.extend(["", "## 次アクション案", ""])
    lines.append("- event_name_year_mismatch は名称正規化か開催年解釈のどちらかを手動レビューする。")
    lines.append("- RDBの外部キー相当チェックが0なら、次は event_series / event_occurrences のJSON契約案へ進める。")
    lines.append("- review_queue は件数が大きいため、status別に人間レビュー対象と自動保留を分離する。")
    lines.append("")
    return "\n".join(lines)


def build_report(observations_path, rdb_path):
    observations = read_json(observations_path)
    observation_summary, observation_issues = audit_observations(observations)
    rdb_summary, rdb_issues = audit_rdb(rdb_path)
    return {
        "generated_by": "audit_unified_model_v2.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "observations": str(observations_path),
            "rdb": str(rdb_path),
        },
        "observation_audit": {
            "summary": observation_summary,
            "issues": observation_issues,
        },
        "rdb_audit": {
            "summary": rdb_summary,
            "issues": rdb_issues,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", default=str(DEFAULT_OBSERVATIONS))
    parser.add_argument("--rdb", default=str(DEFAULT_RDB))
    parser.add_argument("--out-json", default=str(DEFAULT_OUT_JSON))
    parser.add_argument("--out-md", default=str(DEFAULT_OUT_MD))
    args = parser.parse_args()

    report = build_report(Path(args.observations), Path(args.rdb))
    write_json(args.out_json, report)
    Path(args.out_md).write_text(render_md(report), encoding="utf-8")
    obs = report["observation_audit"]["summary"]
    rdb = report["rdb_audit"]["summary"]
    print(
        "unified model v2 audit: "
        f"observations={obs['observation_count']} "
        f"series={obs['series_count']} "
        f"observation_issues={obs['issue_count']} "
        f"rdb_issues={rdb['issue_count']}"
    )


if __name__ == "__main__":
    main()
