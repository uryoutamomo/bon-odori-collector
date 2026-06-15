"""Promote reviewed YouTube channels into a collection registry."""

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path


DATA = Path("data")
REVIEW_IN = DATA / "youtube_channel_review.json"
ANALYTICS_IN = DATA / "youtube_channels.json"
OUT = DATA / "youtube_channel_registry.json"
MARKDOWN_OUT = DATA / "youtube_channel_registry.md"


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


def rss_url(channel_id):
    if not channel_id:
        return ""
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


def registry_status(row):
    decision = row.get("decision")
    priority = row.get("priority")
    if decision == "already_registered":
        return "active"
    if decision == "adopt" and priority == "high":
        return "active"
    if decision == "adopt":
        return "watch"
    if decision == "review":
        return "review"
    return "hold"


def collection_enabled(status):
    return status == "active"


def source_for(row):
    if row.get("already_known") or row.get("decision") == "already_registered":
        return "existing_voices"
    if row.get("decision") in {"adopt", "hold", "review"}:
        return "manual_review"
    return "youtube_search"


def scope_for(row):
    text = " ".join([
        row.get("channel_title") or "",
        row.get("review_reason") or "",
        row.get("next_action") or "",
    ])
    if "福岡" in text or "全国" in text:
        return "national_hold"
    if any(token in text for token in ["台東区", "浅草", "新宿", "渋谷", "丸の内", "東京23区"]):
        return "tokyo_23"
    if "東京" in text:
        return "tokyo_area"
    return "unknown"


def trusted_for(row):
    values = []
    if row.get("decision") == "already_registered":
        values.append("existing_collection")
    if row.get("bon_context_video_count", 0) > 0:
        values.append("event_discovery")
    if row.get("event_date_candidate_count", 0) > 0:
        values.append("date_evidence")
    if row.get("setlist_candidate_count", 0) > 0:
        values.extend(["setlist_extraction", "song_evidence"])
    text = f"{row.get('review_reason') or ''} {row.get('next_action') or ''}"
    if "公式" in text or "URL" in text:
        values.append("official_url_discovery")
    return sorted(set(values))


def date_validation_required(row):
    text = f"{row.get('review_reason') or ''} {row.get('next_action') or ''}"
    return bool(row.get("event_date_candidate_count", 0) > 0 or "日付" in text or "曜日" in text)


def compact_analytics(channel):
    if not channel:
        return {}
    keys = [
        "video_count",
        "bon_odori_video_count",
        "setlist_occurrence_count",
        "setlist_song_count",
        "complete_setlist_count",
        "venue_date_success_count",
        "first_published_at",
        "last_published_at",
        "auto_score",
        "collection_status",
    ]
    return {key: channel.get(key) for key in keys if channel.get(key) not in (None, "")}


def build_registry(review_payload, analytics_payload, generated_at=None):
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    analytics_by_id = {
        row.get("channel_id"): row
        for row in analytics_payload.get("channels", [])
        if row.get("channel_id")
    }
    rows = []
    for row in review_payload.get("rows", []):
        channel_id = row.get("channel_id") or ""
        status = registry_status(row)
        analytics = analytics_by_id.get(channel_id, {})
        rows.append({
            "channel_id": channel_id,
            "channel_title": row.get("channel_title") or "",
            "channel_url": row.get("channel_url") or "",
            "rss_url": rss_url(channel_id),
            "status": status,
            "collection_enabled": collection_enabled(status),
            "priority": row.get("priority") or "normal",
            "source": source_for(row),
            "scope": scope_for(row),
            "date_validation_required": date_validation_required(row),
            "trusted_for": trusted_for(row),
            "review": {
                "decision": row.get("decision") or "",
                "reason": row.get("review_reason") or "",
                "next_action": row.get("next_action") or "",
                "candidate_score": row.get("candidate_score") or 0,
                "score_reasons": row.get("score_reasons") or [],
            },
            "metrics": {
                "found_video_count": row.get("found_video_count") or 0,
                "bon_context_video_count": row.get("bon_context_video_count") or 0,
                "setlist_candidate_count": row.get("setlist_candidate_count") or 0,
                "event_date_candidate_count": row.get("event_date_candidate_count") or 0,
                "analytics": compact_analytics(analytics),
            },
            "sample_videos": row.get("sample_videos") or [],
            "added_at": generated_at,
            "last_reviewed_at": review_payload.get("generated_at") or generated_at,
            "last_collected_at": analytics.get("last_published_at") or None,
        })
    order = {"active": 0, "watch": 1, "review": 2, "hold": 3}
    priority_order = {"high": 0, "normal": 1, "low": 2}
    rows.sort(key=lambda item: (
        order.get(item["status"], 9),
        priority_order.get(item["priority"], 9),
        -item["review"]["candidate_score"],
        item["channel_title"],
    ))
    counts = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {
        "generated_by": "promote_youtube_channel_registry.py",
        "generated_at": generated_at,
        "sources": {
            "review": str(REVIEW_IN),
            "analytics": str(ANALYTICS_IN),
        },
        "channel_count": len(rows),
        "counts": counts,
        "policy": {
            "youtube_is_supporting_evidence": True,
            "do_not_create_new_events_from_youtube_only": True,
            "use_thumbnail_as_evidence_not_venue_photo": True,
            "collect_active_channels_only_by_default": True,
        },
        "channels": rows,
    }


def md_escape(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(registry):
    lines = [
        "# YouTubeチャンネル登録台帳",
        "",
        f"- 生成: {registry['generated_at']}",
        f"- チャンネル数: {registry['channel_count']}件",
    ]
    for status, count in sorted(registry["counts"].items()):
        lines.append(f"- {status}: {count}件")
    lines.extend([
        "",
        "## 運用方針",
        "",
        "- YouTubeは過去実績・曲目・公式URL発見の補助証拠として扱う。",
        "- YouTube単独では新規イベントを本登録しない。",
        "- サムネイルは動画証拠として扱い、会場写真として誤用しない。",
        "- 通常収集は `status=active` かつ `collection_enabled=true` のチャンネルだけを対象にする。",
        "",
        "## チャンネル",
        "",
        "| status | collect | priority | scope | channel | trusted_for | next_action |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ])
    for row in registry["channels"]:
        lines.append(
            "| "
            f"{md_escape(row['status'])} | "
            f"{'yes' if row['collection_enabled'] else 'no'} | "
            f"{md_escape(row['priority'])} | "
            f"{md_escape(row['scope'])} | "
            f"[{md_escape(row['channel_title'])}]({md_escape(row['channel_url'])}) | "
            f"{md_escape(', '.join(row['trusted_for']))} | "
            f"{md_escape(row['review']['next_action'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", default=str(REVIEW_IN))
    parser.add_argument("--analytics", default=str(ANALYTICS_IN))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--markdown-out", default=str(MARKDOWN_OUT))
    args = parser.parse_args()

    registry = build_registry(
        load_json(args.review, {}),
        load_json(args.analytics, {}),
    )
    atomic_write_json(args.out, registry)
    atomic_write_text(args.markdown_out, render_markdown(registry))
    print(
        f"wrote {args.out} ({registry['channel_count']} channels, "
        f"active={registry['counts'].get('active', 0)}, watch={registry['counts'].get('watch', 0)})"
    )


if __name__ == "__main__":
    main()
