#!/usr/bin/env python3
"""Build a read-only P3 shadow report across all current song entrances.

The command reads the master SQLite artifact in URI ``mode=ro`` and only
writes when ``--out-json`` and/or ``--out-md`` is explicitly supplied. It
does not update source artifacts, review_inbox, the master RDB, or public data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from song_processing.song_catalog import SongCatalog
from song_processing.song_evidence_adapters import (
    adapt_human_change_requests,
    adapt_ocr_reviews,
    adapt_x_candidates,
    adapt_youtube_setlists,
    build_snapshot,
    resolve_occurrence_target,
)


DATA = Path("data")
DEFAULT_DB = DATA / "bon_odori_master.sqlite"
DEFAULT_X = DATA / "weekly_harvest_candidates.json"
DEFAULT_YOUTUBE = DATA / "youtube_setlist_occurrences.json"
DEFAULT_OCR = DATA / "song_ocr_review.json"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def lineage(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    return {
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }


def open_read_only(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise FileNotFoundError(f"master DB is missing: {path}")
    return sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)


def build_report(
    *,
    db_path: Path,
    x_path: Path,
    youtube_path: Path,
    ocr_path: Path,
    human_paths: list[Path] | None = None,
) -> dict[str, Any]:
    inputs = {
        "x": lineage(x_path),
        "youtube": lineage(youtube_path),
        "ocr": lineage(ocr_path),
        "human": [lineage(path) for path in (human_paths or [])],
        "master_db": lineage(db_path),
    }
    candidates = []
    candidates.extend(adapt_x_candidates(load_json(x_path)))
    candidates.extend(adapt_youtube_setlists(load_json(youtube_path)))
    candidates.extend(adapt_ocr_reviews(load_json(ocr_path)))
    for path in human_paths or []:
        candidates.extend(adapt_human_change_requests(load_json(path)))

    conn = open_read_only(db_path)
    try:
        catalog = SongCatalog.from_connection(conn)
        snapshot = build_snapshot(
            candidates,
            catalog,
            occurrence_resolver=lambda target: resolve_occurrence_target(conn, target),
        )
    finally:
        conn.close()
    snapshot["generated_by"] = Path(__file__).name
    snapshot["inputs"] = inputs
    return snapshot


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Song evidence adapter shadow",
        "",
        f"- write mode: `{report['write_mode']}`",
        f"- candidates: {report['candidate_count']}",
        f"- sources: `{json.dumps(report['source_counts'], ensure_ascii=False, sort_keys=True)}`",
        f"- routes: `{json.dumps(report['route_counts'], ensure_ascii=False, sort_keys=True)}`",
        f"- catalog states: `{json.dumps(report['catalog_state_counts'], ensure_ascii=False, sort_keys=True)}`",
        "",
        "## Auto-link samples",
        "",
        "| source | raw title | canonical | occurrence | reason |",
        "|---|---|---|---|---|",
    ]
    auto_rows = [row for row in report["items"] if row["route"] == "auto_link"][:20]
    for row in auto_rows:
        lines.append(
            "| {source} | {raw} | {canonical} | {occurrence} | {reason} |".format(
                source=row["source_kind"],
                raw=row["raw_song_title"].replace("|", "\\|"),
                canonical=(row["catalog_resolution"]["canonical_title"] or "").replace("|", "\\|"),
                occurrence=row["event_resolution"].get("occurrence_id") or "",
                reason=row["reason_code"],
            )
        )
    if not auto_rows:
        lines.append("| - | - | - | - | no auto-link candidates |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--x", type=Path, default=DEFAULT_X)
    parser.add_argument("--youtube", type=Path, default=DEFAULT_YOUTUBE)
    parser.add_argument("--ocr", type=Path, default=DEFAULT_OCR)
    parser.add_argument("--human", type=Path, action="append", default=[])
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--out-md", type=Path)
    args = parser.parse_args()

    report = build_report(
        db_path=args.db,
        x_path=args.x,
        youtube_path=args.youtube,
        ocr_path=args.ocr,
        human_paths=args.human,
    )
    if args.out_json:
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if args.out_md:
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.write_text(markdown(report), encoding="utf-8")
    print(
        "song evidence adapter shadow: "
        f"candidates={report['candidate_count']} routes={report['route_counts']}"
    )


if __name__ == "__main__":
    main()
