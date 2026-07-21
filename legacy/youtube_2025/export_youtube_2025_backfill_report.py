"""Export a focused report for the YouTube 2025 backfill."""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


DB = Path("data/bon_odori.sqlite")
YOUTUBE_DB = Path("data/youtube_evidence.sqlite")
FETCH_REPORT = Path("data/youtube_2025_backfill_fetch_report.json")
OUT_JSON = Path("data/youtube_2025_backfill_report.json")
OUT_MD = Path("data/youtube_2025_backfill_report.md")


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def rows(conn, sql, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(sql, params)]


def md_escape(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def build_report(db_path=DB, youtube_db_path=YOUTUBE_DB):
    fetch_report = load_json(FETCH_REPORT, {})
    with sqlite3.connect(db_path) as conn:
        status_counts = rows(
            conn,
            """
            SELECT q.review_status, q.priority, COUNT(*) AS count
            FROM review_queue q
            LEFT JOIN evidence_items i ON i.evidence_id = q.evidence_id
            WHERE i.platform = 'youtube'
              AND i.published_at LIKE '2025%'
            GROUP BY q.review_status, q.priority
            ORDER BY count DESC, q.review_status
            """,
        )
        matched_events = rows(
            conn,
            """
            SELECT e.event_name, e.start_date, COUNT(*) AS evidence_count
            FROM event_evidence_links l
            JOIN events e ON e.event_id = l.event_id
            JOIN evidence_items i ON i.evidence_id = l.evidence_id
            WHERE l.link_status = 'matched_existing_event'
              AND i.published_at LIKE '2025%'
            GROUP BY e.event_id
            ORDER BY evidence_count DESC, e.event_name
            LIMIT 50
            """,
        )
        official_candidates = rows(
            conn,
            """
            SELECT i.account_key, i.title, i.url, i.published_at
            FROM review_queue q
            JOIN evidence_items i ON i.evidence_id = q.evidence_id
            WHERE q.review_status = 'needs_official_confirmation'
              AND i.platform = 'youtube'
              AND i.published_at LIKE '2025%'
            ORDER BY i.published_at, i.title
            LIMIT 100
            """,
        )
        video_review_candidates = rows(
            conn,
            """
            SELECT i.account_key, COUNT(*) AS count
            FROM review_queue q
            JOIN evidence_items i ON i.evidence_id = q.evidence_id
            WHERE q.review_status = 'review_video_evidence'
              AND i.platform = 'youtube'
              AND i.published_at LIKE '2025%'
            GROUP BY i.account_key
            ORDER BY count DESC
            """,
        )
        unmatched_songs = rows(
            conn,
            """
            SELECT l.song_title, COUNT(*) AS evidence_count
            FROM song_evidence_links l
            JOIN evidence_items i ON i.evidence_id = l.evidence_id
            WHERE l.link_status = 'unmatched_song'
              AND i.platform = 'youtube'
              AND i.published_at LIKE '2025%'
            GROUP BY l.song_title
            ORDER BY evidence_count DESC, l.song_title
            LIMIT 100
            """,
        )
    with sqlite3.connect(youtube_db_path) as conn:
        channel_counts = rows(
            conn,
            """
            SELECT
              c.title,
              c.priority,
              json_extract(c.metrics_json, '$.analytics.auto_score') AS auto_score,
              COUNT(v.video_id) AS video_count,
              SUM(CASE WHEN v.has_bon_context THEN 1 ELSE 0 END) AS bon_context_count,
              SUM(CASE WHEN v.action = 'needs_official_confirmation' THEN 1 ELSE 0 END) AS official_count,
              SUM(CASE WHEN v.action = 'append_existing_event' THEN 1 ELSE 0 END) AS append_count,
              MIN(v.published_at) AS first_published_at,
              MAX(v.published_at) AS last_published_at
            FROM videos v
            LEFT JOIN channels c ON c.channel_id = v.channel_id
            WHERE v.published_at LIKE '2025%'
            GROUP BY v.channel_id
            ORDER BY auto_score DESC, video_count DESC
            """,
        )
    total_2025_videos = sum(row.get("video_count") or 0 for row in channel_counts)
    return {
        "generated_by": "export_youtube_2025_backfill_report.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_2025_videos_in_rdb": total_2025_videos,
        "fetch_report": {
            "fetched_2025_video_count": fetch_report.get("fetched_2025_video_count"),
            "api_request_count": fetch_report.get("api_request_count"),
            "by_channel": fetch_report.get("by_channel") or [],
        },
        "channel_counts": channel_counts,
        "review_status_counts": status_counts,
        "matched_existing_events_top": matched_events,
        "official_confirmation_candidates_sample": official_candidates,
        "video_review_candidates_by_channel": video_review_candidates,
        "unmatched_songs_top": unmatched_songs,
    }


def render_markdown(report):
    lines = [
        "# YouTube 2025総浚い レポート",
        "",
        f"- 生成: {report['generated_at']}",
        f"- RDB内2025動画数: {report['total_2025_videos_in_rdb']}",
        f"- 直近API取得2025動画数: {report['fetch_report'].get('fetched_2025_video_count')}",
        f"- 直近APIリクエスト数: {report['fetch_report'].get('api_request_count')}",
        "",
        "## チャンネル別",
        "",
        "| channel | priority | auto_score | 2025 videos | bon context | append action | official candidates | first | last |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in report["channel_counts"]:
        lines.append(
            f"| {md_escape(row['title'])} | {md_escape(row['priority'])} | {row['auto_score'] or ''} | "
            f"{row['video_count']} | {row['bon_context_count'] or 0} | {row['append_count'] or 0} | "
            f"{row['official_count'] or 0} | {md_escape(str(row['first_published_at'])[:10])} | "
            f"{md_escape(str(row['last_published_at'])[:10])} |"
        )
    lines.extend([
        "",
        "## レビュー状態",
        "",
        "| status | priority | count |",
        "| --- | --- | ---: |",
    ])
    for row in report["review_status_counts"]:
        lines.append(f"| {md_escape(row['review_status'])} | {md_escape(row['priority'])} | {row['count']} |")
    lines.extend([
        "",
        "## 既存イベント一致 Top50",
        "",
        "| event | date | evidence_count |",
        "| --- | --- | ---: |",
    ])
    for row in report["matched_existing_events_top"]:
        lines.append(f"| {md_escape(row['event_name'])} | {md_escape(row['start_date'])} | {row['evidence_count']} |")
    lines.extend([
        "",
        "## 公式確認候補サンプル",
        "",
        "| channel_id | published | title | url |",
        "| --- | --- | --- | --- |",
    ])
    for row in report["official_confirmation_candidates_sample"]:
        lines.append(
            f"| {md_escape(row['account_key'])} | {md_escape(str(row['published_at'])[:10])} | "
            f"{md_escape(row['title'])} | {md_escape(row['url'])} |"
        )
    lines.extend([
        "",
        "## 曲マスタ未登録候補 Top100",
        "",
        "| song | evidence_count |",
        "| --- | ---: |",
    ])
    for row in report["unmatched_songs_top"]:
        lines.append(f"| {md_escape(row['song_title'])} | {row['evidence_count']} |")
    lines.append("")
    return "\n".join(lines)


def main():
    report = build_report()
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_MD.write_text(render_markdown(report), encoding="utf-8")
    print(
        "[youtube-2025-report] "
        f"channels={len(report['channel_counts'])} "
        f"statuses={len(report['review_status_counts'])} "
        f"matched_events={len(report['matched_existing_events_top'])} -> {OUT_MD}"
    )


if __name__ == "__main__":
    main()
