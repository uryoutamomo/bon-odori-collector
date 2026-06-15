"""Build a reviewed YouTube channel candidate list for manual harvesting."""

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path


DATA = Path("data")
IN = DATA / "youtube_channel_candidates.json"
OUT = DATA / "youtube_channel_review.json"
MARKDOWN_OUT = DATA / "youtube_channel_review.md"

MANUAL_REVIEWS = {
    "UCKCspf_NrY16rUnODmBqOWA": {
        "decision": "adopt",
        "priority": "high",
        "reason": "東京圏の盆踊り動画が多く、説明欄に会場・日付・MAP・章タイトルが入る。曜日誤記があるため日付検証と併用。",
        "next_action": "東京圏の2025実績発掘に使う。曜日つき日付は暦照合し、公式確認が必要な新規候補は保留する。",
    },
    "UCWz2tM7PAFGT7xSL5OAEllg": {
        "decision": "adopt",
        "priority": "high",
        "reason": "東京圏の街歩き・盆踊り動画があり、既存イベント照合に使える。",
        "next_action": "既存イベントへの動画証拠追加候補として優先確認する。",
    },
    "UCaVANrt14S6q-if2BBOE4TQ": {
        "decision": "adopt",
        "priority": "normal",
        "reason": "奥浅草の曲目つき動画で実績あり。英語説明が多く、曲目抽出と過去年実績の補完に向く。",
        "next_action": "台東区・浅草周辺の過去年実績と曲目証拠の発掘に使う。",
    },
    "UCEYq2_O_Sai0j9chJOmcKtQ": {
        "decision": "adopt",
        "priority": "normal",
        "reason": "丸の内de盆踊りの曲目つき動画で実績あり。件数は少ないが証拠品質が高い。",
        "next_action": "検索で見つかった東京圏動画を個別に確認し、公式確認済みイベントへ紐づける。",
    },
    "UCSHoRoW171uEytgOcKkKU2Q": {
        "decision": "adopt",
        "priority": "normal",
        "reason": "渋谷盆踊りで公式URL候補を説明欄に記載。公式導線発見に有用。",
        "next_action": "新規候補の公式URL探索補助として使う。YouTube単独では本登録しない。",
    },
    "UC0ez88LLPDj2D-WgHiL5nxA": {
        "decision": "hold",
        "priority": "low",
        "reason": "曲目情報はあるが福岡など東京23区外が中心。現行公開DBの範囲外。",
        "next_action": "全国展開や対象範囲拡張時に再確認する。",
    },
}

HOLD_WALK_REASONS = {
    "VioletVik",
    "Walk From Home 🇯🇵",
    "walk Tokyo walk・東京散歩",
    "kibikibi",
    "Jonior Visuals",
    "marry",
    "ノーリーエンタープライズ🪅",
}


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=".tmp-", suffix=".json", delete=False
    ) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        tmp_name = handle.name
    Path(tmp_name).replace(path)


def atomic_write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=".tmp-", suffix=".md", delete=False
    ) as handle:
        handle.write(text)
        tmp_name = handle.name
    Path(tmp_name).replace(path)


def review_channel(row):
    channel_id = row.get("channel_id") or ""
    title = row.get("channel_title") or ""
    if row.get("already_known"):
        return {
            "decision": "already_registered",
            "priority": "high" if row.get("candidate_score", 0) >= 60 else "normal",
            "reason": "既存YouTubeチャンネルDBに登録済み。",
            "next_action": "既存の定期/手動収集対象として維持する。",
        }
    if channel_id in MANUAL_REVIEWS:
        return MANUAL_REVIEWS[channel_id]
    if title in HOLD_WALK_REASONS:
        return {
            "decision": "hold",
            "priority": "low",
            "reason": "単発動画または街歩き寄りで、曲目・会場日付の継続抽出ソースとしては弱い。",
            "next_action": "同チャンネルから複数の東京圏盆踊り動画が見つかったら再確認する。",
        }
    if row.get("candidate_score", 0) >= 60:
        return {
            "decision": "review",
            "priority": "normal",
            "reason": "自動スコアは高いが手動判断未済。",
            "next_action": "サンプル動画を確認して採用可否を決める。",
        }
    return {
        "decision": "hold",
        "priority": "low",
        "reason": "現時点では採用判断に足る曲目・日付・東京圏継続性が不足。",
        "next_action": "検索範囲拡張後に再評価する。",
    }


def compact_sample_videos(row):
    videos = []
    for video in row.get("sample_videos") or []:
        videos.append({
            "title": video.get("title") or "",
            "url": video.get("url") or "",
            "published_at": video.get("published_at") or "",
            "event_date": video.get("event_date") or "",
            "setlist_count": video.get("setlist_count") or 0,
        })
    return videos[:3]


def build_review(payload):
    rows = []
    for channel in payload.get("channels") or []:
        review = review_channel(channel)
        rows.append({
            "channel_id": channel.get("channel_id") or "",
            "channel_title": channel.get("channel_title") or "",
            "channel_url": channel.get("channel_url") or "",
            "already_known": bool(channel.get("already_known")),
            "candidate_score": channel.get("candidate_score") or 0,
            "auto_review_status": channel.get("review_status") or "",
            "found_video_count": channel.get("found_video_count") or 0,
            "bon_context_video_count": channel.get("bon_context_video_count") or 0,
            "setlist_candidate_count": channel.get("setlist_candidate_count") or 0,
            "event_date_candidate_count": channel.get("event_date_candidate_count") or 0,
            "score_reasons": channel.get("score_reasons") or [],
            "decision": review["decision"],
            "priority": review["priority"],
            "review_reason": review["reason"],
            "next_action": review["next_action"],
            "sample_videos": compact_sample_videos(channel),
        })
    order = {"adopt": 0, "already_registered": 1, "review": 2, "hold": 3}
    priority_order = {"high": 0, "normal": 1, "low": 2}
    rows.sort(key=lambda row: (
        order.get(row["decision"], 9),
        priority_order.get(row["priority"], 9),
        -row["candidate_score"],
        row["channel_title"],
    ))
    counts = {}
    for row in rows:
        counts[row["decision"]] = counts.get(row["decision"], 0) + 1
    return {
        "generated_by": "build_youtube_channel_review.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(IN),
        "channel_count": len(rows),
        "counts": counts,
        "rows": rows,
    }


def md_escape(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def md_truncate(value, limit=90):
    value = md_escape(value)
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def render_markdown(review):
    lines = [
        "# YouTubeチャンネル候補レビュー",
        "",
        f"- 候補: {review['channel_count']}件",
    ]
    for decision, count in sorted(review["counts"].items()):
        lines.append(f"- {decision}: {count}件")
    lines.extend([
        "",
        "| decision | priority | score | チャンネル | 動画 | 曲目候補 | 日付 | 理由 | 次アクション |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for row in review["rows"]:
        lines.append(
            "| "
            f"{md_escape(row['decision'])} | "
            f"{md_escape(row['priority'])} | "
            f"{row['candidate_score']} | "
            f"{md_escape(row['channel_title'])} | "
            f"{row['found_video_count']} | "
            f"{row['setlist_candidate_count']} | "
            f"{row['event_date_candidate_count']} | "
            f"{md_truncate(row['review_reason'])} | "
            f"{md_truncate(row['next_action'])} |"
        )
    lines.append("")
    for row in review["rows"]:
        if row["decision"] not in {"adopt", "already_registered"}:
            continue
        lines.extend([
            f"## {row['channel_title']}",
            "",
            f"- decision: {row['decision']}",
            f"- priority: {row['priority']}",
            f"- URL: {row['channel_url']}",
            f"- reason: {row['review_reason']}",
            f"- next_action: {row['next_action']}",
            "",
            "| published | setlist | event_date | sample |",
            "| --- | --- | --- | --- |",
        ])
        for video in row["sample_videos"]:
            lines.append(
                "| "
                f"{md_escape(video.get('published_at'))} | "
                f"{video.get('setlist_count') or 0} | "
                f"{md_escape(video.get('event_date'))} | "
                f"[{md_truncate(video.get('title'), 70)}]({md_escape(video.get('url'))}) |"
            )
        lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default=str(IN))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--md-out", default=str(MARKDOWN_OUT))
    args = parser.parse_args()

    review = build_review(load_json(args.input, {}))
    review["source"] = args.input
    atomic_write_json(args.out, review)
    atomic_write_text(args.md_out, render_markdown(review))
    print(
        "[youtube-channel-review] "
        f"channels={review['channel_count']} counts={review['counts']} -> {args.out}, {args.md_out}"
    )


if __name__ == "__main__":
    main()
