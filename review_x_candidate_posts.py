"""
Review X candidate accounts by their recent posts.

Input:
- data/x_candidate_accounts.json from discover_x_social_graph.py

Output:
- data/x_candidate_post_review.json

This is the second stage after graph discovery. Follow graph only finds
candidate accounts; promotion should be based on post quantity and quality.
"""

import json
import os
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

import collect
from collection_support import x_budget_guard as budget_guard
from collection_support import x_cost_ledger


TWITTERAPI_IO_KEY = os.environ.get("TWITTERAPI_IO_KEY")
CONFIG_FILE = Path("x_queries.json")
CANDIDATES_FILE = Path("data/x_candidate_accounts.json")
REVIEW_FILE = Path("data/x_candidate_post_review.json")


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def norm_handle(handle):
    return (handle or "").strip().lstrip("@").lower()


def fetch_candidate_posts(user_name, cursor=""):
    return collect._x_search(f"from:{user_name} -filter:retweets", cursor)


def estimate_search_credits(tweet_count, cfg):
    pricing = cfg.get("candidate_post_review", {}).get("pricing", {})
    per_tweet = pricing.get("tweet_credits_per_tweet_estimate", 15)
    return max(1, tweet_count) * per_tweet


def map_tweet(tw, fallback_handle):
    author = tw.get("author") or {}
    username = author.get("userName") or author.get("screen_name") or fallback_handle
    tw_id = tw.get("id") or tw.get("id_str") or ""
    url = tw.get("url") or (f"https://x.com/{username}/status/{tw_id}" if username and tw_id else "")
    return {
        "source": "x_candidate_review",
        "account": f"@{username}" if username else f"@{fallback_handle}",
        "name": author.get("name", ""),
        "title": "",
        "text": (tw.get("text") or tw.get("full_text") or "").strip()[:500],
        "url": url,
        "date": tw.get("createdAt") or tw.get("created_at") or "",
        "tags": [],
    }


def review_candidate(candidate, cfg, known_venues):
    handle = norm_handle(candidate.get("handle"))
    pages = cfg.get("candidate_post_review", {}).get(
        "search_pages_per_candidate",
        cfg.get("candidate_post_review", {}).get("timeline_pages_per_candidate", 1),
    )
    cursor = ""
    tweets = []
    calls = 0
    credits = 0

    for _ in range(pages):
        try:
            data = fetch_candidate_posts(handle, cursor)
        except urllib.error.HTTPError as e:
            return {
                "handle": candidate.get("handle"),
                "error": f"HTTP {e.code}",
                "tweets_checked": 0,
                "credits": 0,
                "calls": calls,
            }
        except Exception as e:
            return {
                "handle": candidate.get("handle"),
                "error": str(e),
                "tweets_checked": 0,
                "credits": 0,
                "calls": calls,
            }
        page_tweets = data.get("tweets") or data.get("data") or []
        calls += 1
        credits += estimate_search_credits(len(page_tweets), cfg)
        tweets.extend(page_tweets)
        cursor = data.get("next_cursor") or data.get("cursor") or ""
        if not (data.get("has_next_page", bool(cursor)) and cursor):
            break

    valuable = []
    total_value = 0.0
    reason_counts = {}
    for tw in tweets:
        voice = map_tweet(tw, handle)
        value, reasons = collect._x_post_value_score(voice, cfg, known_venues)
        total_value += value
        for r in reasons:
            reason_counts[r] = reason_counts.get(r, 0) + 1
        if value >= cfg.get("account_ranking", {}).get("min_keep_post_score", 0.0):
            valuable.append({
                "value_score": round(value, 3),
                "reasons": reasons,
                "text": voice["text"],
                "url": voice["url"],
                "date": voice["date"],
            })

    checked = max(len(tweets), 1)
    avg_value = total_value / checked
    future_count = reason_counts.get("future_schedule", 0)
    valuable_count = len(valuable)
    promote_score = avg_value + min(6.0, valuable_count * 0.7) + min(6.0, future_count * 2.0)

    return {
        "handle": candidate.get("handle"),
        "name": candidate.get("name", ""),
        "description": candidate.get("description", ""),
        "graph_candidate_score": candidate.get("candidate_score", 0),
        "graph_reasons": candidate.get("reasons", []),
        "discovered_by_count": len(candidate.get("discovered_by", [])),
        "tweets_checked": len(tweets),
        "valuable_posts": valuable_count,
        "future_schedule_posts": future_count,
        "post_avg_value": round(avg_value, 3),
        "promote_score": round(promote_score, 3),
        "reason_counts": reason_counts,
        "sample_valuable_posts": sorted(valuable, key=lambda v: -v["value_score"])[:5],
        "credits": credits,
        "calls": calls,
    }


def main():
    if not TWITTERAPI_IO_KEY:
        print("[review] TWITTERAPI_IO_KEY 未設定のためスキップ")
        return 0

    cfg = load_json(CONFIG_FILE, {})
    review_cfg = cfg.get("candidate_post_review", {})
    if not review_cfg.get("enabled", True):
        print("[review] candidate_post_review disabled")
        return 0

    # 日次収集と同じ予算帳簿を見る。これが無い間は使った分を自己申告するだけで
    # 上限に当たっても止まらず、そのため手動実行専用に留められていた。
    allowed, budget_message = budget_guard.check(cfg)
    print(f"[review] {budget_message}")
    if not allowed:
        return 0

    candidate_data = load_json(CANDIDATES_FILE, {"candidates": []})
    candidates = candidate_data.get("candidates", [])[:review_cfg.get("max_candidates", 30)]
    if not candidates:
        print("[review] 候補アカウントがありません")
        return 0

    known_venues = collect._load_known_venues()
    credit_usd = review_cfg.get("credit_usd", 0.00001)
    sleep_sec = cfg.get("page_sleep_sec", 2)
    results = []
    total_credits = 0
    total_calls = 0

    for candidate in candidates:
        result = review_candidate(candidate, cfg, known_venues)
        results.append(result)
        total_credits += result.get("credits", 0)
        total_calls += result.get("calls", 0)
        time.sleep(sleep_sec)

    min_promote_score = review_cfg.get("min_promote_score", 5.0)
    min_valuable = review_cfg.get("min_valuable_posts", 2)
    min_future = review_cfg.get("min_future_schedule_posts", 1)
    for r in results:
        if r.get("error"):
            r["recommendation"] = "error"
        elif (
            r.get("promote_score", 0) >= min_promote_score
            and r.get("valuable_posts", 0) >= min_valuable
            and r.get("future_schedule_posts", 0) >= min_future
        ):
            r["recommendation"] = "promote"
        else:
            r["recommendation"] = "watch" if r.get("valuable_posts", 0) > 0 else "reject"

    results.sort(key=lambda r: (
        {"promote": 0, "watch": 1, "reject": 2, "error": 3}.get(r.get("recommendation"), 4),
        -r.get("promote_score", 0),
        -r.get("future_schedule_posts", 0),
        r.get("handle", ""),
    ))
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reviewed_candidates": len(results),
        "cost_estimate": {
            "calls": total_calls,
            "credits": total_credits,
            "usd": round(total_credits * credit_usd, 6),
        },
        "recommendation_counts": {
            "promote": sum(1 for r in results if r.get("recommendation") == "promote"),
            "watch": sum(1 for r in results if r.get("recommendation") == "watch"),
            "reject": sum(1 for r in results if r.get("recommendation") == "reject"),
            "error": sum(1 for r in results if r.get("recommendation") == "error"),
        },
        "results": results,
    }
    output["notion_member_sync"] = {
        "skipped": "requires_user_approval",
        "promote_candidates": output["recommendation_counts"]["promote"],
        "note": (
            "Xメンバーリストへの追加は自動実行しない。"
            "内田さんが user_approved=true を付けた promote だけ、"
            "sync_x_promoted_members.py で同期する。"
        ),
    }
    REVIEW_FILE.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[review] reviewed: {len(results)}")
    print(f"[review] recommendations: {output['recommendation_counts']}")
    print(f"[review] estimated cost: {total_credits} credits / ${output['cost_estimate']['usd']:.6f}")
    budget_guard.record_spend(output["cost_estimate"]["usd"])
    x_cost_ledger.record_run(
        "candidate_probe",
        cost_usd=output["cost_estimate"]["usd"],
        requests=total_calls,
        tweets_fetched=sum(r.get("tweets_checked", 0) for r in results),
        voices_accepted=sum(r.get("valuable_posts", 0) for r in results),
        candidates_found=len(results),
        candidates_promoted=output["recommendation_counts"]["promote"],
        source="review_x_candidate_posts.py",
    )
    print(f"[review] notion member sync skipped: {output['notion_member_sync']}")
    for r in results[:10]:
        print(
            f"[review] {r.get('recommendation')} {r.get('handle')} "
            f"score={r.get('promote_score')} future={r.get('future_schedule_posts')} "
            f"valuable={r.get('valuable_posts')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
