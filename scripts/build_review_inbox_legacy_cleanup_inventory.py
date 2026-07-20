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
import subprocess


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

ALTERNATE_LIVE_WRITERS: dict[str, list[dict]] = {}

OUT_OF_SCOPE = (
    ("x_news_digest_for_oto / rare_signal_candidates", "machine discovery pipeline inputs, not review-inbox reader snapshots"),
    ("weekly_harvest_candidates", "upstream collection material; the review-inbox input is weekly_harvest_review_candidates"),
    ("x_candidate_post_review", "separate X account/member-list workflow"),
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


def git_provenance(root: Path, relative_path: str) -> dict | None:
    """Return the last committed snapshot identity when git metadata is available."""
    result = subprocess.run(
        ["git", "-C", str(root), "log", "-1", "--format=%H%x00%cI", "--", relative_path],
        capture_output=True,
        text=True,
        check=False,
    )
    value = result.stdout.strip()
    if not value or "\x00" not in value:
        return None
    commit, committed_at = value.split("\x00", 1)
    return {"commit": commit, "committed_at": committed_at}


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
            "alternate_live_writers": ALTERNATE_LIVE_WRITERS.get(source_id, []),
            "snapshot_provenance": git_provenance(root, relative_path) if category == "rollback_snapshot" else None,
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
        "alternate_live_writer_count": sum(bool(row["alternate_live_writers"]) for row in rows),
        "out_of_scope": [
            {"name": name, "reason": reason}
            for name, reason in OUT_OF_SCOPE
        ],
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Review inbox legacy cleanup inventory",
        "",
        "この棚卸しはread-onlyであり、削除・移動・workflow変更を行わない。",
        "",
        "| source | path | category | exists | references | alternate writer |",
        "| --- | --- | --- | --- | ---: | --- |",
    ]
    for row in report["rows"]:
        writers = ", ".join(writer["workflow"] for writer in row["alternate_live_writers"]) or "—"
        lines.append(f"| {row['source_id']} | `{row['path']}` | {row['category']} | {str(row['exists']).lower()} | {len(row['workflow_or_adapter_references'])} | {writers} |")
    lines.extend(["", "## Rules", "", "- `parity_input` は対応するscheduled adapterとparity検証が残る間、削除・移動しない。", "- `alternate_live_writer` がある入力は、手動workflowがlegacy UI再生成・commit・直接applyを行える。writerを退役・縮小・維持のいずれにするか、別レビューで明示決定するまで削除候補にしない。", "- `rollback_snapshot` はconsoleの既定入力に戻さず、rollback手順に従ってのみ参照する。JSONの `snapshot_provenance` は最終commitと時刻を記録する。", "- manifest外のlegacy候補は、このinventoryへ追加してから別レビューで扱う。", "", "## Out of scope", ""])
    lines.extend(f"- `{item['name']}`: {item['reason']}" for item in report.get("out_of_scope", []))
    lines.extend([
        "",
        "## Decision required before workflow cleanup",
        "",
        "2026-07-20に内田さんのGOで `weekly_harvest.yml` を縮小し、legacy keyboard-review HTMLの再生成、parity input JSONのcommit、`apply_reviewed` のNotion直接applyを外した。現在このinventory内にalternate live writerはない。",
        "",
        "選択した方針は2（縮小）である。workflowは公開更新・OCR・遡及収集などの手動fallbackを維持し、review inboxを迂回する人間レビュー・直接apply経路だけを持たない。",
        "",
        "rollback snapshot 7件の最終更新は2026-06-22〜2026-07-19であり、reader切替時点の最新状態を保証しない。このためrollbackは「古いlegacy snapshotを読む入口」であって、最新状態への復帰手段とはみなさない。",
        "",
    ])
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
