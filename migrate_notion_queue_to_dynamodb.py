#!/usr/bin/env python3
"""Migrate pre-DynamoDB Notion queue rows into DynamoDB.

This is intentionally conservative:
- only rows created before the cutoff are considered;
- archived / resolved rows are skipped;
- event-candidate v2 rows are not mixed into the legacy venue queue;
- dry-run is the default.
"""

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone

from collection_support.queue_store import DynamoQueueStore


NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
TORIMOCHI_QUEUE_DB_ID = os.environ.get(
    "TORIMOCHI_QUEUE_DB_ID", "f560afee832f4b1084d6e6093d74da16"
)
ACTIVE_STATUSES = {
    "",
    "未確認",
    "要裏取り",
    "関連候補あり",
    "新規会場・要裏取り",
    "保留",
}
SKIP_STATUSES = {
    "該当なし",
    "確認済み",
    "昇格済み",
}
EVENT_CANDIDATE_TYPE = "イベント候補"
APPLY_CONFIRMATION = "MIGRATE NOTION QUEUE TO DYNAMODB"


def notion_request(method, path, payload=None):
    token = os.environ.get("NOTION_API_TOKEN")
    if not token:
        raise RuntimeError("NOTION_API_TOKEN is required")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        f"{NOTION_API_BASE}{path}", data=data, method=method
    )
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Notion-Version", NOTION_VERSION)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())


def query_database(payload):
    rows = []
    cursor = None
    while True:
        page = dict(payload)
        page.setdefault("page_size", 100)
        if cursor:
            page["start_cursor"] = cursor
        data = notion_request(
            "POST", f"/databases/{TORIMOCHI_QUEUE_DB_ID}/query", page
        )
        rows.extend(data.get("results", []))
        if not data.get("has_more"):
            return rows
        cursor = data.get("next_cursor")


def plain(prop):
    if not prop:
        return ""
    prop_type = prop.get("type")
    if prop_type in ("title", "rich_text"):
        return "".join(
            item.get("plain_text", "") for item in prop.get(prop_type, [])
        ).strip()
    if prop_type == "select":
        return (prop.get("select") or {}).get("name", "")
    if prop_type == "url":
        return prop.get("url") or ""
    if prop_type == "date":
        return (prop.get("date") or {}).get("start", "")
    if prop_type == "number":
        value = prop.get("number")
        return "" if value is None else str(value)
    return ""


def multi_names(prop):
    if not prop or prop.get("type") != "multi_select":
        return []
    return [
        item.get("name", "")
        for item in prop.get("multi_select", [])
        if item.get("name")
    ]


def number_value(prop):
    if not prop or prop.get("type") != "number":
        return None
    return prop.get("number")


def parse_notion_row(row):
    props = row.get("properties", {})
    title = plain(props.get("会場名"))
    candidate_type = plain(props.get("種別")) or "会場"
    identity = plain(props.get("証拠ID")) or title
    status = plain(props.get("ステータス")) or "要裏取り"
    detected_date = plain(props.get("検知日"))
    detected_at = detected_date or row.get("created_time")
    if detected_at and len(detected_at) == 10:
        detected_at = f"{detected_at}T00:00:00+09:00"
    candidate = {
        "identity": identity,
        "venue": title or identity,
        "type": candidate_type,
        "status": status,
        "source": plain(props.get("検知ソース")) or "notion_migration",
        "priority": plain(props.get("優先度")) or "通常",
        "url": plain(props.get("検知元URL")),
        "text": plain(props.get("検知元本文")),
        "account": plain(props.get("発言者")),
        "spoken_at": plain(props.get("発言日時")),
        "tweet_id": identity if identity.startswith("evidence:") else "",
        "patterns": multi_names(props.get("検知パターン")),
        "score": number_value(props.get("検知スコア")),
        "score_reasons": plain(props.get("スコア根拠")),
        "time_hints": plain(props.get("時期ヒント")),
        "place_hints": plain(props.get("場所ヒント")),
        "song_hints": plain(props.get("曲・団体ヒント")),
        "year_signals": multi_names(props.get("年次信号")),
        "estimated_event": plain(props.get("推定イベント名")),
        "estimated_venue": plain(props.get("推定会場")),
        "related_key": plain(props.get("関連候補キー")),
        "notion_page_id": row.get("id"),
        "notion_url": row.get("url"),
    }
    return candidate, detected_at


def should_skip(row, cutoff_dt):
    if row.get("archived"):
        return "archived"
    created = datetime.fromisoformat(
        row["created_time"].replace("Z", "+00:00")
    )
    if created >= cutoff_dt:
        return "after_cutoff"
    props = row.get("properties", {})
    status = plain(props.get("ステータス"))
    if status in SKIP_STATUSES:
        return f"status:{status}"
    if status not in ACTIVE_STATUSES:
        return f"unknown_status:{status}"
    candidate_type = plain(props.get("種別")) or "会場"
    if candidate_type == EVENT_CANDIDATE_TYPE:
        return "event_candidate_v2"
    title = plain(props.get("会場名"))
    if not title:
        return "missing_title"
    return ""


def migrate(rows, apply=False):
    store = DynamoQueueStore()
    migrated = []
    skipped_existing = []
    for row in rows:
        candidate, detected_at = parse_notion_row(row)
        candidate_type = candidate.get("type") or "会場"
        identity = candidate.get("identity") or candidate["venue"]
        if store.is_notion_synced(identity, candidate_type):
            skipped_existing.append(candidate)
            continue
        created = store.add_candidate(candidate, detected_at=detected_at)
        if created:
            store.mark_notion_synced(identity, candidate_type)
            migrated.append(candidate)
        else:
            # Existing DynamoDB item without notion_synced=true. Since this row
            # originated in Notion, mark it synced to avoid future duplication.
            store.mark_notion_synced(identity, candidate_type)
            skipped_existing.append(candidate)
    return migrated, skipped_existing


def validate_apply_confirmation(apply, confirmation):
    if not apply:
        return
    if confirmation != APPLY_CONFIRMATION:
        raise ValueError(f"--apply requires --confirm '{APPLY_CONFIRMATION}'")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cutoff", default="2026-06-07T00:00:00+09:00")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        validate_apply_confirmation(args.apply, args.confirm)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    cutoff_dt = datetime.fromisoformat(args.cutoff)
    if cutoff_dt.tzinfo is None:
        cutoff_dt = cutoff_dt.replace(tzinfo=timezone.utc)

    rows = query_database({
        "filter": {
            "timestamp": "created_time",
            "created_time": {"before": args.cutoff},
        },
        "sorts": [{"timestamp": "created_time", "direction": "ascending"}],
    })
    candidates = []
    skip_reasons = {}
    for row in rows:
        reason = should_skip(row, cutoff_dt)
        if reason:
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1
            continue
        candidate, _ = parse_notion_row(row)
        candidates.append((row, candidate))

    print(
        f"[migrate] rows_before_cutoff={len(rows)} "
        f"eligible={len(candidates)} dry_run={not args.apply}"
    )
    for reason, count in sorted(skip_reasons.items()):
        print(f"[migrate] skipped {reason}: {count}")
    for _, candidate in candidates[:20]:
        print(
            "[migrate] candidate "
            f"type={candidate.get('type')} "
            f"status={candidate.get('status')} "
            f"venue={candidate.get('venue')} "
            f"identity={candidate.get('identity')}"
        )

    if not args.apply:
        return

    migrated, existing = migrate([row for row, _ in candidates], apply=True)
    print(f"[migrate] migrated={len(migrated)} existing_or_marked={len(existing)}")


if __name__ == "__main__":
    main()
