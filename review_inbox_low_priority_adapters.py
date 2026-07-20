#!/usr/bin/env python3
"""Pure adapters for B4 song, term, venue, quality, and publication backlogs."""

from __future__ import annotations

import argparse
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Mapping

from review_inbox_source_adapter import load_adapted_source, write_adapted_snapshot


ROOT = Path(__file__).resolve().parent
SOURCE_CONFIG = {
    "daily_song_candidate": (ROOT / "data/weekly_song_candidates_review.json", "song"),
    "daily_term_candidate": (ROOT / "data/weekly_harvest_review_candidates.json", "term"),
    "accepted_venue_song_missing_venue": (ROOT / "data/accepted_venue_song_missing_venue_review.json", "venue_candidate"),
    "historical_reference_quality": (ROOT / "data/historical_reference_quality_review.json", "historical_quality"),
    "publication_gap": (ROOT / "data/publication_gap_review.json", "publication_gap"),
}


def semantic_key(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return re.sub(r"[\s　]+", "", text)


def rows(payload: Any, field: str) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get(field), list):
        raise ValueError(f"low-priority review payload requires {field} list")
    if any(not isinstance(row, dict) for row in payload[field]):
        raise TypeError("low-priority review rows must be objects")
    return payload[field]


def decided(row: Mapping[str, Any], allowed: set[str]) -> bool:
    decision = str(row.get("current_decision") or row.get("decision") or "").strip()
    decided_by = str(row.get("decided_by") or "").strip()
    decided_at = str(row.get("decided_at") or "").strip()
    if decision and decided_by and decided_at:
        if decision not in allowed:
            raise ValueError(f"unsupported decided low-priority action: {decision}")
        return True
    if decision or decided_by or decided_at:
        raise ValueError("partial low-priority review decision is not allowed")
    return False


def common_item(row: Mapping[str, Any], *, kind: str, source_key: str, title: str, action: str, time_scope: str = "reference") -> dict[str, Any]:
    if not source_key or not title:
        raise ValueError("low-priority review item requires semantic identity and title")
    return {
        "kind": kind,
        "domain": "曲・用語・低緊急度",
        "time_scope": time_scope,
        "priority_label": "P3",
        "priority_score": None,
        "title": title,
        "event_name": str(row.get("event_name") or "").strip(),
        "venue": str(row.get("venue") or row.get("suggested_venue") or "").strip(),
        "event_year": row.get("event_year") or row.get("target_year"),
        "source_key": source_key,
        "source_url": str(row.get("evidence_url") or row.get("source_url") or "").strip(),
        "recommended_action": action,
        "payload": dict(row),
    }


class DailySongAdapter:
    source_id = "daily_song_candidate"
    def adapt(self, payload: Any) -> Iterable[Mapping[str, Any]]:
        for row in rows(payload, "rows"):
            if decided(row, {"曲として採用","曲ではない","分割","用語集へ","保留"}): continue
            title = str(row.get("canonical_song_name") or row.get("term") or "").strip()
            yield common_item(row, kind="song", source_key=f"song:{semantic_key(title)}", title=title, action="stage_song_candidate")


class DailyTermAdapter:
    source_id = "daily_term_candidate"
    def adapt(self, payload: Any) -> Iterable[Mapping[str, Any]]:
        for row in rows(payload, "rows"):
            if decided(row, {"採用","不採用","保留"}): continue
            term = str(row.get("term") or "").strip()
            song = str(row.get("song_name") or "").strip()
            venue = str(row.get("venue") or "").strip()
            if song or venue:
                if not song or not venue:
                    raise ValueError("song/venue co-occurrence requires both song and venue")
                key = f"cooccurrence:{semantic_key(song)}|venue:{semantic_key(venue)}"
                action = "stage_song_venue_evidence"
                kind = "song_research"
            else:
                category = semantic_key(row.get("category")); type_name = semantic_key(row.get("type"))
                key = f"term:{category}|type:{type_name}|value:{semantic_key(term)}"
                action = "stage_term_candidate"; kind = "term"
            yield common_item(row, kind=kind, source_key=key, title=term, action=action)


class AcceptedVenueSongAdapter:
    source_id = "accepted_venue_song_missing_venue"
    def adapt(self, payload: Any) -> Iterable[Mapping[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows(payload, "rows"):
            if decided(row, {"会場追加","既存に統合","不採用","保留"}): continue
            venue = str(row.get("suggested_venue") or row.get("term") or "").strip()
            key = semantic_key(venue)
            if not key: raise ValueError("venue candidate requires suggested_venue")
            grouped.setdefault(key, []).append(row)
        for key, source_rows in grouped.items():
            row = dict(source_rows[0])
            row["source_rows"] = source_rows
            row["songs"] = sorted({str(song) for source in source_rows for song in source.get("songs") or [] if str(song).strip()})
            row["source_urls"] = sorted({str(url) for source in source_rows for url in source.get("source_urls") or [] if str(url).strip()})
            venue = str(row.get("suggested_venue") or row.get("term") or "").strip()
            yield common_item(row, kind="venue_candidate", source_key=f"venue:{key}", title=venue, action="stage_venue_candidate")


class HistoricalQualityAdapter:
    source_id = "historical_reference_quality"
    def adapt(self, payload: Any) -> Iterable[Mapping[str, Any]]:
        for row in rows(payload, "review"):
            if decided(row, {"needs_date_research","needs_song_research","keep_historical_reference","remove_historical_reference","hold"}): continue
            review_id = str(row.get("quality_review_id") or "").strip()
            issues = row.get("issue_codes")
            if not review_id or not isinstance(issues, list) or not issues:
                raise ValueError("historical quality review requires id and issue codes")
            unknown = sorted(set(map(str, issues)) - {"historical_date_missing","historical_date_invalid","historical_songs_missing"})
            if unknown: raise ValueError("unsupported historical quality issue: " + ", ".join(unknown))
            action = "needs_date_research" if any(code in issues for code in ("historical_date_missing","historical_date_invalid")) else "needs_song_research"
            title = str(row.get("event_name") or row.get("name") or review_id).strip()
            yield common_item(row, kind="historical_quality", source_key=f"quality:{review_id}", title=title, action=action, time_scope="historical")


class PublicationGapAdapter:
    source_id = "publication_gap"
    def adapt(self, payload: Any) -> Iterable[Mapping[str, Any]]:
        for row in rows(payload, "rows"):
            if decided(row, {"needs_research","hold","reject"}): continue
            gap_id = str(row.get("gap_id") or "").strip()
            action = str(row.get("recommended_action") or "").strip()
            if action not in {"needs_research", "hold", "reject"}:
                raise ValueError(f"unsupported publication gap action: {action or 'missing'}")
            title = str(row.get("term") or row.get("song_name") or gap_id).strip()
            yield common_item(row, kind="publication_gap", source_key=f"gap:{gap_id}", title=title, action=action)


ADAPTERS = {
    "daily_song_candidate": DailySongAdapter,
    "daily_term_candidate": DailyTermAdapter,
    "accepted_venue_song_missing_venue": AcceptedVenueSongAdapter,
    "historical_reference_quality": HistoricalQualityAdapter,
    "publication_gap": PublicationGapAdapter,
}


def build_snapshot(source_id: str, input_path: Path | None = None) -> dict[str, Any]:
    if source_id not in ADAPTERS:
        raise ValueError(f"unsupported low-priority source: {source_id}")
    default_path, _ = SOURCE_CONFIG[source_id]
    snapshot = load_adapted_source(ADAPTERS[source_id](), input_path or default_path)
    snapshot["write_mode"] = "snapshot_only_default_off"
    snapshot["upstream_boundary"] = "pending_low_priority_reviews_only"
    snapshot["selection"] = {"mode":"all","source_keys":[item["source_key"] for item in snapshot["items"]]}
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", choices=sorted(ADAPTERS), required=True)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    snapshot = build_snapshot(args.source_id, args.input)
    write_adapted_snapshot(snapshot, args.output)
    print(f"low-priority snapshot: source={args.source_id} items={snapshot['item_count']} -> {args.output}")


if __name__ == "__main__":
    main()
