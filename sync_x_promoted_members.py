"""Sync saved promote recommendations into the Notion X member list."""

import json
from pathlib import Path

import collect


REVIEW_FILE = Path("data/x_candidate_post_review.json")


def main():
    try:
        output = json.loads(REVIEW_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[review->notion] レビュー結果を読めません: {e}")
        return 1

    summary = collect.add_promoted_x_members(output.get("results", []))
    output["notion_member_sync"] = summary
    REVIEW_FILE.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 1 if summary.get("errors") or summary.get("skipped") else 0


if __name__ == "__main__":
    raise SystemExit(main())
