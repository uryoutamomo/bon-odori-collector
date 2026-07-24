#!/usr/bin/env python3
"""Apply reviewed song content research rows to public song content notes."""

import argparse
import json
from pathlib import Path


CONTENT_NOTES = Path("data/public_song_content_notes.json")


def load_json(path, default=None):
    path = Path(path)
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(path)
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def content_rows(batch):
    rows = []
    for row in batch.get("rows", []):
        if row.get("application_status") == "superseded_by_canonical_term":
            continue
        term = (row.get("term") or "").strip()
        note = (row.get("content_note") or "").strip()
        status = (row.get("content_note_status") or "").strip()
        if not term or not note or status != "公開可":
            continue
        rows.append({
            "term": term,
            "content_note": note,
            "content_note_status": status,
            "source_urls": row.get("source_urls") or [],
            "research_memo": row.get("research_memo") or "",
        })
    return rows


def removal_terms(batch):
    return [
        term.strip()
        for term in batch.get("remove_terms", [])
        if isinstance(term, str) and term.strip()
    ]


def merge_notes(existing_payload, research_rows, removals=None):
    existing_items = existing_payload.get("items") or []
    by_term = {item.get("term"): dict(item) for item in existing_items if item.get("term")}
    order = [item.get("term") for item in existing_items if item.get("term")]

    removed = []
    for term in removals or []:
        if term in by_term:
            del by_term[term]
            removed.append(term)

    applied = []
    for row in research_rows:
        term = row["term"]
        item = by_term.get(term, {"term": term})
        item["content_note"] = row["content_note"]
        item["content_note_status"] = row["content_note_status"]
        if row.get("source_urls"):
            item["source_urls"] = row["source_urls"]
        if row.get("research_memo"):
            item["research_memo"] = row["research_memo"]
        by_term[term] = item
        if term not in order:
            order.append(term)
        applied.append(term)

    payload = dict(existing_payload)
    payload["items"] = [by_term[term] for term in order if term in by_term]
    payload["scope"] = (
        "確認根拠数上位曲を中心に、歌詞引用を避けて曲の内容・背景を短く説明する公開補助データ。"
    )
    return payload, applied, removed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", type=Path)
    parser.add_argument("--content-notes", default=str(CONTENT_NOTES))
    parser.add_argument("--out", default="")
    parser.add_argument("--apply", action="store_true", help="Write back to --content-notes when --out is omitted.")
    args = parser.parse_args()

    existing = load_json(args.content_notes, {"generated_by": "curated_public_song_content_notes", "items": []})
    batch = load_json(args.batch)
    merged, applied, removed = merge_notes(
        existing,
        content_rows(batch),
        removal_terms(batch),
    )

    if args.out:
        out = Path(args.out)
    elif args.apply:
        out = Path(args.content_notes)
    else:
        out = Path(args.content_notes).with_suffix(".preview.json")

    out.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mode = "applied" if args.apply and not args.out else "preview"
    print(f"song content research {mode}: applied_rows={len(applied)} -> {out}")
    if applied:
        print("terms: " + ", ".join(applied))
    if removed:
        print("removed_terms: " + ", ".join(removed))


if __name__ == "__main__":
    main()
