"""Build investigation tasks for registered but incomplete events.

This is a dry-run migration helper. It does not write to Notion or public JSON.
It records the review queue in the master SQLite DB and emits JSON/Markdown
views for human triage.
"""

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from operation_safety.manual_apply_guards import MASTER_RDB_ONE_OFF_CONFIRMATION, require_confirmation
from master_rdb.master_db import MASTER_DB, MASTER_MANIFEST, connect_existing, file_sha256, normalize_text, stable_id, table_counts


DATA = Path("data")
NOTION_DB = DATA / "notion_snapshot.sqlite"
OBSERVED_CANDIDATES = DATA / "observed_promotion_candidates.json"
OUT_JSON = DATA / "registered_event_investigation_queue.json"
OUT_MD = DATA / "registered_event_investigation_queue.md"

TOKYO_23_RE = re.compile(
    r"(千代田区|中央区|港区|新宿区|文京区|台東区|墨田区|江東区|品川区|目黒区|大田区|世田谷区|"
    r"渋谷区|中野区|杉並区|豊島区|北区|荒川区|板橋区|練馬区|足立区|葛飾区|江戸川区)"
)
OUTSIDE_TOKYO_HINT_RE = re.compile(
    r"(北海道|札幌|江別|神奈川県|横浜|川崎|鎌倉|葉山|大豆戸|岸根|鳥山|山梨県|上野原|"
    r"千葉県|埼玉県|兵庫県|神戸|尼崎|福岡県|北九州|苅田)"
)
GENERIC_OR_REVIEW_NAME_RE = re.compile(
    r"^(桜まつり|海岸まつり|盆踊り大会)$|"
    r"(ステージプログラム|イベント名未確認|名称推定|20[0-2]\d)"
)


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rows(db_path, query, params=()):
    with connect_existing(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(query, params)]


def relation_map(notion_db):
    by_event = defaultdict(list)
    for row in rows(
        notion_db,
        """
        SELECT page_id, related_page_id
        FROM notion_relations
        WHERE property_name = '会場'
        """,
    ):
        by_event[row["page_id"]].append(row["related_page_id"])
    return by_event


def venues_by_page(notion_db):
    return {
        row["page_id"]: row
        for row in rows(
            notion_db,
            """
            SELECT page_id, venue_name, area, address
            FROM notion_venues
            """,
        )
    }


def occurrence_by_notion_page(master_db):
    if not Path(master_db).exists():
        return {}
    return {
        row["external_id"]: row["master_id"]
        for row in rows(
            master_db,
            """
            SELECT external_id, master_id
            FROM external_record_links
            WHERE system = 'notion'
              AND source_key = 'events'
              AND master_table = 'event_occurrences'
            """,
        )
    }


def occurrence_state_by_id(master_db):
    if not Path(master_db).exists():
        return {}
    return {
        row["occurrence_id"]: row
        for row in rows(
            master_db,
            """
            SELECT o.occurrence_id, o.event_year, o.date_start, o.date_end,
                   o.venue_id, o.source_url, v.canonical_name AS venue_name,
                   v.area AS venue_area, v.address AS venue_address
            FROM event_occurrences o
            LEFT JOIN venues v ON v.venue_id = o.venue_id
            """,
        )
    }


def observed_candidates_by_occurrence(path):
    data = load_json(path, {})
    grouped = defaultdict(list)
    confidence_rank = {"high": 3, "medium": 2, "low": 1}
    for candidate in data.get("candidates") or []:
        occurrence_id = candidate.get("target_occurrence_id")
        if not occurrence_id:
            continue
        grouped[occurrence_id].append(candidate)
    output = {}
    for occurrence_id, candidates in grouped.items():
        best = max(
            candidates,
            key=lambda row: confidence_rank.get(row.get("promotion_confidence"), 0),
        )
        output[occurrence_id] = {
            "count": len(candidates),
            "best_confidence": best.get("promotion_confidence") or "",
            "best_candidate": best,
        }
    return output


def parse_months(value):
    months = []
    for match in re.finditer(r"(?<!\d)(1[0-2]|[1-9])\s*月?", str(value or "")):
        month = int(match.group(1))
        if month not in months:
            months.append(month)
    return months


def event_year(start_date, event_name):
    for value in [start_date, event_name]:
        match = re.search(r"(20\d{2})", str(value or ""))
        if match:
            return int(match.group(1))
    return 2026


def priority_for(item):
    score = 0
    reasons = []

    if item["scope"] == "primary_unconfirmed":
        score += 2
        reasons.append("status_unconfirmed")

    if item["missing_date"] and item["missing_venue"]:
        score += 3
        reasons.append("missing_date_and_venue")
    elif item["missing_date"]:
        score += 2
        reasons.append("missing_date")
    elif item["missing_venue"]:
        score += 2
        reasons.append("missing_venue")

    if item["source_url"]:
        score += 2
        reasons.append("has_source_url")
    else:
        score -= 1
        reasons.append("no_source_url")

    if item["is_tokyo_23_hint"]:
        score += 2
        reasons.append("tokyo_23_hint")

    if item["is_outside_tokyo_23_hint"]:
        score -= 3
        reasons.append("outside_tokyo_23_hint")

    if item["observed_candidate_count"]:
        if item["observed_candidate_confidence"] in {"high", "medium"}:
            score += 2
            reasons.append("has_observed_promotion_candidate")
        else:
            reasons.append("low_confidence_observed_candidate")
        if item["observed_candidate_confidence"] == "high":
            score += 2
            reasons.append("observed_candidate_high")
        elif item["observed_candidate_confidence"] == "medium":
            score += 1
            reasons.append("observed_candidate_medium")

    if item["needs_name_review"]:
        score -= 2
        reasons.append("needs_name_review")

    if item["needs_occurrence_split"]:
        score -= 2
        reasons.append("needs_occurrence_split")

    if item["has_archival_source_url"]:
        score -= 2
        reasons.append("archival_source_url")

    if 7 in item["annual_months"] or 8 in item["annual_months"]:
        score += 1
        reasons.append("summer_month_hint")

    if item["status"] in {"確認済み", "終了"}:
        score -= 2
        reasons.append("secondary_status")

    if score >= 9:
        label = "P0"
        action = "pre_cutover_quick_research"
    elif score >= 6:
        label = "P1"
        action = "queue_for_post_cutover_research"
    else:
        label = "P2"
        action = "keep_as_migration_queue_only"

    if (
        item["is_outside_tokyo_23_hint"]
        or item["needs_name_review"]
        or item["needs_occurrence_split"]
        or item["has_archival_source_url"]
    ) and label == "P0":
        label = "P1"
        action = "queue_for_post_cutover_research"

    return score, label, action, reasons


def build_queue(notion_db, master_db, observed_candidates_path):
    events = rows(
        notion_db,
        """
        SELECT page_id, event_name, venue_ids_json, start_date, end_date, status,
               annual_months, detail, public_intro, source_url
        FROM notion_events
        ORDER BY event_name
        """,
    )
    rels = relation_map(notion_db)
    venue_rows = venues_by_page(notion_db)
    occurrence_map = occurrence_by_notion_page(master_db)
    occurrence_states = occurrence_state_by_id(master_db)
    observed_by_occurrence = observed_candidates_by_occurrence(observed_candidates_path)

    queue = []
    skipped_complete = 0
    for row in events:
        venue_page_ids = rels.get(row["page_id"]) or json.loads(row.get("venue_ids_json") or "[]")
        venues = [venue_rows[page_id] for page_id in venue_page_ids if page_id in venue_rows]
        occurrence_id = occurrence_map.get(row["page_id"]) or ""
        occurrence_state = occurrence_states.get(occurrence_id) or {}
        rdb_start_date = (occurrence_state.get("date_start") or "").strip()
        rdb_venue_name = (occurrence_state.get("venue_name") or "").strip()
        missing_date = not ((row.get("start_date") or "").strip() or rdb_start_date)
        missing_venue = not (venues or rdb_venue_name)
        if not missing_date and not missing_venue:
            skipped_complete += 1
            continue

        status = row.get("status") or ""
        scope = "primary_unconfirmed" if status == "未確認" else "secondary_incomplete"
        observed = observed_by_occurrence.get(occurrence_id) or {}
        venue_names = [venue.get("venue_name") or "" for venue in venues if venue.get("venue_name")]
        if rdb_venue_name and rdb_venue_name not in venue_names:
            venue_names.append(rdb_venue_name)
        search_text = " ".join(
            [
                row.get("event_name") or "",
                occurrence_state.get("source_url") or row.get("source_url") or "",
                row.get("detail") or "",
                row.get("public_intro") or "",
                " ".join(venue_names),
                occurrence_state.get("venue_area") or "",
                occurrence_state.get("venue_address") or "",
                " ".join(venue.get("area") or "" for venue in venues),
                " ".join(venue.get("address") or "" for venue in venues),
            ]
        )
        outside_hint = bool(OUTSIDE_TOKYO_HINT_RE.search(search_text))
        source_url = occurrence_state.get("source_url") or row.get("source_url") or ""
        item = {
            "task_id": stable_id("evtinv", row["page_id"], row.get("event_name")),
            "scope": scope,
            "occurrence_id": occurrence_id,
            "notion_page_id": row["page_id"],
            "event_name": row.get("event_name") or "",
            "event_year": occurrence_state.get("event_year") or event_year(row.get("start_date"), row.get("event_name")),
            "status": status,
            "missing_date": missing_date,
            "missing_venue": missing_venue,
            "known_venue_names": venue_names,
            "source_url": source_url,
            "annual_months": parse_months(row.get("annual_months")),
            "is_tokyo_23_hint": bool(TOKYO_23_RE.search(search_text)) and not outside_hint,
            "is_outside_tokyo_23_hint": outside_hint,
            "needs_name_review": bool(GENERIC_OR_REVIEW_NAME_RE.search(row.get("event_name") or "")),
            "needs_occurrence_split": len(venue_names) > 1,
            "has_archival_source_url": "bonmaru.zenmin-odori.jp" in source_url,
            "observed_candidate_count": observed.get("count", 0),
            "observed_candidate_confidence": observed.get("best_confidence", ""),
            "observed_candidate": observed.get("best_candidate") or {},
        }
        score, label, action, reasons = priority_for(item)
        item.update(
            {
                "priority_score": score,
                "priority_label": label,
                "recommended_action": action,
                "reason_codes": reasons,
            }
        )
        queue.append(item)

    queue.sort(
        key=lambda item: (
            0 if item["scope"] == "primary_unconfirmed" else 1,
            item["priority_label"],
            -item["priority_score"],
            item["event_name"],
        )
    )
    return queue, skipped_complete


def write_tasks_to_master(master_db, queue):
    now = datetime.now(timezone.utc).isoformat()
    with connect_existing(master_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("DELETE FROM event_investigation_tasks")
        for item in queue:
            conn.execute(
                """
                INSERT INTO event_investigation_tasks(
                  task_id, occurrence_id, notion_page_id, event_name, event_year, status,
                  missing_date, missing_venue, known_venue_names_json, source_url,
                  observed_candidate_count, observed_candidate_confidence,
                  priority_score, priority_label, recommended_action, reason_codes_json,
                  notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["task_id"],
                    item["occurrence_id"] or None,
                    item["notion_page_id"],
                    item["event_name"],
                    item["event_year"],
                    item["status"],
                    int(item["missing_date"]),
                    int(item["missing_venue"]),
                    json.dumps(item["known_venue_names"], ensure_ascii=False),
                    item["source_url"],
                    item["observed_candidate_count"],
                    item["observed_candidate_confidence"],
                    item["priority_score"],
                    item["priority_label"],
                    item["recommended_action"],
                    json.dumps(item["reason_codes"], ensure_ascii=False),
                    "",
                    now,
                    now,
                ),
            )
        conn.commit()


def refresh_manifest(master_db, manifest_path, queue_output_path):
    manifest_path = Path(manifest_path)
    if not manifest_path.exists():
        return
    manifest = load_json(manifest_path, {})
    with connect_existing(master_db) as conn:
        manifest["table_counts"] = table_counts(conn)
    manifest["database_checksum"] = file_sha256(master_db)
    manifest.setdefault("post_build_outputs", {})
    manifest["post_build_outputs"]["registered_event_investigation_queue"] = str(queue_output_path)
    manifest.setdefault("post_build_steps", [])
    if "build_registered_event_investigation_queue.py" not in manifest["post_build_steps"]:
        manifest["post_build_steps"].append("build_registered_event_investigation_queue.py")
    write_json(manifest_path, manifest)


def summary_for(queue, skipped_complete):
    by_scope = Counter(item["scope"] for item in queue)
    by_priority = Counter(item["priority_label"] for item in queue)
    by_status = Counter(item["status"] for item in queue)
    by_gap = Counter(
        "date_and_venue"
        if item["missing_date"] and item["missing_venue"]
        else "date_only"
        if item["missing_date"]
        else "venue_only"
        for item in queue
    )
    return {
        "registered_event_count": len(queue) + skipped_complete,
        "complete_event_count": skipped_complete,
        "incomplete_event_count": len(queue),
        "primary_unconfirmed_incomplete_count": by_scope["primary_unconfirmed"],
        "secondary_incomplete_count": by_scope["secondary_incomplete"],
        "by_scope": dict(by_scope),
        "by_priority": dict(by_priority),
        "by_status": dict(by_status),
        "by_missing_fields": dict(by_gap),
    }


def md_bool(value):
    return "yes" if value else ""


def render_markdown(data):
    summary = data["summary"]
    lines = [
        "# Registered event investigation queue",
        "",
        f"- generated_at: {data['generated_at']}",
        f"- registered_event_count: {summary['registered_event_count']}",
        f"- incomplete_event_count: {summary['incomplete_event_count']}",
        f"- primary_unconfirmed_incomplete_count: {summary['primary_unconfirmed_incomplete_count']}",
        f"- secondary_incomplete_count: {summary['secondary_incomplete_count']}",
        f"- by_priority: {summary['by_priority']}",
        "",
        "## Primary queue",
        "",
        "| priority | score | event | missing date | missing venue | venue | source | observed | action |",
        "| --- | ---: | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in [item for item in data["tasks"] if item["scope"] == "primary_unconfirmed"][:160]:
        source = "yes" if row["source_url"] else ""
        observed = row["observed_candidate_confidence"] or (str(row["observed_candidate_count"]) if row["observed_candidate_count"] else "")
        lines.append(
            f"| {row['priority_label']} | {row['priority_score']} | {row['event_name']} | "
            f"{md_bool(row['missing_date'])} | {md_bool(row['missing_venue'])} | "
            f"{', '.join(row['known_venue_names'])} | {source} | {observed} | {row['recommended_action']} |"
        )
    lines.extend(
        [
            "",
            "## Secondary incomplete",
            "",
            "| priority | score | status | event | missing date | missing venue | action |",
            "| --- | ---: | --- | --- | --- | --- | --- |",
        ]
    )
    for row in [item for item in data["tasks"] if item["scope"] == "secondary_incomplete"][:80]:
        lines.append(
            f"| {row['priority_label']} | {row['priority_score']} | {row['status']} | {row['event_name']} | "
            f"{md_bool(row['missing_date'])} | {md_bool(row['missing_venue'])} | {row['recommended_action']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--notion-db", default=str(NOTION_DB))
    parser.add_argument("--master-db", default=str(MASTER_DB))
    parser.add_argument("--observed-candidates", default=str(OBSERVED_CANDIDATES))
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    parser.add_argument("--manifest", default=str(MASTER_MANIFEST))
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        require_confirmation(
            True,
            args.confirm,
            MASTER_RDB_ONE_OFF_CONFIRMATION,
            "master RDB registered-event investigation derived-table rebuild",
        )
    except ValueError as exc:
        parser.error(str(exc))

    queue, skipped_complete = build_queue(
        Path(args.notion_db),
        Path(args.master_db),
        Path(args.observed_candidates),
    )
    write_tasks_to_master(Path(args.master_db), queue)
    data = {
        "generated_by": "build_registered_event_investigation_queue.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "notion_db": args.notion_db,
            "master_db": args.master_db,
            "observed_candidates": args.observed_candidates,
        },
        "summary": summary_for(queue, skipped_complete),
        "tasks": queue,
    }
    write_json(args.out_json, data)
    Path(args.out_md).write_text(render_markdown(data), encoding="utf-8")
    refresh_manifest(Path(args.master_db), Path(args.manifest), Path(args.out_json))
    print(
        "registered event investigation queue: "
        f"tasks={len(queue)} primary={data['summary']['primary_unconfirmed_incomplete_count']} "
        f"secondary={data['summary']['secondary_incomplete_count']} "
        f"priority={data['summary']['by_priority']}"
    )


if __name__ == "__main__":
    main()
