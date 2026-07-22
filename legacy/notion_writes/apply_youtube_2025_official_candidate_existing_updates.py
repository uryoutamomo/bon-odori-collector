#!/usr/bin/env python3
"""Append validated YouTube 2025 official URL evidence to existing Notion events."""

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from manual_apply_guards import LEGACY_YOUTUBE_NOTION_CONFIRMATION, require_confirmation
from notion_support.notion_api import NotionApi, plain_text
from notion_config import load_local_env


VALIDATION = Path("data/youtube_2025_official_candidate_validation.json")
OUT = Path("data/youtube_2025_official_candidate_existing_apply_result.json")
MD_OUT = Path("data/youtube_2025_official_candidate_existing_apply_result.md")


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


def rich_text_prop(text):
    if not text:
        return {"rich_text": []}
    chunks = [text[i:i + 1900] for i in range(0, len(text), 1900)]
    return {"rich_text": [{"text": {"content": chunk}} for chunk in chunks[:100]]}


def current_detail(page):
    return plain_text((page.get("properties") or {}).get("開催パターン詳細"))


def ready_rows(validation, event_name=None):
    rows = []
    for row in validation.get("rows") or []:
        if row.get("status") != "existing_event_append_ready":
            continue
        match = (row.get("best_existing_matches") or [{}])[0]
        if not match.get("event_id"):
            continue
        if event_name and match.get("event_name") != event_name:
            continue
        rows.append(row)
    return rows


def evidence_note(row):
    match = (row.get("best_existing_matches") or [{}])[0]
    event_name = match.get("event_name") or ""
    dates = row.get("detected_dates") or []
    videos = row.get("videos") or []
    channels = []
    for video in videos:
        channel = video.get("channel_id") or ""
        if channel and channel not in channels:
            channels.append(channel)
    lines = [
        "[youtube_evidence] YouTube 2025公式URL確認済み証拠",
        f"- 対象イベント: {event_name}",
        f"- 検出日付: {', '.join(dates) if dates else '未抽出'}",
        f"- 動画数: {row.get('video_count') or len(videos)}",
        f"- 公式確認URL: {row.get('primary_url') or ''}",
    ]
    if channels:
        lines.append(f"- チャンネルID: {', '.join(channels[:8])}")
    for video in videos[:5]:
        lines.append(
            f"- 代表動画: {video.get('video_url') or ''} / "
            f"{video.get('detected_event_date') or ''} / {video.get('title') or ''}"
        )
    if len(videos) > 5:
        lines.append(f"- 追加動画: {len(videos) - 5}件（詳細はapply結果JSON）")
    return "\n".join(lines)


def has_existing_summary(detail, event_name, primary_url, dates):
    if not detail or "[youtube_evidence]" not in detail:
        return False
    marker = "[youtube_evidence] YouTube 2025公式URL確認済み証拠"
    if marker not in detail:
        return False
    if f"- 対象イベント: {event_name}" not in detail or "- 動画数:" not in detail:
        return False
    if primary_url and primary_url not in detail:
        return False
    return bool(dates) and all(date_value in detail for date_value in dates)


def merged_detail(existing, note):
    if not note:
        return existing or ""
    if note in (existing or ""):
        return existing or ""
    if existing:
        return existing.rstrip() + "\n\n" + note
    return note


def build_updates(api, validation, event_name=None):
    updates = []
    for row in ready_rows(validation, event_name=event_name):
        match = row["best_existing_matches"][0]
        page = api.retrieve_page(match["event_id"])
        old_detail = current_detail(page)
        note = evidence_note(row)
        event_name_value = match.get("event_name") or ""
        video_urls = [video.get("video_url") or "" for video in row.get("videos") or [] if video.get("video_url")]
        duplicate_urls = [url for url in video_urls if url in old_detail]
        all_urls_duplicate = bool(video_urls) and len(duplicate_urls) == len(video_urls)
        summary_present = has_existing_summary(
            old_detail,
            event_name_value,
            row.get("primary_url") or "",
            row.get("detected_dates") or [],
        )
        new_detail = old_detail if (all_urls_duplicate or summary_present) else merged_detail(old_detail, note)
        updates.append(
            {
                "target_event_name": event_name_value,
                "target_page_id": match["event_id"],
                "target_page_url": match.get("source_url") or "",
                "primary_url": row.get("primary_url") or "",
                "detected_dates": row.get("detected_dates") or [],
                "video_count": row.get("video_count") or 0,
                "duplicate_url_count": len(duplicate_urls),
                "all_urls_duplicate": all_urls_duplicate,
                "summary_present": summary_present,
                "changed": new_detail != old_detail,
                "note": note,
                "properties": {"開催パターン詳細": rich_text_prop(new_detail)},
            }
        )
    return updates


def md_escape(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(output):
    lines = [
        "# YouTube 2025 公式URL確認済み既存イベント追記 apply結果",
        "",
        f"- 生成: {output['generated_at']}",
        f"- mode: {output['mode']}",
        f"- ready: {output['ready_count']}",
        f"- changed: {output['changed_count']}",
        f"- applied: {output['applied_count']}",
        "",
        "| event | dates | videos | changed | duplicate_urls | summary_present |",
        "| --- | --- | ---: | --- | ---: | --- |",
    ]
    for row in output["updates"]:
        lines.append(
            f"| {md_escape(row['target_event_name'])} | {md_escape(', '.join(row['detected_dates']))} | "
            f"{row['video_count']} | {'yes' if row['changed'] else 'no'} | "
            f"{row['duplicate_url_count']} | {'yes' if row['summary_present'] else 'no'} |"
        )
    for row in output["updates"]:
        lines.extend(["", f"## {row['target_event_name']}", "", "```text", row["note"], "```"])
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--validation", type=Path, default=VALIDATION)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--markdown-out", type=Path, default=MD_OUT)
    parser.add_argument("--event-name")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        require_confirmation(
            args.apply,
            args.confirm,
            LEGACY_YOUTUBE_NOTION_CONFIRMATION,
            "legacy YouTube official-candidate Notion update",
        )
    except ValueError as exc:
        parser.error(str(exc))

    load_local_env()
    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    validation = load_json(args.validation, {})
    updates = build_updates(api, validation, event_name=args.event_name)
    applied = []
    if args.apply:
        for row in updates:
            if row.get("changed"):
                api.update_page(row["target_page_id"], row["properties"])
                applied.append(row["target_page_id"])

    output = {
        "generated_by": "apply_youtube_2025_official_candidate_existing_updates.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if args.apply else "dry_run",
        "apply_performed": bool(args.apply),
        "source": str(args.validation),
        "ready_count": len(updates),
        "changed_count": sum(1 for row in updates if row.get("changed")),
        "applied_count": len(applied),
        "updates": updates,
    }
    atomic_write_json(args.out, output)
    atomic_write_text(args.markdown_out, render_markdown(output))
    print(
        "youtube 2025 official candidate existing updates: "
        f"mode={output['mode']} ready={output['ready_count']} "
        f"changed={output['changed_count']} applied={output['applied_count']} -> {args.out}"
    )


if __name__ == "__main__":
    main()
