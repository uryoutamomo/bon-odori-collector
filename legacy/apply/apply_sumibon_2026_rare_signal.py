#!/usr/bin/env python3
"""Apply reviewed SUMIBON 2026 rare-signal registration candidate.

This is intentionally narrow: it applies only the official-confirmed
SUMIBON row staged from the rare-signal flow.
"""

import json
import shutil
from pathlib import Path

from master_db import (
    MASTER_DB,
    connect_existing,
    json_text,
    normalize_text,
    now_utc,
    refresh_manifest_database_state,
    stable_id,
)


DATA = Path("data")
BACKUP_DIR = DATA / "backups"
REGISTRATION_CANDIDATES = DATA / "rare_signal_registration_candidates.json"
REPORT_JSON = DATA / "sumibon_2026_rare_signal_apply_report.json"
REPORT_MD = DATA / "sumibon_2026_rare_signal_apply_report.md"


CONFIRMED_CANDIDATE_ID = "xoto_b9fe367e3a7316d6"

EVENT = {
    "candidate_id": CONFIRMED_CANDIDATE_ID,
    "event_name": "すみゆめ踊行列：SUMIBON",
    "series_name": "すみゆめ踊行列：SUMIBON",
    "venue": {
        "canonical_name": "隅田公園そよ風ひろば",
        "area": "墨田区",
        "address": "東京都墨田区向島1-3",
        "access": "とうきょうスカイツリー駅・本所吾妻橋駅・浅草駅から徒歩圏内",
        "scale": "大",
        "public_intro": "隅田公園そよ風ひろばで開かれる、すみゆめの生歌生演奏盆踊りフェスティバル。",
        "past_memo": "2026年公式ページで、雨天時は墨田区立両国中学校体育館を会場とする旨を確認。",
        "source_url": "https://sumiyume.jp/event-page/odori2026/",
        "latitude": 35.710982,
        "longitude": 139.803605,
    },
    "venue_aliases": ["隅田公園 そよ風ひろば", "そよ風ひろば", "Sumida Park Soyokaze Hiroba"],
    "area": "墨田区",
    "date_start": "2026-10-25",
    "date_end": "2026-10-25",
    "source_kind": "official_current_year",
    "source_url": "https://sumiyume.jp/event-page/odori2026/",
    "series_source_url": "https://sumiyume.jp/event-page/odori2026/",
    "public_intro": "隅田公園そよ風ひろばで2026年10月25日(日)14:00〜20:00に開かれる、すみゆめの生歌生演奏盆踊りフェスティバル。",
    "detail": "\n".join(
        [
            "公式ページで、2026年10月25日(日)14:00〜20:00に「すみゆめ踊行列：SUMIBON / Sumi-Yume Bon Dance Festival」を開催する旨を確認。",
            "会場は隅田公園そよ風ひろば（墨田区向島1-3）。雨天時は墨田区立両国中学校体育館（墨田区横網1-8-1）。",
            "なつたろさんのX告知でも、日時・会場・生歌生演奏の盆踊り企画であることを確認。",
            "- 公式URL: https://sumiyume.jp/event-page/odori2026/",
            "- X発見URL: https://x.com/natsutr_bon/status/2070359523823640931",
        ]
    ),
    "confidence": "confirmed",
    "reason": "rare-signal backcheckで公式ページを確認済み。日時・会場・イベント名が揃っているためMaster RDBへ登録する。",
}


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def rows(conn, query, params=()):
    conn.row_factory = None
    cur = conn.execute(query, params)
    columns = [col[0] for col in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def backup_db(now):
    stamp = now.replace("-", "").replace(":", "").replace("+00:00", "Z")
    backup = BACKUP_DIR / f"{MASTER_DB.stem}.{stamp}{MASTER_DB.suffix}.bak"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(MASTER_DB, backup)
    return backup


def validate_registration_candidate():
    payload = load_json(REGISTRATION_CANDIDATES, {"registration_candidates": []})
    matches = [
        row
        for row in payload.get("registration_candidates") or []
        if row.get("candidate_id") == CONFIRMED_CANDIDATE_ID
    ]
    if not matches:
        return [{"severity": "high", "issue_type": "missing_registration_candidate"}]
    row = matches[0]
    if not row.get("ready_for_registration"):
        return [{"severity": "high", "issue_type": "candidate_not_ready", "candidate": row}]
    if EVENT["source_url"] not in (row.get("confirmed_source_urls") or []):
        return [{"severity": "high", "issue_type": "official_source_not_confirmed", "candidate": row}]
    return []


def ensure_venue(conn, item, now):
    venue = item["venue"]
    existing = rows(
        conn,
        """
        SELECT venue_id
        FROM venues
        WHERE normalized_name = ?
          AND COALESCE(address, '') = ?
        """,
        (normalize_text(venue["canonical_name"]), venue.get("address") or ""),
    )
    if existing:
        venue_id = existing[0]["venue_id"]
        created = False
        conn.execute(
            """
            UPDATE venues
            SET area = ?,
                access = COALESCE(NULLIF(?, ''), access),
                scale = COALESCE(NULLIF(?, ''), scale),
                public_intro = COALESCE(NULLIF(?, ''), public_intro),
                past_memo = COALESCE(NULLIF(?, ''), past_memo),
                source_url = COALESCE(NULLIF(?, ''), source_url),
                latitude = COALESCE(?, latitude),
                longitude = COALESCE(?, longitude),
                review_status = 'active',
                updated_at = ?
            WHERE venue_id = ?
            """,
            (
                venue["area"],
                venue.get("access") or "",
                venue.get("scale") or "",
                venue.get("public_intro") or "",
                venue.get("past_memo") or "",
                venue.get("source_url") or "",
                venue.get("latitude"),
                venue.get("longitude"),
                now,
                venue_id,
            ),
        )
    else:
        venue_id = stable_id("ven", venue["canonical_name"], venue.get("address") or "", venue.get("source_url") or "")
        created = True
        conn.execute(
            """
            INSERT INTO venues(
              venue_id, origin, canonical_name, normalized_name, area, address,
              access, scale, public_intro, past_memo, source_url,
              latitude, longitude, review_status, created_at, updated_at
            ) VALUES (?, 'curated', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                venue_id,
                venue["canonical_name"],
                normalize_text(venue["canonical_name"]),
                venue["area"],
                venue.get("address") or "",
                venue.get("access") or "",
                venue.get("scale") or "",
                venue.get("public_intro") or "",
                venue.get("past_memo") or "",
                venue.get("source_url") or "",
                venue.get("latitude"),
                venue.get("longitude"),
                now,
                now,
            ),
        )

    for alias in [venue["canonical_name"], *(item.get("venue_aliases") or [])]:
        conn.execute(
            """
            INSERT OR IGNORE INTO venue_aliases(
              venue_id, alias, normalized_alias, source, confidence
            ) VALUES (?, ?, ?, 'sumibon_2026_rare_signal', 'manual')
            """,
            (venue_id, alias, normalize_text(alias)),
        )
    return venue_id, created


def ensure_series(conn, item, venue_id, now):
    series_id = stable_id("ser", item["series_name"], venue_id, item["series_source_url"])
    before = rows(conn, "SELECT series_id FROM event_series WHERE series_id = ?", (series_id,))
    conn.execute(
        """
        INSERT INTO event_series(
          series_id, origin, series_key, canonical_name, normalized_name,
          usual_venue_id, area, program_type, annual_months_json,
          schedule_rule_type, schedule_rule_detail, public_intro, source_url,
          status, created_at, updated_at
        ) VALUES (?, 'curated', ?, ?, ?, ?, ?, '盆踊り', ?, '', '', ?, ?, 'active', ?, ?)
        ON CONFLICT(series_id) DO UPDATE SET
          canonical_name = excluded.canonical_name,
          normalized_name = excluded.normalized_name,
          usual_venue_id = excluded.usual_venue_id,
          area = excluded.area,
          program_type = excluded.program_type,
          annual_months_json = excluded.annual_months_json,
          public_intro = excluded.public_intro,
          source_url = excluded.source_url,
          status = 'active',
          updated_at = excluded.updated_at
        """,
        (
            series_id,
            stable_id("serkey", item["series_name"], venue_id, length=12),
            item["series_name"],
            normalize_text(item["series_name"]),
            venue_id,
            item["area"],
            json_text([int(item["date_start"][5:7])]),
            item["public_intro"],
            item["series_source_url"],
            now,
            now,
        ),
    )
    return series_id, not bool(before)


def upsert_occurrence(conn, item, series_id, venue_id, now):
    occurrence_id = stable_id("occ", series_id, 2026, item["event_name"])
    occurrence_date_id = stable_id("odate", occurrence_id, item["date_start"], item["date_end"], item["source_url"])
    before = rows(conn, "SELECT occurrence_id FROM event_occurrences WHERE occurrence_id = ?", (occurrence_id,))
    conn.execute(
        """
        INSERT INTO event_occurrences(
          occurrence_id, origin, series_id, event_year, occurrence_sequence,
          display_name, venue_id, date_start, date_end, date_status,
          lifecycle_status, confidence, source_kind, source_url,
          inherited_from_occurrence_id, public_intro_override, detail,
          created_at, updated_at
        ) VALUES (?, 'curated', ?, 2026, 1, ?, ?, ?, ?, 'confirmed', 'published', ?, ?, ?, NULL, ?, ?, ?, ?)
        ON CONFLICT(occurrence_id) DO UPDATE SET
          display_name = excluded.display_name,
          venue_id = excluded.venue_id,
          date_start = excluded.date_start,
          date_end = excluded.date_end,
          date_status = excluded.date_status,
          lifecycle_status = excluded.lifecycle_status,
          confidence = excluded.confidence,
          source_kind = excluded.source_kind,
          source_url = excluded.source_url,
          public_intro_override = excluded.public_intro_override,
          detail = excluded.detail,
          updated_at = excluded.updated_at
        """,
        (
            occurrence_id,
            series_id,
            item["event_name"],
            venue_id,
            item["date_start"],
            item["date_end"],
            item["confidence"],
            item["source_kind"],
            item["source_url"],
            item["public_intro"],
            item["detail"],
            now,
            now,
        ),
    )
    conn.execute(
        """
        INSERT OR REPLACE INTO occurrence_dates(
          occurrence_date_id, occurrence_id, date_start, date_end, date_type,
          confidence, source_evidence_id, basis, created_at
        ) VALUES (?, ?, ?, ?, 'confirmed', ?, NULL, ?, ?)
        """,
        (
            occurrence_date_id,
            occurrence_id,
            item["date_start"],
            item["date_end"],
            item["confidence"],
            item["source_kind"],
            now,
        ),
    )
    return occurrence_id, occurrence_date_id, "updated" if before else "inserted"


def render_markdown(report):
    lines = [
        "# SUMIBON 2026 rare signal apply report",
        "",
        f"- generated_at: {report['generated_at']}",
        f"- backup: {report['backup']}",
        f"- applied: {len(report['applied'])}",
        f"- issues: {len(report['issues'])}",
        "",
        "| event | date | action | source |",
        "|---|---:|---|---|",
    ]
    for item in report["applied"]:
        lines.append(
            f"| {item['event_name']} | {item['date_start']} | {item['occurrence_action']} | {item['source_url']} |"
        )
    if report["issues"]:
        lines.extend(["", "## Issues", "", "```json", json.dumps(report["issues"], ensure_ascii=False, indent=2), "```"])
    return "\n".join(lines) + "\n"


def main():
    now = now_utc()
    backup = backup_db(now)
    issues = validate_registration_candidate()
    applied = []
    if not issues:
        with connect_existing() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            with conn:
                venue_id, venue_created = ensure_venue(conn, EVENT, now)
                series_id, series_created = ensure_series(conn, EVENT, venue_id, now)
                occurrence_id, occurrence_date_id, occurrence_action = upsert_occurrence(conn, EVENT, series_id, venue_id, now)
                fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
                if fk_rows:
                    issues.append({"severity": "high", "issue_type": "foreign_key_check_failed", "rows": [tuple(row) for row in fk_rows[:20]]})
                    raise RuntimeError("foreign_key_check_failed")
                applied.append(
                    {
                        "candidate_id": EVENT["candidate_id"],
                        "event_name": EVENT["event_name"],
                        "series_id": series_id,
                        "series_created": series_created,
                        "venue_id": venue_id,
                        "venue_created": venue_created,
                        "occurrence_id": occurrence_id,
                        "occurrence_action": occurrence_action,
                        "occurrence_date_id": occurrence_date_id,
                        "date_start": EVENT["date_start"],
                        "date_end": EVENT["date_end"],
                        "source_kind": EVENT["source_kind"],
                        "source_url": EVENT["source_url"],
                        "reason": EVENT["reason"],
                    }
                )
        refresh_manifest_database_state()

    report = {
        "generated_at": now,
        "generated_by": "apply_sumibon_2026_rare_signal.py",
        "backup": str(backup),
        "applied": applied,
        "issues": issues,
    }
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    REPORT_MD.write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if issues:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
