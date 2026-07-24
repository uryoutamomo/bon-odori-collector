"""Ingest data/youtube_setlist_occurrences.json into the master RDB as observed evidence.

This is the "new direct path" chosen over reviving the frozen legacy
build_song_occurrences.py pipeline (see data/master_rdb_migration_freeze.json,
group legacy_song_occurrence_generation, still active). It writes new
observed_occurrences / observed_occurrence_songs / evidence_items /
occurrence_song_evidence_links rows sourced from cleaned YouTube setlist data
(see commit 5944839 fixing extract_youtube_setlists.py's input-bloat bugs).

Deliberately does NOT populate probability: song_processing/song_occurrences.py's
prediction_probability()/evidence_view_for_year() have not been rewritten to be
RDB-native yet (that is a separate follow-up). This script only raises real
observed-setlist evidence into the RDB so that rewrite has something to compute
against; it must not fabricate a probability value ahead of that logic existing.

Default mode writes only to a copied SQLite DB. Production writes require
--apply and the confirmation phrase.
"""

import argparse
import json
import shutil
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import audit_master_rdb
from rdb_builders.build_master_rdb import quality_flags
from master_rdb.master_db import (
    MASTER_DB,
    connect_existing,
    json_text,
    normalize_text,
    now_utc,
    refresh_manifest_database_state,
    stable_id,
    table_counts,
)
from report_apply.event_report_helpers import find_occurrence_candidates


DATA = Path("data")
SOURCE = DATA / "youtube_setlist_occurrences.json"
OUT_DB = DATA / "youtube_setlist_occurrences_apply_dry_run.sqlite"
OUT_JSON = DATA / "youtube_setlist_occurrences_apply_report.json"
OUT_MD = DATA / "youtube_setlist_occurrences_apply_report.md"
BACKUP_DIR = DATA / "backups"
CONFIRM_PHRASE = "APPLY YOUTUBE SETLIST OCCURRENCES RDB"
SCRIPT_NAME = "apply_youtube_setlist_occurrences_rdb.py"

# Chosen from a manual spot-check of find_occurrence_candidates() scores against this
# dataset (2026-07-24): every match >=0.7 sampled was correct; 0.6-0.7 contained a real
# false positive (飛鳥山公園盆踊り会 -> 鳥山町町内会 at 0.631, wrong venue) alongside
# several correct-but-noisy matches. Missing a match is safe (row stays unmatched and is
# still stored as raw evidence); a wrong match is not, so this errs toward precision.
MATCH_SCORE_THRESHOLD = 0.7
RELIABILITY_BY_CONFIDENCE = {"high": 0.95, "medium": 0.80, "low": 0.55}


def rows(conn, query, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(query, params)]


def scalar(conn, query, params=()):
    return conn.execute(query, params).fetchone()[0]


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy_db(source, out_db):
    source = Path(source)
    out_db = Path(out_db)
    if not source.exists():
        raise FileNotFoundError(source)
    out_db.parent.mkdir(parents=True, exist_ok=True)
    if out_db.exists():
        out_db.unlink()
    shutil.copy2(source, out_db)


def backup_db(source, now):
    source = Path(source)
    if not source.exists():
        raise FileNotFoundError(source)
    stamp = now.replace("-", "").replace(":", "").replace("+00:00", "Z")
    backup = BACKUP_DIR / f"{source.stem}.{stamp}{source.suffix}.bak"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, backup)
    return backup


def validate_apply_request(args):
    if not args.apply:
        return
    if args.confirm != CONFIRM_PHRASE:
        raise ValueError(f"--apply requires --confirm '{CONFIRM_PHRASE}'")
    if Path(args.out_db) == Path(args.master_db):
        raise ValueError("--out-db must not equal --master-db")


def occurrence_year(occurrence):
    for date_value in (occurrence.get("event_date"), (occurrence.get("matched_public_event") or {}).get("date")):
        if date_value:
            try:
                return int(str(date_value)[:4])
            except ValueError:
                continue
    return None


def song_id_for_title(conn, title):
    row = conn.execute(
        "SELECT song_id FROM songs WHERE normalized_title = ?",
        (normalize_text(title),),
    ).fetchone()
    return row[0] if row else None


def best_match(conn, occurrence, year):
    if year is None:
        return None
    candidates = find_occurrence_candidates(
        conn,
        occurrence["event_name_hint"],
        venue_name_hint=occurrence.get("venue"),
        event_year=year,
        limit=1,
    )
    if not candidates or candidates[0]["match_score"] < MATCH_SCORE_THRESHOLD:
        return None
    return candidates[0]


def apply_occurrence(conn, occurrence, now):
    event_name = occurrence.get("event_name_hint") or ""
    venue_name = occurrence.get("venue") or ""
    occurrence_key = occurrence.get("occurrence_key") or ""
    year = occurrence_year(occurrence)
    match = best_match(conn, occurrence, year)
    matched_occurrence_id = match["occurrence_id"] if match else None

    flags = quality_flags(event_name, venue_name)
    if not year:
        flags = flags + ["missing_event_date"]
    if "venue_looks_like_text_fragment" in flags:
        quality_status = "discard_candidate"
    elif "outside_tokyo_23_hint" in flags:
        quality_status = "out_of_scope"
    elif matched_occurrence_id:
        quality_status = "matched_curated"
    else:
        quality_status = "review"

    observed_occurrence_id = stable_id(
        "obsocc", "youtube_setlist", occurrence_key, event_name, venue_name, year or 0
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO observed_occurrences(
          observed_occurrence_id, source, source_occurrence_id, raw_event_name, raw_venue_name,
          normalized_event_name, normalized_venue_name, event_year, matched_occurrence_id,
          match_status, quality_status, quality_flags_json, source_payload_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            observed_occurrence_id,
            "youtube_setlist_occurrences",
            occurrence_key,
            event_name,
            venue_name,
            normalize_text(event_name),
            normalize_text(venue_name),
            year or 0,
            matched_occurrence_id,
            "matched_curated" if matched_occurrence_id else "unmatched",
            quality_status,
            json.dumps(flags, ensure_ascii=False),
            json_text(
                {
                    "occurrence_key": occurrence_key,
                    "event_name_hint": event_name,
                    "venue": venue_name,
                    "event_date": occurrence.get("event_date"),
                    "accounts": occurrence.get("accounts"),
                    "confidence": occurrence.get("confidence"),
                    "matched_public_event": occurrence.get("matched_public_event"),
                    "match_score": match["match_score"] if match else None,
                }
            ),
            now,
            now,
        ),
    )

    confidence = occurrence.get("confidence") or "low"
    reliability = RELIABILITY_BY_CONFIDENCE.get(confidence, 0.55)
    setlist_complete = 1 if confidence == "high" else 0
    accounts = occurrence.get("accounts") or []
    speaker_count = len(set(accounts)) or 1
    source_videos = occurrence.get("source_videos") or []
    first_video = source_videos[0] if source_videos else {}

    song_relation_count = 0
    evidence_count = 0
    for song in occurrence.get("setlist") or []:
        title = song.get("title") or ""
        if not title:
            continue
        normalized = normalize_text(title)
        role = "result"
        song_id = song_id_for_title(conn, title)
        occurrence_song_id = None
        if matched_occurrence_id:
            # occurrence_songs.occurrence_song_id is not a stable function of its own unique key
            # across every writer (e.g. the firsthand field-report pipeline uses an "osong_" prefix
            # instead of this script's "ocs_"). The real identity is the UNIQUE(occurrence_id,
            # normalized_title, role) constraint, so look up an existing row by that key first and
            # reuse its id -- otherwise a fresh INSERT OR IGNORE silently no-ops on the unique
            # conflict while leaving our freshly-computed id unreferenced, and the next statement's
            # FK to it fails.
            existing = conn.execute(
                """
                SELECT occurrence_song_id FROM occurrence_songs
                WHERE occurrence_id = ? AND normalized_title = ? AND role = ?
                """,
                (matched_occurrence_id, normalized, role),
            ).fetchone()
            if existing:
                occurrence_song_id = existing[0]
                conn.execute(
                    """
                    UPDATE occurrence_songs
                    SET evidence_count = evidence_count + 1,
                        source_count = source_count + 1,
                        last_observed_at = COALESCE(NULLIF(?, ''), last_observed_at),
                        updated_at = ?
                    WHERE occurrence_song_id = ?
                    """,
                    (first_video.get("published_at") or "", now, occurrence_song_id),
                )
            else:
                occurrence_song_id = stable_id("ocs", matched_occurrence_id, normalized, role)
                conn.execute(
                    """
                    INSERT INTO occurrence_songs(
                      occurrence_song_id, origin, occurrence_id, song_id, song_title_raw, normalized_title,
                      role, evidence_status, probability, confidence, source_count, evidence_count,
                      inherited_from_year, first_observed_at, last_observed_at, notes, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        occurrence_song_id,
                        "observed_youtube_setlist",
                        matched_occurrence_id,
                        song_id,
                        title,
                        normalized,
                        role,
                        "observed",
                        None,
                        "unknown",
                        1,
                        1,
                        None,
                        first_video.get("published_at") or "",
                        first_video.get("published_at") or "",
                        json_text({"basis": "youtube_observed_setlist", "extraction_confidence": confidence}),
                        now,
                        now,
                    ),
                )

        observed_occurrence_song_id = stable_id("obsocs", observed_occurrence_id, normalized, role)
        conn.execute(
            """
            INSERT OR IGNORE INTO observed_occurrence_songs(
              observed_occurrence_song_id, observed_occurrence_id, occurrence_song_id,
              raw_song_title, normalized_title, matched_song_id, match_status, role,
              evidence_status, probability, evidence_count, speaker_count, setlist_complete,
              prediction_reliability_json, evidence_urls_json, source_payload_json,
              created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                observed_occurrence_song_id,
                observed_occurrence_id,
                occurrence_song_id,
                title,
                normalized,
                song_id,
                "matched_song" if song_id else "unmatched",
                role,
                "observed",
                None,
                1,
                speaker_count,
                setlist_complete,
                json_text([reliability]),
                json_text([song.get("url")] if song.get("url") else []),
                json_text({"confidence": confidence, "reliability_key": occurrence.get("reliability_key")}),
                now,
                now,
            ),
        )
        song_relation_count += 1

        evidence_id = stable_id("ev", "youtube_setlist", observed_occurrence_id, normalized, song.get("url") or "")
        conn.execute(
            """
            INSERT OR IGNORE INTO evidence_items(
              evidence_id, platform, evidence_type, source_key, source_id, account_key,
              title, text_excerpt, url, published_at, observed_at, detected_event_date,
              raw_status, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence_id,
                "youtube",
                "observed",
                "youtube_setlist_occurrences",
                occurrence_key,
                ",".join(accounts),
                first_video.get("title") or "",
                "",
                song.get("url") or "",
                first_video.get("published_at") or "",
                first_video.get("published_at") or "",
                occurrence.get("event_date") or "",
                "result",
                json_text(
                    {
                        "song_number": song.get("number"),
                        "occurrence_key": occurrence_key,
                        "confidence": confidence,
                    }
                ),
            ),
        )
        evidence_count += 1
        if occurrence_song_id:
            conn.execute(
                """
                INSERT OR IGNORE INTO occurrence_song_evidence_links(
                  occurrence_song_id, evidence_id, link_status, confidence, notes
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (occurrence_song_id, evidence_id, "linked", reliability, "youtube_setlist_occurrences"),
            )

    return {
        "observed_occurrence_id": observed_occurrence_id,
        "occurrence_key": occurrence_key,
        "matched_occurrence_id": matched_occurrence_id,
        "match_score": match["match_score"] if match else None,
        "quality_status": quality_status,
        "song_relation_count": song_relation_count,
        "evidence_count": evidence_count,
    }


def apply_all(conn, occurrences, now):
    results = [apply_occurrence(conn, occurrence, now) for occurrence in occurrences]
    return results


def consistency_checks(conn, results):
    issues = []
    fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_rows:
        issues.append(
            {
                "severity": "high",
                "issue_type": "foreign_key_check_failed",
                "count": len(fk_rows),
                "sample": [tuple(row) for row in fk_rows[:10]],
            }
        )
    matched_count = sum(1 for r in results if r["matched_occurrence_id"])
    if matched_count == 0:
        issues.append({"severity": "high", "issue_type": "no_matches_produced"})
    orphan_links = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM occurrence_song_evidence_links l
        LEFT JOIN occurrence_songs s ON s.occurrence_song_id = l.occurrence_song_id
        LEFT JOIN evidence_items e ON e.evidence_id = l.evidence_id
        WHERE s.occurrence_song_id IS NULL OR e.evidence_id IS NULL
        """,
    )
    if orphan_links:
        issues.append({"severity": "high", "issue_type": "orphan_evidence_link", "count": orphan_links})
    fabricated_probability = scalar(
        conn,
        """
        SELECT COUNT(*) FROM occurrence_songs
        WHERE origin = 'observed_youtube_setlist' AND probability IS NOT NULL
        """,
    )
    if fabricated_probability:
        issues.append(
            {
                "severity": "high",
                "issue_type": "fabricated_probability_value",
                "count": fabricated_probability,
            }
        )
    return issues


def audit_db(db_path, out_json=None, out_md=None):
    args = SimpleNamespace(
        db=str(db_path),
        notion_db=str(audit_master_rdb.NOTION_DB),
        song_occurrences=str(audit_master_rdb.SONG_OCCURRENCES),
        manifest=str(audit_master_rdb.MASTER_MANIFEST),
        out_json=str(out_json or OUT_JSON.with_suffix(".audit.json")),
        out_md=str(out_md or OUT_MD.with_suffix(".audit.md")),
    )
    return audit_master_rdb.audit(args)


def issue_summary(issues):
    return dict(Counter(row.get("severity") for row in issues))


def render_markdown(result):
    summary = result["summary"]
    lines = [
        "# YouTube setlist occurrences RDB apply report",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- target_db: `{result['outputs']['target_db']}`",
        f"- backup_db: `{result['outputs']['backup_db']}`",
        f"- db_committed: {result['write_guard']['db_committed']}",
        f"- rolled_back: {result['write_guard']['rolled_back']}",
        f"- match_score_threshold: {MATCH_SCORE_THRESHOLD}",
        "",
        "## Summary",
        "",
    ]
    for key, value in summary.items():
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## Scope",
            "",
            "- probability: intentionally left NULL (RDB-native computation is a separate follow-up)",
            "- Notion write-back: skipped",
            "- public JSON write: skipped (not wired into export_public_events.py yet)",
            "",
        ]
    )
    if result["issues"]:
        lines.extend(["## Issues", ""])
        for issue in result["issues"]:
            lines.append(f"- {issue['severity']} {issue['issue_type']}: {issue}")
        lines.append("")
    return "\n".join(lines)


def run(args):
    validate_apply_request(args)
    now = now_utc()
    data = json.loads(Path(args.source).read_text(encoding="utf-8"))
    occurrences = data.get("occurrences") or []

    target_db = Path(args.master_db if args.apply else args.out_db)
    backup_path = ""
    if args.apply:
        preflight_db = DATA / "youtube_setlist_occurrences_apply_preflight.sqlite"
        copy_db(args.master_db, preflight_db)
        with connect_existing(preflight_db) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            preflight_results = apply_all(conn, occurrences, now)
            preflight_issues = consistency_checks(conn, preflight_results)
            conn.commit()
        preflight_audit = audit_db(preflight_db)
        if any(row.get("severity") == "high" for row in preflight_issues + preflight_audit["issues"]):
            raise ValueError(
                "preflight refused high severity issues: "
                f"checks={issue_summary(preflight_issues)} "
                f"audit={preflight_audit['issues_by_severity']}"
            )
        backup_path = str(backup_db(args.master_db, now))
    else:
        copy_db(args.master_db, args.out_db)

    committed = False
    rolled_back = False
    with connect_existing(target_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        results = apply_all(conn, occurrences, now)
        issues = consistency_checks(conn, results)
        has_high_issue = any(row.get("severity") == "high" for row in issues)
        if has_high_issue:
            conn.rollback()
            rolled_back = True
        else:
            conn.commit()
            committed = True
        counts = table_counts(conn)

    audit_result = audit_db(
        target_db,
        out_json=args.out_json.with_suffix(".audit.json"),
        out_md=args.out_md.with_suffix(".audit.md"),
    )
    if args.apply and audit_result["issues_by_severity"].get("high"):
        raise ValueError(f"post-apply audit has high issues: {audit_result['issues_by_severity']}")
    if args.apply and committed:
        refresh_manifest_database_state(args.master_db, updated_at=now)

    matched_results = [r for r in results if r["matched_occurrence_id"]]
    result = {
        "generated_by": SCRIPT_NAME,
        "generated_at": now,
        "mode": "apply" if args.apply else "dry_run",
        "sources": {"master_db": str(args.master_db), "source_json": str(args.source)},
        "outputs": {
            "target_db": str(target_db),
            "dry_run_db": "" if args.apply else str(args.out_db),
            "backup_db": backup_path,
            "json": str(args.out_json),
            "markdown": str(args.out_md),
        },
        "options": {"apply": bool(args.apply), "match_score_threshold": MATCH_SCORE_THRESHOLD},
        "write_guard": {
            "db_committed": committed,
            "rolled_back": rolled_back,
            "rollback_reason": "high_severity_issue" if rolled_back else "",
        },
        "summary": {
            "occurrences_processed": len(results),
            "occurrences_matched": len(matched_results),
            "occurrences_unmatched": len(results) - len(matched_results),
            "song_relations_written": sum(r["song_relation_count"] for r in results),
            "evidence_items_written": sum(r["evidence_count"] for r in results),
            "issues_by_severity": issue_summary(issues),
            "audit_issues_by_severity": audit_result["issues_by_severity"],
            "table_counts": counts,
        },
        "matched_sample": matched_results[:20],
        "issues": issues,
        "audit": {
            "issue_count": audit_result["issue_count"],
            "issues_by_severity": audit_result["issues_by_severity"],
            "issues_by_type": audit_result["issues_by_type"],
        },
    }
    write_json(args.out_json, result)
    Path(args.out_md).write_text(render_markdown(result), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master-db", type=Path, default=MASTER_DB)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--out-db", type=Path, default=OUT_DB)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        result = run(args)
    except ValueError as exc:
        parser.error(str(exc))
    print(
        "youtube setlist occurrences rdb apply: "
        f"mode={result['mode']} "
        f"committed={result['write_guard']['db_committed']} "
        f"matched={result['summary']['occurrences_matched']}/{result['summary']['occurrences_processed']} "
        f"song_relations={result['summary']['song_relations_written']} "
        f"issues={result['summary']['issues_by_severity']} "
        f"audit={result['summary']['audit_issues_by_severity']}"
    )
    return 1 if result["summary"]["issues_by_severity"].get("high") else 0


if __name__ == "__main__":
    raise SystemExit(main())
