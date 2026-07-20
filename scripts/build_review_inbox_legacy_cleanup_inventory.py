#!/usr/bin/env python3
"""Inventory retained legacy review inputs before a review-inbox cleanup.

This is deliberately read-only.  B5 closes legacy *console outputs*, but some
legacy-shaped JSON is still a fresh adapter input used to prove parity.  The
inventory makes that distinction explicit before any move or deletion.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

# The manifest is intentionally finite: adding a new retained source requires a
# conscious contract change rather than silently classifying arbitrary files.
SOURCES = (
    ("rare_signal_backcheck", "data/rare_signal_backcheck_queue.json", "parity_input", "B2 adapter input; do not remove while scheduled dual-write remains enabled."),
    ("youtube_active", "data/youtube_active_video_review.json", "parity_input", "B3 aggregate adapter input."),
    ("youtube_year_backfill", "data/youtube_year_backfill_review_queue.json", "parity_input", "B3 aggregate adapter input."),
    ("youtube_user_confirmation", "data/youtube_user_confirmation_queue.json", "parity_input", "B3 aggregate adapter input."),
    ("daily_song", "data/weekly_song_candidates_review.json", "parity_input", "B4 adapter input."),
    ("daily_term", "data/weekly_harvest_review_candidates.json", "parity_input", "B4 adapter input."),
    ("accepted_venue_song_missing_venue", "data/accepted_venue_song_missing_venue_review.json", "parity_input", "B4 adapter input."),
    ("historical_reference_quality", "data/historical_reference_quality_review.json", "parity_input", "B4 adapter input."),
    ("publication_gap", "data/publication_gap_review.json", "parity_input", "B4 adapter input."),
    ("legacy_official_source", "data/official_source_review_candidates.json", "rollback_snapshot", "B1 legacy reader snapshot; retained only for rollback."),
    ("legacy_registered_investigation", "data/registered_event_investigation_queue.json", "rollback_snapshot", "B1 legacy reader snapshot; retained only for rollback."),
    ("legacy_predicted_research", "data/predicted_occurrence_research_queue.json", "rollback_snapshot", "B1 legacy reader snapshot; retained only for rollback."),
    ("legacy_predicted_date_review", "data/predicted_occurrence_date_review.json", "rollback_snapshot", "B1 legacy reader snapshot; retained only for rollback."),
    ("legacy_missing_source_url", "data/missing_source_url_review.json", "rollback_snapshot", "B1 legacy reader snapshot; retained only for rollback."),
    ("legacy_missing_venue", "data/missing_occurrence_venue_review.json", "rollback_snapshot", "B1 legacy reader snapshot; retained only for rollback."),
    ("legacy_historical_promotion", "data/historical_promotion_candidate_review.json", "rollback_snapshot", "B1 legacy reader snapshot; retained only for rollback."),
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_files(root: Path) -> list[Path]:
    paths = []
    for relative in (".github/workflows",):
        directory = root / relative
        if directory.is_dir():
            paths.extend(sorted(directory.rglob("*.yml")))
    paths.extend(sorted(root.glob("review_inbox*.py")))
    paths.extend(sorted(root.glob("run_review_inbox*.py")))
    paths.append(root / "review_console" / "data.py")
    return [path for path in paths if path.is_file()]


def references(root: Path, relative_path: str) -> list[str]:
    needle = relative_path.removeprefix("data/")
    found = []
    for path in text_files(root):
        if needle in path.read_text(encoding="utf-8"):
            found.append(str(path.relative_to(root)))
    return found


def build_inventory(root: Path) -> dict:
    rows = []
    for source_id, relative_path, category, rationale in SOURCES:
        path = root / relative_path
        is_file = path.is_file()
        rows.append({
            "source_id": source_id,
            "path": relative_path,
            "category": category,
            "rationale": rationale,
            "exists": path.exists(),
            "sha256": sha256(path) if is_file else None,
            "workflow_or_adapter_references": references(root, relative_path),
        })
    return {
        "schema_version": 1,
        "generated_by": "scripts/build_review_inbox_legacy_cleanup_inventory.py",
        "write_boundary": "read_only",
        "rows": rows,
        "category_counts": {
            category: sum(row["category"] == category for row in rows)
            for category in sorted({row["category"] for row in rows})
        },
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Review inbox legacy cleanup inventory",
        "",
        "この棚卸しはread-onlyであり、削除・移動・workflow変更を行わない。",
        "",
        "| source | path | category | exists | references |",
        "| --- | --- | --- | --- | ---: |",
    ]
    for row in report["rows"]:
        lines.append(f"| {row['source_id']} | `{row['path']}` | {row['category']} | {str(row['exists']).lower()} | {len(row['workflow_or_adapter_references'])} |")
    lines.extend(["", "## Rules", "", "- `parity_input` は対応するscheduled adapterとparity検証が残る間、削除・移動しない。", "- `rollback_snapshot` はconsoleの既定入力に戻さず、rollback手順に従ってのみ参照する。", "- manifest外のlegacy候補は、このinventoryへ追加してから別レビューで扱う。", ""])
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    args = parser.parse_args()
    report = build_inventory(args.root.resolve())
    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.out_md.write_text(render_markdown(report), encoding="utf-8")


if __name__ == "__main__":
    main()
