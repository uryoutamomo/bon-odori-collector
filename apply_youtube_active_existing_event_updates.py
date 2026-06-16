#!/usr/bin/env python3
"""Apply or dry-run active YouTube evidence notes onto existing Notion events."""

import argparse
import json
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from notion_api import NotionApi, plain_text
from notion_config import load_local_env


PLAN = Path("data/youtube_active_existing_event_update_dry_run.json")
OUT = Path("data/youtube_active_existing_event_update_apply_result.json")
MARKDOWN_OUT = Path("data/youtube_active_existing_event_update_apply_result.md")


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


def merge_unique(values):
    out = []
    for value in values:
        if value and value not in out:
            out.append(value)
    return out


def video_key(video):
    return video.get("url") or ""


def ready_rows(plan, event_name=None):
    rows = []
    for row in plan.get("rows") or []:
        if row.get("status") != "ready":
            continue
        if event_name and row.get("target_event_name") != event_name:
            continue
        rows.append(row)
    return rows


def rows_by_event(plan, event_name=None):
    grouped = defaultdict(list)
    for row in ready_rows(plan, event_name=event_name):
        key = (row.get("target_event_name") or "", row.get("target_page_id") or "")
        if key[0] and key[1]:
            grouped[key].append(row)
    return grouped


def event_summary_note(event_name, rows):
    videos = []
    official_urls = []
    songs = []
    dates = []
    channels = []
    for row in rows:
        if row.get("event_date"):
            dates.append(row["event_date"])
        official_urls.extend(row.get("official_urls") or [])
        songs.extend(row.get("songs") or [])
        for video in row.get("videos") or []:
            if video_key(video) and all(video_key(existing) != video_key(video) for existing in videos):
                videos.append(video)
            if video.get("channel"):
                channels.append(video["channel"])

    dates = merge_unique(sorted(dates))
    official_urls = merge_unique(official_urls)
    songs = merge_unique(songs)
    channels = merge_unique(channels)
    representative = videos[:5]

    lines = [
        "[youtube_evidence] YouTube実績証拠",
        f"- 対象イベント: {event_name}",
        f"- 検出日付: {', '.join(dates) if dates else '未抽出'}",
        f"- 動画数: {len(videos)}",
    ]
    if channels:
        lines.append(f"- チャンネル: {', '.join(channels[:8])}")
    for video in representative:
        lines.append(f"- 代表動画: {video['url']} / {video.get('channel', '')} / {video.get('title', '')}")
    if len(videos) > len(representative):
        lines.append(
            f"- 追加動画: {len(videos) - len(representative)}件 "
            "(詳細はapply結果JSON)"
        )
    if official_urls:
        lines.append(f"- 関連URL: {', '.join(official_urls[:5])}")
    lines.append(f"- 曲目候補: {', '.join(songs) if songs else '未抽出'}")
    return "\n".join(lines), videos, songs


def merged_detail(existing, note):
    if not note:
        return existing or ""
    if note in (existing or ""):
        return existing or ""
    if existing:
        return existing.rstrip() + "\n\n" + note
    return note


def has_existing_youtube_summary(detail, event_name):
    if not detail or "[youtube_evidence]" not in detail:
        return False
    if event_name and f"- 対象イベント: {event_name}" not in detail:
        return False
    return "- 動画数:" in detail or "- 追加動画:" in detail


def build_updates(api, plan, event_name=None):
    updates = []
    for (target_event_name, page_id), rows in sorted(rows_by_event(plan, event_name=event_name).items()):
        page = api.retrieve_page(page_id)
        old_detail = current_detail(page)
        note, videos, songs = event_summary_note(target_event_name, rows)
        urls = [video_key(video) for video in videos if video_key(video)]
        duplicate_urls = [url for url in urls if url in old_detail]
        all_urls_duplicate = bool(urls) and len(duplicate_urls) == len(urls)
        summary_present = has_existing_youtube_summary(old_detail, target_event_name)
        new_detail = old_detail if (all_urls_duplicate or summary_present) else merged_detail(old_detail, note)
        updates.append({
            "target_event_name": target_event_name,
            "target_page_id": page_id,
            "target_page_url": rows[0].get("target_page_url") or "",
            "input_rows": len(rows),
            "video_count": len(videos),
            "song_count": len(songs),
            "dates": merge_unique(sorted(row.get("event_date") or "" for row in rows)),
            "duplicate_url_count": len(duplicate_urls),
            "all_urls_duplicate": all_urls_duplicate,
            "summary_present": summary_present,
            "apply_status": "ready",
            "changed": new_detail != old_detail,
            "note": note,
            "properties": {"開催パターン詳細": rich_text_prop(new_detail)},
        })
    return updates


def skipped_rows(plan, event_name=None):
    rows = []
    for row in plan.get("rows") or []:
        if event_name and row.get("target_event_name") != event_name:
            continue
        if row.get("status") == "ready":
            continue
        rows.append({
            "target_event_name": row.get("target_event_name") or "",
            "target_page_id": row.get("target_page_id") or "",
            "status": row.get("status") or "",
            "reason": "; ".join(row.get("warnings") or []) or "dry-run row is not ready",
            "video_count": row.get("video_count") or 0,
            "song_count": row.get("song_count") or 0,
        })
    return rows


def md_escape(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(output):
    lines = [
        "# YouTube active既存イベント追記 apply計画",
        "",
        f"- 生成: {output['generated_at']}",
        f"- mode: {output['mode']}",
        f"- ready updates: {output['ready_count']}件",
        f"- changed: {output['changed_count']}件",
        f"- applied: {output['applied_count']}件",
        f"- skipped: {output['skipped_count']}件",
        "",
        "| status | イベント | 入力 | 動画 | 曲 | 変更 | 重複URL |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in output["updates"]:
        lines.append(
            "| "
            f"{row['apply_status']} | "
            f"{md_escape(row['target_event_name'])} | "
            f"{row['input_rows']} | "
            f"{row['video_count']} | "
            f"{row['song_count']} | "
            f"{'yes' if row['changed'] else 'no'} | "
            f"{row['duplicate_url_count']} |"
        )
    if output["skipped"]:
        lines.extend(["", "## skipped", ""])
        for row in output["skipped"]:
            lines.append(
                f"- {row['status']}: {row['target_event_name']} "
                f"(videos={row['video_count']}, songs={row['song_count']}) {row['reason']}"
            )
    for row in output["updates"]:
        lines.extend([
            "",
            f"## {row['target_event_name']}",
            "",
            f"- page: {row['target_page_url']}",
            "",
            "```text",
            row["note"],
            "```",
        ])
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=PLAN)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--markdown-out", type=Path, default=MARKDOWN_OUT)
    parser.add_argument("--event-name", help="Only apply rows for this exact event name.")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    load_local_env()
    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    plan = load_json(args.plan, {})
    updates = build_updates(api, plan, event_name=args.event_name)
    applied = []
    if args.apply:
        for row in updates:
            if row.get("apply_status") == "ready" and row.get("changed"):
                api.update_page(row["target_page_id"], row["properties"])
                applied.append(row["target_page_id"])

    output = {
        "generated_by": "apply_youtube_active_existing_event_updates.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if args.apply else "dry_run",
        "apply_performed": bool(args.apply),
        "source": str(args.plan),
        "ready_count": len(updates),
        "changed_count": sum(1 for row in updates if row.get("changed")),
        "applied_count": len(applied),
        "skipped_count": len(skipped_rows(plan, event_name=args.event_name)),
        "updates": updates,
        "skipped": skipped_rows(plan, event_name=args.event_name),
    }
    atomic_write_json(args.out, output)
    atomic_write_text(args.markdown_out, render_markdown(output))
    print(
        "youtube active existing event updates: "
        f"mode={output['mode']} ready={output['ready_count']} "
        f"changed={output['changed_count']} applied={output['applied_count']} "
        f"skipped={output['skipped_count']} -> {args.out}"
    )


if __name__ == "__main__":
    main()
