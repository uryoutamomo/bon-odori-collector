"""Dry-run export of public event-song occurrences from the master SQLite DB."""

import argparse
import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from rdb_builders.build_master_rdb import song_role
from master_rdb.master_db import MASTER_DB, connect_existing, json_text, normalize_text, stable_id


DATA = Path("data")
SOURCE_OCCURRENCES = DATA / "song_occurrences.json"
PUBLIC_OCCURRENCES = DATA / "public" / "event_song_occurrences_public.json"
OUT_JSON = DATA / "master_rdb_event_song_occurrences_public.dry_run.json"
OUT_DIFF = DATA / "master_rdb_event_song_occurrences_diff.json"
OUT_DIFF_MD = DATA / "master_rdb_event_song_occurrences_diff.md"


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


def parse_json(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def public_probability(value):
    if value is None:
        return None
    number = float(value)
    if number.is_integer():
        return int(number)
    return number


def export_rows(args):
    with connect_existing(args.db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT
              o.observed_occurrence_id,
              o.source_occurrence_id,
              o.raw_event_name,
              o.raw_venue_name,
              o.event_year,
              s.raw_song_title,
              s.normalized_title,
              s.match_status,
              master_song.canonical_title AS matched_canonical_title,
              master_song.status AS matched_song_status,
              s.role,
              s.probability,
              s.evidence_count,
              s.speaker_count,
              s.setlist_complete,
              s.prediction_reliability_json,
              s.evidence_urls_json,
              s.source_payload_json
            FROM observed_occurrences o
            LEFT JOIN observed_occurrence_songs s
              ON s.observed_occurrence_id = o.observed_occurrence_id
            LEFT JOIN songs master_song
              ON master_song.song_id = s.matched_song_id
            WHERE s.observed_occurrence_song_id IS NULL
               OR s.match_status != 'rejected_llm_review'
            ORDER BY o.event_year, o.raw_venue_name, o.raw_event_name, s.probability DESC, s.raw_song_title
            """
        ).fetchall()

    grouped = {}
    for row in rows:
        occurrence_id = row["source_occurrence_id"] or row["observed_occurrence_id"]
        occurrence = grouped.setdefault(
            row["observed_occurrence_id"],
            {
                "occurrence_id": occurrence_id,
                "event_name": row["raw_event_name"],
                "venue": row["raw_venue_name"] or "",
                "year": row["event_year"],
                "songs": [],
                "_songs_by_name": {},
            },
        )
        if row["raw_song_title"] is None:
            continue
        prediction = parse_json(row["source_payload_json"], {}).get("prediction") or {}
        name = row["matched_canonical_title"] or row["raw_song_title"]
        key = normalize_text(name)
        candidate = {
            "name": name,
            "probability": public_probability(row["probability"]),
            "basis": prediction.get("basis") or "unknown",
            "basis_label": prediction.get("basis_label") or "",
            "evidence_count": row["evidence_count"],
            "speaker_count": row["speaker_count"],
            "setlist_complete": bool(row["setlist_complete"]),
            "prediction_reliability": parse_json(row["prediction_reliability_json"], []),
            "evidence_urls": parse_json(row["evidence_urls_json"], []),
        }
        current = occurrence["_songs_by_name"].get(key)
        if current is None:
            occurrence["_songs_by_name"][key] = candidate
            occurrence["songs"].append(candidate)
            continue
        current["probability"] = max(
            value for value in (current.get("probability"), candidate.get("probability"))
            if value is not None
        ) if any(value is not None for value in (current.get("probability"), candidate.get("probability"))) else None
        current["evidence_count"] = int(current.get("evidence_count") or 0) + int(candidate.get("evidence_count") or 0)
        current["speaker_count"] = max(int(current.get("speaker_count") or 0), int(candidate.get("speaker_count") or 0))
        current["setlist_complete"] = bool(current.get("setlist_complete") or candidate.get("setlist_complete"))
        current["prediction_reliability"] = sorted(
            set(current.get("prediction_reliability") or [])
            | set(candidate.get("prediction_reliability") or [])
        )
        current["evidence_urls"] = list(
            dict.fromkeys((current.get("evidence_urls") or []) + (candidate.get("evidence_urls") or []))
        )

    occurrences = sorted(
        grouped.values(),
        key=lambda row: (row["year"], row["venue"], row["event_name"], row["occurrence_id"]),
    )
    for occurrence in occurrences:
        occurrence.pop("_songs_by_name", None)
        occurrence["songs"].sort(key=lambda row: (-(row["probability"] or 0), row["name"]))

    result = {
        "generated_by": "export_master_rdb_song_occurrences.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target_year": load_json(args.public_occurrences, {}).get("target_year"),
        "occurrences": occurrences,
    }
    if not args.production:
        result["dry_run"] = True
        result["source_database"] = str(args.db)
    return result


def occurrence_key(row):
    return (row.get("occurrence_id") or "", row.get("event_name") or "", row.get("venue") or "", row.get("year"))


def public_song_counter(data):
    counter = Counter()
    rows_by_key = {}
    for occurrence in data.get("occurrences") or []:
        occ_key = occurrence_key(occurrence)
        rows_by_key[occ_key] = occurrence
        for song in occurrence.get("songs") or []:
            counter[
                (
                    occ_key,
                    song.get("name") or "",
                    song.get("probability"),
                    song.get("basis") or "",
                    song.get("basis_label") or "",
                    song.get("evidence_count"),
                    song.get("speaker_count"),
                    bool(song.get("setlist_complete")),
                    tuple(song.get("prediction_reliability") or []),
                    tuple(song.get("evidence_urls") or []),
                )
            ] += 1
    return rows_by_key, counter


def source_observed_song_ids(source):
    counter = Counter()
    details = defaultdict(list)
    for occurrence in source.get("occurrences") or []:
        event_name = occurrence.get("event_name") or ""
        venue = occurrence.get("venue") or ""
        year = int(occurrence.get("year") or 0)
        observed_occurrence_id = stable_id(
            "obsocc",
            occurrence.get("occurrence_id") or "",
            event_name,
            venue,
            year,
        )
        for song in occurrence.get("songs") or []:
            title = song.get("song_name") or ""
            role = song_role(song, year)
            observed_song_id = stable_id("obsocs", observed_occurrence_id, normalize_text(title), role)
            counter[observed_song_id] += 1
            details[observed_song_id].append(
                {
                    "occurrence_id": occurrence.get("occurrence_id"),
                    "event_name": event_name,
                    "venue": venue,
                    "year": year,
                    "song_name": title,
                    "role": role,
                    "basis": (song.get("prediction") or {}).get("basis"),
                }
            )
    return counter, details


def sqlite_observed_song_ids(db_path):
    with connect_existing(db_path) as conn:
        return Counter(
            row[0]
            for row in conn.execute("SELECT observed_occurrence_song_id FROM observed_occurrence_songs")
        )


def compare(args, exported):
    public = load_json(args.public_occurrences, {})
    source = load_json(args.source_occurrences, {})
    public_occurrences, public_songs = public_song_counter(public)
    exported_occurrences, exported_songs = public_song_counter(exported)
    source_song_ids, source_song_id_details = source_observed_song_ids(source)
    sqlite_song_ids = sqlite_observed_song_ids(args.db)

    missing_occurrence_keys = sorted(set(public_occurrences) - set(exported_occurrences))
    extra_occurrence_keys = sorted(set(exported_occurrences) - set(public_occurrences))
    missing_public_song_rows = public_songs - exported_songs
    extra_public_song_rows = exported_songs - public_songs
    missing_sqlite_song_ids = source_song_ids - sqlite_song_ids
    duplicate_collapsed_ids = {
        key: count
        for key, count in source_song_ids.items()
        if count > 1
    }

    return {
        "generated_by": "export_master_rdb_song_occurrences.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": str(args.db),
        "public_source": str(args.public_occurrences),
        "source_occurrences": str(args.source_occurrences),
        "export": str(args.out_json),
        "summary": {
            "public_occurrence_count": len(public.get("occurrences") or []),
            "exported_occurrence_count": len(exported.get("occurrences") or []),
            "source_occurrence_count": len(source.get("occurrences") or []),
            "public_song_relation_count": sum(len(row.get("songs") or []) for row in public.get("occurrences") or []),
            "exported_song_relation_count": sum(len(row.get("songs") or []) for row in exported.get("occurrences") or []),
            "source_song_relation_count": sum(len(row.get("songs") or []) for row in source.get("occurrences") or []),
            "missing_occurrence_count": len(missing_occurrence_keys),
            "extra_occurrence_count": len(extra_occurrence_keys),
            "missing_public_song_row_count": sum(missing_public_song_rows.values()),
            "extra_public_song_row_count": sum(extra_public_song_rows.values()),
            "missing_sqlite_observed_song_id_count": sum(missing_sqlite_song_ids.values()),
            "duplicate_collapsed_observed_song_id_count": len(duplicate_collapsed_ids),
        },
        "field_coverage": {
            "speaker_count": "stored",
            "setlist_complete": "stored",
            "prediction_reliability": "stored",
            "evidence_urls": "stored_limited_to_public_first_5",
        },
        "missing_occurrences_sample": [list(key) for key in missing_occurrence_keys[:20]],
        "extra_occurrences_sample": [list(key) for key in extra_occurrence_keys[:20]],
        "missing_public_song_rows_sample": [
            {"count": count, "key": serialize_public_song_key(key)}
            for key, count in missing_public_song_rows.most_common(20)
        ],
        "extra_public_song_rows_sample": [
            {"count": count, "key": serialize_public_song_key(key)}
            for key, count in extra_public_song_rows.most_common(20)
        ],
        "missing_sqlite_observed_song_ids_sample": [
            {
                "observed_occurrence_song_id": key,
                "missing_count": count,
                "source_rows": source_song_id_details.get(key, [])[:5],
            }
            for key, count in missing_sqlite_song_ids.most_common(20)
        ],
        "duplicate_collapsed_observed_song_ids_sample": [
            {
                "observed_occurrence_song_id": key,
                "source_count": count,
                "source_rows": source_song_id_details.get(key, [])[:5],
            }
            for key, count in sorted(duplicate_collapsed_ids.items(), key=lambda item: (-item[1], item[0]))[:20]
        ],
    }


def serialize_public_song_key(key):
    occ_key, name, probability, basis, basis_label, evidence_count, speaker_count, setlist_complete, reliability, urls = key
    return {
        "occurrence": {
            "occurrence_id": occ_key[0],
            "event_name": occ_key[1],
            "venue": occ_key[2],
            "year": occ_key[3],
        },
        "song": {
            "name": name,
            "probability": probability,
            "basis": basis,
            "basis_label": basis_label,
            "evidence_count": evidence_count,
            "speaker_count": speaker_count,
            "setlist_complete": setlist_complete,
            "prediction_reliability": list(reliability),
            "evidence_urls": list(urls),
        },
    }


def render_markdown(diff):
    summary = diff["summary"]
    lines = [
        "# Master RDB event-song occurrence export diff",
        "",
        f"- generated_at: {diff['generated_at']}",
        f"- database: {diff['database']}",
        f"- export: {diff['export']}",
        "",
        "## Summary",
        "",
    ]
    for key, value in summary.items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Field coverage", ""])
    for key, value in diff["field_coverage"].items():
        lines.append(f"- {key}: {value}")
    if diff["duplicate_collapsed_observed_song_ids_sample"]:
        lines.extend(["", "## Duplicate collapsed observed song IDs", ""])
        for row in diff["duplicate_collapsed_observed_song_ids_sample"][:10]:
            first = row["source_rows"][0] if row["source_rows"] else {}
            lines.append(
                "- "
                f"{row['observed_occurrence_song_id']}: "
                f"source_count={row['source_count']} "
                f"{first.get('event_name')} / {first.get('venue')} / {first.get('year')} / {first.get('song_name')}"
            )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(MASTER_DB))
    parser.add_argument("--source-occurrences", default=str(SOURCE_OCCURRENCES))
    parser.add_argument("--public-occurrences", default=str(PUBLIC_OCCURRENCES))
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-diff", default=str(OUT_DIFF))
    parser.add_argument("--out-md", default=str(OUT_DIFF_MD))
    parser.add_argument("--production", action="store_true")
    parser.add_argument("--skip-compare", action="store_true")
    args = parser.parse_args()

    exported = export_rows(args)
    diff = None if args.skip_compare else compare(args, exported)
    write_json(args.out_json, exported)
    if diff:
        write_json(args.out_diff, diff)
        Path(args.out_md).write_text(render_markdown(diff), encoding="utf-8")
    print(
        "master rdb song occurrences export: "
        f"occurrences={len(exported['occurrences'])} "
        f"songs={sum(len(row.get('songs') or []) for row in exported['occurrences'])} "
        f"production={args.production}"
        + (
            " "
            f"missing_public_song_rows={diff['summary']['missing_public_song_row_count']} "
            f"extra_public_song_rows={diff['summary']['extra_public_song_row_count']}"
            if diff else ""
        )
    )


if __name__ == "__main__":
    main()
