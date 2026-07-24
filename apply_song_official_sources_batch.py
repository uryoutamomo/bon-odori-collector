#!/usr/bin/env python3
"""Merge official song source URLs into public song content notes."""

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


def dedupe_urls(urls):
    seen = set()
    result = []
    for url in urls:
        url = (url or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(url)
    return result


def source_rows(batch):
    rows = []
    for row in batch.get("rows", []):
        term = (row.get("term") or "").strip()
        official_urls = dedupe_urls(row.get("official_source_urls") or [])
        if not term or not official_urls:
            continue
        rows.append({
            "term": term,
            "official_source_urls": official_urls,
            "official_source_memo": (row.get("official_source_memo") or "").strip(),
        })
    return rows


def merge_sources(existing_payload, rows):
    existing_items = existing_payload.get("items") or []
    by_term = {item.get("term"): dict(item) for item in existing_items if item.get("term")}
    order = [item.get("term") for item in existing_items if item.get("term")]

    applied = []
    skipped = []
    for row in rows:
        term = row["term"]
        item = by_term.get(term)
        if not item:
            skipped.append({"term": term, "reason": "missing_existing_content_note"})
            continue

        current = item.get("source_urls") or []
        item["source_urls"] = dedupe_urls([*row["official_source_urls"], *current])
        item["official_source_urls"] = dedupe_urls([
            *(item.get("official_source_urls") or []),
            *row["official_source_urls"],
        ])
        if row.get("official_source_memo"):
            memos = item.get("official_source_memos") or []
            if row["official_source_memo"] not in memos:
                memos.append(row["official_source_memo"])
            item["official_source_memos"] = memos
        by_term[term] = item
        applied.append(term)

    payload = dict(existing_payload)
    payload["items"] = [by_term[term] for term in order if term in by_term]
    payload["scope"] = (
        "確認根拠数上位曲を中心に、歌詞引用を避けて曲の内容・背景を短く説明する公開補助データ。"
    )
    return payload, applied, skipped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", type=Path)
    parser.add_argument("--content-notes", default=str(CONTENT_NOTES))
    parser.add_argument("--out", default="")
    parser.add_argument("--apply", action="store_true", help="Write back to --content-notes when --out is omitted.")
    args = parser.parse_args()

    existing = load_json(args.content_notes, {"generated_by": "curated_public_song_content_notes", "items": []})
    batch = load_json(args.batch)
    merged, applied, skipped = merge_sources(existing, source_rows(batch))

    if args.out:
        out = Path(args.out)
    elif args.apply:
        out = Path(args.content_notes)
    else:
        out = Path(args.content_notes).with_suffix(".official_sources_preview.json")

    out.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mode = "applied" if args.apply and not args.out else "preview"
    print(f"song official sources {mode}: applied_rows={len(applied)} skipped={len(skipped)} -> {out}")
    if applied:
        print("terms: " + ", ".join(applied))
    if skipped:
        print("skipped: " + json.dumps(skipped, ensure_ascii=False))


if __name__ == "__main__":
    main()
