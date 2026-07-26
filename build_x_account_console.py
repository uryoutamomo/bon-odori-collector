#!/usr/bin/env python3
"""Build the X account roster view for the review console.

Until 2026-07-26 there was no way to see who we actually read on X. The roster
lived in Notion, the scores lived in a 5MB local JSON, and the two were never
shown side by side — so "誰が重要な盆踊ラーなのか把握できていない" was literally
true of the tooling, not just of the data.

This joins the two into one reviewable list: who is in the collection roster,
why (manual priority / auto-enrolled from score / official account), how good
their posts have been, and when we last saw them post.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import collect

OUT = Path("data") / "x_account_console.json"

SOURCE_LABELS = {
    "important_informant": "重要情報提供者（手動登録）",
    "collection_roster": "収集名簿（Notion移行分）",
    "auto_trusted": "スコアから自動編入",
    "official_or_organizer_social": "公式・主催アカウント",
    "notion_member_list": "Notionメンバーリスト",
}


def days_since(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - parsed).days


def build(accounts, scores, now=None):
    rows = []
    for account in accounts:
        handle = collect._norm_handle(account.get("handle"))
        score_row = scores.get(handle) or {}
        last_seen = score_row.get("last_seen") or ""
        silent_days = days_since(last_seen)
        manual_status = account.get("manual_status") or ""
        rows.append({
            "handle": f"@{handle}",
            "display_name": score_row.get("display_name") or account.get("name") or "",
            "roster_source": account.get("source_type") or "notion_member_list",
            "roster_source_label": SOURCE_LABELS.get(
                account.get("source_type") or "notion_member_list", "その他"
            ),
            "manual_status": manual_status or "通常",
            "score_status": score_row.get("status") or "unscored",
            "usefulness_rank": score_row.get("usefulness_rank") or "",
            "score": round(score_row.get("score") or 0, 2),
            "usefulness_score": score_row.get("usefulness_score") or 0,
            "posts_seen": score_row.get("posts_seen") or 0,
            "valuable_posts": score_row.get("valuable_posts") or 0,
            "future_schedule_posts": score_row.get("future_schedule_posts") or 0,
            "poster_image_posts": (score_row.get("top_reasons") or {}).get("media_hint", 0),
            "last_seen": last_seen,
            "silent_days": silent_days,
            "profile_url": f"https://x.com/{handle}",
            "review_hint": (
                "この情報源を今後も読むかを決める。優先=毎回必ず読む / 通常=スコア順 / "
                "休止=読まない。長く投稿が無い、盆踊り以外の投稿ばかり、といった場合は休止にする"
            ),
        })
    # 判断が必要な順: 手動優先 → スコア高 → 沈黙が長い
    rows.sort(
        key=lambda row: (
            0 if row["manual_status"] == "優先" else 1,
            -(row["usefulness_score"] or 0),
            row["handle"].lower(),
        )
    )
    stale = [row for row in rows if (row["silent_days"] or 0) >= 60]
    return {
        "generated_by": "build_x_account_console.py",
        "generated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "count": len(rows),
        "summary": {
            "manual_priority": sum(1 for row in rows if row["manual_status"] == "優先"),
            "manual_muted": sum(1 for row in rows if row["manual_status"] == "休止"),
            "auto_enrolled": sum(1 for row in rows if row["roster_source"] == "auto_trusted"),
            "trusted": sum(1 for row in rows if row["score_status"] == "trusted"),
            "silent_60d_or_more": len(stale),
        },
        "accounts": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    cfg = collect._load_x_config() or {}
    accounts = collect.load_whitelist_accounts(cfg)
    scores = collect._load_x_account_scores(cfg).get("accounts", {})
    output = build(accounts, scores)

    out_path = Path(args.out)
    out_path.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary = output["summary"]
    print(
        f"X情報源一覧を生成: {output['count']}アカウント "
        f"(優先{summary['manual_priority']} / 自動編入{summary['auto_enrolled']} / "
        f"休止{summary['manual_muted']} / 60日以上沈黙{summary['silent_60d_or_more']}) -> {out_path}"
    )


if __name__ == "__main__":
    main()
