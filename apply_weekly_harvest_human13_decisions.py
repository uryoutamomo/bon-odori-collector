#!/usr/bin/env python3
"""Apply the human-reviewed daily X harvest terms and co-occurrence rows."""

import argparse
import json
import os
import urllib.request
from pathlib import Path

from manual_apply_guards import LEGACY_NOTION_REPAIR_CONFIRMATION, require_confirmation
from notion_config import (
    GLOSSARY_V2_DATABASE_ID,
    SONG_MASTER_DATABASE_ID,
    VENUE_DATABASE_ID,
    load_local_env,
)
from register_song_master_initial import rich_text
from triage_weekly_song_candidates import norm, notion_request, title_index


load_local_env()

TOKEN = os.environ.get("NOTION_API_TOKEN")
GLOSSARY_DB_ID = os.environ.get("GLOSSARY_V2_DB_ID") or GLOSSARY_V2_DATABASE_ID
SONG_DB_ID = os.environ.get("SONG_MASTER_DB_ID") or SONG_MASTER_DATABASE_ID
CANDIDATES = Path("data/weekly_harvest_candidates_human13.json")
DECISIONS = Path("data/weekly_harvest_human13_result.json")
OUT = Path("data/weekly_harvest_human13_apply_result.json")

ACCEPT = {"採用"}
REJECT = {"不採用"}
HOLD = {"保留"}


def load_json(path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def candidate_rows(path):
    data = load_json(path)
    return {row["term"]: row for row in data.get("rows", [])}


def decision_rows(path):
    data = load_json(path)
    return [row for row in data.get("rows", []) if row.get("decision")]


def plain_text(prop):
    if not prop:
        return ""
    prop_type = prop.get("type")
    if prop_type in ("title", "rich_text"):
        return "".join(item.get("plain_text", "") for item in prop.get(prop_type, [])).strip()
    return ""


def query_glossary_term(term):
    data = notion_request(
        "POST",
        f"/databases/{GLOSSARY_DB_ID}/query",
        {
            "filter": {"property": "使用語", "title": {"equals": term}},
            "page_size": 10,
        },
    )
    return data.get("results", [])


def term_kind(row):
    typ = row.get("type") or row.get("category") or ""
    if typ in {"参加スタイル語", "行動語", "界隈語"}:
        return "行動語"
    if typ == "準公式用語":
        return "行動語"
    return "行動語"


def term_roles(term):
    if term in {"参戦"}:
        return ["参加予告", "参加報告"]
    if term in {"踊り始め", "盆踊りオフ会", "梯子"}:
        return ["参加報告"]
    if term in {"練習会", "輪踊り"}:
        return ["開催示唆"]
    return []


def glossary_props(row, review_note):
    term = row["term"]
    memo = (
        "日次X収穫レビューで内田さん採用。\n"
        f"元分類: {row.get('type') or row.get('category', '')}\n"
        f"理由: {row.get('reason', '')}\n"
        f"レビュー注記: {review_note}\n"
        f"証拠URL: {row.get('evidence_url', '')}\n"
        f"証拠抜粋: {row.get('evidence_text', '')[:900]}"
    )
    props = {
        "使用語": {"title": rich_text(term[:200])},
        "解釈": {"rich_text": rich_text(row.get("interpretation") or term)},
        "種別": {"select": {"name": term_kind(row)}},
        "シグナル役割": {"multi_select": [{"name": role} for role in term_roles(term)]},
        "確度": {"select": {"name": "複数一致" if int(row.get("evidence_count") or 0) >= 2 else "推察"}},
        "状態": {"select": {"name": "有効"}},
        "自動適用可": {"checkbox": False},
        "証拠数": {"number": int(row.get("evidence_count") or 1)},
        "メモ": {"rich_text": rich_text(memo)},
    }
    if row.get("evidence_url"):
        props["出典URL"] = {"url": row["evidence_url"]}
    return props


def update_glossary_props(row, review_note):
    props = glossary_props(row, review_note)
    props.pop("使用語", None)
    return props


def apply_term(row, review_note, dry_run=False):
    existing = query_glossary_term(row["term"])
    if dry_run:
        return {
            "term": row["term"],
            "action": "update" if existing else "create",
            "dry_run": True,
        }
    if existing:
        page_id = existing[0]["id"]
        notion_request(
            "PATCH",
            f"/pages/{page_id}",
            {"properties": update_glossary_props(row, review_note)},
        )
        return {"term": row["term"], "action": "update", "page_id": page_id}
    page = notion_request(
        "POST",
        "/pages",
        {
            "parent": {"database_id": GLOSSARY_DB_ID},
            "properties": glossary_props(row, review_note),
        },
    )
    return {"term": row["term"], "action": "create", "page_id": page["id"]}


def apply_cooccurrence(row, dry_run=False):
    songs = title_index(SONG_DB_ID)
    venues = title_index(VENUE_DATABASE_ID)
    song = songs.get(norm(row.get("song_name")))
    venue = venues.get(norm(row.get("venue")))
    if not song or not venue:
        return {
            "term": row["term"],
            "action": "missing_target",
            "song_found": bool(song),
            "venue_found": bool(venue),
        }
    current = song["page"].get("properties", {}).get("会場", {}).get("relation", [])
    venue_ids = sorted({item["id"] for item in current} | {venue["id"]})
    if dry_run:
        return {
            "term": row["term"],
            "action": "update_song_venue_relation",
            "song": song["name"],
            "venue": venue["name"],
            "dry_run": True,
        }
    notion_request(
        "PATCH",
        f"/pages/{song['id']}",
        {"properties": {"会場": {"relation": [{"id": page_id} for page_id in venue_ids]}}},
    )
    return {
        "term": row["term"],
        "action": "update_song_venue_relation",
        "song": song["name"],
        "venue": venue["name"],
        "page_id": song["id"],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, default=CANDIDATES)
    parser.add_argument("--decisions", type=Path, default=DECISIONS)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        require_confirmation(
            not args.dry_run,
            args.confirm,
            LEGACY_NOTION_REPAIR_CONFIRMATION,
            "legacy weekly harvest human13 Notion repair",
        )
    except ValueError as exc:
        parser.error(str(exc))

    if not TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    candidates = candidate_rows(args.candidates)
    applied_terms = []
    applied_cooccurrences = []
    rejected = []
    held = []
    skipped = []
    for decision in decision_rows(args.decisions):
        term = decision["term"]
        row = candidates.get(term)
        if not row:
            skipped.append({"term": term, "reason": "candidate not found"})
            continue
        value = decision["decision"]
        if value in REJECT:
            rejected.append({"term": term})
            continue
        if value in HOLD:
            held.append({"term": term, "note": decision.get("note", "")})
            continue
        if value not in ACCEPT:
            skipped.append({"term": term, "decision": value, "reason": "unknown decision"})
            continue
        if row.get("category") == "曲×会場共起":
            applied_cooccurrences.append(apply_cooccurrence(row, args.dry_run))
        elif row.get("category") == "用語候補":
            applied_terms.append(apply_term(row, decision.get("note", ""), args.dry_run))
        else:
            skipped.append({"term": term, "category": row.get("category"), "reason": "unsupported category"})

    result = {
        "dry_run": args.dry_run,
        "candidates": str(args.candidates),
        "decisions": str(args.decisions),
        "applied_term_count": len(applied_terms),
        "applied_cooccurrence_count": len(applied_cooccurrences),
        "rejected_count": len(rejected),
        "held_count": len(held),
        "skipped_count": len(skipped),
        "applied_terms": applied_terms,
        "applied_cooccurrences": applied_cooccurrences,
        "rejected": rejected,
        "held": held,
        "skipped": skipped,
    }
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "done: terms={applied_term_count} cooccurrences={applied_cooccurrence_count} "
        "rejected={rejected_count} held={held_count} skipped={skipped_count} "
        "dry_run={dry_run}".format(**result)
    )
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
