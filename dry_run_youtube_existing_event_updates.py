#!/usr/bin/env python3
"""Build a dry-run proposal for appending YouTube evidence to existing events."""

import argparse
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from notion_support.notion_api import NotionApi, plain_text
from notion_config import EVENT_DATA_SOURCE_ID


PLAN = Path("data/youtube_event_update_plan.json")
PUBLIC_EVENTS = Path("data/public/events_public.json")
OUT = Path("data/youtube_existing_event_update_dry_run.json")
MARKDOWN_OUT = Path("data/youtube_existing_event_update_dry_run.md")


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


def find_event(api, name):
    rows = api.query_data_source(
        EVENT_DATA_SOURCE_ID,
        {"filter": {"property": "イベント名", "title": {"equals": name}}, "page_size": 5},
    )
    return rows[0] if rows else None


def page_detail(page):
    return plain_text((page.get("properties") or {}).get("開催パターン詳細"))


def page_url(page):
    return page.get("url") or f"https://www.notion.so/{page.get('id', '').replace('-', '')}"


def public_event_by_name(public_events, name):
    for event in public_events:
        if event.get("name") == name:
            return event
    return {}


def song_titles(row):
    titles = []
    seen = set()
    for song in row.get("songs") or []:
        title = song.get("title") or ""
        key = title.casefold()
        if not title or key in seen:
            continue
        seen.add(key)
        titles.append(title)
    return titles


def normalized_song_key(value):
    value = str(value or "").casefold()
    value = re.sub(r"[①②③④⑤⑥⑦⑧⑨⑩0-9０-９]+", "", value)
    value = re.sub(r"[^0-9a-z一-龥ぁ-んァ-ヶー]+", "", value)
    return value


def songs_covered_by_detail(row, existing_detail):
    titles = song_titles(row)
    if not titles or not existing_detail:
        return False
    detail_key = normalized_song_key(existing_detail)
    return all(normalized_song_key(title) in detail_key for title in titles)


def evidence_note(row):
    match = row.get("matched_public_event") or {}
    songs = song_titles(row)
    lines = [
        "[youtube_evidence] 2025実績証拠",
        f"- 対象イベント: {match.get('name') or ''}",
        f"- 検出日付: {row.get('youtube_event_date') or ''}",
        f"- 動画: {row.get('source_video_url') or ''}",
        f"- チャンネル: {row.get('source_channel_title') or ''}",
        f"- サムネイル: {row.get('thumbnail_url') or ''}",
        f"- 曲目候補: {', '.join(songs) if songs else '未抽出'}",
    ]
    return "\n".join(lines)


def detail_covers_date(detail, source_date):
    if not detail or not source_date:
        return False
    if source_date in detail:
        return True
    match = re.search(r"(20\d{2})-(\d{2})-(\d{2}).{0,12}[〜~](\d{1,2})", detail)
    if not match:
        return False
    year, month, start_day, end_day = match.groups()
    source_year, source_month, source_day = source_date.split("-")
    if source_year != year or source_month != month:
        return False
    return int(start_day) <= int(source_day) <= int(end_day)


def date_warning(row, public_event):
    match = row.get("matched_public_event") or {}
    source_date = row.get("youtube_event_date") or ""
    start = match.get("date") or ""
    end = match.get("date_end") or start
    if not source_date or not start:
        return ""
    if source_date[:4] < start[:4]:
        return ""
    if start <= source_date <= end:
        return ""
    if detail_covers_date(public_event.get("detail") or "", source_date):
        return "公開データのdate_endが空ですが、detail上はYouTube日付を含む複数日開催です"
    return f"YouTube日付 {source_date} が公開イベント日付 {start}〜{end} の範囲外です"


def row_warnings(row, page, existing_detail, public_event):
    warnings = []
    match = row.get("matched_public_event") or {}
    if not page:
        warnings.append("Notionイベントページが見つかりません")
    if (match.get("score") or 0) < 70:
        warnings.append(f"既存イベント照合スコアが低めです: {match.get('score')}")
    warning = date_warning(row, public_event)
    if warning:
        warnings.append(warning)
    url = row.get("source_video_url") or ""
    if url and url in (existing_detail or ""):
        warnings.append("同じYouTube URLが開催パターン詳細に既に含まれています")
    if len(song_titles(row)) <= 1 and not songs_covered_by_detail(row, existing_detail):
        warnings.append("曲目候補が1件以下です。セットリストとしては不完全な可能性があります")
    if len(song_titles(row)) <= 1 and songs_covered_by_detail(row, existing_detail):
        warnings.append("曲目候補は既存のYouTube証拠に含まれています")
    return warnings


def proposed_status(warnings, would_change_detail=True):
    blockers = {"Notionイベントページが見つかりません"}
    if any(warning in blockers for warning in warnings):
        return "blocked"
    done_warnings = {
        "同じYouTube URLが開催パターン詳細に既に含まれています",
        "曲目候補は既存のYouTube証拠に含まれています",
    }
    if (
        warnings
        and not would_change_detail
        and (
            "同じYouTube URLが開催パターン詳細に既に含まれています" in warnings
            or all(warning in done_warnings for warning in warnings)
        )
    ):
        return "done"
    if warnings:
        return "review"
    return "ready"


def build_dry_run(api, plan, public_events=None):
    public_events = public_events or []
    rows = []
    for row in plan.get("rows") or []:
        if row.get("action") != "append_evidence_to_existing_event":
            continue
        match = row.get("matched_public_event") or {}
        target_name = match.get("name") or ""
        public_event = public_event_by_name(public_events, target_name)
        page = find_event(api, target_name)
        existing_detail = page_detail(page) if page else ""
        note = evidence_note(row)
        warnings = row_warnings(row, page, existing_detail, public_event)
        duplicate_url = bool(row.get("source_video_url") and row.get("source_video_url") in existing_detail)
        covered_songs = songs_covered_by_detail(row, existing_detail)
        would_change_detail = bool(note and note not in existing_detail and not duplicate_url and not covered_songs)
        rows.append({
            "candidate_key": row.get("candidate_key") or "",
            "status": proposed_status(warnings, would_change_detail),
            "target_event_name": target_name,
            "target_page_id": page.get("id") if page else "",
            "target_page_url": page_url(page) if page else "",
            "matched_public_event": match,
            "public_event_detail": public_event.get("detail") or "",
            "youtube_event_date": row.get("youtube_event_date") or "",
            "source_video_url": row.get("source_video_url") or "",
            "source_video_title": row.get("source_video_title") or "",
            "source_channel_title": row.get("source_channel_title") or "",
            "thumbnail_url": row.get("thumbnail_url") or "",
            "song_count": len(song_titles(row)),
            "songs": row.get("songs") or [],
            "warnings": warnings,
            "proposed_note": note,
            "would_change_detail": would_change_detail,
        })
    return rows


def md_escape(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(output):
    lines = [
        "# YouTube既存イベント追記 dry-run",
        "",
        f"- 生成: {output['generated_at']}",
        f"- 対象: {output['input_count']}件",
        f"- ready: {output['ready_count']}件",
        f"- review: {output['review_count']}件",
        f"- blocked: {output['blocked_count']}件",
        f"- done: {output['done_count']}件",
        "",
        "| status | イベント | 日付 | 曲数 | 変更 | 警告 | 動画 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in output["rows"]:
        lines.append(
            "| "
            f"{md_escape(row['status'])} | "
            f"{md_escape(row['target_event_name'])} | "
            f"{md_escape(row['youtube_event_date'])} | "
            f"{row['song_count']} | "
            f"{'yes' if row['would_change_detail'] else 'no'} | "
            f"{md_escape('; '.join(row['warnings']))} | "
            f"{md_escape(row['source_video_url'])} |"
        )
    lines.append("")
    for row in output["rows"]:
        lines.extend([
            f"## {row['target_event_name']}",
            "",
            f"- status: {row['status']}",
            f"- Notion: {row['target_page_url']}",
            f"- video: {row['source_video_url']}",
            f"- channel: {row['source_channel_title']}",
            f"- thumbnail: {row['thumbnail_url']}",
            f"- warnings: {', '.join(row['warnings']) if row['warnings'] else 'なし'}",
            "",
            "```text",
            row["proposed_note"],
            "```",
            "",
        ])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=PLAN)
    parser.add_argument("--public-events", type=Path, default=PUBLIC_EVENTS)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--md-out", type=Path, default=MARKDOWN_OUT)
    args = parser.parse_args()

    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    plan = load_json(args.plan, {})
    rows = build_dry_run(api, plan, load_json(args.public_events, []))
    output = {
        "generated_by": "dry_run_youtube_existing_event_updates.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "dry_run",
        "source": str(args.plan),
        "public_event_source": str(args.public_events),
        "input_count": len(rows),
        "ready_count": sum(1 for row in rows if row["status"] == "ready"),
        "review_count": sum(1 for row in rows if row["status"] == "review"),
        "blocked_count": sum(1 for row in rows if row["status"] == "blocked"),
        "done_count": sum(1 for row in rows if row["status"] == "done"),
        "rows": rows,
    }
    atomic_write_json(args.out, output)
    atomic_write_text(args.md_out, render_markdown(output))
    print(
        "[youtube-existing-dry-run] "
        f"input={output['input_count']} ready={output['ready_count']} "
        f"review={output['review_count']} blocked={output['blocked_count']} "
        f"done={output['done_count']} "
        f"-> {args.out}, {args.md_out}"
    )


if __name__ == "__main__":
    main()
