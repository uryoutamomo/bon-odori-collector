"""Replace low-value X member-list accounts with reviewed candidates.

This script is intentionally explicit: candidates and paused accounts are
listed in code so a local run is auditable.
"""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from operation_safety.manual_apply_guards import LEGACY_NOTION_REPAIR_CONFIRMATION, require_confirmation


ADD_CANDIDATES = [
    {
        "handle": "@tadashi_isono",
        "name": "いその忠　(中央区議会議員)",
        "recommendation": "promote",
        "user_approved": True,
        "promote_score": 23.8,
        "tweets_checked": 2,
        "valuable_posts": 2,
        "future_schedule_posts": 1,
        "reason_counts": {"future_schedule": 1, "venue": 2, "date_time": 2},
    },
    {
        "handle": "@kasui21",
        "name": "逢樹ひろ",
        "recommendation": "promote",
        "user_approved": True,
        "promote_score": 11.8,
        "tweets_checked": 2,
        "valuable_posts": 2,
        "future_schedule_posts": 0,
        "reason_counts": {"venue": 1, "experience": 1},
    },
    {
        "handle": "@gokuraku_15",
        "name": "さとまり",
        "recommendation": "promote",
        "user_approved": True,
        "promote_score": 9.3,
        "tweets_checked": 2,
        "valuable_posts": 2,
        "future_schedule_posts": 0,
        "reason_counts": {"venue": 1, "date_time": 1},
    },
    {
        "handle": "@qtjittan",
        "name": "jittan",
        "recommendation": "promote",
        "user_approved": True,
        "promote_score": 9.3,
        "tweets_checked": 2,
        "valuable_posts": 2,
        "future_schedule_posts": 0,
        "reason_counts": {"experience": 1, "context": 1},
    },
    {
        "handle": "@kaz0045",
        "name": "オレンジ（Mishima Kazuhiro）",
        "recommendation": "promote",
        "user_approved": True,
        "promote_score": 17.8,
        "tweets_checked": 2,
        "valuable_posts": 2,
        "future_schedule_posts": 1,
        "reason_counts": {"future_schedule": 1, "experience": 1},
    },
]


PAUSE_HANDLES = [
    "@mrapple_bycandy",
    "@tarokoba55",
    "@fried_wakame",
    "@nakano_bonodori",
    "@kasumi_1030_",
]


def load_dotenv(path=".env"):
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def pause_accounts(handles):
    import collect

    wanted = {collect._norm_handle(handle) for handle in handles}
    accounts = collect.load_whitelist_accounts()
    paused = []
    missing = sorted(wanted)
    for account in accounts:
        handle = collect._norm_handle(account.get("handle"))
        if handle not in wanted:
            continue
        page_id = account.get("page_id")
        if not page_id:
            continue
        collect._update_page_props_best_effort(
            page_id,
            {"収集ステータス": {"select": {"name": "休止"}}},
        )
        paused.append(f"@{handle}")
        if handle in missing:
            missing.remove(handle)
    return {"paused": paused, "missing": [f"@{handle}" for handle in missing]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        require_confirmation(
            True,
            args.confirm,
            LEGACY_NOTION_REPAIR_CONFIRMATION,
            "legacy X member replacement",
        )
    except ValueError as exc:
        parser.error(str(exc))

    load_dotenv()

    import collect

    add_summary = collect.add_promoted_x_members(ADD_CANDIDATES)
    pause_summary = pause_accounts(PAUSE_HANDLES)
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "add_candidates": [row["handle"] for row in ADD_CANDIDATES],
        "pause_handles": PAUSE_HANDLES,
        "add_summary": add_summary,
        "pause_summary": pause_summary,
    }
    out = Path("data/x_member_replacement_result.json")
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if add_summary.get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
