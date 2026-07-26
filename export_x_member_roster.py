#!/usr/bin/env python3
"""Export the legacy Notion "X メンバーリスト" into a local roster file.

Until now the list of accounts whose timelines we read directly lived only in
Notion, even though the project moved off Notion as a source of truth. That left
the roster frozen at whatever was in Notion (69 accounts) while the local scoring
ledger had grown to several hundred `trusted` accounts that were never read.

This exports Notion once into `data/x_collection_roster.json`, which then becomes
the local source of truth. Notion stays readable as a fallback but is no longer
required for collection to work.
"""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import collect

OUT = Path("data") / "x_collection_roster.json"


def export_from_notion():
    if not collect.NOTION_TOKEN:
        raise SystemExit(
            "NOTION_API_TOKEN が未設定です。.env に設定してから実行してください。"
        )
    accounts = []
    cursor = None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        data = collect._notion_query_database(collect.X_MEMBER_LIST_DB_ID, payload)
        for row in data.get("results", []):
            props = row.get("properties", {})
            handle = collect._x_member_handle_from_props(props)
            if not handle:
                continue
            accounts.append({
                "handle": f"@{handle}",
                "manual_status": collect._prop_select(props.get("収集ステータス", {})),
                "notion_page_id": row.get("id", ""),
                "origin": "notion_x_member_list",
            })
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return accounts


def merge(existing, accounts):
    """Keep manual edits already made in the local roster."""
    by_handle = {
        str(row.get("handle", "")).lstrip("@").lower(): row
        for row in existing.get("accounts") or []
    }
    for row in accounts:
        key = row["handle"].lstrip("@").lower()
        if key in by_handle:
            current = by_handle[key]
            # ローカルで付けた休止・優先の判断を Notion の値で潰さない
            current.setdefault("notion_page_id", row["notion_page_id"])
            if not current.get("manual_status"):
                current["manual_status"] = row["manual_status"]
        else:
            by_handle[key] = row
    return sorted(by_handle.values(), key=lambda row: row["handle"].lower())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    out_path = Path(args.out)
    existing = {}
    if out_path.exists():
        existing = json.loads(out_path.read_text(encoding="utf-8"))

    accounts = export_from_notion()
    merged = merge(existing, accounts)
    out_path.write_text(
        json.dumps(
            {
                "_comment": (
                    "X収集で直接タイムラインを読むアカウント名簿のローカル正本。"
                    "Notion「Xメンバーリスト」からの移行元データ。"
                    "manual_status: 優先 / 通常 / 休止。"
                ),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "count": len(merged),
                "accounts": merged,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Xメンバー名簿をエクスポート: {len(merged)}アカウント -> {out_path}")


if __name__ == "__main__":
    main()
