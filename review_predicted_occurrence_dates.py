"""Review predicted occurrence date queue against curated 2026 occurrences.

Default mode is read-only. Apply mode only marks prediction rows that are
already superseded by a curated occurrence; it does not create occurrences,
write Notion, or change public JSON.
"""

import argparse
import json
import shutil
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from master_db import MASTER_DB


DATA = Path("data")
OUT_JSON = DATA / "predicted_occurrence_date_review.json"
OUT_MD = DATA / "predicted_occurrence_date_review.md"
BACKUP_DIR = DATA / "backups"
CONFIRM = "APPLY PREDICTED DATE REVIEW"


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rows(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def backup_db(source, now):
    stamp = now.replace("-", "").replace(":", "").replace("+00:00", "Z")
    backup = BACKUP_DIR / f"{Path(source).stem}.{stamp}{Path(source).suffix}.bak"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, backup)
    return backup


def curated_2026_occurrence(conn, prediction):
    matches = rows(
        conn,
        """
        SELECT o.occurrence_id, o.display_name, o.event_year, o.date_start, o.date_end,
               o.date_status, o.lifecycle_status, o.confidence, o.source_url,
               v.canonical_name AS venue_name
        FROM event_occurrences o
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        WHERE o.series_id = ?
          AND o.event_year = ?
          AND o.date_status IN ('confirmed', 'ended')
        ORDER BY o.date_status = 'confirmed' DESC, o.updated_at DESC
        """,
        (prediction["target_series_id"], prediction["predicted_year"]),
    )
    return matches[0] if matches else None


def curated_2026_occurrence_by_name(conn, prediction):
    matches = rows(
        conn,
        """
        SELECT o.occurrence_id, o.series_id, s.canonical_name AS series_name,
               o.display_name, o.event_year, o.date_start, o.date_end,
               o.date_status, o.lifecycle_status, o.confidence, o.source_url,
               v.canonical_name AS venue_name
        FROM event_occurrences o
        JOIN event_series s ON s.series_id = o.series_id
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        WHERE o.display_name = ?
          AND o.event_year = ?
          AND o.date_status IN ('confirmed', 'ended')
        ORDER BY o.date_status = 'confirmed' DESC, o.updated_at DESC
        """,
        (prediction["target_event_name"], prediction["predicted_year"]),
    )
    return matches[0] if matches else None


def linked_curated_occurrence(conn, prediction):
    if not prediction.get("target_occurrence_id"):
        return None
    matches = rows(
        conn,
        """
        SELECT o.occurrence_id, o.series_id, s.canonical_name AS series_name,
               o.display_name, o.event_year, o.date_start, o.date_end,
               o.date_status, o.lifecycle_status, o.confidence, o.source_url,
               v.canonical_name AS venue_name
        FROM event_occurrences o
        JOIN event_series s ON s.series_id = o.series_id
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        WHERE o.occurrence_id = ?
          AND o.event_year = ?
          AND o.date_status IN ('confirmed', 'ended')
        """,
        (prediction["target_occurrence_id"], prediction["predicted_year"]),
    )
    return matches[0] if matches else None


def classify_against_curated(prediction, curated, linked=False):
    predicted_start = prediction["date_start"]
    predicted_end = prediction["date_end"] or prediction["date_start"]
    curated_start = curated["date_start"]
    curated_end = curated["date_end"] or curated["date_start"]
    if predicted_start == curated_start and predicted_end == curated_end:
        new_status = "matches_curated"
        action = "already_matches_curated" if prediction["application_status"] == new_status else "mark_matches_curated"
        reason = "linked_occurrence_matches_curated" if linked else "predicted_date_matches_curated_occurrence"
    else:
        new_status = "superseded_by_curated"
        action = (
            "already_superseded_by_curated"
            if prediction["application_status"] == new_status
            else "mark_superseded_by_curated"
        )
        reason = (
            "linked_occurrence_has_different_confirmed_date"
            if linked
            else "curated_occurrence_has_different_confirmed_date"
        )
    return {
        "predicted_date_id": prediction["predicted_date_id"],
        "event_name": prediction["target_event_name"],
        "current_status": prediction["application_status"],
        "new_status": new_status,
        "review_action": action,
        "reason": reason,
        "predicted": prediction,
        "curated_occurrence": curated,
    }


def classify_prediction(conn, prediction):
    linked_curated = linked_curated_occurrence(conn, prediction)
    if linked_curated:
        return classify_against_curated(prediction, linked_curated, linked=True)

    curated = curated_2026_occurrence(conn, prediction)
    if not curated:
        same_name_curated = curated_2026_occurrence_by_name(conn, prediction)
        if same_name_curated:
            return {
                "predicted_date_id": prediction["predicted_date_id"],
                "event_name": prediction["target_event_name"],
                "current_status": prediction["application_status"],
                "review_action": "series_link_review_curated_exists",
                "reason": "curated_2026_occurrence_exists_on_different_series",
                "predicted": prediction,
                "curated_occurrence": same_name_curated,
            }
        return {
            "predicted_date_id": prediction["predicted_date_id"],
            "event_name": prediction["target_event_name"],
            "current_status": prediction["application_status"],
            "review_action": "keep_prediction_queue",
            "reason": "no_curated_2026_occurrence",
            "predicted": prediction,
            "curated_occurrence": None,
        }
    return classify_against_curated(prediction, curated)


def apply_review(conn, item, now):
    if item["review_action"] not in {"mark_matches_curated", "mark_superseded_by_curated"}:
        return None
    predicted_date_id = item["predicted_date_id"]
    occurrence_id = item["curated_occurrence"]["occurrence_id"]
    conn.execute(
        """
        UPDATE predicted_occurrence_dates
        SET application_status = ?,
            target_occurrence_id = ?,
            updated_at = ?
        WHERE predicted_date_id = ?
        """,
        (item["new_status"], occurrence_id, now, predicted_date_id),
    )
    conn.execute(
        """
        UPDATE notion_sync_jobs
        SET status = ?,
            result_json = ?
        WHERE target_table = 'predicted_occurrence_dates'
          AND target_id = ?
          AND status = 'pending'
        """,
        (
            item["new_status"],
            json.dumps(
                {
                    "reviewed_by": "review_predicted_occurrence_dates.py",
                    "reviewed_at": now,
                    "reason": item["reason"],
                    "curated_occurrence_id": occurrence_id,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            predicted_date_id,
        ),
    )
    return {
        "predicted_date_id": predicted_date_id,
        "event_name": item["event_name"],
        "new_status": item["new_status"],
        "target_occurrence_id": occurrence_id,
    }


def build_report(conn):
    predictions = rows(
        conn,
        """
        SELECT p.*, s.canonical_name, s.area, v.canonical_name AS usual_venue
        FROM predicted_occurrence_dates p
        JOIN event_series s ON s.series_id = p.target_series_id
        LEFT JOIN venues v ON v.venue_id = s.usual_venue_id
        ORDER BY p.application_status, p.score DESC, p.target_event_name
        """,
    )
    review = [classify_prediction(conn, item) for item in predictions]
    return predictions, review


def render_markdown(result):
    lines = [
        "# Predicted occurrence date review",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {'APPLY' if result['options']['apply'] else 'DRY-RUN'}",
        f"- master_db: `{result['sources']['master_db']}`",
        f"- backup_db: `{result['outputs'].get('backup_db') or ''}`",
        f"- prediction_count: {result['summary']['prediction_count']}",
        f"- actions: {result['summary']['actions']}",
        f"- applied_count: {result['summary']['applied_count']}",
        "",
        "| action | event | predicted | curated | reason |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in result["review"]:
        pred = item["predicted"]
        curated = item.get("curated_occurrence") or {}
        predicted_dates = f"{pred['date_start']} to {pred.get('date_end') or ''}".strip()
        curated_dates = ""
        if curated:
            curated_dates = f"{curated.get('date_start') or ''} to {curated.get('date_end') or ''}".strip()
        lines.append(
            f"| {item['review_action']} | {item['event_name']} | {predicted_dates} | {curated_dates} | {item['reason']} |"
        )
    lines.append("")
    return "\n".join(lines)


def run(args):
    if args.apply and args.confirm != CONFIRM:
        raise SystemExit(f"--apply requires --confirm '{CONFIRM}'")
    now = datetime.now(timezone.utc).isoformat()
    backup_path = ""
    if args.apply:
        backup_path = str(backup_db(args.master_db, now))
    with sqlite3.connect(args.master_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        predictions, review = build_report(conn)
        applied = []
        if args.apply:
            for item in review:
                applied_item = apply_review(conn, item, now)
                if applied_item:
                    applied.append(applied_item)
            fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
            if fk_rows:
                conn.rollback()
                raise SystemExit(f"foreign_key_check failed after apply: {fk_rows[:10]}")
            conn.commit()
    result = {
        "generated_by": "review_predicted_occurrence_dates.py",
        "generated_at": now,
        "scope": "predicted_date_review_no_notion_no_public_json",
        "sources": {"master_db": str(args.master_db)},
        "outputs": {"backup_db": backup_path},
        "options": {"apply": bool(args.apply)},
        "summary": {
            "prediction_count": len(predictions),
            "actions": dict(Counter(item["review_action"] for item in review)),
            "applied_count": len(applied),
        },
        "applied": applied,
        "review": review,
    }
    write_json(args.out_json, result)
    Path(args.out_md).write_text(render_markdown(result), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-db", default=str(MASTER_DB))
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    result = run(args)
    print(
        "predicted occurrence date review: "
        f"actions={result['summary']['actions']} applied={result['summary']['applied_count']}"
    )


if __name__ == "__main__":
    main()
