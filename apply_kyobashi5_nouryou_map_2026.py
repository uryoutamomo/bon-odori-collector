#!/usr/bin/env python3
"""Apply the 2026 Kyobashi-5 official flyer (納涼マップ) to the master RDB.

Source: LINE-shared flyer image from 京橋五の部連合町会・京橋五の部地区委員会
(reviewed by Uchida-san, transcribed by koto). Updates three existing
occurrences (date/venue confirmation) and registers one new event
(明石町会 納涼盆踊り). 湊三丁目町会/湊二丁目町会 and the 2027 入船一・二丁目町会
event are intentionally out of scope (see docs/firsthand-field-report-operations.md
sibling runbook conventions; this is an official-source one-off, not a
firsthand report).

Default mode writes only to a copied SQLite DB. Production writes require
--apply and the confirmation phrase.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from firsthand_report_helpers import ensure_venue
from master_db import (
    MASTER_DB,
    connect_existing,
    json_text,
    normalize_text,
    refresh_manifest_database_state,
    stable_id,
    table_counts,
)
from rdb_apply_support import audit_db, backup_db, copy_db, has_high_issue, issue_summary, rows, scalar, write_json


DATA = Path("data")
OUT_DB = DATA / "kyobashi5_nouryou_map_2026_apply_dry_run.sqlite"
OUT_JSON = DATA / "kyobashi5_nouryou_map_2026_apply_report.json"
OUT_MD = DATA / "kyobashi5_nouryou_map_2026_apply_report.md"
BACKUP_DIR = DATA / "backups"
PREFLIGHT_DB = DATA / "kyobashi5_nouryou_map_2026_apply_preflight.sqlite"
CONFIRM_PHRASE = "APPLY KYOBASHI5 NOURYOU MAP 2026"

FLYER_TITLE = "令和8年 納涼マップ 京橋五の部"
FLYER_ACCOUNT = "京橋五の部連合町会・京橋五の部地区委員会"
FLYER_TEXT = (
    "令和8年 納涼マップ（京橋五の部連合町会・京橋五の部地区委員会）。内田さんがLINEで受け取った"
    "公式配布チラシ画像をことが書き起こし。屋台の飲食物は有料、内容は当日変更となる場合あり、との注記あり。\n"
    "1 新富町会「新富銀座納涼盆踊り大会」7月17日(金)・18日(土)19:00-21:00 京橋公園。"
    "屋台やきそば・わたあめ・ポップコーン・かき氷等、飲み物ソフトドリンク・生ビール、イベントゲームコーナー。\n"
    "2 湊一・二、入船一・二丁目町会「鉄砲洲納涼盆踊り」8月3日(月)・4日(火)・5日(水)18:45-21:00 鉄砲洲公園。"
    "5日(水)中止の場合は6日(木)に順延。屋台軽食類、飲み物ビール・サワー・ソフトドリンク。\n"
    "3 明石町会「納涼盆踊り」8月6日(木)・7日(金)18:00-21:00 明石小学校。"
    "屋台軽食類、飲み物生ビール・ジュース等、イベント子ども盆踊り大会(お菓子付)。\n"
    "5 入船三丁目町会「納涼盆踊り」8月24日(月)・25日(火)18:30-21:00 入船三丁目交差点。"
    "屋台やきそば・かき氷等、飲み物ビール・ラムネ等(さらに地域の飲食店からのメニューを提供)。"
)
FLYER_EVIDENCE_ID = stable_id("ev", "kyobashi5_nouryou_map_2026", FLYER_ACCOUNT)

NOW_PLACEHOLDER = None  # set at runtime


def apply_change(conn, now):
    """Returns (applied: dict, issues: list)."""
    issues = []
    applied = {"resolved": True, "updated": [], "created": []}

    # --- evidence (shared across all four occurrences) ---
    conn.execute(
        """
        INSERT INTO evidence_items (
          evidence_id, platform, evidence_type, source_key, source_id, account_key,
          title, text_excerpt, url, published_at, observed_at, detected_event_date,
          raw_status, raw_json
        ) VALUES (?, 'web', 'poster_post', ?, NULL, ?, ?, ?, NULL, ?, ?, NULL, 'reviewed', ?)
        ON CONFLICT(evidence_id) DO UPDATE SET
          text_excerpt=excluded.text_excerpt,
          observed_at=excluded.observed_at
        """,
        (
            FLYER_EVIDENCE_ID,
            normalize_text(FLYER_ACCOUNT),
            FLYER_ACCOUNT,
            FLYER_TITLE,
            FLYER_TEXT,
            now,
            now,
            json_text({"source": "line_shared_flyer_image", "transcribed_by": "koto"}),
        ),
    )

    def link_evidence(occurrence_id, notes):
        conn.execute(
            """
            INSERT INTO occurrence_evidence_links (
              occurrence_id, evidence_id, target, link_status, confidence, notes
            ) VALUES (?, ?, 'date_venue_program', 'accepted', 0.95, ?)
            ON CONFLICT(occurrence_id, evidence_id, target) DO UPDATE SET
              confidence=excluded.confidence,
              notes=excluded.notes
            """,
            (occurrence_id, FLYER_EVIDENCE_ID, notes),
        )

    # --- 1) 新富町会: update existing occ_225f239652267ed9 ---
    shintomi_id = "occ_225f239652267ed9"
    existing = rows(conn, "SELECT occurrence_id FROM event_occurrences WHERE occurrence_id = ?", (shintomi_id,))
    if not existing:
        issues.append({"severity": "high", "issue_type": "expected_occurrence_missing", "occurrence_id": shintomi_id})
    else:
        shintomi_venue = ensure_venue(conn, "京橋公園", area="中央区", now=now)
        if shintomi_venue["status"] == "ambiguous":
            issues.append({"severity": "high", "issue_type": "ambiguous_venue", "occurrence": shintomi_id, "candidates": shintomi_venue["candidates"]})
        else:
            conn.execute(
                """
                UPDATE event_occurrences
                SET venue_id = ?, date_start = '2026-07-17', date_end = '2026-07-18',
                    date_status = 'confirmed', lifecycle_status = 'published', confidence = 'high',
                    source_kind = 'official_current_year',
                    detail = ?, updated_at = ?
                WHERE occurrence_id = ?
                """,
                (
                    shintomi_venue["venue_id"],
                    "新富町会「新富銀座納涼盆踊り大会」。19:00-21:00。屋台やきそば・わたあめ・ポップコーン・かき氷等、"
                    "飲み物ソフトドリンク・生ビール、イベントゲームコーナー。（令和8年納涼マップ京橋五の部より）",
                    now,
                    shintomi_id,
                ),
            )
            date_id = stable_id("date", shintomi_id, "2026-07-17", "2026-07-18")
            conn.execute(
                """
                INSERT INTO occurrence_dates (
                  occurrence_date_id, occurrence_id, date_start, date_end, date_type,
                  confidence, basis, created_at
                ) VALUES (?, ?, '2026-07-17', '2026-07-18', 'confirmed', 'high', ?, ?)
                ON CONFLICT(occurrence_date_id) DO UPDATE SET date_start=excluded.date_start, date_end=excluded.date_end
                """,
                (date_id, shintomi_id, "令和8年納涼マップ京橋五の部で確認。", now),
            )
            link_evidence(shintomi_id, "新富町会の日程・会場・屋台情報の根拠。")
            applied["updated"].append({"occurrence_id": shintomi_id, "venue_id": shintomi_venue["venue_id"], "venue_status": shintomi_venue["status"]})

    # --- 2) 鉄砲洲納涼盆踊り: already confirmed, add detail note + evidence link only ---
    teppouzu_id = "occ_69eb62d9b1773ad9"
    existing = rows(conn, "SELECT occurrence_id, detail FROM event_occurrences WHERE occurrence_id = ?", (teppouzu_id,))
    if not existing:
        issues.append({"severity": "high", "issue_type": "expected_occurrence_missing", "occurrence_id": teppouzu_id})
    else:
        prior_detail = existing[0]["detail"] or ""
        addendum = "5日(水)が中止の場合は6日(木)に順延。（令和8年納涼マップ京橋五の部より）"
        if addendum not in prior_detail:
            new_detail = (prior_detail + "\n" + addendum).strip()
            conn.execute(
                "UPDATE event_occurrences SET detail = ?, updated_at = ? WHERE occurrence_id = ?",
                (new_detail, now, teppouzu_id),
            )
        link_evidence(teppouzu_id, "日程・会場は既存確認済み。順延条件の追加根拠。")
        applied["updated"].append({"occurrence_id": teppouzu_id, "venue_id": None, "venue_status": "unchanged"})

    # --- 3) 明石町会: new venue + new series/occurrence ---
    akashi_venue = ensure_venue(conn, "明石小学校", area="中央区", now=now)
    if akashi_venue["status"] == "ambiguous":
        issues.append({"severity": "high", "issue_type": "ambiguous_venue", "occurrence": "明石町会", "candidates": akashi_venue["candidates"]})
    else:
        akashi_series_key = normalize_text("明石町会納涼盆踊り")
        existing_series = rows(conn, "SELECT series_id FROM event_series WHERE series_key = ?", (akashi_series_key,))
        if existing_series:
            akashi_series_id = existing_series[0]["series_id"]
        else:
            akashi_series_id = stable_id("series", akashi_series_key)
            conn.execute(
                """
                INSERT INTO event_series (
                  series_id, origin, series_key, canonical_name, normalized_name,
                  usual_venue_id, area, program_type, annual_months_json,
                  status, created_at, updated_at
                ) VALUES (?, 'curated', ?, ?, ?, ?, '中央区', 'bon_odori', '[8]', 'active', ?, ?)
                ON CONFLICT(series_id) DO NOTHING
                """,
                (akashi_series_id, akashi_series_key, "明石町会 納涼盆踊り", akashi_series_key, akashi_venue["venue_id"], now, now),
            )
        existing_occ = rows(
            conn,
            "SELECT occurrence_id FROM event_occurrences WHERE series_id = ? AND event_year = 2026",
            (akashi_series_id,),
        )
        akashi_occ_id = existing_occ[0]["occurrence_id"] if existing_occ else stable_id("occ", akashi_series_id, 2026, 1)
        conn.execute(
            """
            INSERT INTO event_occurrences (
              occurrence_id, origin, series_id, event_year, occurrence_sequence,
              display_name, venue_id, date_start, date_end, date_status,
              lifecycle_status, confidence, source_kind, source_url, detail,
              created_at, updated_at
            ) VALUES (?, 'curated', ?, 2026, 1, ?, ?, '2026-08-06', '2026-08-07', 'confirmed',
              'published', 'high', 'official_current_year', NULL, ?, ?, ?)
            ON CONFLICT(occurrence_id) DO UPDATE SET
              venue_id=excluded.venue_id, date_start=excluded.date_start, date_end=excluded.date_end,
              date_status='confirmed', detail=excluded.detail, updated_at=excluded.updated_at
            """,
            (
                akashi_occ_id,
                akashi_series_id,
                "明石町会 納涼盆踊り",
                akashi_venue["venue_id"],
                "18:00-21:00。屋台軽食類、飲み物生ビール・ジュース等、イベント子ども盆踊り大会(お菓子付)。"
                "（令和8年納涼マップ京橋五の部より）",
                now,
                now,
            ),
        )
        date_id = stable_id("date", akashi_occ_id, "2026-08-06", "2026-08-07")
        conn.execute(
            """
            INSERT INTO occurrence_dates (
              occurrence_date_id, occurrence_id, date_start, date_end, date_type,
              confidence, basis, created_at
            ) VALUES (?, ?, '2026-08-06', '2026-08-07', 'confirmed', 'high', ?, ?)
            ON CONFLICT(occurrence_date_id) DO UPDATE SET date_start=excluded.date_start, date_end=excluded.date_end
            """,
            (date_id, akashi_occ_id, "令和8年納涼マップ京橋五の部で確認。", now),
        )
        link_evidence(akashi_occ_id, "明石町会の新規登録・日程・会場・屋台情報の根拠。")
        applied["created"].append({"occurrence_id": akashi_occ_id, "venue_id": akashi_venue["venue_id"], "venue_status": akashi_venue["status"]})

    # --- 4) 入船三丁目町会: update existing occ_56e51b72ec7acc7e ---
    irifune3_id = "occ_56e51b72ec7acc7e"
    existing = rows(conn, "SELECT occurrence_id FROM event_occurrences WHERE occurrence_id = ?", (irifune3_id,))
    if not existing:
        issues.append({"severity": "high", "issue_type": "expected_occurrence_missing", "occurrence_id": irifune3_id})
    else:
        irifune3_venue = ensure_venue(conn, "入船三丁目交差点", area="中央区", now=now)
        if irifune3_venue["status"] == "ambiguous":
            issues.append({"severity": "high", "issue_type": "ambiguous_venue", "occurrence": irifune3_id, "candidates": irifune3_venue["candidates"]})
        else:
            conn.execute(
                """
                UPDATE event_occurrences
                SET venue_id = ?, date_start = '2026-08-24', date_end = '2026-08-25',
                    date_status = 'confirmed', lifecycle_status = 'published', confidence = 'high',
                    source_kind = 'official_current_year',
                    public_intro_override = ?,
                    detail = ?, updated_at = ?
                WHERE occurrence_id = ?
                """,
                (
                    irifune3_venue["venue_id"],
                    "入船三丁目町会の納涼盆踊り。2026年の開催日・会場が公式チラシで確認されました。",
                    "18:30-21:00。屋台やきそば・かき氷等、飲み物ビール・ラムネ等(さらに地域の飲食店からのメニューを提供)。"
                    "（令和8年納涼マップ京橋五の部より。2024年の過去実績曲目は引き続き参照可）",
                    now,
                    irifune3_id,
                ),
            )
            date_id = stable_id("date", irifune3_id, "2026-08-24", "2026-08-25")
            conn.execute(
                """
                INSERT INTO occurrence_dates (
                  occurrence_date_id, occurrence_id, date_start, date_end, date_type,
                  confidence, basis, created_at
                ) VALUES (?, ?, '2026-08-24', '2026-08-25', 'confirmed', 'high', ?, ?)
                ON CONFLICT(occurrence_date_id) DO UPDATE SET date_start=excluded.date_start, date_end=excluded.date_end
                """,
                (date_id, irifune3_id, "令和8年納涼マップ京橋五の部で確認。", now),
            )
            link_evidence(irifune3_id, "日程未確認→確定、会場未確認→確定の根拠。")
            applied["updated"].append({"occurrence_id": irifune3_id, "venue_id": irifune3_venue["venue_id"], "venue_status": irifune3_venue["status"]})

    return applied, issues


def consistency_checks(conn, applied):
    if not applied.get("resolved"):
        return []
    issues = []
    fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
    if fk_rows:
        issues.append({"severity": "high", "issue_type": "foreign_key_check_failed", "count": len(fk_rows), "sample": [tuple(r) for r in fk_rows[:10]]})
    for entry in applied["updated"] + applied["created"]:
        occ_id = entry["occurrence_id"]
        row = rows(conn, "SELECT date_start, date_end, date_status FROM event_occurrences WHERE occurrence_id = ?", (occ_id,))
        if not row:
            issues.append({"severity": "high", "issue_type": "occurrence_missing_after_apply", "occurrence_id": occ_id})
        elif row[0]["date_status"] != "confirmed":
            issues.append({"severity": "high", "issue_type": "date_status_not_confirmed", "occurrence_id": occ_id, "actual": row[0]["date_status"]})
    return issues


def render_markdown(result):
    applied = result["applied"]
    lines = [
        "# Kyobashi-5 official flyer (令和8年納涼マップ) apply result",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- db_committed: {result['write_guard']['db_committed']}",
        f"- rolled_back: {result['write_guard']['rolled_back']}",
        f"- issues_by_severity: {result['summary']['issues_by_severity']}",
        f"- audit_issues_by_severity: {result['summary']['audit_issues_by_severity']}",
        "",
        "## Updated (3)",
        "",
    ]
    for e in applied.get("updated", []):
        lines.append(f"- {e['occurrence_id']} venue={e.get('venue_id')} ({e.get('venue_status')})")
    lines += ["", "## Created (1)", ""]
    for e in applied.get("created", []):
        lines.append(f"- {e['occurrence_id']} venue={e.get('venue_id')} ({e.get('venue_status')})")
    lines += ["", "## Out of scope (not applied)", "", "- 湊三丁目町会 納涼子ども会（盆踊り判定保留）", "- 湊二丁目町会 湊二お楽しみ会（盆踊り判定保留）", "- 入船一・二丁目町会（2027年3月開催予定、時期・内容とも対象外）", ""]
    if result["issues"]:
        lines += ["## Issues", ""]
        for issue in result["issues"]:
            lines.append(f"- {issue['severity']} {issue['issue_type']}: {issue}")
        lines.append("")
    return "\n".join(lines)


def run(args):
    if args.apply and args.confirm != CONFIRM_PHRASE:
        raise ValueError(f"--apply requires --confirm '{CONFIRM_PHRASE}'")
    if args.apply and Path(args.out_db) == Path(args.master_db):
        raise ValueError("--out-db must not equal --master-db")

    now = datetime.now(timezone.utc).isoformat()
    target_db = Path(args.master_db if args.apply else args.out_db)
    backup_path = ""

    if args.apply:
        copy_db(args.master_db, PREFLIGHT_DB)
        with connect_existing(PREFLIGHT_DB) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            preflight_applied, preflight_change_issues = apply_change(conn, now)
            preflight_issues = preflight_change_issues + consistency_checks(conn, preflight_applied)
            conn.commit()
        preflight_audit = audit_db(PREFLIGHT_DB, PREFLIGHT_DB.with_suffix(".audit.json"), PREFLIGHT_DB.with_suffix(".audit.md"))
        if has_high_issue(preflight_issues, preflight_audit["issues"]):
            raise ValueError(
                f"preflight refused high severity issues: checks={issue_summary(preflight_issues)} audit={preflight_audit['issues_by_severity']}"
            )
        backup_path = str(backup_db(args.master_db, now, BACKUP_DIR))
    else:
        copy_db(args.master_db, args.out_db)

    committed = False
    rolled_back = False
    with connect_existing(target_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        applied, change_issues = apply_change(conn, now)
        issues = change_issues + consistency_checks(conn, applied)
        if has_high_issue(issues):
            conn.rollback()
            rolled_back = True
        else:
            conn.commit()
            committed = True
        counts = table_counts(conn)

    audit_result = audit_db(target_db, args.out_json.with_suffix(".audit.json"), args.out_md.with_suffix(".audit.md"))
    if args.apply and audit_result["issues_by_severity"].get("high"):
        raise ValueError(f"post-apply audit has high issues: {audit_result['issues_by_severity']}")
    if args.apply and committed:
        refresh_manifest_database_state(args.master_db, updated_at=now)

    result = {
        "generated_by": "apply_kyobashi5_nouryou_map_2026.py",
        "generated_at": now,
        "mode": "apply" if args.apply else "dry_run",
        "sources": {"master_db": str(args.master_db), "flyer_title": FLYER_TITLE},
        "outputs": {
            "target_db": str(target_db),
            "dry_run_db": "" if args.apply else str(args.out_db),
            "backup_db": backup_path,
            "json": str(args.out_json),
            "markdown": str(args.out_md),
        },
        "options": {"apply": bool(args.apply)},
        "write_guard": {
            "db_committed": committed,
            "rolled_back": rolled_back,
            "rollback_reason": "high_severity_issue" if rolled_back else "",
        },
        "summary": {
            "issues_count": len(issues),
            "issues_by_severity": issue_summary(issues),
            "audit_issues_by_severity": audit_result["issues_by_severity"],
            "table_counts": counts,
        },
        "applied": applied,
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
        "kyobashi5 nouryou map 2026 apply: "
        f"mode={result['mode']} committed={result['write_guard']['db_committed']} "
        f"issues={result['summary']['issues_by_severity']} audit={result['summary']['audit_issues_by_severity']} "
        f"target_db={result['outputs']['target_db']}"
    )
    return 1 if result["summary"]["issues_by_severity"].get("high") else 0


if __name__ == "__main__":
    raise SystemExit(main())
