#!/usr/bin/env python3
"""Apply strong retrospective X-derived song candidates to Notion song master."""

import argparse
import json
import os
from pathlib import Path

from manual_apply_guards import LEGACY_NOTION_REPAIR_CONFIRMATION, require_confirmation
from notion_support.notion_config import (
    EVENT_DATABASE_ID,
    SONG_MASTER_DATABASE_ID,
    VENUE_DATABASE_ID,
    load_local_env,
)
from register_song_master_initial import classify_song
from triage_weekly_song_candidates import (
    matched_page_ids,
    norm,
    notion_request,
    rich_text,
    title_index,
)


load_local_env()

TOKEN = os.environ.get("NOTION_API_TOKEN")
SONG_DB_ID = os.environ.get("SONG_MASTER_DB_ID") or SONG_MASTER_DATABASE_ID
SOURCE = Path("data/retrospective_song_triage.json")
OUT = Path("data/retrospective_song_apply_result.json")


def load_json(path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def relation_ids(prop):
    if not prop or prop.get("type") != "relation":
        return []
    return [item["id"] for item in prop.get("relation", [])]


def number_value(prop):
    return prop.get("number") if prop and prop.get("type") == "number" else None


def song_props(row, venue_ids, event_ids, existing_page=None):
    props = existing_page.get("properties", {}) if existing_page else {}
    current_venues = relation_ids(props.get("会場", {}))
    current_events = relation_ids(props.get("イベント", {}))
    current_evidence = number_value(props.get("証拠数", {})) or 0
    evidence_count = max(int(current_evidence), int(row.get("evidence_count") or 0))
    memo = (
        "過去年X収穫候補からおと判断で強い曲候補として処理。\n"
        f"元候補: {row.get('raw_name', '')}\n"
        f"正規曲名: {row.get('canonical_song_name', '')}\n"
        f"理由: {row.get('reason', '')}\n"
        f"候補スコア: {row.get('score', '')}\n"
        f"証拠数: {row.get('evidence_count', '')}\n"
        f"証拠抜粋: {row.get('evidence_sample', '')[:900]}"
    )
    out = {
        "分類": {"select": {"name": classify_song(row["canonical_song_name"])}},
        "状態": {"select": {"name": "有効"}},
        "証拠数": {"number": evidence_count},
        "メモ": {"rich_text": rich_text(memo)},
    }
    if not existing_page:
        out["曲名"] = {"title": rich_text(row["canonical_song_name"][:200])}
    merged_venues = [{"id": page_id} for page_id in sorted(set(current_venues + venue_ids))]
    merged_events = [{"id": page_id} for page_id in sorted(set(current_events + event_ids))]
    if merged_venues:
        out["会場"] = {"relation": merged_venues}
    if merged_events:
        out["イベント"] = {"relation": merged_events}
    return out


def strong_rows(data):
    return [row for row in data.get("rows", []) if row.get("bucket") == "new_song_candidate"]


def apply_rows(rows, dry_run=False):
    songs = title_index(SONG_DB_ID)
    venues = title_index(VENUE_DATABASE_ID)
    events = title_index(EVENT_DATABASE_ID)
    created = []
    updated = []
    for row in rows:
        song_name = row["canonical_song_name"]
        key = norm(song_name)
        evidence_text = row.get("evidence_sample") or ""
        venue_ids = matched_page_ids(evidence_text, venues)
        event_ids = matched_page_ids(evidence_text, events)
        existing = songs.get(key)
        if dry_run:
            target = "update" if existing else "create"
            (updated if existing else created).append(
                {
                    "song_name": song_name,
                    "source_term": row.get("raw_name", ""),
                    "target": target,
                    "venue_relations": len(venue_ids),
                    "event_relations": len(event_ids),
                    "dry_run": True,
                }
            )
            continue
        if existing:
            notion_request(
                "PATCH",
                f"/pages/{existing['id']}",
                {"properties": song_props(row, venue_ids, event_ids, existing["page"])},
            )
            updated.append({"song_name": song_name, "source_term": row.get("raw_name", ""), "page_id": existing["id"]})
        else:
            page = notion_request(
                "POST",
                "/pages",
                {
                    "parent": {"database_id": SONG_DB_ID},
                    "properties": song_props(row, venue_ids, event_ids),
                },
            )
            created.append({"song_name": song_name, "source_term": row.get("raw_name", ""), "page_id": page["id"]})
            songs[key] = {"id": page["id"], "name": song_name, "page": page}
    return created, updated


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        require_confirmation(
            not args.dry_run,
            args.confirm,
            LEGACY_NOTION_REPAIR_CONFIRMATION,
            "legacy retrospective song Notion repair",
        )
    except ValueError as exc:
        parser.error(str(exc))

    if not TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    if not SONG_DB_ID:
        raise SystemExit("SONG_MASTER_DB_ID is not set")

    data = load_json(args.source)
    rows = strong_rows(data)
    created, updated = apply_rows(rows, args.dry_run)
    result = {
        "dry_run": args.dry_run,
        "source": str(args.source),
        "strong_candidate_count": len(rows),
        "created_count": len(created),
        "updated_count": len(updated),
        "created": created,
        "updated": updated,
    }
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "done: strong={strong_candidate_count} created={created_count} "
        "updated={updated_count} dry_run={dry_run}".format(**result)
    )
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
