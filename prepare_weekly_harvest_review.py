#!/usr/bin/env python3
"""Prepare weekly harvest review queues and a compact run summary."""

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_SOURCE = Path("data/weekly_harvest_candidates.json")
DEFAULT_SONG_TRIAGE = Path("data/weekly_song_triage_result.json")
DEFAULT_SONG_REVIEW = Path("data/weekly_song_candidates_review.json")
DEFAULT_REVIEW_OUT = Path("data/weekly_harvest_review_candidates.json")
DEFAULT_SUMMARY_JSON = Path("data/weekly_harvest_summary.json")
DEFAULT_SUMMARY_MD = Path("data/weekly_harvest_summary.md")


def load_json(path, default=None):
    if not path.exists():
        return default if default is not None else {}
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def split_non_song_review_rows(rows):
    return [row for row in rows if row.get("category") != "曲候補"]


def category_counts(rows):
    return dict(Counter(row.get("category") or "未分類" for row in rows))


def sample_terms(rows, limit=12):
    return [row.get("term", "") for row in rows[:limit] if row.get("term")]


def build_summary(source, song_triage, non_song_rows, song_review):
    all_rows = source.get("rows", [])
    song_review_rows = song_review.get("rows", [])
    summary = {
        "generated_by": "prepare_weekly_harvest_review.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source.get("generated_by", ""),
        "source_generated_at": source.get("generated_at", ""),
        "days": source.get("days"),
        "voice_count": source.get("voice_count", 0),
        "candidate_count": len(all_rows),
        "category_counts": category_counts(all_rows),
        "non_song_review_count": len(non_song_rows),
        "song_candidate_count": song_triage.get("song_candidate_count", 0),
        "song_direct_dry_run_count": song_triage.get("direct_count", 0),
        "song_review_count": len(song_review_rows),
        "song_rejected_noise_count": song_triage.get("rejected_noise_count", 0),
        "review_files": {
            "non_song_json": str(DEFAULT_REVIEW_OUT),
            "non_song_ui": "data/weekly_harvest_review_ui.html",
            "song_json": str(DEFAULT_SONG_REVIEW),
            "song_ui": "data/weekly_song_candidates_review_ui.html",
        },
        "apply_commands": [
            "python apply_weekly_song_review_decisions.py --dry-run",
            "python apply_weekly_harvest_human13_decisions.py --candidates data/weekly_harvest_review_candidates.json --decisions data/weekly_harvest_review_decisions.json --out data/weekly_harvest_apply_result.json --dry-run",
        ],
        "samples": {
            "non_song_review": sample_terms(non_song_rows),
            "song_review": sample_terms(song_review_rows),
        },
    }
    return summary


def render_markdown(summary):
    lines = [
        "# 週次収穫サマリ",
        "",
        f"- 生成時刻: {summary['generated_at']}",
        f"- 対象期間: 直近 {summary.get('days') or '?'} 日",
        f"- 対象voices: {summary['voice_count']}件",
        f"- 候補総数: {summary['candidate_count']}件",
        "",
        "## 内訳",
    ]
    for category, count in sorted(summary["category_counts"].items()):
        lines.append(f"- {category}: {count}件")
    lines += [
        "",
        "## レビュー対象",
        f"- 用語・共起レビュー: {summary['non_song_review_count']}件",
        f"- 曲候補レビュー: {summary['song_review_count']}件",
        f"- 曲の明白候補 dry-run: {summary['song_direct_dry_run_count']}件",
        f"- 曲ノイズ除外: {summary['song_rejected_noise_count']}件",
        "",
        "## 生成物",
    ]
    for label, path in summary["review_files"].items():
        lines.append(f"- {label}: `{path}`")
    lines += [
        "",
        "## 反映コマンド",
    ]
    for command in summary["apply_commands"]:
        lines.append(f"- `{command}`")
    if summary["samples"]["non_song_review"]:
        lines += ["", "## 用語・共起レビュー例"]
        lines.extend(f"- {term}" for term in summary["samples"]["non_song_review"])
    if summary["samples"]["song_review"]:
        lines += ["", "## 曲レビュー例"]
        lines.extend(f"- {term}" for term in summary["samples"]["song_review"])
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--song-triage", type=Path, default=DEFAULT_SONG_TRIAGE)
    parser.add_argument("--song-review", type=Path, default=DEFAULT_SONG_REVIEW)
    parser.add_argument("--review-out", type=Path, default=DEFAULT_REVIEW_OUT)
    parser.add_argument("--summary-json", type=Path, default=DEFAULT_SUMMARY_JSON)
    parser.add_argument("--summary-md", type=Path, default=DEFAULT_SUMMARY_MD)
    args = parser.parse_args()

    source = load_json(args.source, {"rows": []})
    song_triage = load_json(args.song_triage, {})
    song_review = load_json(args.song_review, {"rows": []})
    non_song_rows = split_non_song_review_rows(source.get("rows", []))

    review_payload = {
        "generated_by": "prepare_weekly_harvest_review.py",
        "source": str(args.source),
        "count": len(non_song_rows),
        "rows": non_song_rows,
    }
    write_json(args.review_out, review_payload)

    summary = build_summary(source, song_triage, non_song_rows, song_review)
    summary["review_files"]["non_song_json"] = str(args.review_out)
    summary["review_files"]["song_json"] = str(args.song_review)
    write_json(args.summary_json, summary)
    args.summary_md.write_text(render_markdown(summary), encoding="utf-8")

    print(
        "weekly harvest summary: candidates={candidate_count} non_song_review={non_song_review_count} "
        "song_review={song_review_count} song_direct_dry_run={song_direct_dry_run_count}".format(**summary)
    )
    print(f"wrote {args.review_out}")
    print(f"wrote {args.summary_json}")
    print(f"wrote {args.summary_md}")


if __name__ == "__main__":
    main()
