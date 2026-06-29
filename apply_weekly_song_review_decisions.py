#!/usr/bin/env python3
"""Apply reviewed weekly song decisions to the song master database."""

import argparse
import json
import os
from pathlib import Path

from manual_apply_guards import LEGACY_NOTION_REPAIR_CONFIRMATION, require_confirmation
from notion_config import SONG_MASTER_DATABASE_ID, load_local_env
from register_song_master_initial import classify_song
from triage_weekly_song_candidates import (
    rich_text,
    norm,
    notion_request,
    title_index,
)


load_local_env()

TOKEN = os.environ.get("NOTION_API_TOKEN")
SONG_DB_ID = os.environ.get("SONG_MASTER_DB_ID") or SONG_MASTER_DATABASE_ID
REVIEW_SOURCE = Path("data/weekly_song_candidates_review.json")
DECISIONS = Path("data/weekly_song_review_decisions.json")
OUT = Path("data/weekly_song_review_apply_result.json")

ACCEPT_DECISIONS = {"曲として採用", "採用", "曲マスタ"}
REJECT_DECISIONS = {"曲ではない", "不採用"}
HOLD_DECISIONS = {"保留"}


def load_json(path):
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def source_rows(path):
    data = load_json(path)
    return {row["term"]: row for row in data.get("rows", [])}


def decision_rows(path):
    data = load_json(path)
    rows = data.get("rows", data if isinstance(data, list) else [])
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        decision = row.get("decision") or ""
        if not decision:
            continue
        out.append(row)
    return out


def song_props(song_name, source, note):
    memo = (
        "日次X収穫レビュー結果から曲マスタへ反映。\n"
        f"元候補: {source.get('term', song_name)}\n"
        f"レビュー注記: {note}\n"
        f"証拠URL: {source.get('evidence_url', '')}\n"
        f"証拠抜粋: {source.get('evidence_text', '')[:900]}"
    )
    props = {
        "曲名": {"title": rich_text(song_name[:200])},
        "分類": {"select": {"name": classify_song(song_name)}},
        "状態": {"select": {"name": "有効"}},
        "証拠数": {"number": int(source.get("evidence_count") or 1)},
        "メモ": {"rich_text": rich_text(memo)},
    }
    if source.get("evidence_url"):
        props["出典・音源URL"] = {"url": source["evidence_url"]}
    return props


def split_song_names(note):
    return [
        item.strip()
        for item in note.replace("、", "\n").replace(",", "\n").replace("/", "\n").splitlines()
        if item.strip()
    ]


def update_existing_props(song_name, source, note):
    props = song_props(song_name, source, note)
    props.pop("曲名", None)
    return props


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=REVIEW_SOURCE)
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
            "legacy weekly song review Notion repair",
        )
    except ValueError as exc:
        parser.error(str(exc))

    if not TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    if not SONG_DB_ID:
        raise SystemExit("SONG_MASTER_DB_ID is not set")
    if not args.decisions.exists():
        raise SystemExit(f"decisions file not found: {args.decisions}")

    sources = source_rows(args.source)
    songs = title_index(SONG_DB_ID)
    created = []
    updated = []
    rejected = []
    held = []
    skipped = []
    for decision in decision_rows(args.decisions):
        term = decision.get("term") or ""
        source = sources.get(term)
        if not source:
            skipped.append({"term": term, "reason": "source row not found"})
            continue
        value = decision.get("decision") or ""
        note = decision.get("note") or ""
        song_name = note.strip() or source.get("canonical_song_name") or term
        if value in REJECT_DECISIONS:
            rejected.append({"term": term, "decision": value})
            continue
        if value in HOLD_DECISIONS or value in {"用語集へ"}:
            held.append({"term": term, "decision": value, "note": note})
            continue
        if value == "分割":
            song_names = split_song_names(note)
            if not song_names:
                held.append({"term": term, "decision": value, "note": "split names missing"})
                continue
        else:
            song_names = [note.strip() or source.get("canonical_song_name") or term]
        if value not in ACCEPT_DECISIONS:
            if value != "分割":
                skipped.append({"term": term, "decision": value, "reason": "unknown decision"})
                continue
        for song_name in song_names:
            existing = songs.get(norm(song_name))
            if args.dry_run:
                (updated if existing else created).append(
                    {"song_name": song_name, "term": term, "dry_run": True}
                )
                continue
            if existing:
                notion_request(
                    "PATCH",
                    f"/pages/{existing['id']}",
                    {"properties": update_existing_props(song_name, source, note)},
                )
                updated.append({"song_name": song_name, "term": term, "page_id": existing["id"]})
            else:
                page = notion_request(
                    "POST",
                    "/pages",
                    {
                        "parent": {"database_id": SONG_DB_ID},
                        "properties": song_props(song_name, source, note),
                    },
                )
                created.append({"song_name": song_name, "term": term, "page_id": page["id"]})
                songs[norm(song_name)] = {"id": page["id"], "name": song_name, "page": page}

    result = {
        "dry_run": args.dry_run,
        "source": str(args.source),
        "decisions": str(args.decisions),
        "created_count": len(created),
        "updated_count": len(updated),
        "rejected_count": len(rejected),
        "held_count": len(held),
        "skipped_count": len(skipped),
        "created": created,
        "updated": updated,
        "rejected": rejected,
        "held": held,
        "skipped": skipped,
    }
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "done: created={created_count} updated={updated_count} "
        "rejected={rejected_count} held={held_count} skipped={skipped_count} "
        "dry_run={dry_run}".format(**result)
    )
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
