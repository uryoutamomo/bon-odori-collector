#!/usr/bin/env python3
"""Apply conservative YouTube 2025 date backfills to existing Notion events."""

import argparse
import json
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from operation_safety.manual_apply_guards import LEGACY_YOUTUBE_NOTION_CONFIRMATION, require_confirmation
from notion_api import NotionApi, plain_text
from notion_config import load_local_env


PLAN = Path("data/youtube_2025_date_backfill_plan.json")
OUT = Path("data/youtube_2025_date_backfill_apply_result.json")
MD_OUT = Path("data/youtube_2025_date_backfill_apply_result.md")
TODAY = date(2026, 6, 16)


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


def date_prop(start, end=None):
    if not start:
        return {"date": None}
    date_value = {"start": start}
    if end and end != start:
        date_value["end"] = end
    return {"date": date_value}


def select_prop(value):
    return {"select": {"name": value}} if value else {"select": None}


def event_status(date_value):
    if not date_value:
        return "要確認"
    y, m, d = [int(part) for part in date_value.split("-")]
    return "終了" if date(y, m, d) < TODAY else "確認済み"


def current_detail(page):
    return plain_text((page.get("properties") or {}).get("開催パターン詳細"))


def backfill_note(row):
    matches = row.get("source_check", {}).get("date_matches", {})
    matched = ", ".join(matches.get(row["proposed_date_range"]["start"], [])[:3])
    lines = [
        "[youtube_2025_date_backfill] 開催日補正",
        f"- 補正日: {row['proposed_date_range']['start']}",
        f"- 根拠URL: {row['source_check']['url']}",
        f"- URL内一致: {matched or '日付表記一致'}",
        f"- YouTube検出日付: {', '.join(row.get('detected_dates') or [])}",
        f"- 対象動画数: {row.get('video_count', 0)}",
    ]
    return "\n".join(lines)


def merged_detail(existing, note):
    if not note:
        return existing or ""
    if note in (existing or ""):
        return existing or ""
    if existing:
        return existing.rstrip() + "\n\n" + note
    return note


def ready_rows(plan):
    return [row for row in plan.get("rows") or [] if row.get("status") == "ready"]


def build_updates(api, plan):
    updates = []
    for row in ready_rows(plan):
        page = api.retrieve_page(row["target_page_id"])
        old_detail = current_detail(page)
        note = backfill_note(row)
        new_detail = merged_detail(old_detail, note)
        start = row["proposed_date_range"]["start"]
        end = row["proposed_date_range"].get("end") or start
        props = {
            "開催日": date_prop(start, end),
            "状態": select_prop(event_status(start)),
            "開催パターン詳細": rich_text_prop(new_detail),
        }
        updates.append(
            {
                "target_event_name": row["target_event_name"],
                "target_page_id": row["target_page_id"],
                "target_page_url": row.get("target_page_url") or "",
                "old_date_range": row["current_date_range"],
                "new_date_range": row["proposed_date_range"],
                "video_count": row.get("video_count", 0),
                "source_url": row["source_check"]["url"],
                "changed": True,
                "note": note,
                "properties": props,
            }
        )
    return updates


def md_escape(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(output):
    lines = [
        "# YouTube 2025 日付補正 apply結果",
        "",
        f"- 生成: {output['generated_at']}",
        f"- mode: {output['mode']}",
        f"- ready: {output['ready_count']}",
        f"- applied: {output['applied_count']}",
        "",
        "| event | date | videos | source |",
        "| --- | --- | ---: | --- |",
    ]
    for row in output["updates"]:
        lines.append(
            f"| {md_escape(row['target_event_name'])} | "
            f"{md_escape(row['new_date_range']['start'])} | "
            f"{row['video_count']} | {md_escape(row['source_url'])} |"
        )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=PLAN)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--markdown-out", type=Path, default=MD_OUT)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        require_confirmation(
            args.apply,
            args.confirm,
            LEGACY_YOUTUBE_NOTION_CONFIRMATION,
            "legacy YouTube 2025 date backfill Notion update",
        )
    except ValueError as exc:
        parser.error(str(exc))

    load_local_env()
    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    plan = load_json(args.plan, {})
    updates = build_updates(api, plan)
    applied = []
    if args.apply:
        for row in updates:
            api.update_page(row["target_page_id"], row["properties"])
            applied.append(row["target_page_id"])
    output = {
        "generated_by": "apply_youtube_2025_date_backfill.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if args.apply else "dry_run",
        "apply_performed": bool(args.apply),
        "source": str(args.plan),
        "ready_count": len(updates),
        "applied_count": len(applied),
        "updates": updates,
    }
    atomic_write_json(args.out, output)
    atomic_write_text(args.markdown_out, render_markdown(output))
    print(
        "youtube 2025 date backfill: "
        f"mode={output['mode']} ready={output['ready_count']} "
        f"applied={output['applied_count']} -> {args.out}"
    )


if __name__ == "__main__":
    main()
