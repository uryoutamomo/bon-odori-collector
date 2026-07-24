"""
X social graph discovery for bon-odori sources.

Small, manual-first experiment:
- Choose high-value seed accounts from data/x_account_scores.json.
- Fetch one page of followings for each seed via twitterapi.io.
- Aggregate candidates followed by valuable seeds.
- Save graph/candidates JSON and estimated cost.

This does not change the live X member list. It only creates reviewable data.
"""

import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


TWITTERAPI_IO_KEY = os.environ.get("TWITTERAPI_IO_KEY")
TWITTERAPI_IO_BASE = "https://api.twitterapi.io/twitter/user/followings"
CONFIG_FILE = Path("x_queries.json")
SCORES_FILE = Path("data/x_account_scores.json")
GRAPH_FILE = Path("data/x_social_graph.json")
CANDIDATES_FILE = Path("data/x_candidate_accounts.json")

PROFILE_VALUE_KEYWORDS = (
    "盆踊り", "盆おどり", "盆踊", "音頭", "民謡", "踊り", "踊る",
    "祭", "まつり", "夏祭り", "納涼", "やぐら", "櫓", "浴衣",
    "太鼓", "町会", "自治会", "商店街", "神社", "寺", "観光",
)


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def norm_handle(handle):
    return (handle or "").strip().lstrip("@").lower()


def choose_seeds(scores, cfg):
    discovery = cfg.get("social_graph_discovery", {})
    accounts = list((scores.get("accounts") or {}).values())
    max_seeds = discovery.get("max_seed_accounts", 10)
    seed_statuses = discovery.get("seed_statuses", ["trusted"])
    fallback_statuses = discovery.get("fallback_seed_statuses", ["active"])

    def ranked(statuses):
        return sorted(
            [a for a in accounts if a.get("status") in statuses],
            key=lambda a: (-a.get("score", 0), -a.get("valuable_posts", 0), a.get("handle", "")),
        )

    # Manually curated important informants are always worth a seed slot,
    # regardless of their observed score/status: thin post history should not
    # exclude someone Uchida-san has personally vetted. This checks the
    # manual_status flag directly instead of inflating the observed score, so
    # the score/status persisted to the evidence RDB keeps reflecting genuine
    # engagement (see collect.py's _annotate_important_informants).
    priority_seeds = sorted(
        [a for a in accounts if a.get("manual_status") == "優先"],
        key=lambda a: (-a.get("score", 0), a.get("handle", "")),
    )

    seeds = list(priority_seeds)
    seen = {norm_handle(s.get("handle")) for s in seeds}
    seeds.extend([a for a in ranked(seed_statuses) if norm_handle(a.get("handle")) not in seen])
    if len(seeds) < max_seeds:
        seen = {norm_handle(s.get("handle")) for s in seeds}
        seeds.extend([a for a in ranked(fallback_statuses) if norm_handle(a.get("handle")) not in seen])
    return seeds[:max_seeds]


def estimate_followings_credits(returned_count, cfg):
    pricing = cfg.get("social_graph_discovery", {}).get("pricing", {})
    min_credits = pricing.get("followings_min_credits_per_call", 60)
    per_user = pricing.get("followings_credits_per_user_at_200", 1)
    return max(min_credits, returned_count * per_user)


def fetch_followings(user_name, page_size, cursor=""):
    params = {"userName": user_name, "pageSize": page_size}
    if cursor:
        params["cursor"] = cursor
    url = f"{TWITTERAPI_IO_BASE}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"X-API-Key": TWITTERAPI_IO_KEY})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def profile_text(user):
    parts = [
        user.get("userName", ""),
        user.get("name", ""),
        user.get("description", ""),
        (user.get("profile_bio") or {}).get("description", ""),
        user.get("location", ""),
    ]
    return " ".join(p for p in parts if p)


def score_candidate(candidate, known_handles):
    user = candidate["profile"]
    text = profile_text(user)
    keyword_hits = [kw for kw in PROFILE_VALUE_KEYWORDS if kw in text]
    source_count = len(candidate["discovered_by"])
    seed_score_sum = sum(src.get("seed_score", 0) for src in candidate["discovered_by"])
    followers = user.get("followers") or 0
    following = user.get("following") or 0

    score = 0.0
    # Follow graph is only a discovery hint. Actual rank must come from post quality.
    score += min(3.0, source_count * 0.75)
    score += min(2.0, seed_score_sum / 50.0)
    score += min(6.0, len(keyword_hits) * 1.5)
    if followers:
        score += min(1.0, math.log10(max(followers, 1)) / 3.0)
    if following and followers:
        ratio = followers / max(following, 1)
        if ratio >= 0.5:
            score += 1.0
    if norm_handle(user.get("userName")) in known_handles:
        score -= 100.0

    reasons = []
    if source_count:
        reasons.append(f"graph_hint_followed_by_seeds:{source_count}")
    if keyword_hits:
        reasons.append("profile_keywords:" + ",".join(keyword_hits[:8]))
    if followers:
        reasons.append(f"followers:{followers}")
    if norm_handle(user.get("userName")) in known_handles:
        reasons.append("already_seen")
    return round(score, 3), reasons


def main():
    if not TWITTERAPI_IO_KEY:
        print("[social] TWITTERAPI_IO_KEY 未設定のためスキップ")
        return 0

    cfg = load_json(CONFIG_FILE, {})
    discovery = cfg.get("social_graph_discovery", {})
    if not discovery.get("enabled", True):
        print("[social] social_graph_discovery disabled")
        return 0

    scores = load_json(SCORES_FILE, {"accounts": {}})
    seeds = choose_seeds(scores, cfg)
    if not seeds:
        print("[social] seed account がありません")
        return 0

    page_size = discovery.get("page_size", 200)
    max_pages = discovery.get("max_pages_per_seed", 1)
    credit_usd = discovery.get("credit_usd", 0.00001)
    sleep_sec = cfg.get("page_sleep_sec", 2)
    known_handles = set(scores.get("accounts", {}).keys())

    graph = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "followings",
        "seeds": [],
        "edges": [],
        "cost_estimate": {"credits": 0, "usd": 0.0, "calls": 0, "returned_users": 0},
    }
    candidates = {}

    for seed in seeds:
        seed_handle = norm_handle(seed.get("handle"))
        cursor = ""
        seed_summary = {
            "handle": f"@{seed_handle}",
            "score": seed.get("score", 0),
            "status": seed.get("status", ""),
            "pages": 0,
            "returned_users": 0,
        }
        for _ in range(max_pages):
            try:
                data = fetch_followings(seed_handle, page_size, cursor)
            except urllib.error.HTTPError as e:
                print(f"[social] HTTP {e.code}: @{seed_handle}")
                break
            except Exception as e:
                print(f"[social] fetch error @{seed_handle}: {e}")
                break

            users = data.get("followings") or []
            returned = len(users)
            credits = estimate_followings_credits(returned, cfg)
            graph["cost_estimate"]["credits"] += credits
            graph["cost_estimate"]["calls"] += 1
            graph["cost_estimate"]["returned_users"] += returned
            seed_summary["pages"] += 1
            seed_summary["returned_users"] += returned

            for user in users:
                h = norm_handle(user.get("userName"))
                if not h:
                    continue
                graph["edges"].append({"source": f"@{seed_handle}", "target": f"@{h}", "type": "following"})
                cand = candidates.setdefault(h, {
                    "handle": f"@{h}",
                    "profile": user,
                    "discovered_by": [],
                })
                cand["discovered_by"].append({
                    "seed": f"@{seed_handle}",
                    "seed_score": seed.get("score", 0),
                    "seed_status": seed.get("status", ""),
                })

            cursor = data.get("next_cursor") or data.get("cursor") or ""
            if not (data.get("has_next_page") and cursor):
                break
            time.sleep(sleep_sec)
        graph["seeds"].append(seed_summary)

    graph["cost_estimate"]["usd"] = round(graph["cost_estimate"]["credits"] * credit_usd, 6)

    min_score = discovery.get("min_candidate_score", 3.0)
    out_candidates = []
    for cand in candidates.values():
        score, reasons = score_candidate(cand, known_handles)
        cand_out = {
            "handle": cand["handle"],
            "name": cand["profile"].get("name", ""),
            "description": cand["profile"].get("description", "") or (cand["profile"].get("profile_bio") or {}).get("description", ""),
            "location": cand["profile"].get("location", ""),
            "followers": cand["profile"].get("followers"),
            "following": cand["profile"].get("following"),
            "url": cand["profile"].get("url", ""),
            "candidate_score": score,
            "reasons": reasons,
            "discovered_by": cand["discovered_by"],
        }
        if score >= min_score:
            out_candidates.append(cand_out)

    out_candidates.sort(key=lambda c: (-c["candidate_score"], -len(c["discovered_by"]), c["handle"]))
    result = {
        "generated_at": graph["generated_at"],
        "cost_estimate": graph["cost_estimate"],
        "seed_count": len(seeds),
        "candidate_count": len(out_candidates),
        "candidates": out_candidates,
    }

    GRAPH_FILE.parent.mkdir(parents=True, exist_ok=True)
    GRAPH_FILE.write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding="utf-8")
    CANDIDATES_FILE.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[social] seeds: {len(seeds)}")
    print(f"[social] returned users: {graph['cost_estimate']['returned_users']}")
    print(f"[social] candidates: {len(out_candidates)}")
    print(f"[social] estimated cost: {graph['cost_estimate']['credits']} credits / ${graph['cost_estimate']['usd']:.6f}")
    for cand in out_candidates[:10]:
        print(f"[social] candidate {cand['handle']} score={cand['candidate_score']} by={len(cand['discovered_by'])} {cand['reasons'][:2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
