#!/usr/bin/env python3
"""Sync machine-readable fixed-date rules into the Notion event DB.

Default mode is a dry run. Use --apply to update pages, and --ensure-schema
with --apply to add the fixed-date columns when they are missing.
"""

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from notion_support.notion_api import NotionApi, plain_text
from notion_config import EVENT_DATA_SOURCE_ID, load_local_env
from manual_apply_guards import require_confirmation


RULES = Path("data/public_fixed_date_rules.json")
OUT_JSON = Path("data/fixed_date_rule_notion_sync_plan.json")
OUT_MD = Path("data/fixed_date_rule_notion_sync_plan.md")
CONFIRM_PHRASE = "APPLY FIXED DATE RULES TO NOTION"

FIXED_DATE_SCHEMA = {
    "固定日開始月": {"number": {}},
    "固定日開始日": {"number": {}},
    "固定日終了月": {"number": {}},
    "固定日終了日": {"number": {}},
    "固定日根拠URL": {"url": {}},
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


def normalize(value):
    return "".join(str(value or "").split()).casefold()


def rich_text_prop(text):
    if not text:
        return {"rich_text": []}
    chunks = [text[i:i + 1900] for i in range(0, len(text), 1900)]
    return {"rich_text": [{"text": {"content": chunk}} for chunk in chunks[:100]]}


def current_detail(page):
    return plain_text((page.get("properties") or {}).get("開催パターン詳細"))


def title(page):
    return plain_text((page.get("properties") or {}).get("イベント名"))


def expected_type(prop_definition):
    return next(iter(prop_definition.keys()))


def schema_plan(api):
    data_source = api.retrieve_data_source(EVENT_DATA_SOURCE_ID)
    actual = data_source.get("properties") or {}
    missing = {}
    wrong_type = []
    for name, definition in FIXED_DATE_SCHEMA.items():
        current = actual.get(name)
        if not current:
            missing[name] = definition
            continue
        expected = expected_type(definition)
        if current.get("type") != expected:
            wrong_type.append({
                "property": name,
                "expected": expected,
                "actual": current.get("type"),
            })
    return {
        "missing_properties": missing,
        "wrong_type": wrong_type,
        "property_count": len(actual),
    }


def append_fixed_date_note(existing, rule):
    if "[fixed_date_rule]" in (existing or ""):
        return existing or ""
    date_label = f"{rule['month']}/{rule['day']}"
    end_month = rule.get("end_month") or rule["month"]
    end_day = rule.get("end_day") or rule["day"]
    if (end_month, end_day) != (rule["month"], rule["day"]):
        date_label = f"{date_label}〜{end_month}/{end_day}"
    lines = [
        "[fixed_date_rule] おと（Codex）固定日ルール記録",
        f"- 固定日: 毎年{date_label}",
        f"- 根拠: {rule.get('basis') or ''}",
    ]
    if rule.get("source_url"):
        lines.append(f"- 根拠URL: {rule['source_url']}")
    note = "\n".join(lines)
    if existing:
        return existing.rstrip() + "\n\n" + note
    return note


def properties_for_rule(rule, existing_detail):
    end_month = rule.get("end_month") or rule["month"]
    end_day = rule.get("end_day") or rule["day"]
    return {
        "開催パターン種別": {"select": {"name": "固定日"}},
        "固定日開始月": {"number": int(rule["month"])},
        "固定日開始日": {"number": int(rule["day"])},
        "固定日終了月": {"number": int(end_month)},
        "固定日終了日": {"number": int(end_day)},
        "固定日根拠URL": {"url": rule.get("source_url") or None},
        "開催パターン詳細": rich_text_prop(append_fixed_date_note(existing_detail, rule)),
    }


def build_event_index(rows):
    index = {}
    for page in rows:
        event_name = title(page)
        if event_name:
            index.setdefault(normalize(event_name), []).append(page)
    return index


def build_updates(api, rules):
    rows = api.query_data_source(EVENT_DATA_SOURCE_ID)
    index = build_event_index(rows)
    updates = []
    for rule in rules:
        matches = index.get(normalize(rule.get("name"))) or []
        if not matches:
            updates.append({
                "rule_name": rule.get("name"),
                "venue": rule.get("venue"),
                "status": "missing_event_page",
                "matches": 0,
            })
            continue
        if len(matches) > 1:
            updates.append({
                "rule_name": rule.get("name"),
                "venue": rule.get("venue"),
                "status": "ambiguous_event_name",
                "matches": len(matches),
                "page_ids": [page.get("id") for page in matches],
            })
            continue
        page = matches[0]
        detail = current_detail(page)
        properties = properties_for_rule(rule, detail)
        updates.append({
            "rule_name": rule.get("name"),
            "venue": rule.get("venue"),
            "status": "ready",
            "matches": 1,
            "page_id": page.get("id"),
            "page_url": page.get("url") or "",
            "changed": properties.get("開催パターン詳細") != rich_text_prop(detail),
            "fixed_date": {
                "month": int(rule["month"]),
                "day": int(rule["day"]),
                "end_month": int(rule.get("end_month") or rule["month"]),
                "end_day": int(rule.get("end_day") or rule["day"]),
                "source_url": rule.get("source_url") or "",
            },
            "properties": properties,
        })
    return updates


def md_escape(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(output):
    lines = [
        "# 固定日ルール Notion同期計画",
        "",
        f"- 生成: {output['generated_at']}",
        f"- mode: {output['mode']}",
        f"- schema missing: {len(output['schema']['missing_properties'])}件",
        f"- ready: {output['ready_count']}件",
        f"- applied: {output['applied_count']}件",
        "",
        "| status | イベント | 会場 | 固定日 | page |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in output["updates"]:
        fixed = row.get("fixed_date") or {}
        date_label = ""
        if fixed:
            date_label = f"{fixed['month']}/{fixed['day']}〜{fixed['end_month']}/{fixed['end_day']}"
        lines.append(
            "| "
            f"{row['status']} | "
            f"{md_escape(row.get('rule_name'))} | "
            f"{md_escape(row.get('venue'))} | "
            f"{date_label} | "
            f"{row.get('page_url') or ''} |"
        )
    if output["schema"]["wrong_type"]:
        lines.extend(["", "## schema type mismatch", ""])
        for row in output["schema"]["wrong_type"]:
            lines.append(
                f"- {row['property']}: expected {row['expected']}, actual {row['actual']}"
            )
    lines.append("")
    return "\n".join(lines)


def main():
    load_local_env()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rules", default=str(RULES))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--ensure-schema", action="store_true")
    args = parser.parse_args()
    try:
        require_confirmation(args.apply, args.confirm, CONFIRM_PHRASE, "fixed-date Notion sync")
    except ValueError as exc:
        parser.error(str(exc))

    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    rules = load_json(args.rules, {}).get("rules") or []
    schema = schema_plan(api)
    if schema["wrong_type"]:
        raise SystemExit("Notion fixed-date schema has type mismatches; resolve manually first.")

    mode = "apply" if args.apply else "dry_run"
    schema_applied = False
    if args.apply and args.ensure_schema and schema["missing_properties"]:
        api.update_data_source(
            EVENT_DATA_SOURCE_ID,
            {"properties": schema["missing_properties"]},
        )
        schema_applied = True
        schema = schema_plan(api)

    updates = build_updates(api, rules)
    applied_count = 0
    if args.apply:
        for row in updates:
            if row.get("status") != "ready":
                continue
            api.update_page(row["page_id"], row["properties"])
            row["status"] = "applied"
            applied_count += 1

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "data_source_id": EVENT_DATA_SOURCE_ID,
        "schema_applied": schema_applied,
        "schema": schema,
        "rule_count": len(rules),
        "ready_count": sum(1 for row in updates if row.get("status") in {"ready", "applied"}),
        "applied_count": applied_count,
        "updates": updates,
    }
    atomic_write_json(OUT_JSON, output)
    atomic_write_text(OUT_MD, render_markdown(output))
    print(json.dumps({
        "mode": mode,
        "schema_applied": schema_applied,
        "ready_count": output["ready_count"],
        "applied_count": applied_count,
        "out_json": str(OUT_JSON),
        "out_md": str(OUT_MD),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
