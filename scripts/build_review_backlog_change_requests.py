#!/usr/bin/env python3
"""Build finite, dry-run-only RDB requests from frozen backlog decisions."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SONG_DECISIONS = DATA / "publication_gap_song_identity_llm_decisions.json"
YOUTUBE_DECISIONS = DATA / "review_backlog_youtube_llm_decisions_remaining.json"
REVIEW_INBOX = DATA / "review_inbox.json"
DEFAULT_OUT = DATA / "change_requests" / "review_backlog_llm_20260818.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def request_id(prefix: str, source_key: str) -> str:
    digest = hashlib.sha256(source_key.encode("utf-8")).hexdigest()[:16]
    return f"llm_{prefix}_{digest}"


def target_status(decision: dict) -> str:
    target = decision.get("target_catalog_match") or {}
    if target.get("status") in {"候補", "要確認", "candidate"}:
        return "candidate"
    if target.get("public_ready") is False:
        return "candidate"
    return "active"


def build_song_requests(decisions: list[dict]) -> list[dict]:
    requests = []
    for row in decisions:
        common = {
            "request_id": request_id("song", row["source_key"]),
            "raw_song_name": row["raw_song_name"],
            "source_decision_key": row["source_key"],
            "source_payload_hash": row["source_payload_hash"],
            "decision_reason": row["reason_detail"],
            "dry_run_only": True,
        }
        if row["decision"] == "既存曲へ統合":
            target = row.get("target_catalog_match") or {}
            request = {
                **common,
                "change_type": "merge_song_identity",
                "target_song_name": row["target_song_name"],
                "target_song_id": target.get("song_id"),
                "target_status": target_status(row),
                "target_catalog_source": target.get("catalog_source"),
            }
        elif row["decision"] == "曲名ノイズとして除外":
            request = {**common, "change_type": "retract_song_identity"}
        elif row["decision"] == "新規曲候補として維持":
            request = {
                **common,
                "change_type": "register_song_candidate",
                "target_song_name": row["target_song_name"],
            }
        else:
            raise ValueError(f"unsupported song decision: {row['decision']}")
        requests.append(request)
    return requests


def parse_video_id(source_key: str) -> str:
    match = re.match(r"^video:([^|]+)(?:\||$)", source_key)
    if not match:
        raise ValueError(f"invalid YouTube source key: {source_key}")
    return match.group(1)


def build_youtube_requests(decisions: list[dict], inbox_items: list[dict]) -> list[dict]:
    inbox = {(row["source_id"], row["source_key"]): row for row in inbox_items}
    requests = []
    for row in decisions:
        item = inbox.get(("youtube_evidence", row["source_key"]))
        if not item:
            raise ValueError(f"YouTube review item is missing: {row['source_key']}")
        if item.get("inbox_id") != row["inbox_id"]:
            raise ValueError(f"YouTube inbox identity changed: {row['source_key']}")
        if item.get("source_payload_hash") != row["source_payload_hash"]:
            raise ValueError(f"YouTube payload hash changed: {row['source_key']}")
        payload = item.get("payload") or {}
        video = parse_video_id(row["source_key"])
        requests.append(
            {
                "request_id": request_id("youtube", row["source_key"]),
                "change_type": "record_youtube_review_decision",
                "source_key": row["source_key"],
                "inbox_id": row["inbox_id"],
                "source_payload_hash": row["source_payload_hash"],
                "video_id": video,
                "video_url": item.get("source_url") or f"https://www.youtube.com/watch?v={video}",
                "decision": "accepted" if row["decision"] == "採用" else "rejected",
                "reason_detail": row["reason_detail"],
                "decided_at": row["decided_at"],
                "source": {
                    "title": item.get("title") or payload.get("title") or "",
                    "channel_id": payload.get("channel_id") or "",
                    "published_at": payload.get("published_at") or "",
                    "detected_event_date": payload.get("detected_event_date") or "",
                },
                "review_payload": payload,
                "dry_run_only": True,
            }
        )
    return requests


def build(*, generated_at: str) -> dict:
    songs = load(SONG_DECISIONS)
    youtube = load(YOUTUBE_DECISIONS)
    inbox = load(REVIEW_INBOX)
    song_requests = build_song_requests(songs["decisions"])
    youtube_requests = build_youtube_requests(youtube["decisions"], inbox["items"])
    requests = song_requests + youtube_requests
    counts = {}
    for request in requests:
        key = request["change_type"]
        counts[key] = counts.get(key, 0) + 1
    expected = {
        "merge_song_identity": 84,
        "retract_song_identity": 55,
        "register_song_candidate": 8,
        "record_youtube_review_decision": 247,
    }
    if counts != expected:
        raise ValueError(f"unexpected request counts: {counts}")
    return {
        "request_type": "rdb_change_requests",
        "schema_version": 1,
        "generated_by": "scripts/build_review_backlog_change_requests.py",
        "generated_at": generated_at,
        "scope": "review_backlog_llm_20260818",
        "review_input_master_db_sha256": songs["input"]["master_rdb_sha256"],
        "input_lineage": {
            "song_decisions": {
                "path": str(SONG_DECISIONS.relative_to(ROOT)),
                "sha256": sha256(SONG_DECISIONS),
            },
            "youtube_decisions": {
                "path": str(YOUTUBE_DECISIONS.relative_to(ROOT)),
                "sha256": sha256(YOUTUBE_DECISIONS),
            },
            "review_inbox": {
                "path": str(REVIEW_INBOX.relative_to(ROOT)),
                "sha256": sha256(REVIEW_INBOX),
            },
        },
        "summary": {"request_count": len(requests), "change_type_counts": counts},
        "requests": requests,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    payload = build(generated_at=args.generated_at)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(payload["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()
