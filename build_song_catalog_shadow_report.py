"""Observe-only comparison between the static "known song" provider and the
RDB-backed SongCatalog, across every source that currently feeds a song
name into either the public export or the daily triage.

This script never writes to the master DB or to any generated data file
that another pipeline reads. The only file it writes is the report itself,
and only when the caller explicitly asks for one via --out-json/--out-md;
with neither flag given, it writes nothing at all. It exists to answer,
before any runtime switch happens: what would change if extract_song_hints()
and weekly_song_triage.classify_candidate() consulted SongCatalog instead of
the static JSON files?

Sources compared (each string is looked up once, regardless of how many
sources mention it):
  - static: everything song_processing.bon_odori_songs.master_song_names()
    currently treats as "known" (song_master_initial_registration.json +
    rdb_song_review_source.json, the latter 100% unreviewed as of 2026-08-04)
  - rdb: canonical_title + alias rows straight from the songs/song_aliases
    tables (via SongCatalog)
  - weekly: the `term` field of every weekly_harvest_candidates.json row
    whose category is 曲候補 (song candidate) -- the same rows
    weekly_song_triage.classify_candidate() actually triages as songs.
    The file also carries 曲×会場共起 (song-venue co-occurrence) and
    用語候補 (glossary term candidate) rows, whose `term` values are not
    song-name candidates and are excluded here for that reason
  - public: every songs[].name currently in the exported public JSON
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from song_processing.song_catalog import SongCatalog, SongMatchType, SongReviewState

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_DB = REPO_ROOT / "data" / "bon_odori_master.sqlite"
DEFAULT_SONG_MASTER_REGISTRATION = REPO_ROOT / "data" / "song_master_initial_registration.json"
DEFAULT_RDB_SONG_REVIEW_SOURCE = REPO_ROOT / "data" / "rdb_song_review_source.json"
DEFAULT_WEEKLY_CANDIDATES = REPO_ROOT / "data" / "weekly_harvest_candidates.json"
DEFAULT_PUBLIC_EVENTS = REPO_ROOT / "data" / "public" / "events_public.json"

# The exact same divergence vocabulary is used regardless of how many
# sources mention a value, so downstream summaries stay a fixed shape.
DIVERGENCE_SAME_VERIFIED = "same_verified"
DIVERGENCE_STATIC_ONLY = "static_only"
DIVERGENCE_RDB_VERIFIED_ONLY = "rdb_verified_only"
DIVERGENCE_RDB_CANDIDATE_ONLY = "rdb_candidate_only"
DIVERGENCE_RDB_REJECTED_ONLY = "rdb_rejected_only"
DIVERGENCE_AMBIGUOUS_ALIAS = "ambiguous_alias"
DIVERGENCE_UNRESOLVED = "unresolved"

ALL_DIVERGENCE_CODES = (
    DIVERGENCE_SAME_VERIFIED,
    DIVERGENCE_STATIC_ONLY,
    DIVERGENCE_RDB_VERIFIED_ONLY,
    DIVERGENCE_RDB_CANDIDATE_ONLY,
    DIVERGENCE_RDB_REJECTED_ONLY,
    DIVERGENCE_AMBIGUOUS_ALIAS,
    DIVERGENCE_UNRESOLVED,
)


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _legacy_static_norm(value: str) -> str:
    """Reproduce song_processing.bon_odori_songs._norm_song() exactly:
    whitespace removal + casefold. This is the normalization the CURRENT
    static provider (is_master_song()) actually uses for membership tests,
    which differs from master_rdb.normalize_text() (used by SongCatalog).
    Comparing "static_is_master" with anything other than this exact
    normalization would not be a faithful shadow of current behavior."""
    return re.sub(r"\s+", "", str(value or "")).casefold()


def load_static_known_names(
    registration_path: Path, review_source_path: Path
) -> set[str]:
    """Reproduce exactly what master_song_names() in bon_odori_songs.py
    currently treats as known, without importing that module (which would
    pull in its module-level lru_cache tied to its own hardcoded paths)."""
    names: set[str] = set()
    registration = _load_json(registration_path)
    for bucket in ("created", "skipped"):
        for row in registration.get(bucket) or []:
            name = row.get("song_name")
            if name:
                names.add(name)

    review_source = _load_json(review_source_path)
    for row in review_source.get("rows") or []:
        name = row.get("canonical_song_name") or row.get("term")
        if name:
            names.add(name)

    return names


WEEKLY_SONG_CANDIDATE_CATEGORY = "曲候補"


def load_weekly_terms(path: Path) -> list[str]:
    """Only rows tagged as an actual song candidate (曲候補). The same file
    also carries 曲×会場共起 (song-venue co-occurrence) and 用語候補 (glossary
    term candidate) rows, whose `term` values are not song-name candidates
    and would inflate `unresolved` if compared as such."""
    data = _load_json(path)
    terms = []
    for row in data.get("rows") or []:
        if row.get("category") != WEEKLY_SONG_CANDIDATE_CATEGORY:
            continue
        term = row.get("term")
        if term:
            terms.append(term)
    return terms


def load_public_song_names(path: Path) -> list[str]:
    data = _load_json(path)
    events = data.get("events") if isinstance(data, dict) else data
    names = []
    for event in events or []:
        for song in event.get("songs") or []:
            name = song.get("name")
            if name:
                names.append(name)
    return names


def classify(
    value: str,
    *,
    static_norms: set[str],
    catalog: SongCatalog,
) -> tuple[str, dict]:
    static_hit = _legacy_static_norm(value) in static_norms
    resolution = catalog.resolve(value)
    has_rdb_match = resolution.match_type in (SongMatchType.CANONICAL, SongMatchType.ALIAS)

    # Classification order matters: an RDB row that matched but carries an
    # unrecognized/unknown status is a divergence in its own right (the RDB
    # has *something* for this value, just not a state we trust), and must
    # not be reported as "static_only" just because review_state isn't
    # VERIFIED/CANDIDATE/REJECTED.
    if resolution.match_type == SongMatchType.AMBIGUOUS_ALIAS:
        code = DIVERGENCE_AMBIGUOUS_ALIAS
    elif resolution.review_state == SongReviewState.VERIFIED:
        code = DIVERGENCE_SAME_VERIFIED if static_hit else DIVERGENCE_RDB_VERIFIED_ONLY
    elif resolution.review_state == SongReviewState.CANDIDATE:
        code = DIVERGENCE_RDB_CANDIDATE_ONLY
    elif resolution.review_state == SongReviewState.REJECTED:
        code = DIVERGENCE_RDB_REJECTED_ONLY
    elif has_rdb_match:
        # RDB matched (canonical/alias) but status is UNKNOWN: neither side
        # gives a trustworthy verdict, so this is unresolved rather than
        # "the static provider alone knows this" -- even if static_hit.
        code = DIVERGENCE_UNRESOLVED
    elif static_hit:
        code = DIVERGENCE_STATIC_ONLY
    else:
        code = DIVERGENCE_UNRESOLVED

    detail = {
        "value": value,
        "normalized": resolution.normalized_query,
        "static_is_master": static_hit,
        "rdb_match_type": resolution.match_type.value,
        "rdb_review_state": resolution.review_state.value,
        "rdb_canonical_title": resolution.canonical_title,
        "rdb_stored_status": resolution.stored_status,
        "divergence": code,
    }
    return code, detail


def build_report(
    *,
    db_path: Path,
    registration_path: Path,
    review_source_path: Path,
    weekly_path: Path,
    public_path: Path,
) -> dict:
    static_known = load_static_known_names(registration_path, review_source_path)
    static_norms = {_legacy_static_norm(name) for name in static_known}

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        catalog = SongCatalog.from_connection(conn)
        rdb_canonical_titles = {
            title for (title,) in conn.execute(
                "SELECT canonical_title FROM songs ORDER BY song_id"
            )
        }
        rdb_alias_values = {
            alias for (alias,) in conn.execute(
                "SELECT alias FROM song_aliases ORDER BY normalized_alias, song_id"
            )
        }
    finally:
        conn.close()

    weekly_terms = load_weekly_terms(weekly_path)
    public_names = load_public_song_names(public_path)

    # Every value that appears in any of the four sources, with which
    # source(s) it came from recorded per value. static_known and rdb
    # (canonical+alias) are themselves "sources" for this purpose so a
    # value known only to one side is still visible in the report.
    sources_by_value: dict[str, set[str]] = {}
    for name in static_known:
        sources_by_value.setdefault(name, set()).add("static")
    for term in weekly_terms:
        sources_by_value.setdefault(term, set()).add("weekly")
    for name in public_names:
        sources_by_value.setdefault(name, set()).add("public")
    # RDB canonical + alias strings themselves count as an "rdb" source so
    # a song known only to the RDB (and mentioned nowhere else) is visible.
    for title in rdb_canonical_titles:
        sources_by_value.setdefault(title, set()).add("rdb")
    for alias in rdb_alias_values:
        sources_by_value.setdefault(alias, set()).add("rdb")

    rows = []
    divergence_counts: Counter[str] = Counter()
    for value in sorted(sources_by_value):
        code, detail = classify(value, static_norms=static_norms, catalog=catalog)
        detail["sources"] = sorted(sources_by_value[value])
        rows.append(detail)
        divergence_counts[code] += 1

    source_counts = {
        "static": len(static_known),
        "weekly": len(weekly_terms),
        "weekly_unique": len(set(weekly_terms)),
        "public": len(public_names),
        "public_unique": len(set(public_names)),
        # Raw (pre-normalization) unique value counts, kept separate because
        # "canonical" and "alias" are different tables with different
        # meanings -- collapsing them under one "rdb_canonical" label (the
        # previous name) misrepresented what was actually counted.
        "rdb_canonical": len(rdb_canonical_titles),
        "rdb_alias": len(rdb_alias_values),
        "rdb_unique_values": len(rdb_canonical_titles | rdb_alias_values),
    }

    return {
        "generated_by": "build_song_catalog_shadow_report.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": {
            "db": str(db_path),
            "song_master_initial_registration": str(registration_path),
            "rdb_song_review_source": str(review_source_path),
            "weekly_harvest_candidates": str(weekly_path),
            "public_events": str(public_path),
        },
        "source_counts": source_counts,
        "divergence_counts": {code: divergence_counts.get(code, 0) for code in ALL_DIVERGENCE_CODES},
        "total_values": len(rows),
        "rows": rows,
    }


def render_markdown(report: dict) -> str:
    lines = ["# Song catalog shadow report", ""]
    lines.append(f"generated_at: {report['generated_at']}")
    lines.append("")
    lines.append("## Source counts")
    for key, value in report["source_counts"].items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    lines.append("## Divergence counts")
    for code in ALL_DIVERGENCE_CODES:
        lines.append(f"- {code}: {report['divergence_counts'].get(code, 0)}")
    lines.append("")
    lines.append(f"Total distinct values compared: {report['total_values']}")
    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--song-master-registration", type=Path, default=DEFAULT_SONG_MASTER_REGISTRATION
    )
    parser.add_argument(
        "--rdb-song-review-source", type=Path, default=DEFAULT_RDB_SONG_REVIEW_SOURCE
    )
    parser.add_argument("--weekly-candidates", type=Path, default=DEFAULT_WEEKLY_CANDIDATES)
    parser.add_argument("--public-events", type=Path, default=DEFAULT_PUBLIC_EVENTS)
    parser.add_argument("--out-json", type=Path, default=None)
    parser.add_argument("--out-md", type=Path, default=None)
    args = parser.parse_args()

    report = build_report(
        db_path=args.db,
        registration_path=args.song_master_registration,
        review_source_path=args.rdb_song_review_source,
        weekly_path=args.weekly_candidates,
        public_path=args.public_events,
    )

    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if args.out_md:
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.write_text(render_markdown(report), encoding="utf-8")

    print(
        "song catalog shadow report: "
        f"total_values={report['total_values']} "
        f"divergence={dict(report['divergence_counts'])}"
    )


if __name__ == "__main__":
    main()
