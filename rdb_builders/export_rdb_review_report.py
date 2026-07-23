"""Export review queues from the unified Bon Odori RDB."""

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


DB = Path("data/bon_odori.sqlite")
OUT_JSON = Path("data/rdb_review_queue.json")
OUT_MD = Path("data/rdb_review_queue.md")


def rows(conn, sql, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(sql, params)]


def build_report(db_path=DB):
    with closing(sqlite3.connect(db_path)) as conn:
        status_counts = rows(
            conn,
            """
            SELECT review_status, priority, COUNT(*) AS count
            FROM review_queue
            GROUP BY review_status, priority
            ORDER BY count DESC, review_status
            """,
        )
        matched_existing = rows(
            conn,
            """
            SELECT e.event_name, e.start_date, i.title, i.url, l.link_source
            FROM event_evidence_links l
            JOIN events e ON e.event_id = l.event_id
            JOIN evidence_items i ON i.evidence_id = l.evidence_id
            WHERE l.link_status = 'matched_existing_event'
            ORDER BY e.start_date DESC, e.event_name, i.title
            """,
        )
        needs_confirmation = rows(
            conn,
            """
            SELECT q.review_status, q.priority, i.title, i.url, q.reason
            FROM review_queue q
            LEFT JOIN evidence_items i ON i.evidence_id = q.evidence_id
            WHERE q.review_status IN ('needs_official_confirmation', 'review_video_evidence', 'out_of_scope')
            ORDER BY q.priority, q.review_status, i.title
            """,
        )
        unmatched_songs = rows(
            conn,
            """
            SELECT song_title, COUNT(*) AS evidence_count
            FROM song_evidence_links
            WHERE link_status = 'unmatched_song'
            GROUP BY song_title
            ORDER BY evidence_count DESC, song_title
            LIMIT 50
            """,
        )
        issues = rows(
            conn,
            "SELECT severity, issue_type, description, payload_json FROM rdb_issues ORDER BY severity, issue_type",
        )
    return {
        "generated_by": "export_rdb_review_report.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": str(db_path),
        "status_counts": status_counts,
        "matched_existing_event": matched_existing,
        "needs_confirmation_or_hold": needs_confirmation,
        "unmatched_songs_top": unmatched_songs,
        "issues": issues,
    }


def md_escape(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(report):
    lines = [
        "# RDBレビューキュー",
        "",
        f"- 生成: {report['generated_at']}",
        f"- DB: {report['database']}",
        "",
        "## 状態別件数",
        "",
        "| status | priority | count |",
        "| --- | --- | ---: |",
    ]
    for row in report["status_counts"]:
        lines.append(f"| {md_escape(row['review_status'])} | {md_escape(row['priority'])} | {row['count']} |")

    lines.extend([
        "",
        "## 既存イベント一致・Notion反映候補",
        "",
        "| event | date | video | url | source |",
        "| --- | --- | --- | --- | --- |",
    ])
    for row in report["matched_existing_event"]:
        lines.append(
            f"| {md_escape(row['event_name'])} | {md_escape(row['start_date'])} | "
            f"{md_escape(row['title'])} | {md_escape(row['url'])} | {md_escape(row['link_source'])} |"
        )

    lines.extend([
        "",
        "## 公式確認・保留",
        "",
        "| status | priority | title | url | reason |",
        "| --- | --- | --- | --- | --- |",
    ])
    for row in report["needs_confirmation_or_hold"]:
        lines.append(
            f"| {md_escape(row['review_status'])} | {md_escape(row['priority'])} | "
            f"{md_escape(row['title'])} | {md_escape(row['url'])} | {md_escape(row['reason'])} |"
        )

    lines.extend([
        "",
        "## 曲マスタ未登録候補 Top50",
        "",
        "| song | evidence_count |",
        "| --- | ---: |",
    ])
    for row in report["unmatched_songs_top"]:
        lines.append(f"| {md_escape(row['song_title'])} | {row['evidence_count']} |")

    lines.extend([
        "",
        "## 小さな未解決点",
        "",
        "| severity | type | description |",
        "| --- | --- | --- |",
    ])
    for row in report["issues"]:
        lines.append(f"| {md_escape(row['severity'])} | {md_escape(row['issue_type'])} | {md_escape(row['description'])} |")
    lines.append("")
    return "\n".join(lines)


def write_report(report, out_json=OUT_JSON, out_md=OUT_MD):
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(render_markdown(report), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DB))
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    args = parser.parse_args()

    report = build_report(Path(args.db))
    write_report(report, Path(args.out_json), Path(args.out_md))
    print(
        "RDB review report: "
        f"matched_existing_event={len(report['matched_existing_event'])}, "
        f"needs_confirmation_or_hold={len(report['needs_confirmation_or_hold'])}, "
        f"unmatched_songs_top={len(report['unmatched_songs_top'])}"
    )


if __name__ == "__main__":
    main()
