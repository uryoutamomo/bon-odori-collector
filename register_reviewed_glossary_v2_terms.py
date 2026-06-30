#!/usr/bin/env python3
"""Register user-reviewed glossary v2 terms into Notion as candidates."""

import argparse
import json
import os
import urllib.request
from pathlib import Path

from manual_apply_guards import LEGACY_NOTION_REPAIR_CONFIRMATION, require_confirmation
from notion_config import GLOSSARY_V2_DATABASE_ID, load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
TOKEN = os.environ.get("NOTION_API_TOKEN")
DB_ID = os.environ.get("GLOSSARY_V2_DB_ID") or GLOSSARY_V2_DATABASE_ID
SOURCE = Path("data/glossary_v2_oto123_review_result.json")
OUT = Path("data/glossary_v2_oto123_registered_terms.json")
CHECK_OUT = Path("data/glossary_v2_oto123_registration_check.json")


def notion_request(method, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{NOTION_API}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Notion-Version", NOTION_VERSION)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())


def rich_text(value, limit=1900):
    value = str(value or "")[:limit]
    return [{"type": "text", "text": {"content": value}}] if value else []


def existing_pages(term):
    data = notion_request(
        "POST",
        f"/databases/{DB_ID}/query",
        {
            "filter": {"property": "使用語", "title": {"equals": term}},
            "page_size": 10,
        },
    )
    return data.get("results", [])


def kind_for(row):
    category = row.get("category") or ""
    if category == "行動・参加スタイル語":
        return "行動語"
    if category == "略語・表記ゆれ・呼び名":
        return "団体語"
    if category == "感情・評価・界隈ノリ語":
        return "行動語"
    return "行動語"


def roles_for(row):
    # These reviewed terms are exploratory candidates. Keep runtime signal roles
    # empty until a later promotion pass decides which ones should affect matching.
    return []


def memo(row, duplicate_note=""):
    parts = [
        "用語集v2 3おとレビュー採用語。",
        f"元分類: {row.get('category', '')}",
        f"抽出担当: {row.get('source_agent', '')}",
        f"理由: {row.get('reason', '')}",
        f"証拠: {row.get('evidence_text', '')}",
    ]
    if duplicate_note:
        parts.append(duplicate_note)
    if row.get("review_note"):
        parts.append(f"レビュー注記: {row['review_note']}")
    return "\n".join(part for part in parts if part)


def props_for(row, duplicate_note=""):
    props = {
        "使用語": {"title": rich_text(row["term"][:200])},
        "解釈": {"rich_text": rich_text(row.get("interpretation") or row["term"])},
        "種別": {"select": {"name": kind_for(row)}},
        "シグナル役割": {"multi_select": roles_for(row)},
        "確度": {"select": {"name": "推察"}},
        "状態": {"select": {"name": "候補"}},
        "自動適用可": {"checkbox": False},
        "証拠数": {"number": 1 if row.get("evidence_url") or row.get("evidence_text") else 0},
        "メモ": {"rich_text": rich_text(memo(row, duplicate_note))},
    }
    if row.get("evidence_url"):
        props["出典URL"] = {"url": row["evidence_url"]}
    return props


def load_unique_accepted():
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    by_term = {}
    duplicates = {}
    for row in data.get("accepted", []):
        term = row.get("term") or ""
        if not term:
            continue
        if term in by_term:
            duplicates.setdefault(term, []).append(row)
            continue
        by_term[term] = row
    return by_term, duplicates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    if not TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    try:
        require_confirmation(
            not args.dry_run,
            args.confirm,
            LEGACY_NOTION_REPAIR_CONFIRMATION,
            "legacy reviewed glossary v2 term registration",
        )
    except ValueError as exc:
        parser.error(str(exc))

    accepted, duplicates = load_unique_accepted()
    created = []
    skipped = []
    failed = []
    for term, row in accepted.items():
        duplicate_note = ""
        if term in duplicates:
            categories = sorted({row.get("category", "") for row in [row, *duplicates[term]]})
            duplicate_note = f"同一使用語の採用重複を代表行に統合: {', '.join(categories)}"
        existing = existing_pages(term)
        if existing:
            skipped.append(
                {
                    "term": term,
                    "reason": "existing",
                    "count": len(existing),
                    "page_ids": [page["id"] for page in existing],
                }
            )
            print(f"skip existing: {term}")
            continue
        if args.dry_run:
            created.append({"term": term, "dry_run": True})
            print(f"dry-run create: {term} [{kind_for(row)}]")
            continue
        try:
            page = notion_request(
                "POST",
                "/pages",
                {
                    "parent": {"database_id": DB_ID},
                    "properties": props_for(row, duplicate_note),
                },
            )
            created.append({"term": term, "page_id": page["id"]})
            print(f"created: {term}")
        except Exception as exc:
            failed.append({"term": term, "error": str(exc)})
            print(f"failed: {term}: {exc}")

    result = {
        "source": str(SOURCE),
        "dry_run": args.dry_run,
        "accepted_unique": len(accepted),
        "created_count": len(created),
        "skipped_count": len(skipped),
        "failed_count": len(failed),
        "duplicates_collapsed": sorted(duplicates),
        "created": created,
        "skipped": skipped,
        "failed": failed,
    }
    out_path = CHECK_OUT if args.dry_run else OUT
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "done: unique={accepted_unique} created={created_count} "
        "skipped={skipped_count} failed={failed_count} dry_run={dry_run}".format(**result)
    )
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
