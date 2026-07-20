#!/usr/bin/env python3
"""Generate local fallback glossary/song review artifacts without applying decisions."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


DATA = Path("data")
REPORT_JSON = DATA / "manual_glossary_review_run.json"
REPORT_MD = DATA / "manual_glossary_review_run.md"


def run_command(args: list[str]) -> dict:
    result = subprocess.run(args, text=True, capture_output=True)
    return {
        "command": args,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def command_line(args: list[str]) -> str:
    return " ".join(args)


def render_markdown(report: dict) -> str:
    lines = [
        "# 日次X収穫レビュー生成（手動fallback）",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- status: {report['status']}",
        f"- days: {report['days']}",
        "",
        "## outputs",
        "",
    ]
    for path in report["outputs"]:
        lines.append(f"- `{path}`")
    lines.extend(["", "## commands", ""])
    for item in report["commands"]:
        status = "ok" if item["returncode"] == 0 else f"failed:{item['returncode']}"
        lines.append(f"- `{command_line(item['command'])}` -> {status}")
        if item.get("stdout"):
            lines.extend(["", "```text", item["stdout"][:2000], "```", ""])
        if item.get("stderr"):
            lines.extend(["", "```text", item["stderr"][:2000], "```", ""])
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument(
        "--manual",
        action="store_true",
        help="Required to generate local fallback review artifacts.",
    )
    args = parser.parse_args()

    if not args.manual:
        raise SystemExit(
            "run_manual_glossary_review.py is a manual local fallback. "
            "Use `python3 run_manual_glossary_review.py --manual --days 7`."
        )

    commands = [
        ["python3", "build_weekly_harvest_candidates.py", "--days", str(args.days)],
        ["python3", "triage_weekly_song_candidates.py", "--dry-run"],
        ["python3", "prepare_weekly_harvest_review.py"],
        [
            "python3",
            "build_keyboard_review_ui.py",
            "--input",
            "data/weekly_harvest_review_candidates.json",
            "--rows-key",
            "rows",
            "--out",
            "data/weekly_harvest_review_ui.html",
            "--title",
            "日次X収穫レビュー（用語・共起）",
            "--summary-fields",
            "interpretation,type,confidence,evidence_count",
            "--detail-fields",
            "reason,evidence_text,evidence_url",
            "--source-field",
            "evidence",
            "--key-fields",
            "term,category,type,evidence_url",
            "--download-name",
            "weekly_harvest_review_decisions.json",
            "--storage-key",
            "weekly-harvest-review-v1",
        ],
        [
            "python3",
            "build_keyboard_review_ui.py",
            "--input",
            "data/weekly_song_candidates_review.json",
            "--rows-key",
            "rows",
            "--out",
            "data/weekly_song_candidates_review_ui.html",
            "--title",
            "日次X収穫レビュー（曲候補）",
            "--summary-fields",
            "canonical_song_name,triage_reason,evidence_count",
            "--detail-fields",
            "reason,evidence_text,evidence_url",
            "--source-field",
            "evidence",
            "--key-fields",
            "term,category,type,evidence_url",
            "--decisions-labels",
            "採用,不採用,曲マスタ外,保留",
            "--download-name",
            "weekly_song_review_decisions.json",
            "--storage-key",
            "weekly-song-review-v1",
        ],
    ]

    results = []
    status = "ok"
    for command in commands:
        item = run_command(command)
        results.append(item)
        if item["returncode"] != 0:
            status = "failed"
            if not args.continue_on_error:
                break

    outputs = [
        "data/weekly_harvest_candidates.json",
        "data/weekly_song_triage_result.json",
        "data/weekly_song_candidates_review.json",
        "data/weekly_harvest_review_candidates.json",
        "data/weekly_harvest_summary.json",
        "data/weekly_harvest_summary.md",
        "data/weekly_harvest_review_ui.html",
        "data/weekly_song_candidates_review_ui.html",
    ]
    report = {
        "generated_by": "run_manual_glossary_review.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "days": args.days,
        "commands": results,
        "outputs": outputs,
    }
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(render_markdown(report), encoding="utf-8")
    print(f"local harvest review fallback: {status} -> {REPORT_MD}")
    if status != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
