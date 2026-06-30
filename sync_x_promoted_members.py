"""Sync user-approved promote recommendations into the Notion X member list."""

import json
from pathlib import Path

import collect


REVIEW_FILE = Path("data/x_candidate_post_review.json")


def _is_user_approved(row):
    if row.get("user_approved") is True:
        return True
    if row.get("approved_by_user") is True:
        return True
    decision = str(row.get("registration_decision") or "").strip().lower()
    return decision in {"approve", "approved", "add", "register", "登録", "追加", "承認"}


def approved_promote_results(results):
    return [
        row for row in (results or [])
        if _is_user_approved(row)
    ]


def main():
    try:
        output = json.loads(REVIEW_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[review->notion] レビュー結果を読めません: {e}")
        return 1

    approved = approved_promote_results(output.get("results", []))
    if approved:
        summary = collect.add_promoted_x_members(approved)
    else:
        summary = {
            "promoted": 0,
            "added": 0,
            "existing": 0,
            "errors": 0,
            "skipped": "no_user_approved_promote",
            "note": "内田さん承認済みの promote 候補がないため追加しません。",
        }
        print("[review->notion] 承認済みpromote候補なし。追加スキップ")
    output["notion_member_sync"] = summary
    REVIEW_FILE.write_text(
        json.dumps(output, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return 1 if summary.get("errors") or summary.get("skipped") else 0


if __name__ == "__main__":
    raise SystemExit(main())
