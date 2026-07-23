"""Export Notion apply/review plans from the unified Bon Odori RDB."""

import argparse
import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


DB = Path("data/bon_odori.sqlite")
EVENT_PLAN_JSON = Path("data/rdb_event_apply_plan.json")
EVENT_PLAN_MD = Path("data/rdb_event_apply_plan.md")
SONG_REVIEW_JSON = Path("data/rdb_song_review_source.json")
SONG_REVIEW_MD = Path("data/rdb_song_review_source.md")
SUMMARY_JSON = Path("data/rdb_apply_plan_summary.json")

YOUTUBE_URL_RE = re.compile(r"https?://(?:www\.)?(?:youtube\.com|youtu\.be)/(?:watch\?v=|shorts/)?[A-Za-z0-9_-]+[^\s、。，)）]*")


def rows(conn, sql, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(sql, params)]


def md_escape(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def detail_urls(detail):
    return set(YOUTUBE_URL_RE.findall(detail or ""))


def event_row_status(event, item):
    urls = detail_urls(event.get("detail") or "")
    if item.get("url") in urls:
        return "no_action_url_already_present", "Notion詳細欄に同一YouTube URLがある"
    detail = event.get("detail") or ""
    if (
        "[youtube_evidence]" in detail
        and (
            "追加動画:" in detail
            or (f"対象イベント: {event.get('event_name')}" in detail and "動画数:" in detail)
        )
    ):
        return "no_action_summary_present", "Notion詳細欄にYouTube証拠の要約反映があるため重複追記しない"
    if str(item.get("published_at") or "").startswith("2025"):
        return "review_batch_2025_backfill", "2025総浚いの大量候補のため、段階レビュー後に反映する"
    return "ready", "既存イベントにYouTube証拠として追記可能"


def build_event_plan(conn):
    source_rows = rows(
        conn,
        """
        SELECT
          e.event_id,
          e.event_name,
          e.start_date,
          e.end_date,
          e.source_url AS target_page_url,
          e.detail,
          i.evidence_id,
          i.title,
          i.url,
          i.published_at,
          i.account_key,
          l.link_source,
          l.confidence
        FROM event_evidence_links l
        JOIN events e ON e.event_id = l.event_id
        JOIN evidence_items i ON i.evidence_id = l.evidence_id
        WHERE l.link_status = 'matched_existing_event'
        ORDER BY e.start_date DESC, e.event_name, i.published_at, i.title
        """,
    )
    plan_rows = []
    for row in source_rows:
        status, reason = event_row_status(row, row)
        plan_rows.append(
            {
                "status": status,
                "reason": reason,
                "target_event_name": row["event_name"],
                "target_page_id": row["event_id"],
                "target_page_url": row["target_page_url"],
                "event_date": row["start_date"],
                "end_date": row["end_date"],
                "evidence_id": row["evidence_id"],
                "link_source": row["link_source"],
                "confidence": row["confidence"],
                "videos": [
                    {
                        "url": row["url"],
                        "title": row["title"],
                        "channel": row["account_key"],
                        "published_at": row["published_at"],
                    }
                ],
                "songs": [],
                "official_urls": [],
            }
        )
    return {
        "generated_by": "export_rdb_apply_plans.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": str(DB),
        "rows": plan_rows,
    }


def build_song_review_source(conn):
    source_rows = rows(
        conn,
        """
        SELECT
          l.song_title,
          COUNT(*) AS evidence_count,
          MIN(i.url) AS evidence_url,
          MIN(i.title) AS evidence_title,
          MIN(i.text_excerpt) AS evidence_text,
          GROUP_CONCAT(DISTINCT i.evidence_id) AS evidence_ids
        FROM song_evidence_links l
        JOIN evidence_items i ON i.evidence_id = l.evidence_id
        WHERE l.link_status = 'unmatched_song'
        GROUP BY l.song_title
        ORDER BY evidence_count DESC, l.song_title
        """,
    )
    review_rows = []
    for row in source_rows:
        review_rows.append(
            {
                "status": "needs_song_master_review",
                "term": row["song_title"],
                "canonical_song_name": row["song_title"],
                "evidence_count": row["evidence_count"],
                "evidence_url": row["evidence_url"],
                "evidence_text": row["evidence_text"] or row["evidence_title"] or "",
                "evidence_ids": [value for value in (row["evidence_ids"] or "").split(",") if value],
                "suggested_action": "review_then_add_or_alias",
            }
        )
    return {
        "generated_by": "export_rdb_apply_plans.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": str(DB),
        "rows": review_rows,
    }


def status_counts(rows_):
    counts = {}
    for row in rows_:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return counts


def render_event_markdown(plan):
    lines = [
        "# RDBイベント反映計画",
        "",
        f"- 生成: {plan['generated_at']}",
        f"- DB: {plan['database']}",
        "",
        "## 状態別件数",
        "",
        "| status | count |",
        "| --- | ---: |",
    ]
    for status, count in sorted(status_counts(plan["rows"]).items()):
        lines.append(f"| {md_escape(status)} | {count} |")
    lines.extend(
        [
            "",
            "## 明細",
            "",
            "| status | event | date | video | url | reason |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in plan["rows"]:
        video = (row.get("videos") or [{}])[0]
        lines.append(
            f"| {md_escape(row['status'])} | {md_escape(row['target_event_name'])} | "
            f"{md_escape(row['event_date'])} | {md_escape(video.get('title'))} | "
            f"{md_escape(video.get('url'))} | {md_escape(row['reason'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_song_markdown(source):
    lines = [
        "# RDB曲マスタレビュー元データ",
        "",
        f"- 生成: {source['generated_at']}",
        f"- DB: {source['database']}",
        f"- 候補数: {len(source['rows'])}",
        "",
        "| song | evidence_count | sample_url | sample_text |",
        "| --- | ---: | --- | --- |",
    ]
    for row in source["rows"]:
        lines.append(
            f"| {md_escape(row['term'])} | {row['evidence_count']} | "
            f"{md_escape(row['evidence_url'])} | {md_escape(row['evidence_text'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def build_plans(db_path=DB):
    with closing(sqlite3.connect(db_path)) as conn:
        event_plan = build_event_plan(conn)
        song_source = build_song_review_source(conn)
    summary = {
        "generated_by": "export_rdb_apply_plans.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": str(db_path),
        "event_plan_counts": status_counts(event_plan["rows"]),
        "song_review_candidates": len(song_source["rows"]),
        "outputs": {
            "event_plan_json": str(EVENT_PLAN_JSON),
            "event_plan_md": str(EVENT_PLAN_MD),
            "song_review_json": str(SONG_REVIEW_JSON),
            "song_review_md": str(SONG_REVIEW_MD),
        },
    }
    return event_plan, song_source, summary


def write_plans(event_plan, song_source, summary, event_json=EVENT_PLAN_JSON, event_md=EVENT_PLAN_MD, song_json=SONG_REVIEW_JSON, song_md=SONG_REVIEW_MD, summary_json=SUMMARY_JSON):
    for path in [event_json, event_md, song_json, song_md, summary_json]:
        path.parent.mkdir(parents=True, exist_ok=True)
    event_json.write_text(json.dumps(event_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    event_md.write_text(render_event_markdown(event_plan), encoding="utf-8")
    song_json.write_text(json.dumps(song_source, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    song_md.write_text(render_song_markdown(song_source), encoding="utf-8")
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(DB))
    args = parser.parse_args()

    event_plan, song_source, summary = build_plans(Path(args.db))
    write_plans(event_plan, song_source, summary)
    print(
        "RDB apply plans: "
        f"event_plan={summary['event_plan_counts']}, "
        f"song_review_candidates={summary['song_review_candidates']}"
    )


if __name__ == "__main__":
    main()
