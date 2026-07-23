#!/usr/bin/env python3
"""Apply reviewed song publication decisions to public song content notes."""

import argparse
import json
from pathlib import Path


DECISIONS = Path("data/song_publication_review_decision_ledger.json")
CONTENT_NOTES = Path("data/public_song_content_notes.json")
SONG_MASTER = Path("data/youtube_song_master.json")


def load_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default if default is not None else {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def review_rows(payload):
    return [row for row in payload.get("rows", []) if isinstance(row, dict)]


def hydrate_decisions(decisions_payload, song_master_payload):
    """Restore generated song metadata omitted from the compact decision ledger."""
    by_term = {
        row.get("song_name"): row
        for row in song_master_payload.get("songs", [])
        if row.get("song_name")
    }
    hydrated = dict(decisions_payload)
    hydrated["rows"] = [
        {**by_term.get(row.get("term"), {}), **row}
        for row in review_rows(decisions_payload)
    ]
    return hydrated


def build_public_note(row):
    note = (row.get("description") or "").strip()
    if not note:
        note = "盆踊り会場の曲目として確認されている曲です。"
    item = {
        "term": row["term"],
        "content_note": note,
        "content_note_status": "公開可",
        "review_decision": "song_publication_review:publish",
    }
    if row.get("youtube_urls"):
        item["source_urls"] = row["youtube_urls"][:5]
    return item


def merge_notes(existing_payload, decisions_payload):
    existing_items = existing_payload.get("items") or []
    by_term = {item.get("term"): dict(item) for item in existing_items if item.get("term")}
    added = []
    updated = []
    skipped = []

    for row in review_rows(decisions_payload):
        term = row.get("term")
        decision = row.get("decision")
        if not term:
            continue
        if decision != "publish":
            skipped.append({"term": term, "decision": decision or ""})
            continue
        new_item = build_public_note(row)
        current = by_term.get(term)
        if not current:
            by_term[term] = new_item
            added.append(term)
            continue
        if current.get("content_note_status") == "公開可" and current.get("content_note"):
            skipped.append({"term": term, "decision": decision, "reason": "already_public"})
            continue
        merged = dict(current)
        for key, value in new_item.items():
            if key == "term":
                continue
            merged[key] = value
        by_term[term] = merged
        updated.append(term)

    ordered_terms = [item.get("term") for item in existing_items if item.get("term")]
    for term in added:
        if term not in ordered_terms:
            ordered_terms.append(term)

    result = dict(existing_payload)
    result.setdefault("generated_by", "curated_public_song_content_notes")
    result.setdefault("scope", "公開補助データ")
    result["items"] = [by_term[term] for term in ordered_terms if term in by_term]
    summary = {
        "publish_decisions": sum(1 for row in review_rows(decisions_payload) if row.get("decision") == "publish"),
        "added": len(added),
        "updated": len(updated),
        "skipped": len(skipped),
        "added_terms": added,
        "updated_terms": updated,
        "skipped_terms": skipped,
    }
    return result, summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--decisions", default=str(DECISIONS))
    parser.add_argument("--content-notes", default=str(CONTENT_NOTES))
    parser.add_argument("--song-master", default=str(SONG_MASTER))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    decisions = hydrate_decisions(
        load_json(args.decisions, {"rows": []}),
        load_json(args.song_master, {"songs": []}),
    )
    existing = load_json(args.content_notes, {"generated_by": "curated_public_song_content_notes", "items": []})
    result, summary = merge_notes(existing, decisions)

    if args.apply:
        write_json(args.content_notes, result)

    print(json.dumps({**summary, "applied": args.apply}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
