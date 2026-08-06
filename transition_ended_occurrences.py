"""Transition completed confirmed occurrences to the canonical ``ended`` state.

The command is dry-run by default. Production use is deliberately explicit so
the daily collector can publish the RDB update through its existing CAS path.
"""

import argparse
import json
import sqlite3
from datetime import date
from pathlib import Path

from event_model.event_state_axes import update_occurrence_state_axes
from master_rdb.master_db import connect_existing, now_utc


DEFAULT_DB = Path("data/bon_odori_master.sqlite")
APPLY_CONFIRMATION = "TRANSITION ENDED OCCURRENCES"


def transition_candidates(conn, as_of_date):
    """Return confirmed occurrences whose final scheduled date has passed."""
    cursor = conn.execute(
        """
            SELECT
              o.occurrence_id,
              o.display_name AS event_name,
              o.date_start,
              o.date_end,
              COALESCE(NULLIF(o.date_end, ''), o.date_start) AS schedule_end,
              COALESCE(v.area, s.area, '') AS area
            FROM event_occurrences AS o
            JOIN event_series AS s ON s.series_id = o.series_id
            LEFT JOIN venues AS v ON v.venue_id = o.venue_id
            WHERE o.current_event_state = 'confirmed'
              AND COALESCE(NULLIF(o.date_end, ''), o.date_start) < ?
            ORDER BY schedule_end, o.display_name, o.occurrence_id
        """,
        (as_of_date.isoformat(),),
    )
    fields = [column[0] for column in cursor.description]
    return [dict(zip(fields, row)) for row in cursor]


def apply_transitions(conn, candidates, *, now=None):
    """Apply a previously selected transition set. Empty sets are idempotent."""
    now = now or now_utc()
    transitioned = []
    for candidate in candidates:
        occurrence_id = candidate["occurrence_id"]
        update_occurrence_state_axes(conn, occurrence_id, "ended", "confirmed")
        conn.execute(
            "UPDATE event_occurrences SET updated_at = ? WHERE occurrence_id = ?",
            (now, occurrence_id),
        )
        transitioned.append(occurrence_id)
    return transitioned


def build_report(conn, as_of_date, *, apply=False):
    candidates = transition_candidates(conn, as_of_date)
    report = {
        "mode": "apply" if apply else "dry_run",
        "as_of_date": as_of_date.isoformat(),
        "count": len(candidates),
        "targets": candidates,
    }
    if apply:
        report["transitioned_occurrence_ids"] = apply_transitions(conn, candidates)
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--as-of-date", type=date.fromisoformat, default=date.today())
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm")
    parser.add_argument("--report-out", type=Path)
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    if args.apply and args.confirm != APPLY_CONFIRMATION:
        raise SystemExit(f"--apply requires --confirm {APPLY_CONFIRMATION!r}")

    with connect_existing(args.db) as conn:
        conn.row_factory = sqlite3.Row
        report = build_report(conn, args.as_of_date, apply=args.apply)
        if args.apply:
            conn.commit()

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report_out:
        args.report_out.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    return report


if __name__ == "__main__":
    main()
