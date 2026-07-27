#!/usr/bin/env python3
"""Dry-run existing-event evidence updates from active YouTube video review rows."""

import argparse
import json
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from notion_support.notion_api import NotionApi, plain_text
from notion_support.notion_config import EVENT_DATA_SOURCE_ID


REVIEW = Path("data/youtube_active_video_review.json")
YOUTUBE_SETLISTS = Path("data/youtube_setlist_occurrences.json")
OUT = Path("data/youtube_active_existing_event_update_dry_run.json")
MARKDOWN_OUT = Path("data/youtube_active_existing_event_update_dry_run.md")

EVENT_NAME_ALIASES = {
    "国立旭通りジューンフェスタ盆踊り": [
        "ジューンフェスタ2026 盆踊り（国立市旭通り商店会）",
        "国立旭通りジューンフェスタ",
        "国立ジューンフェスタ",
    ],
}


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=".tmp-", suffix=".json", delete=False
    ) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        tmp_name = handle.name
    Path(tmp_name).replace(path)


def atomic_write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=".tmp-", suffix=".md", delete=False
    ) as handle:
        handle.write(text)
        tmp_name = handle.name
    Path(tmp_name).replace(path)


def event_name_candidates(name):
    return [name] + EVENT_NAME_ALIASES.get(name, [])


def find_event(api, name):
    for candidate in event_name_candidates(name):
        rows = api.query_data_source(
            EVENT_DATA_SOURCE_ID,
            {"filter": {"property": "イベント名", "title": {"equals": candidate}}, "page_size": 5},
        )
        if rows:
            return rows[0]
    return None


def page_detail(page):
    return plain_text((page.get("properties") or {}).get("開催パターン詳細"))


def page_url(page):
    return page.get("url") or f"https://www.notion.so/{page.get('id', '').replace('-', '')}"


def setlist_by_occurrence_key(payload):
    rows = {}
    for occurrence in payload.get("occurrences") or []:
        key = occurrence.get("occurrence_key") or ""
        if key:
            rows[key] = occurrence
    return rows


def target_event_name(row):
    match = row.get("matched_public_event") or {}
    if match.get("name"):
        return match["name"]
    occurrences = row.get("setlist_occurrences") or []
    return occurrences[0].get("event_name") if occurrences else ""


def evidence_event_date(row):
    detected_date = row.get("detected_event_date") or ""
    if detected_date:
        return detected_date
    match = row.get("matched_public_event") or {}
    reasons = set(match.get("reasons") or [])
    # A curated alias can identify the event series across years, but the
    # current public occurrence date is not evidence for an undated video.
    if reasons & {"event_alias_in_youtube", "cross_year_event_alias"}:
        return ""
    return match.get("date") or ""


def group_key(row):
    event_name = target_event_name(row)
    occurrences = row.get("setlist_occurrences") or []
    occurrence_key = occurrences[0].get("occurrence_key") if occurrences else ""
    event_date = evidence_event_date(row)
    return event_name, occurrence_key, event_date


def add_unique(rows, row, key_fn):
    key = key_fn(row)
    if not key:
        return
    if all(key_fn(existing) != key for existing in rows):
        rows.append(row)


def build_groups(review):
    groups = {}
    for row in review.get("rows") or []:
        if row.get("action") != "append_existing_event":
            continue
        event_name, occurrence_key, event_date = group_key(row)
        if not event_name:
            continue
        group = groups.setdefault((event_name, occurrence_key, event_date), {
            "target_event_name": event_name,
            "occurrence_key": occurrence_key,
            "event_date": event_date,
            "matched_public_event": row.get("matched_public_event") or {},
            "videos": [],
            "official_urls": [],
        })
        add_unique(
            group["videos"],
            {
                "url": row.get("video_url") or "",
                "title": row.get("title") or "",
                "channel": row.get("channel_title") or "",
                "published_at": row.get("published_at") or "",
            },
            lambda item: item.get("url"),
        )
        for url in row.get("official_urls") or []:
            if url and url not in group["official_urls"]:
                group["official_urls"].append(url)
    return list(groups.values())


def occurrence_songs(group, setlists):
    occurrence = setlists.get(group.get("occurrence_key") or "") or {}
    return [
        item.get("title") or ""
        for item in occurrence.get("setlist") or []
        if item.get("title")
    ]


def proposed_note(group, setlists):
    songs = occurrence_songs(group, setlists)
    lines = [
        "[youtube_evidence] YouTube実績証拠",
        f"- 対象イベント: {group['target_event_name']}",
        f"- 検出日付: {group.get('event_date') or ''}",
        f"- 動画数: {len(group['videos'])}",
    ]
    for video in group["videos"][:8]:
        lines.append(f"- 動画: {video['url']} / {video['channel']} / {video['title']}")
    if len(group["videos"]) > 8:
        lines.append(f"- 追加動画: {len(group['videos']) - 8}件")
    if group["official_urls"]:
        lines.append(f"- 関連URL: {', '.join(group['official_urls'][:5])}")
    lines.append(f"- 曲目候補: {', '.join(songs) if songs else '未抽出'}")
    return "\n".join(lines)


def has_event_level_youtube_evidence(existing_detail, event_name, event_date):
    if not existing_detail or "[youtube_evidence]" not in existing_detail:
        return False
    if event_name and f"- 対象イベント: {event_name}" not in existing_detail:
        return False
    if event_date and event_date not in existing_detail:
        return False
    return True


def row_status(page, existing_detail, note, videos, event_name="", event_date=""):
    if not page:
        return "blocked", ["Notionイベントページが見つかりません"], False
    if has_event_level_youtube_evidence(existing_detail, event_name, event_date):
        return "done", ["同じイベント日付のYouTube証拠が開催パターン詳細に既に含まれています"], False
    duplicate_urls = [video["url"] for video in videos if video.get("url") and video["url"] in existing_detail]
    if note in existing_detail or len(duplicate_urls) == len(videos):
        return "done", ["同じYouTube URLが開催パターン詳細に既に含まれています"], False
    warnings = []
    if duplicate_urls:
        warnings.append(f"一部のYouTube URLは既に含まれています: {len(duplicate_urls)}件")
    return ("review" if warnings else "ready"), warnings, True


def build_dry_run(api, review, setlists):
    rows = []
    for group in build_groups(review):
        page = find_event(api, group["target_event_name"])
        existing_detail = page_detail(page) if page else ""
        note = proposed_note(group, setlists)
        status, warnings, would_change_detail = row_status(
            page,
            existing_detail,
            note,
            group["videos"],
            event_name=group["target_event_name"],
            event_date=group.get("event_date") or "",
        )
        rows.append({
            "status": status,
            "target_event_name": group["target_event_name"],
            "target_page_id": page.get("id") if page else "",
            "target_page_url": page_url(page) if page else "",
            "event_date": group.get("event_date") or "",
            "occurrence_key": group.get("occurrence_key") or "",
            "video_count": len(group["videos"]),
            "videos": group["videos"],
            "official_urls": group["official_urls"],
            "song_count": len(occurrence_songs(group, setlists)),
            "songs": occurrence_songs(group, setlists),
            "warnings": warnings,
            "proposed_note": note,
            "would_change_detail": would_change_detail,
        })
    rows.sort(key=lambda row: (
        {"ready": 0, "review": 1, "blocked": 2, "done": 3}.get(row["status"], 9),
        row["target_event_name"],
        row["event_date"],
    ))
    return rows


def md_escape(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(output):
    lines = [
        "# YouTube active既存イベント追記 dry-run",
        "",
        f"- 生成: {output['generated_at']}",
        f"- 対象: {output['input_count']}件",
        f"- ready: {output['ready_count']}件",
        f"- review: {output['review_count']}件",
        f"- blocked: {output['blocked_count']}件",
        f"- done: {output['done_count']}件",
        "",
        "| status | イベント | 日付 | 動画 | 曲 | 変更 | 警告 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in output["rows"]:
        lines.append(
            "| "
            f"{md_escape(row['status'])} | "
            f"{md_escape(row['target_event_name'])} | "
            f"{md_escape(row['event_date'])} | "
            f"{row['video_count']} | "
            f"{row['song_count']} | "
            f"{'yes' if row['would_change_detail'] else 'no'} | "
            f"{md_escape('; '.join(row['warnings']))} |"
        )
    lines.append("")
    for row in output["rows"]:
        lines.extend([
            f"## {row['target_event_name']} ({row['status']})",
            "",
            f"- page: {row['target_page_url']}",
            f"- videos: {row['video_count']}",
            f"- songs: {', '.join(row['songs']) if row['songs'] else '未抽出'}",
            "",
            "```text",
            row["proposed_note"],
            "```",
            "",
        ])
    return "\n".join(lines)


def build_output(api, review, setlists):
    rows = build_dry_run(api, review, setlists)
    return {
        "generated_by": "dry_run_youtube_active_existing_event_updates.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(REVIEW),
        "setlist_source": str(YOUTUBE_SETLISTS),
        "input_count": len(rows),
        "ready_count": sum(1 for row in rows if row["status"] == "ready"),
        "review_count": sum(1 for row in rows if row["status"] == "review"),
        "blocked_count": sum(1 for row in rows if row["status"] == "blocked"),
        "done_count": sum(1 for row in rows if row["status"] == "done"),
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--markdown-out", type=Path, default=MARKDOWN_OUT)
    args = parser.parse_args()

    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    output = build_output(
        api,
        load_json(REVIEW, {}),
        setlist_by_occurrence_key(load_json(YOUTUBE_SETLISTS, {})),
    )
    atomic_write_json(args.out, output)
    atomic_write_text(args.markdown_out, render_markdown(output))
    print(
        "youtube active existing event dry-run: "
        f"ready={output['ready_count']} review={output['review_count']} "
        f"blocked={output['blocked_count']} done={output['done_count']} -> {args.out}"
    )


if __name__ == "__main__":
    main()
