#!/usr/bin/env python3
"""Merge the frozen completion judgments into exact-match review overlays."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from review_inbox_adapters.backlog_decision_overlay import validated_decision_index
from review_inbox_adapters.low_priority_adapters import build_snapshot as build_low_snapshot
from review_inbox_adapters.parity import item_payload_hash


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def merge_by_identity(*groups: list[dict]) -> list[dict]:
    merged: dict[tuple[str, str], dict] = {}
    for rows in groups:
        for row in rows:
            key = (row["source_id"], row["source_key"])
            merged[key] = dict(row)
    return [merged[key] for key in sorted(merged)]


def build_youtube(*, generated_at: str) -> dict:
    existing = load("review_backlog_youtube_decision_overlay.json").get("decisions") or []
    remaining = load("review_backlog_youtube_llm_decisions_remaining.json").get("decisions") or []
    decisions = merge_by_identity(existing, remaining)
    overlay = {
        "schema_version": 1,
        "generated_by": "おと（Codex）/Terra",
        "generated_at": generated_at,
        "summary": {},
        "decisions": decisions,
    }
    index = validated_decision_index(overlay)
    inbox_rows = load("review_inbox.json").get("items") or []
    snapshot_items = [row for row in inbox_rows if row.get("source_id") == "youtube_evidence"]
    remaining_index = {
        (row["source_id"], row["source_key"]): row for row in remaining
    }
    remaining_exact = sum(
        bool(
            (decision := remaining_index.get(("youtube_evidence", item["source_key"])))
            and decision["inbox_id"] == item["inbox_id"]
            and decision["source_payload_hash"] == item["source_payload_hash"]
        )
        for item in snapshot_items
    )
    if remaining_exact != len(remaining) or len(remaining) != 247:
        raise ValueError(f"remaining YouTube decisions cover {remaining_exact}/{len(remaining)} current items")
    current_exact = 0
    current_counts = {"採用": 0, "不採用": 0}
    for item in snapshot_items:
        decision = index.get(("youtube_evidence", item["source_key"]))
        if decision and decision["inbox_id"] == item["inbox_id"] and decision["source_payload_hash"] == item["source_payload_hash"]:
            current_exact += 1
            current_counts[decision["decision"]] += 1
    if current_exact != len(snapshot_items):
        raise ValueError(f"YouTube overlay covers {current_exact}/{len(snapshot_items)} current items")
    overlay["summary"] = {
        "decision_count": len(decisions),
        "current_item_count": len(snapshot_items),
        "current_exact_count": current_exact,
        "new_current_decisions": len(remaining),
        "prior_current_decisions": current_exact - len(remaining),
        "current_採用": current_counts["採用"],
        "current_不採用": current_counts["不採用"],
        "採用": sum(row["decision"] == "採用" for row in decisions),
        "不採用": sum(row["decision"] == "不採用" for row in decisions),
        "保留": 0,
    }
    return overlay


def publication_mechanical_decisions(*, generated_at: str) -> list[dict]:
    snapshot = build_low_snapshot("publication_gap", decision_overlay_path=None)
    rows = [
        item
        for item in snapshot["items"]
        if item["payload"].get("gap_type") not in {
            "公開曲実績の曲名が曲マスタにない",
            "根拠ありイベントが公開整備待ち",
        }
    ]
    if len(rows) != 12:
        raise ValueError(f"expected 12 publication sync gaps, got {len(rows)}")
    return [
        {
            "source_id": "publication_gap",
            "source_key": item["source_key"],
            "inbox_id": item["inbox_id"],
            "source_payload_hash": item_payload_hash(item),
            "decision": "公開同期対象",
            "actor_type": "agent",
            "actor_id": "おと（Codex）",
            "decided_at": generated_at,
            "reason_detail": "採用済みまたはpublic_readyの上流データに対し、公開辞書側だけが未同期である。",
        }
        for item in rows
    ]


def event_date_decisions() -> list[dict]:
    rows = load("publication_gap_event_date_research.json").get("decisions") or []
    if len(rows) != 38 or any(row.get("classification") != "no_current_year_evidence" for row in rows):
        raise ValueError("event-date draft must contain 38 no-current-year-evidence decisions")
    return [
        {
            "source_id": "publication_gap",
            "source_key": f"gap:{row['gap_id']}",
            "inbox_id": row["inbox_id"],
            "source_payload_hash": row["source_payload_hash"],
            "decision": "2026年根拠なし",
            "actor_type": "agent",
            "actor_id": "おと（Codex）/Terra",
            "decided_at": row["checked_at"],
            "reason_detail": row["reason_detail"],
            "evidence_urls": row.get("evidence_urls") or [],
            "classification": row["classification"],
        }
        for row in rows
    ]


def x_gap_decisions() -> list[dict]:
    rows = load("x_gap_kuramae_research.json").get("decisions") or []
    if len(rows) != 1 or rows[0].get("recommended_decision") != "needs_official_confirmation":
        raise ValueError("x-gap draft must contain the one official-confirmation decision")
    row = rows[0]
    return [{
        "source_id": row["source_id"],
        "source_key": row["source_key"],
        "inbox_id": row["inbox_id"],
        "source_payload_hash": row["source_payload_hash"],
        "decision": "公式確認待ち",
        "actor_type": row["actor_type"],
        "actor_id": row["actor_id"],
        "decided_at": row["decided_at"],
        "reason_detail": row["reason_detail"],
        "evidence_urls": row.get("evidence_urls") or [],
        "classification": row["classification"],
    }]


def build_general(*, generated_at: str) -> dict:
    existing = load("review_backlog_decision_overlay.json").get("decisions") or []
    historical = load("historical_reference_quality_llm_research.json").get("decisions") or []
    song_identity = load("publication_gap_song_identity_llm_decisions.json").get("decisions") or []
    added = historical + song_identity + event_date_decisions() + publication_mechanical_decisions(generated_at=generated_at) + x_gap_decisions()
    if len(added) != 258:
        raise ValueError(f"expected 258 new non-YouTube decisions, got {len(added)}")
    current = {
        (row.get("source_id"), row.get("source_key")): row
        for row in load("review_inbox.json").get("items") or []
    }
    exact_added = sum(
        bool(
            (item := current.get((row["source_id"], row["source_key"])))
            and row["inbox_id"] == item.get("inbox_id")
            and row["source_payload_hash"] == item.get("source_payload_hash")
        )
        for row in added
    )
    if exact_added != len(added):
        raise ValueError(f"non-YouTube decisions cover {exact_added}/{len(added)} current items")
    decisions = merge_by_identity(existing, added)
    overlay = {
        "schema_version": 1,
        "generated_by": "おと（Codex）/Terra",
        "generated_at": generated_at,
        "purpose": "Freeze all remaining exact-input LLM judgments without mutating canonical domain facts.",
        "summary": {
            "decision_count": len(decisions),
            "new_current_decisions": len(added),
            "historical_reference_quality": len(historical),
            "publication_song_identity": len(song_identity),
            "publication_event_date": 38,
            "publication_sync": 12,
            "x_gap": 1,
        },
        "decisions": decisions,
    }
    validated_decision_index(overlay)
    return overlay


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--generated-at", required=True)
    args = parser.parse_args()
    write(DATA / "review_backlog_youtube_decision_overlay.json", build_youtube(generated_at=args.generated_at))
    write(DATA / "review_backlog_decision_overlay.json", build_general(generated_at=args.generated_at))
    print("review backlog completion overlays built")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
