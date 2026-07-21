"""Build local validation samples and draft ranks for X bon-odori accounts.

This script is intentionally local-only. It does not call X or Notion.
It turns existing data/voices.json into:

- data/x_rank_validation_samples.json: posts for human review
- data/x_account_rank_proposal.json: account rank proposal
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import collect


VOICES_FILE = Path("data/voices.json")
SAMPLES_FILE = Path("data/x_rank_validation_samples.json")
PROPOSAL_FILE = Path("data/x_account_rank_proposal.json")


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def post_kind(reasons):
    reasons = set(reasons or [])
    tags = []
    if "future_schedule" in reasons or "schedule_like" in reasons:
        tags.append("発見型")
    if reasons.intersection({"future_schedule", "schedule_like", "venue", "date_time", "media_hint", "link"}):
        tags.append("裏取り型")
    if "experience" in reasons:
        tags.append("参加レポ型")
    if "venue" in reasons:
        tags.append("地域/会場型")
    if not tags:
        tags.append("文脈確認型")
    return tags


def short_text(text, limit=220):
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def scored_posts(voices, cfg, known_venues):
    posts = []
    for voice in voices:
        if voice.get("source") not in ("x", "x_whitelist"):
            continue
        account = collect._norm_handle(voice.get("account"))
        if not account:
            continue
        score, reasons = collect._x_post_value_score(voice, cfg, known_venues)
        posts.append({
            "account": f"@{account}",
            "name": voice.get("name", ""),
            "date": voice.get("date", ""),
            "url": voice.get("url", ""),
            "source": voice.get("source", ""),
            "score": round(score, 3),
            "reasons": reasons,
            "kind_tags": post_kind(reasons),
            "text": short_text(voice.get("text", "")),
            "review": {
                "human_label": "",
                "usefulness_type": [],
                "notes": "",
            },
        })
    return posts


def pick_validation_samples(posts, high_count=50, mid_count=20, low_count=10):
    ordered = sorted(posts, key=lambda p: (-p["score"], p.get("date", ""), p["account"]))
    high = ordered[:high_count]

    positive = [p for p in ordered if 1.5 <= p["score"] < 8.0]
    step = max(1, len(positive) // max(mid_count, 1))
    mid = positive[::step][:mid_count]

    low_pool = sorted(posts, key=lambda p: (p["score"], p["account"], p.get("date", "")))
    low = low_pool[:low_count]

    seen = set()
    samples = []
    for bucket_name, bucket in (("high", high), ("middle", mid), ("low", low)):
        for post in bucket:
            key = post.get("url") or (post["account"], post["date"], post["text"])
            if key in seen:
                continue
            seen.add(key)
            row = dict(post)
            row["sample_bucket"] = bucket_name
            samples.append(row)
    return samples


def rank_accounts(voices, cfg):
    scores = collect._build_x_account_scores(voices, cfg).get("accounts", {})
    rows = []
    for key, row in scores.items():
        rank = row.get("usefulness_rank", "Probation")
        rows.append({
            "handle": row.get("handle", f"@{key}"),
            "rank": rank,
            "usefulness_score": row.get("usefulness_score", 0),
            "confidence": row.get("confidence", "low"),
            "role_tags": row.get("role_tags", []),
            "auto_status": row.get("status", ""),
            "quality_score": row.get("quality_score", row.get("score", 0)),
            "lifetime_quality_score": row.get("lifetime_score", row.get("score", 0)),
            "recent_quality_score": row.get("recent_score", 0),
            "posts_seen": row.get("posts_seen", 0),
            "recent_posts_seen": row.get("recent_posts_seen", 0),
            "valuable_posts": row.get("valuable_posts", 0),
            "recent_valuable_posts": row.get("recent_valuable_posts", 0),
            "noise_posts": row.get("noise_posts", 0),
            "value_ratio": row.get("value_ratio", 0),
            "recent_value_ratio": row.get("recent_value_ratio", 0),
            "last_seen": row.get("last_seen", ""),
            "top_reasons": row.get("top_reasons", {}),
            "review": {
                "human_decision": "",
                "notes": "",
            },
        })
    rank_order = {"S": 0, "A": 1, "B": 2, "Candidate": 3, "Probation": 4, "Muted": 5}
    return sorted(rows, key=lambda r: (
        rank_order.get(r["rank"], 9),
        {"high": 0, "medium": 1, "low": 2}.get(r["confidence"], 9),
        -r["usefulness_score"],
        r["handle"].lower(),
    ))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--high", type=int, default=50)
    parser.add_argument("--mid", type=int, default=20)
    parser.add_argument("--low", type=int, default=10)
    args = parser.parse_args()

    voices = load_json(VOICES_FILE, [])
    cfg = collect._load_x_config() or {}
    known_venues = collect._load_known_venues()
    posts = scored_posts(voices, cfg, known_venues)
    samples = pick_validation_samples(posts, args.high, args.mid, args.low)
    proposal = rank_accounts(voices, cfg)

    generated_at = datetime.now(timezone.utc).isoformat()
    write_json(SAMPLES_FILE, {
        "generated_at": generated_at,
        "source_file": str(VOICES_FILE),
        "hypotheses": [
            "H1: 高スコア投稿は人間評価でも有益である",
            "H2: 有益投稿を複数出すアカウントは今後も役に立つ",
            "H3: 1投稿だけ高得点のアカウントは即Sランクにしない方がよい",
            "H4: 未来日程・会場名・写真/チラシ・リンクは裏取り成功率が高い",
            "H5: 参加レポ型は新規発見には弱いが行く判断に役立つ",
        ],
        "review_labels": ["有益", "微妙", "不要"],
        "samples": samples,
    })
    write_json(PROPOSAL_FILE, {
        "generated_at": generated_at,
        "source_file": str(VOICES_FILE),
        "rank_policy": {
            "S": "有益投稿8件以上、観測10件以上、スコア6以上",
            "A": "有益投稿3件以上、観測5件以上、スコア4以上",
            "B": "有益投稿2件以上、スコア3以上",
            "Candidate": "有益投稿はあるが継続性は未確認",
            "Muted": "低スコアまたはノイズ多め",
        },
        "accounts": proposal,
    })

    counts = {}
    for row in proposal:
        counts[row["rank"]] = counts.get(row["rank"], 0) + 1
    print(f"[rank] validation samples: {len(samples)} -> {SAMPLES_FILE}")
    print(f"[rank] account proposal: {len(proposal)} accounts -> {PROPOSAL_FILE}")
    print(f"[rank] rank counts: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
