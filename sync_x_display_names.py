"""Backfill Notion X member display names from collected X posts."""

import argparse
import json
import os
from pathlib import Path


def load_env():
    try:
        for line in Path(".env").read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                os.environ.setdefault(key, value)
    except FileNotFoundError:
        pass


load_env()
import collect  # noqa: E402


VOICES_FILE = Path("data/voices.json")
OUTPUT_FILE = Path("data/x_display_name_updates.json")


def load_latest_names():
    latest = {}
    try:
        voices = json.loads(VOICES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return latest
    for voice in voices:
        if voice.get("source") not in ("x", "x_whitelist", "x_proactive"):
            continue
        handle = collect._norm_handle(voice.get("account"))
        name = " ".join((voice.get("name") or "").split()).strip()
        date = voice.get("date") or ""
        if not handle or not name or name.startswith("@"):
            continue
        current = latest.get(handle)
        if not current or date > current["date"]:
            latest[handle] = {"name": name[:200], "date": date}
    return latest


def fetch_members():
    rows = []
    cursor = None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        data = collect._notion_query_database(collect.X_MEMBER_LIST_DB_ID, payload)
        for page in data.get("results", []):
            props = page.get("properties", {})
            handle = collect._x_member_handle_from_props(props)
            if not handle:
                continue
            rows.append({
                "page_id": page.get("id", ""),
                "handle": handle,
                "display_name": collect._prop_plain(props.get("表示名", {})),
            })
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return rows


def should_update_display_name(handle, current_display):
    current = (current_display or "").strip()
    if not current:
        return True
    return collect._norm_handle(current) == collect._norm_handle(handle)


def build_updates(members, latest_names):
    updates = []
    for row in members:
        handle = collect._norm_handle(row.get("handle"))
        latest = latest_names.get(handle)
        if not latest:
            continue
        current = row.get("display_name") or ""
        if not should_update_display_name(handle, current):
            continue
        if current == latest["name"]:
            continue
        updates.append({
            "page_id": row["page_id"],
            "handle": f"@{handle}",
            "current_display_name": current,
            "new_display_name": latest["name"],
            "source_date": latest["date"],
        })
    return updates


def write_updates(updates):
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps({
        "count": len(updates),
        "updates": updates,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_updates(updates):
    updated = 0
    for row in updates:
        collect._update_page_props_best_effort(row["page_id"], {
            "表示名": {
                "title": [{"text": {"content": row["new_display_name"][:200]}}]
            }
        })
        updated += 1
    return updated


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    latest_names = load_latest_names()
    members = fetch_members()
    updates = build_updates(members, latest_names)
    write_updates(updates)
    print(f"[display-name] candidates: {len(updates)} -> {OUTPUT_FILE}")
    for row in updates[:20]:
        print(
            f"[display-name] {row['handle']}: "
            f"{row['current_display_name']!r} -> {row['new_display_name']!r}"
        )
    if args.apply:
        print(f"[display-name] Notion updated: {apply_updates(updates)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
