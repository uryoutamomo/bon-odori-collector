"""Export a conservative Notion apply plan for YouTube 2025 backfill."""

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


DB = Path("data/bon_odori.sqlite")
OUT = Path("data/youtube_2025_safe_existing_event_plan.json")
MD_OUT = Path("data/youtube_2025_safe_existing_event_plan.md")
MAX_SONGS_PER_EVENT = 40


def rows(conn, sql, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(sql, params)]


def md_escape(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def build_plan(db_path=DB):
    with sqlite3.connect(db_path) as conn:
        safe_rows = rows(
            conn,
            """
            SELECT
              e.event_id,
              e.event_name,
              e.start_date,
              e.end_date,
              e.source_url AS target_page_url,
              i.evidence_id,
              i.title,
              i.url,
              i.published_at,
              i.detected_event_date,
              i.account_key,
              l.confidence
            FROM event_evidence_links l
            JOIN events e ON e.event_id = l.event_id
            JOIN evidence_items i ON i.evidence_id = l.evidence_id
            WHERE l.link_status = 'matched_existing_event'
              AND i.platform = 'youtube'
              AND i.published_at LIKE '2025%'
              AND e.start_date LIKE '2025%'
              AND i.detected_event_date >= e.start_date
              AND i.detected_event_date <= COALESCE(NULLIF(e.end_date, ''), e.start_date)
            ORDER BY e.start_date, e.event_name, i.detected_event_date, i.title
            """,
        )
        evidence_ids = [row["evidence_id"] for row in safe_rows]
        song_rows = []
        if evidence_ids:
            placeholders = ",".join("?" for _ in evidence_ids)
            song_rows = rows(
                conn,
                f"""
                SELECT evidence_id, song_title, link_status
                FROM song_evidence_links
                WHERE evidence_id IN ({placeholders})
                ORDER BY link_status, song_title
                """,
                evidence_ids,
            )
    songs_by_evidence = defaultdict(list)
    for row in song_rows:
        title = row.get("song_title") or ""
        if title and title not in songs_by_evidence[row["evidence_id"]]:
            songs_by_evidence[row["evidence_id"]].append(title)

    grouped = defaultdict(list)
    for row in safe_rows:
        grouped[(row["event_id"], row["event_name"], row["start_date"], row["end_date"], row["target_page_url"])].append(row)

    plan_rows = []
    for (event_id, event_name, start_date, end_date, target_page_url), event_rows in grouped.items():
        videos = []
        songs = []
        dates = []
        for row in event_rows:
            videos.append(
                {
                    "url": row["url"],
                    "title": row["title"],
                    "channel": row["account_key"],
                    "published_at": row["published_at"],
                }
            )
            if row.get("detected_event_date") and row["detected_event_date"] not in dates:
                dates.append(row["detected_event_date"])
            for song in songs_by_evidence.get(row["evidence_id"], []):
                if song not in songs:
                    songs.append(song)
        plan_rows.append(
            {
                "status": "ready",
                "target_event_name": event_name,
                "target_page_id": event_id,
                "target_page_url": target_page_url,
                "event_date": ", ".join(dates) if dates else start_date,
                "date_range": {"start": start_date, "end": end_date or start_date},
                "videos": videos,
                "songs": songs[:MAX_SONGS_PER_EVENT],
                "songs_truncated": max(0, len(songs) - MAX_SONGS_PER_EVENT),
                "official_urls": [],
                "safety": {
                    "criteria": [
                        "youtube video published in 2025",
                        "Notion event start_date is in 2025",
                        "detected_event_date falls within Notion event date range",
                    ],
                    "video_count": len(videos),
                    "song_count": len(songs),
                },
            }
        )
    plan_rows.sort(key=lambda row: (row["date_range"]["start"], row["target_event_name"]))
    return {
        "generated_by": "export_youtube_2025_safe_notion_plan.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_db": str(db_path),
        "criteria": "2025 published YouTube videos with detected_event_date inside a 2025 Notion event date range",
        "event_count": len(plan_rows),
        "video_count": sum(len(row["videos"]) for row in plan_rows),
        "rows": plan_rows,
    }


def render_markdown(plan):
    lines = [
        "# YouTube 2025安全反映計画",
        "",
        f"- 生成: {plan['generated_at']}",
        f"- イベント: {plan['event_count']}",
        f"- 動画: {plan['video_count']}",
        f"- 条件: {plan['criteria']}",
        "",
        "| event | date_range | videos | songs | truncated |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for row in plan["rows"]:
        lines.append(
            f"| {md_escape(row['target_event_name'])} | "
            f"{md_escape(row['date_range']['start'])}..{md_escape(row['date_range']['end'])} | "
            f"{len(row['videos'])} | {len(row['songs'])} | {row['songs_truncated']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    plan = build_plan()
    OUT.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MD_OUT.write_text(render_markdown(plan), encoding="utf-8")
    print(f"[youtube-2025-safe-plan] events={plan['event_count']} videos={plan['video_count']} -> {OUT}")


if __name__ == "__main__":
    main()
