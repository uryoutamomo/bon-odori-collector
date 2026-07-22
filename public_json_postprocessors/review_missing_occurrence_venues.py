"""Classify event occurrences that still have no venue_id.

This is read-only review material. It intentionally separates likely duplicate
series/linking issues from venue fill candidates so the migration does not
silently attach weak venue guesses to public-facing occurrences.
"""

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from master_rdb.master_db import MASTER_DB, connect_existing, normalize_text


DATA = Path("data")
QUEUE_JSON = DATA / "registered_event_investigation_queue.json"
DECISIONS_JSON = DATA / "ph2_event_occurrence_review_decisions.json"
OUT_JSON = DATA / "missing_occurrence_venue_review.json"
OUT_MD = DATA / "missing_occurrence_venue_review.md"


CONFIRMED_NEW_VENUES = {
    "honjo_chiiki_plaza_big_ship": {
        "canonical_name": "本所地域プラザ BIG SHIP 多目的ホール",
        "aliases": [
            "墨田区本所地域プラザ BIG SHIP 多目的ホール",
            "本所地域プラザ BIG SHIP",
            "本所地域プラザ",
        ],
        "area": "墨田区",
        "address": "東京都墨田区本所1丁目13番4号",
        "access": "都営浅草線「蔵前」駅徒歩10分、JR「両国」駅徒歩15分",
        "source_url": "https://www.kinshicho-kawachiondo.jp/archives/1067",
        "source_kind": "official_event_page",
    },
    "kyobashi_plaza_kuminkan": {
        "canonical_name": "京橋プラザ区民館",
        "aliases": ["京橋プラザ", "中央区京橋プラザ"],
        "area": "中央区",
        "address": "東京都中央区銀座一丁目25番3号",
        "access": "東京メトロ有楽町線「新富町」駅徒歩2分、都営浅草線「宝町」駅徒歩5分",
        "source_url": "https://www.city.chuo.lg.jp/a0013/kurashi/chiikicommunity/kuminkan/syukaisisetu02.html",
        "source_kind": "official_facility",
    },
    "tsukishima_daini_jido_koen": {
        "canonical_name": "月島第二児童公園",
        "aliases": ["月島第二公園"],
        "area": "中央区",
        "address": "東京都中央区勝どき一丁目9番8号",
        "access": "",
        "source_url": "https://www.city.chuo.lg.jp/a0037/machizukuri/kouenryokka/kouen/kouen_hiroba_ichiran.html",
        "source_kind": "official_facility_list",
    },
}


REVIEW_HINTS = {
    "新橋こいち祭": {
        "review_action": "series_link_review_existing_venue_candidate",
        "candidate_venue_name": "桜田公園",
        "candidate_venue_id": "ven_331b917a98238b0d",
        "confidence": "high",
        "reason": "same official source has a curated 第28回新橋こいち祭 盆踊り occurrence with 桜田公園",
        "next_step": "link or merge the generic 新橋こいち祭 series with the curated numbered bon-odori series before filling venue_id",
    },
    "マロニエまつり盆踊り大会": {
        "review_action": "series_link_review_existing_venue_candidate",
        "candidate_venue_name": "ヒューリック浅草橋ビル前",
        "candidate_venue_id": "ven_e82a2aed94e45d29",
        "confidence": "high",
        "reason": "same date has curated 浅草橋マロニエまつり盆踊り occurrence with venue",
        "next_step": "treat as duplicate/alias review rather than a standalone venue fill",
    },
    "藤沢七夕まつり（DJ盆踊り大会）": {
        "review_action": "ready_existing_venue_candidate",
        "candidate_venue_name": "辻堂神台公園",
        "candidate_venue_id": "ven_61c6063cf53195b5",
        "confidence": "high",
        "reason": "retrospective venue registration recorded 辻堂駅北口神台公園 / 辻堂神台公園 for the same 2026-07-04 event",
        "next_step": "safe candidate for local RDB venue_id fill after deciding whether predicted 2026 rows should be materialized",
    },
    "郡上おどり in 青山": {
        "review_action": "series_link_review_existing_venue_candidate",
        "candidate_venue_name": "秩父宮ラグビー場駐車場",
        "candidate_venue_id": "ven_a52431fddb1891f8",
        "confidence": "high",
        "reason": "same public event exists on a different series with confirmed 2026 dates and venue",
        "next_step": "resolve duplicate 郡上おどり in 青山 series before applying the venue to the 2025 row",
    },
    "銀座一丁目東町会・新富町会 納涼盆踊り大会": {
        "review_action": "ready_new_venue_candidate",
        "candidate_action": "already_decided",
        "current_decision": "auto_create_venue_and_fill_occurrence",
        "decided_by": "auto_rule:official_facility_plus_observed_evidence",
        "candidate_venue_name": "京橋プラザ区民館",
        "candidate_venue_id": "",
        "candidate_venue_data": CONFIRMED_NEW_VENUES["kyobashi_plaza_kuminkan"],
        "confidence": "high",
        "reason": "official Chuo City facility page confirms 京橋プラザ区民館, and multiple observed YouTube evidence rows confirm the 2025 event/date/organizers at 京橋プラザ",
        "next_step": "auto-create the confirmed venue and fill this occurrence venue_id; no human venue review required",
    },
    "月島第二児童公園 盆踊り": {
        "review_action": "ready_new_venue_candidate",
        "candidate_action": "already_decided",
        "current_decision": "auto_create_venue_and_fill_occurrence",
        "decided_by": "auto_rule:official_facility_list_confirms_venue",
        "candidate_venue_name": "月島第二児童公園",
        "candidate_venue_id": "",
        "candidate_venue_data": CONFIRMED_NEW_VENUES["tsukishima_daini_jido_koen"],
        "confidence": "medium",
        "reason": "official Chuo City park/facility list confirms 月島第二児童公園 and address; event date/source is still unconfirmed, so this is venue-fill only",
        "next_step": "auto-create the confirmed venue and fill this occurrence venue_id; keep out of public export until a current official/organizer event source is confirmed",
    },
    "鉄砲洲児童公園 盆踊り": {
        "review_action": "new_venue_candidate_needs_source",
        "candidate_venue_name": "鉄砲洲児童公園",
        "candidate_venue_id": "",
        "confidence": "low",
        "reason": "event name contains a venue-like place name, but the occurrence has no source_url",
        "next_step": "confirm address/source before creating a venue row",
    },
    "雷門盆踊り（浅草）": {
        "review_action": "new_venue_candidate_needs_source",
        "candidate_venue_name": "雷門付近",
        "candidate_venue_id": "",
        "confidence": "low",
        "reason": "name gives an area hint, not a precise venue; no source_url on the occurrence",
        "next_step": "find official/current source before creating or linking a venue",
    },
    "佃島の盆踊り": {
        "review_action": "manual_venue_research_required",
        "candidate_venue_name": "",
        "candidate_venue_id": "",
        "confidence": "low",
        "reason": "central tourism source gives event context, but no master venue candidate is present",
        "next_step": "research exact venue before filling venue_id",
    },
    "中野駅前大盆踊り大会": {
        "review_action": "manual_venue_research_required",
        "candidate_venue_name": "",
        "candidate_venue_id": "",
        "confidence": "low",
        "reason": "official site URL exists, but no current master venue candidate was found",
        "next_step": "check official site and create/link the exact venue if confirmed",
    },
    "えどぐらん（江東区）": {
        "review_action": "manual_name_or_venue_research_required",
        "candidate_venue_name": "",
        "candidate_venue_id": "",
        "confidence": "low",
        "reason": "name resembles 京橋エドグラン but says 江東区; do not link to existing 京橋エドグラン without review",
        "next_step": "verify event name and venue source before any venue_id fill",
    },
    "すみだ河内音頭 小盆踊り": {
        "review_action": "ready_new_venue_candidate",
        "candidate_action": "already_decided",
        "current_decision": "auto_create_venue_and_fill_occurrence",
        "decided_by": "auto_rule:official_event_page_has_exact_venue_address",
        "candidate_venue_name": "本所地域プラザ BIG SHIP 多目的ホール",
        "candidate_venue_id": "",
        "candidate_venue_data": CONFIRMED_NEW_VENUES["honjo_chiiki_plaza_big_ship"],
        "confidence": "high",
        "reason": "official event page confirms 2026-05-16 event venue as 墨田区本所地域プラザ BIG SHIP 多目的ホール with address 東京都墨田区本所1丁目13番4号",
        "next_step": "auto-create the confirmed venue and fill this occurrence venue_id",
    },
}


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def rows(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def venue_by_id(conn, venue_id):
    if not venue_id:
        return None
    found = rows(
        conn,
        """
        SELECT venue_id, canonical_name, area, address, source_url
        FROM venues
        WHERE venue_id = ?
        """,
        (venue_id,),
    )
    return found[0] if found else None


def existing_venue_by_names(conn, names):
    normalized_names = [normalize_text(name) for name in names if normalize_text(name)]
    if not normalized_names:
        return None
    for normalized in normalized_names:
        found = rows(
            conn,
            """
            SELECT venue_id, canonical_name, area, address, source_url
            FROM venues
            WHERE normalized_name = ?
            LIMIT 1
            """,
            (normalized,),
        )
        if found:
            return found[0]
        found = rows(
            conn,
            """
            SELECT v.venue_id, v.canonical_name, v.area, v.address, v.source_url
            FROM venue_aliases a
            JOIN venues v ON v.venue_id = a.venue_id
            WHERE a.normalized_alias = ?
            LIMIT 1
            """,
            (normalized,),
        )
        if found:
            return found[0]
    return None


def existing_venue_name_matches(conn, event_name):
    norm = normalize_text(event_name)
    matches = []
    for venue in rows(conn, "SELECT venue_id, canonical_name, area, address FROM venues ORDER BY canonical_name"):
        venue_norm = normalize_text(venue["canonical_name"])
        if venue_norm and (venue_norm in norm or norm in venue_norm):
            matches.append(venue)
    return matches[:5]


def queue_by_occurrence(queue):
    return {
        task.get("occurrence_id"): task
        for task in queue.get("tasks") or []
        if task.get("occurrence_id")
    }


def decisions_by_event(decisions):
    return {
        decision.get("event_name"): decision
        for decision in decisions.get("decisions") or []
        if decision.get("event_name")
    }


def classify(conn, occurrence, task, decision):
    hint = dict(REVIEW_HINTS.get(occurrence["display_name"]) or {})
    if not hint:
        hint = {
            "review_action": "manual_venue_research_required",
            "candidate_venue_name": "",
            "candidate_venue_id": "",
            "confidence": "low",
            "reason": "no stored review hint exists",
            "next_step": "research exact venue before filling venue_id",
        }

    candidate_venue = venue_by_id(conn, hint.get("candidate_venue_id"))
    candidate_venue_data = hint.get("candidate_venue_data") or {}
    if not candidate_venue and candidate_venue_data:
        candidate_names = [
            candidate_venue_data.get("canonical_name"),
            *(candidate_venue_data.get("aliases") or []),
            hint.get("candidate_venue_name"),
        ]
        candidate_venue = existing_venue_by_names(conn, candidate_names)
        if candidate_venue:
            hint["candidate_venue_id"] = candidate_venue["venue_id"]
            if hint.get("review_action") == "ready_new_venue_candidate":
                hint["review_action"] = "ready_existing_venue_candidate"
    existing_name_matches = existing_venue_name_matches(conn, occurrence["display_name"])
    observed_candidate = (task or {}).get("observed_candidate") or {}

    return {
        "occurrence_id": occurrence["occurrence_id"],
        "event_name": occurrence["display_name"],
        "event_year": occurrence["event_year"],
        "date_start": occurrence.get("date_start") or "",
        "date_end": occurrence.get("date_end") or "",
        "date_status": occurrence.get("date_status") or "",
        "lifecycle_status": occurrence.get("lifecycle_status") or "",
        "source_url": occurrence.get("source_url") or "",
        "series_id": occurrence.get("series_id") or "",
        "series_usual_venue_id": occurrence.get("usual_venue_id") or "",
        "review_action": hint["review_action"],
        "candidate_action": hint.get("candidate_action") or "",
        "current_decision": hint.get("current_decision") or "",
        "decided_by": hint.get("decided_by") or "",
        "candidate_venue_name": hint.get("candidate_venue_name") or "",
        "candidate_venue_id": hint.get("candidate_venue_id") or "",
        "candidate_venue": candidate_venue,
        "candidate_venue_data": candidate_venue_data,
        "confidence": hint.get("confidence") or "unknown",
        "reason": hint.get("reason") or "",
        "next_step": hint.get("next_step") or "",
        "queue_priority": (task or {}).get("priority_label") or "",
        "queue_reason_codes": (task or {}).get("reason_codes") or [],
        "observed_candidate": {
            "proposed_date_start": observed_candidate.get("proposed_date_start") or "",
            "proposed_venue": observed_candidate.get("proposed_venue") or "",
            "promotion_confidence": observed_candidate.get("promotion_confidence") or "",
            "evidence_url_count": observed_candidate.get("evidence_url_count") or 0,
        },
        "prior_review_decision": decision or None,
        "existing_venue_name_matches": existing_name_matches,
    }


def build(args):
    queue = load_json(args.queue_json, {})
    decisions = load_json(args.decisions_json, {})
    queue_index = queue_by_occurrence(queue)
    decision_index = decisions_by_event(decisions)
    with connect_existing(args.master_db) as conn:
        occurrences = rows(
            conn,
            """
            SELECT o.occurrence_id, o.display_name, o.event_year, o.date_start,
                   o.date_end, o.date_status, o.lifecycle_status, o.source_url,
                   o.series_id, s.usual_venue_id, s.area
            FROM event_occurrences o
            JOIN event_series s ON s.series_id = o.series_id
            WHERE o.venue_id IS NULL
            ORDER BY o.event_year, o.display_name
            """,
        )
        review = [
            classify(
                conn,
                occurrence,
                queue_index.get(occurrence["occurrence_id"]),
                decision_index.get(occurrence["display_name"]),
            )
            for occurrence in occurrences
        ]

    result = {
        "generated_by": "review_missing_occurrence_venues.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "read_only_missing_occurrence_venue_review",
        "sources": {
            "master_db": str(args.master_db),
            "queue_json": str(args.queue_json),
            "decisions_json": str(args.decisions_json),
        },
        "summary": {
            "missing_venue_occurrence_count": len(review),
            "actions": dict(Counter(item["review_action"] for item in review)),
            "candidate_existing_venue_count": sum(1 for item in review if item.get("candidate_venue_id")),
            "new_or_unregistered_venue_candidate_count": sum(
                1 for item in review if item.get("candidate_venue_name") and not item.get("candidate_venue_id")
            ),
            "auto_resolved_count": sum(
                1 for item in review if item.get("candidate_action") == "already_decided"
            ),
        },
        "review": review,
    }
    write_json(args.out_json, result)
    Path(args.out_md).write_text(render_markdown(result), encoding="utf-8")
    return result


def render_markdown(result):
    lines = [
        "# Missing occurrence venue review",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- scope: {result['scope']}",
        f"- missing_venue_occurrence_count: {result['summary']['missing_venue_occurrence_count']}",
        f"- actions: {result['summary']['actions']}",
        f"- candidate_existing_venue_count: {result['summary']['candidate_existing_venue_count']}",
        f"- new_or_unregistered_venue_candidate_count: {result['summary']['new_or_unregistered_venue_candidate_count']}",
        f"- auto_resolved_count: {result['summary']['auto_resolved_count']}",
        "",
        "| action | event | date | candidate venue | confidence | next step |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in result["review"]:
        date_range = item["date_start"]
        if item["date_end"] and item["date_end"] != item["date_start"]:
            date_range = f"{item['date_start']} to {item['date_end']}"
        candidate = item["candidate_venue_name"]
        if item["candidate_venue_id"]:
            candidate = f"{candidate} (`{item['candidate_venue_id']}`)"
        lines.append(
            f"| {item['review_action']} | {item['event_name']} | {date_range} | "
            f"{candidate} | {item['confidence']} | {item['next_step']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-db", default=str(MASTER_DB))
    parser.add_argument("--queue-json", default=str(QUEUE_JSON))
    parser.add_argument("--decisions-json", default=str(DECISIONS_JSON))
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    args = parser.parse_args()
    result = build(args)
    print(f"missing occurrence venue review: actions={result['summary']['actions']}")


if __name__ == "__main__":
    main()
