#!/usr/bin/env python3
"""Audit YouTube review rows that look like song/clip fragments, not events."""

from __future__ import annotations

import json
import re
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


REVIEW = Path("data/youtube_active_video_review.json")
OUT = Path("data/youtube_song_clip_fragment_audit.json")
OUT_MD = Path("data/youtube_song_clip_fragment_audit.md")

REVIEW_ACTIONS = {"review_video_evidence", "needs_official_confirmation", "bon_component_of_parent_event"}
SONG_QUOTE_RE = re.compile(r"[「『\"“][^」』\"”]{1,60}[」』\"”]")
SHORTS_RE = re.compile(r"#\s*shorts\b|\bshorts\b", re.I)
SONG_BY_RE = re.compile(r"\s[-ー–]\s*[^/【】]{1,50}| by [^/【】]{1,50}", re.I)
PART_RE = re.compile(r"\b(?:part|pt)\s*[0-9０-９]+\b|[\[（(][0-9０-９]+/[0-9０-９]+[\]）)]", re.I)
NUMBERED_RE = re.compile(r"(?:盆踊り|Bon Dance|Bon Odori)[ 　]*[0-9０-９]+|[0-9０-９]+終?\b")
FULL_EVENT_RE = re.compile(r"全曲|全[0-9０-９]+曲|第一部|第二部|第[一二三四五六七八九十]+部|初日|最終日|フィナーレ|Full|Festival\b", re.I)


def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=".tmp-", suffix=".json", delete=False
    ) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        tmp_name = handle.name
    Path(tmp_name).replace(path)


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=".tmp-", suffix=".md", delete=False
    ) as handle:
        handle.write(text)
        tmp_name = handle.name
    Path(tmp_name).replace(path)


def evidence_flags(row: dict) -> list[str]:
    flags = []
    title = row.get("title") or ""
    if SHORTS_RE.search(title):
        flags.append("shorts")
    if SONG_QUOTE_RE.search(title):
        flags.append("song_quote")
    if SONG_BY_RE.search(title):
        flags.append("song_by_artist")
    if PART_RE.search(title):
        flags.append("part_clip")
    if NUMBERED_RE.search(title):
        flags.append("numbered_clip")
    if row.get("parent_event_name"):
        flags.append("parent_event_component")
    if FULL_EVENT_RE.search(title):
        flags.append("full_event_hint")
    return flags


def has_strong_event_evidence(row: dict) -> bool:
    return bool(row.get("official_urls") or row.get("matched_public_event") or row.get("setlist_occurrences"))


def classify(row: dict) -> tuple[str, list[str], str]:
    flags = evidence_flags(row)
    note = row.get("auto_review_note") or ""
    if note in {"shorts_song_fragment", "parent_event_song_clip_fragment"}:
        return "already_auto_ignored", flags, f"既に {note} として自動除外済み"
    if row.get("action") not in REVIEW_ACTIONS:
        return "", flags, ""
    if has_strong_event_evidence(row):
        return "", flags, ""
    if "shorts" in flags:
        return "high_confidence_song_clip", flags, "shorts かつ公式/既存一致/setlist根拠なし"
    if "parent_event_component" in flags and ({"song_quote", "song_by_artist", "numbered_clip"} & set(flags)):
        return "high_confidence_song_clip", flags, "親イベント内の単曲/番号付き断片"
    if "song_quote" in flags and not ({"full_event_hint", "part_clip"} & set(flags)):
        return "likely_song_clip", flags, "曲名引用が中心で、全曲/部構成の手がかりが弱い"
    if "song_by_artist" in flags and "full_event_hint" not in flags:
        return "likely_song_clip", flags, "曲名 - アーティスト型の単曲動画に見える"
    if "numbered_clip" in flags and "full_event_hint" not in flags:
        return "possible_song_clip", flags, "番号付き断片に見える"
    return "", flags, ""


def audit_rows(rows: list[dict]) -> list[dict]:
    output = []
    for row in rows:
        bucket, flags, reason = classify(row)
        if not bucket:
            continue
        output.append(
            {
                "bucket": bucket,
                "action": row.get("action") or "",
                "auto_review_note": row.get("auto_review_note") or "",
                "channel_title": row.get("channel_title") or "",
                "published_at": row.get("published_at") or "",
                "detected_event_date": row.get("detected_event_date") or "",
                "title": row.get("title") or "",
                "video_url": row.get("video_url") or "",
                "parent_event_name": row.get("parent_event_name") or "",
                "component_label": row.get("component_label") or "",
                "flags": flags,
                "reason": reason,
            }
        )
    output.sort(key=lambda row: (row["bucket"], row["channel_title"], row["detected_event_date"], row["title"]))
    return output


def render_markdown(payload: dict) -> str:
    lines = [
        "# YouTube 曲紹介/断片動画 監査",
        "",
        f"- 生成: {payload['generated_at']}",
        f"- 対象: {payload['source']}",
        "",
        "## Summary",
        "",
    ]
    for bucket, count in payload["bucket_counts"].items():
        lines.append(f"- {bucket}: {count}")
    lines.extend(["", "## By Channel", ""])
    for key, count in payload["channel_counts"].items():
        lines.append(f"- {key}: {count}")
    lines.extend(
        [
            "",
            "## Rows",
            "",
            "| bucket | action | channel | date | parent | title | reason |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in payload["rows"]:
        title = row["title"].replace("|", "\\|")
        if row["video_url"]:
            title = f"[{title}]({row['video_url']})"
        lines.append(
            "| "
            f"{row['bucket']} | "
            f"{row['action']} | "
            f"{row['channel_title'].replace('|', '\\|')} | "
            f"{(row['detected_event_date'] or row['published_at'][:10]).replace('|', '\\|')} | "
            f"{row['parent_event_name'].replace('|', '\\|')} | "
            f"{title} | "
            f"{row['reason'].replace('|', '\\|')} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    review = load_json(REVIEW, {})
    rows = review.get("rows") or []
    audit = audit_rows(rows)
    payload = {
        "generated_by": "audit_youtube_song_clip_fragments.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(REVIEW),
        "row_count": len(audit),
        "bucket_counts": dict(Counter(row["bucket"] for row in audit)),
        "channel_counts": dict(Counter(row["channel_title"] for row in audit)),
        "rows": audit,
    }
    atomic_write_json(OUT, payload)
    atomic_write_text(OUT_MD, render_markdown(payload))
    print(f"wrote {OUT} ({payload['row_count']} rows, buckets={payload['bucket_counts']})")


if __name__ == "__main__":
    main()
