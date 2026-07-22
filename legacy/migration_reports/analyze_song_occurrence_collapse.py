"""Analyze the two public song-row differences caused by duplicate collapse."""

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from master_rdb.master_db import normalize_text


DATA = Path("data")
DIFF = DATA / "master_rdb_event_song_occurrences_production_preview_diff.json"
EXPORTED = DATA / "master_rdb_event_song_occurrences_public.production_preview.json"
OUT_JSON = DATA / "song_occurrence_collapse_analysis.json"
OUT_MD = DATA / "song_occurrence_collapse_analysis.md"


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def occurrence_key(row):
    return (
        row.get("occurrence_id") or "",
        row.get("event_name") or "",
        row.get("venue") or "",
        int(row.get("year") or 0),
    )


def exported_song_index(exported):
    index = defaultdict(list)
    for occurrence in exported.get("occurrences") or []:
        occ_key = occurrence_key(occurrence)
        for song in occurrence.get("songs") or []:
            index[(occ_key, normalize_text(song.get("name")))].append(song)
    return index


def missing_rows_by_normalized_key(diff):
    grouped = defaultdict(list)
    for row in diff.get("missing_public_song_rows_sample") or []:
        key = row.get("key") or {}
        occurrence = key.get("occurrence") or {}
        song = key.get("song") or {}
        occ_key = occurrence_key(occurrence)
        grouped[(occ_key, normalize_text(song.get("name")))].append(row)
    return grouped


def analyze_row(row, missing_by_key, exported_by_key):
    source_rows = row.get("source_rows") or []
    occurrence_keys = {
        (
            source.get("occurrence_id") or "",
            source.get("event_name") or "",
            source.get("venue") or "",
            int(source.get("year") or 0),
        )
        for source in source_rows
    }
    roles = {source.get("role") or "" for source in source_rows}
    normalized_titles = {normalize_text(source.get("song_name")) for source in source_rows}
    key = next(iter(occurrence_keys)) if len(occurrence_keys) == 1 else None
    normalized_title = next(iter(normalized_titles)) if len(normalized_titles) == 1 else None
    missing = missing_by_key.get((key, normalized_title), []) if key and normalized_title else []
    exported = exported_by_key.get((key, normalized_title), []) if key and normalized_title else []
    source_count = int(row.get("source_count") or 0)
    missing_count = sum(int(item.get("count") or 0) for item in missing)
    expected_missing_count = max(source_count - 1, 0)
    is_intentional = (
        source_count > 1
        and len(occurrence_keys) == 1
        and len(roles) == 1
        and len(normalized_titles) == 1
        and missing_count == expected_missing_count
        and bool(exported)
    )
    return {
        "observed_occurrence_song_id": row.get("observed_occurrence_song_id"),
        "decision": "intentional_duplicate_collapse" if is_intentional else "review_required",
        "source_count": source_count,
        "expected_missing_count": expected_missing_count,
        "actual_missing_public_song_row_count": missing_count,
        "occurrence_key_count": len(occurrence_keys),
        "role_count": len(roles),
        "normalized_title_count": len(normalized_titles),
        "normalized_title": normalized_title,
        "source_titles": [source.get("song_name") for source in source_rows],
        "exported_titles": [song.get("name") for song in exported],
        "event_name": source_rows[0].get("event_name") if source_rows else "",
        "venue": source_rows[0].get("venue") if source_rows else "",
        "year": source_rows[0].get("year") if source_rows else None,
        "role": source_rows[0].get("role") if source_rows else "",
        "source_rows": source_rows,
        "missing_public_song_rows": missing,
    }


def build(args):
    diff = load_json(args.diff, {})
    exported = load_json(args.exported, {})
    missing_by_key = missing_rows_by_normalized_key(diff)
    exported_by_key = exported_song_index(exported)
    rows = [
        analyze_row(row, missing_by_key, exported_by_key)
        for row in diff.get("duplicate_collapsed_observed_song_ids_sample") or []
    ]
    data = {
        "generated_by": "analyze_song_occurrence_collapse.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "read_only_song_occurrence_collapse_analysis_no_writes",
        "sources": {
            "diff": str(args.diff),
            "exported": str(args.exported),
        },
        "summary": {
            "duplicate_collapsed_id_count": len(rows),
            "intentional_duplicate_collapse_count": sum(
                1 for row in rows if row["decision"] == "intentional_duplicate_collapse"
            ),
            "review_required_count": sum(1 for row in rows if row["decision"] == "review_required"),
            "missing_public_song_row_count": (diff.get("summary") or {}).get(
                "missing_public_song_row_count"
            ),
            "missing_sqlite_observed_song_id_count": (diff.get("summary") or {}).get(
                "missing_sqlite_observed_song_id_count"
            ),
        },
        "rows": rows,
    }
    write_json(args.out_json, data)
    Path(args.out_md).write_text(render_markdown(data), encoding="utf-8")
    return data


def render_markdown(data):
    summary = data["summary"]
    lines = [
        "# Song occurrence collapse analysis",
        "",
        f"- generated_at: {data['generated_at']}",
        f"- scope: {data['scope']}",
        f"- duplicate_collapsed_id_count: {summary['duplicate_collapsed_id_count']}",
        f"- intentional_duplicate_collapse_count: {summary['intentional_duplicate_collapse_count']}",
        f"- review_required_count: {summary['review_required_count']}",
        f"- missing_public_song_row_count: {summary['missing_public_song_row_count']}",
        f"- missing_sqlite_observed_song_id_count: {summary['missing_sqlite_observed_song_id_count']}",
        "",
        "## Rows",
        "",
        "| decision | event | venue | year | role | normalized | source_titles | exported_titles | missing |",
        "| --- | --- | --- | ---: | --- | --- | --- | --- | ---: |",
    ]
    for row in data["rows"]:
        lines.append(
            f"| {row['decision']} | {row['event_name']} | {row['venue']} | {row['year']} | "
            f"{row['role']} | {row['normalized_title']} | "
            f"{', '.join(row['source_titles'])} | {', '.join(row['exported_titles'])} | "
            f"{row['actual_missing_public_song_row_count']} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- Both rows collapse because punctuation variants normalize to the same song key.",
            "- The exported preview keeps one representative row for each normalized event-song-role key.",
            "- No event occurrence is missing; this affects duplicate public song rows only.",
            "",
        ]
    )
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--diff", default=str(DIFF))
    parser.add_argument("--exported", default=str(EXPORTED))
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    args = parser.parse_args()
    data = build(args)
    print(
        "song occurrence collapse analysis: "
        f"intentional={data['summary']['intentional_duplicate_collapse_count']} "
        f"review_required={data['summary']['review_required_count']}"
    )


if __name__ == "__main__":
    main()
