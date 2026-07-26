#!/usr/bin/env python3
"""Remove the DJ segment headings that had already reached the public song layer.

bonsuke.jp listed "DJタイム" (東本願寺, 2025 observed + 2026 inherited prediction)
and "DJ「俚謡山脈」" / "DJ「珍盤亭娯楽師匠」" (大和町八幡神社) as songs danced at
those events. They are progression headings from the YouTube setlists, not song
titles. 21252b0 added a shape check that rejects this class at ingest time, but
the four occurrence_songs rows written before that gate existed are still in the
RDB and still published. 内田さん decided on 2026-07-26 to remove them rather
than move them into the event description.

Following the existing 曲マスタ整理 convention (see the ten songs.status='無効'
rows), the songs rows are not deleted: they are marked 無効 with the reason in
memo so the decision stays auditable, and only the occurrence_songs rows -- the
layer export_public_events.py publishes -- are removed. observed_occurrence_songs
keeps the raw observation (that the video description really did say this), with
its occurrence_song_id detached; that is the same shape as the 30178 observed
rows that never reached the public layer.

Default mode writes to a copied SQLite DB. Apply mode touches only the rows
listed in this file and does not write Notion or public JSON.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from master_rdb.master_db import MASTER_DB, refresh_manifest_database_state, table_counts


DATA = Path("data")
OUT_DB = DATA / "dj_segment_song_removal_20260726_dry_run.sqlite"
OUT_JSON = DATA / "dj_segment_song_removal_20260726_apply_report.json"
BACKUP_DIR = DATA / "backups"
CONFIRM = "APPLY DJ SEGMENT SONG REMOVAL 20260726"
INACTIVE_STATUS = "無効"
MEMO_SUFFIX = "曲マスタ整理: 無効化。\n理由: YouTubeセットリストのDJ進行見出しで、曲名ではない。"

# occurrence_songs rows to delete, with the state they must be in beforehand so a
# drifted RDB is skipped instead of silently deleting something else.
OCCURRENCE_SONGS = [
    {
        "occurrence_song_id": "ocs_inherit_df3e48cc4c8fd857",
        "expected_song_title_raw": "DJタイム",
        "expected_occurrence_id": "occ_22c38bfed7ff79db",
        "occurrence_label": "東本願寺盆踊り 2026 (inherited prediction, 57%)",
    },
    {
        "occurrence_song_id": "ocs_eaf526d40354bb24",
        "expected_song_title_raw": "DJタイム",
        "expected_occurrence_id": "occ_c2b890eb32b32469",
        "occurrence_label": "東本願寺盆踊り 2025 (observed, the prediction's source)",
    },
    {
        "occurrence_song_id": "ocs_4c630a84238e7ec4",
        "expected_song_title_raw": "DJ「俚謡山脈」",
        "expected_occurrence_id": "occ_332b7b4f03829f7e",
        "occurrence_label": "大和町八幡神社大盆踊り会 2026 (observed, 95%)",
    },
    {
        "occurrence_song_id": "ocs_10e9dfc0fdc8d877",
        "expected_song_title_raw": "DJ「珍盤亭娯楽師匠」",
        "expected_occurrence_id": "occ_332b7b4f03829f7e",
        "occurrence_label": "大和町八幡神社大盆踊り会 2026 (observed, 95%)",
    },
]

# songs rows to deactivate (not delete).
SONGS = [
    {"song_id": "song_cand_2595c2aa125ee6a0", "expected_canonical_title": "DJタイム"},
    {"song_id": "song_cand_0c8fa3c0245811c2", "expected_canonical_title": "DJ「俚謡山脈」"},
    {"song_id": "song_cand_62cc39e3c2fb8f0b", "expected_canonical_title": "DJ「珍盤亭娯楽師匠」"},
]


def rows(conn: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy_db(source: Path, out_db: Path) -> None:
    out_db.parent.mkdir(parents=True, exist_ok=True)
    if out_db.exists():
        out_db.unlink()
    shutil.copy2(source, out_db)


def backup_db(source: Path, now: str) -> Path:
    stamp = now.replace("-", "").replace(":", "").replace("+00:00", "Z")
    backup = BACKUP_DIR / f"{source.stem}.{stamp}{source.suffix}.bak"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, backup)
    return backup


def occurrence_song(conn: sqlite3.Connection, occurrence_song_id: str) -> dict[str, Any] | None:
    found = rows(
        conn,
        """
        SELECT occurrence_song_id, occurrence_id, song_id, song_title_raw, origin, role,
               evidence_status, probability
        FROM occurrence_songs WHERE occurrence_song_id = ?
        """,
        (occurrence_song_id,),
    )
    return found[0] if found else None


def song(conn: sqlite3.Connection, song_id: str) -> dict[str, Any] | None:
    found = rows(
        conn,
        "SELECT song_id, canonical_title, status, evidence_count, source_url, memo FROM songs WHERE song_id = ?",
        (song_id,),
    )
    return found[0] if found else None


def build_plan(conn: sqlite3.Connection) -> tuple[list, list, list, list, list]:
    planned_songs_rows: list[dict[str, Any]] = []
    planned_song_master: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for item in OCCURRENCE_SONGS:
        before = occurrence_song(conn, item["occurrence_song_id"])
        if not before:
            skipped.append({**item, "skip_reason": "missing_occurrence_song"})
            continue
        if before["song_title_raw"] != item["expected_song_title_raw"]:
            skipped.append({**item, "skip_reason": "unexpected_title", "before": before})
            continue
        if before["occurrence_id"] != item["expected_occurrence_id"]:
            skipped.append({**item, "skip_reason": "unexpected_occurrence", "before": before})
            continue
        planned_songs_rows.append({**item, "before": before})

    for item in SONGS:
        before = song(conn, item["song_id"])
        if not before:
            skipped.append({**item, "skip_reason": "missing_song"})
            continue
        if before["canonical_title"] != item["expected_canonical_title"]:
            skipped.append({**item, "skip_reason": "unexpected_canonical_title", "before": before})
            continue
        if before["status"] == INACTIVE_STATUS:
            skipped.append({**item, "skip_reason": "already_inactive", "before": before})
            continue
        planned_song_master.append({**item, "before": before})

    ids = tuple(item["occurrence_song_id"] for item in planned_songs_rows)
    placeholders = ",".join("?" * len(ids)) or "NULL"
    evidence_links = rows(
        conn,
        f"SELECT occurrence_song_id, evidence_id, link_status FROM occurrence_song_evidence_links WHERE occurrence_song_id IN ({placeholders})",
        ids,
    )
    observed_links = rows(
        conn,
        f"""
        SELECT observed_occurrence_song_id, occurrence_song_id, raw_song_title, matched_song_id, match_status
        FROM observed_occurrence_songs WHERE occurrence_song_id IN ({placeholders})
        """,
        ids,
    )
    return planned_songs_rows, planned_song_master, evidence_links, observed_links, skipped


def apply_plan(
    conn: sqlite3.Connection,
    planned_songs_rows: list[dict[str, Any]],
    planned_song_master: list[dict[str, Any]],
    now: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    for item in planned_songs_rows:
        ocs_id = item["occurrence_song_id"]
        # Detach the observation before the row it points at disappears, so the raw
        # evidence survives without a dangling FK.
        conn.execute(
            "UPDATE observed_occurrence_songs SET occurrence_song_id = NULL, updated_at = ? WHERE occurrence_song_id = ?",
            (now, ocs_id),
        )
        conn.execute("DELETE FROM occurrence_song_evidence_links WHERE occurrence_song_id = ?", (ocs_id,))
        conn.execute("DELETE FROM occurrence_songs WHERE occurrence_song_id = ?", (ocs_id,))

    deactivated: list[dict[str, Any]] = []
    for item in planned_song_master:
        before = item["before"]
        memo = (before.get("memo") or "").rstrip()
        memo = f"{memo}\n\n{MEMO_SUFFIX}" if memo else MEMO_SUFFIX
        conn.execute(
            "UPDATE songs SET status = ?, evidence_count = 0, source_url = '', memo = ?, updated_at = ? WHERE song_id = ?",
            (INACTIVE_STATUS, memo, now, item["song_id"]),
        )
        deactivated.append({**item, "after": song(conn, item["song_id"])})

    removed = [
        {**item, "after": occurrence_song(conn, item["occurrence_song_id"])}
        for item in planned_songs_rows
    ]
    return removed, deactivated


def rollback_checks(
    conn: sqlite3.Connection,
    removed: list[dict[str, Any]],
    deactivated: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_rows:
        issues.append({"severity": "high", "issue_type": "foreign_key_check_failed", "count": len(fk_rows)})

    for item in removed:
        if item.get("after") is not None:
            issues.append(
                {
                    "severity": "high",
                    "issue_type": "occurrence_song_not_removed",
                    "occurrence_song_id": item["occurrence_song_id"],
                }
            )
        leftover_links = conn.execute(
            "SELECT COUNT(*) FROM occurrence_song_evidence_links WHERE occurrence_song_id = ?",
            (item["occurrence_song_id"],),
        ).fetchone()[0]
        if leftover_links:
            issues.append(
                {
                    "severity": "high",
                    "issue_type": "evidence_link_not_removed",
                    "occurrence_song_id": item["occurrence_song_id"],
                    "count": leftover_links,
                }
            )

    for item in deactivated:
        after = item.get("after") or {}
        if after.get("status") != INACTIVE_STATUS:
            issues.append(
                {"severity": "high", "issue_type": "song_not_deactivated", "song_id": item["song_id"]}
            )

    # Nothing outside the DJ rows may lose its public song entry.
    remaining_dj = conn.execute(
        "SELECT COUNT(*) FROM occurrence_songs WHERE song_title_raw LIKE 'DJ%' OR song_title_raw LIKE '%DJタイム%'"
    ).fetchone()[0]
    if remaining_dj:
        issues.append({"severity": "medium", "issue_type": "dj_rows_remain", "count": remaining_dj})
    return issues


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--master-db", type=Path, default=MASTER_DB)
    parser.add_argument("--dry-run-db", type=Path, default=OUT_DB)
    args = parser.parse_args()

    now = datetime.now(timezone.utc).isoformat()
    mode = "apply" if args.apply else "dry_run"
    backup = ""

    if args.apply:
        if args.confirm != CONFIRM:
            raise SystemExit(f"--apply requires --confirm {CONFIRM!r}")
        backup = str(backup_db(args.master_db, now))
        working_db = args.master_db
    else:
        copy_db(args.master_db, args.dry_run_db)
        working_db = args.dry_run_db

    with closing(sqlite3.connect(working_db)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        before_counts = table_counts(conn)
        planned_rows, planned_master, evidence_links, observed_links, skipped = build_plan(conn)
        removed, deactivated = apply_plan(conn, planned_rows, planned_master, now)
        issues = rollback_checks(conn, removed, deactivated)
        if issues:
            conn.rollback()
            rolled_back, db_committed = True, False
        else:
            conn.commit()
            rolled_back, db_committed = False, True
            if args.apply:
                refresh_manifest_database_state(working_db, updated_at=now)
        after_counts = table_counts(conn)

    result = {
        "generated_at": now,
        "generated_by": "apply_dj_segment_song_removal_20260726.py",
        "mode": mode,
        "outputs": {"target_db": str(args.master_db if args.apply else args.dry_run_db), "backup_db": backup},
        "write_guard": {"db_committed": db_committed, "rolled_back": rolled_back},
        "summary": {
            "occurrence_songs_removed": len(removed),
            "songs_deactivated": len(deactivated),
            "evidence_links_removed": len(evidence_links),
            "observed_rows_detached": len(observed_links),
            "skipped_count": len(skipped),
            "issues_by_severity": dict(Counter(i.get("severity", "unknown") for i in issues)),
            "before_counts": before_counts,
            "after_counts": after_counts,
        },
        "removed_occurrence_songs": removed,
        "deactivated_songs": deactivated,
        "removed_evidence_links": evidence_links,
        "detached_observed_rows": observed_links,
        "skipped": skipped,
        "issues": issues,
    }
    write_json(OUT_JSON, result)
    print(
        "dj segment song removal: "
        f"mode={mode} removed={len(removed)} deactivated={len(deactivated)} "
        f"links={len(evidence_links)} detached={len(observed_links)} "
        f"committed={db_committed} report={OUT_JSON}"
    )


if __name__ == "__main__":
    main()
