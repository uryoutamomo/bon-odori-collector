#!/usr/bin/env python3
"""Apply ready YouTube evidence notes from the existing-event dry-run."""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from operation_safety.manual_apply_guards import LEGACY_YOUTUBE_NOTION_CONFIRMATION, require_confirmation
from notion_api import NotionApi, plain_text


PLAN = Path("data/youtube_existing_event_update_dry_run.json")
OUT = Path("data/youtube_existing_event_update_apply_result.json")


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def text_prop(text):
    return {"rich_text": [{"text": {"content": text[:1900]}}]} if text else {"rich_text": []}


def current_detail(page):
    props = page.get("properties", {})
    return plain_text(props.get("開催パターン詳細"))


def merged_detail(existing, note):
    if not note:
        return existing or ""
    if note in (existing or ""):
        return existing or ""
    if existing:
        return existing.rstrip() + "\n\n" + note
    return note


def should_include(row, event_name=None):
    if event_name and row.get("target_event_name") != event_name:
        return False
    return True


def build_updates(api, plan, event_name=None):
    rows = []
    for row in plan.get("rows") or []:
        if not should_include(row, event_name=event_name):
            continue
        result = {
            "candidate_key": row.get("candidate_key") or "",
            "target_event_name": row.get("target_event_name") or "",
            "target_page_id": row.get("target_page_id") or "",
            "source_video_url": row.get("source_video_url") or "",
            "status": row.get("status") or "",
        }
        if row.get("status") != "ready":
            result["apply_status"] = "skipped"
            result["reason"] = "dry-run row is not ready"
            rows.append(result)
            continue
        page_id = row.get("target_page_id") or ""
        if not page_id:
            result["apply_status"] = "blocked"
            result["reason"] = "missing target_page_id"
            rows.append(result)
            continue
        page = api.retrieve_page(page_id)
        old_detail = current_detail(page)
        note = row.get("proposed_note") or ""
        url = row.get("source_video_url") or ""
        duplicate_url = bool(url and url in old_detail)
        new_detail = old_detail if duplicate_url else merged_detail(old_detail, note)
        result.update({
            "apply_status": "ready",
            "changed": new_detail != old_detail,
            "duplicate_url": duplicate_url,
            "properties": {
                "開催パターン詳細": text_prop(new_detail),
            },
            "note": note,
        })
        rows.append(result)
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=PLAN)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--event-name", help="Only apply rows for this exact event name.")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        require_confirmation(
            args.apply,
            args.confirm,
            LEGACY_YOUTUBE_NOTION_CONFIRMATION,
            "legacy YouTube existing-event Notion update",
        )
    except ValueError as exc:
        parser.error(str(exc))

    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    plan = load_json(args.plan, {})
    rows = build_updates(api, plan, event_name=args.event_name)
    applied = []
    if args.apply:
        for row in rows:
            if row.get("apply_status") == "ready" and row.get("changed"):
                api.update_page(row["target_page_id"], row["properties"])
                applied.append(row["target_page_id"])
    output = {
        "generated_by": "apply_youtube_existing_event_updates.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if args.apply else "dry_run",
        "apply_performed": bool(args.apply),
        "input_count": len(rows),
        "ready_count": sum(1 for row in rows if row.get("apply_status") == "ready"),
        "changed_count": sum(1 for row in rows if row.get("changed")),
        "applied_count": len(applied),
        "rows": rows,
    }
    write_json(args.out, output)
    print(
        "youtube existing event updates: "
        f"mode={output['mode']} ready={output['ready_count']} "
        f"changed={output['changed_count']} applied={output['applied_count']} -> {args.out}"
    )


if __name__ == "__main__":
    main()
