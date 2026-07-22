#!/usr/bin/env python3
"""Register glossary v2 seed candidates into Notion as review candidates."""

import argparse
import json
import os
import urllib.request
from pathlib import Path

from operation_safety.manual_apply_guards import LEGACY_NOTION_REPAIR_CONFIRMATION, require_confirmation
from notion_config import GLOSSARY_V2_DATABASE_ID, load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
TOKEN = os.environ.get("NOTION_API_TOKEN")
DB_ID = os.environ.get("GLOSSARY_V2_DB_ID") or GLOSSARY_V2_DATABASE_ID
SOURCE = Path("data/glossary_v2_seed_candidates.json")

SKIP_TERMS = {
    "子供盆踊り",
    "相馬盆",
    "見取り図盆踊り",
}
SKIP_INTERPRETATIONS = {
    "盆踊り大会",
}


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


def date_value(value):
    return {"start": value[:10]} if value else None


def existing_term(term):
    data = notion_request("POST", f"/databases/{DB_ID}/query", {
        "filter": {"property": "使用語", "title": {"equals": term}},
        "page_size": 1,
    })
    return bool(data.get("results"))


def memo(candidate):
    target = candidate.get("inferred_target") or {}
    parts = [
        f"推論先: {target.get('kind', '')} {target.get('name', '')}".strip(),
        f"理由: {', '.join(candidate.get('reasons', []))}",
        f"証拠数: {candidate.get('evidence_count', 0)}",
    ]
    evidence = candidate.get("evidence") or []
    if evidence:
        text = (evidence[0].get("text") or "").replace("\n", " ")
        parts.append(f"初出例: {text[:360]}")
    return "\n".join(part for part in parts if part)


def candidate_props(candidate):
    evidence = candidate.get("evidence") or []
    first = evidence[0] if evidence else {}
    kind = candidate.get("kind") or "行動語"
    props = {
        "使用語": {"title": [{"type": "text", "text": {"content": candidate["term"][:200]}}]},
        "解釈": {"rich_text": rich_text(candidate.get("interpretation") or candidate["term"])},
        "種別": {"select": {"name": kind}},
        "シグナル役割": {
            "multi_select": [{"name": role} for role in candidate.get("roles", [])]
        },
        "確度": {"select": {"name": "推察"}},
        "状態": {"select": {"name": "候補"}},
        "自動適用可": {"checkbox": False},
        "証拠数": {"number": candidate.get("evidence_count", 0)},
        "メモ": {"rich_text": rich_text(memo(candidate))},
    }
    if kind == "曲名":
        props["曲名"] = {"rich_text": rich_text(candidate.get("interpretation") or candidate["term"])}
    if first.get("url"):
        props["出典URL"] = {"url": first["url"]}
    first_date = date_value(first.get("date") or "")
    if first_date:
        props["初出日"] = {"date": first_date}
        props["最終検出日"] = {"date": first_date}
    return props


def selected_candidates(limit):
    with SOURCE.open(encoding="utf-8") as f:
        data = json.load(f)
    rows = []
    seen = set()
    for candidate in data.get("candidates", []):
        term = candidate.get("term") or ""
        interpretation = candidate.get("interpretation") or ""
        if (
            not term
            or term in SKIP_TERMS
            or interpretation in SKIP_INTERPRETATIONS
            or term in seen
        ):
            continue
        seen.add(term)
        rows.append(candidate)
        if len(rows) >= limit:
            break
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=30)
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
            "legacy glossary v2 seed registration",
        )
    except ValueError as exc:
        parser.error(str(exc))
    created = 0
    skipped = 0
    for candidate in selected_candidates(args.limit):
        term = candidate["term"]
        if existing_term(term):
            skipped += 1
            print(f"skip existing: {term}")
            continue
        if args.dry_run:
            print(f"dry-run create: {term} -> {candidate.get('interpretation')}")
            created += 1
            continue
        notion_request("POST", "/pages", {
            "parent": {"database_id": DB_ID},
            "properties": candidate_props(candidate),
        })
        created += 1
        print(f"created: {term}")
    print(f"done: created={created} skipped={skipped} dry_run={args.dry_run}")


if __name__ == "__main__":
    main()
