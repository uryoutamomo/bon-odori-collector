#!/usr/bin/env python3
"""Apply or dry-run retrospective evidence notes onto existing Notion events."""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from manual_apply_guards import LEGACY_YOUTUBE_NOTION_CONFIRMATION, require_confirmation
from notion_support.notion_api import NotionApi, plain_text
from notion_config import EVENT_DATA_SOURCE_ID


PLAN = Path("data/retrospective_existing_event_update_plan.json")
OUT = Path("data/retrospective_existing_event_update_apply_result.json")


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


def find_event(api, name):
    if not name:
        return None
    rows = api.query_data_source(
        EVENT_DATA_SOURCE_ID,
        {"filter": {"property": "イベント名", "title": {"equals": name}}, "page_size": 5},
    )
    return rows[0] if rows else None


def current_detail(page):
    props = page.get("properties", {})
    return plain_text(props.get("開催パターン詳細"))


def evidence_note(row):
    urls = []
    for ev in row.get("evidence") or []:
        url = ev.get("url")
        if url and url not in urls:
            urls.append(url)
    alias = row.get("candidate_event_name") or ""
    date = row.get("candidate_date") or ""
    lines = [
        "[retrospective_harvest] 追加証拠",
        f"- 検出名: {alias}",
    ]
    if date:
        lines.append(f"- 検出日付: {date}")
    for url in urls[:3]:
        lines.append(f"- 出典: {url}")
    return "\n".join(lines)


def merged_detail(existing, note):
    if note in (existing or ""):
        return existing or ""
    if existing:
        return existing.rstrip() + "\n\n" + note
    return note


def build_updates(api, plan):
    rows = []
    for row in plan.get("rows") or []:
        if row.get("action") != "append_evidence_to_existing":
            rows.append({
                "candidate_event_name": row.get("candidate_event_name"),
                "action": row.get("action"),
                "status": "skipped",
                "reason": "manual review required",
            })
            continue
        target_name = row.get("target_event_name") or ""
        page = find_event(api, target_name)
        if not page:
            rows.append({
                "candidate_event_name": row.get("candidate_event_name"),
                "target_event_name": target_name,
                "action": row.get("action"),
                "status": "not_found",
                "reason": "target event title not found in Notion",
            })
            continue
        note = evidence_note(row)
        old_detail = current_detail(page)
        new_detail = merged_detail(old_detail, note)
        rows.append({
            "candidate_event_name": row.get("candidate_event_name"),
            "target_event_name": target_name,
            "target_page_id": page.get("id"),
            "action": row.get("action"),
            "status": "ready",
            "changed": new_detail != old_detail,
            "properties": {
                "開催パターン詳細": text_prop(new_detail),
            },
            "note": note,
        })
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=PLAN)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        require_confirmation(
            args.apply,
            args.confirm,
            LEGACY_YOUTUBE_NOTION_CONFIRMATION,
            "legacy retrospective existing-event Notion update",
        )
    except ValueError as exc:
        parser.error(str(exc))

    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    plan = load_json(args.plan, {})
    rows = build_updates(api, plan)
    applied = []
    if args.apply:
        for row in rows:
            if row.get("status") == "ready" and row.get("changed"):
                api.update_page(row["target_page_id"], row["properties"])
                applied.append(row["target_page_id"])
    output = {
        "generated_by": "apply_retrospective_existing_event_updates.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if args.apply else "dry_run",
        "apply_performed": bool(args.apply),
        "input_count": len(plan.get("rows") or []),
        "ready_count": sum(1 for row in rows if row.get("status") == "ready"),
        "changed_count": sum(1 for row in rows if row.get("changed")),
        "applied_count": len(applied),
        "rows": rows,
    }
    write_json(args.out, output)
    print(
        "retrospective existing event updates: "
        f"mode={output['mode']} ready={output['ready_count']} "
        f"changed={output['changed_count']} applied={output['applied_count']} -> {args.out}"
    )


if __name__ == "__main__":
    main()
