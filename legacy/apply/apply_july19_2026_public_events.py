"""Add reviewed July 19, 2026 public event occurrences to the master RDB.

These are current-year event pages with enough public evidence to publish.
The source_kind distinguishes organizer/official evidence from third-party
event listings; neither path deploys the public site.
"""

import json
import shutil
from pathlib import Path

from master_rdb.master_db import (
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
REPORT_JSON = DATA / "july19_2026_public_events_apply_report.json"
REPORT_MD = DATA / "july19_2026_public_events_apply_report.md"


EVENTS = [
    {
        "event_name": "第26回 四谷納涼踊り大会",
        "series_id": "ser_7450bc9f827dfbb8",
        "series_name": "四谷納涼踊り大会",
        "venue_id": "ven_76e8c6960af5ceb8",
        "venue_updates": {
            "canonical_name": "四谷ひろばグランド（旧四谷第四小）",
            "area": "新宿区",
            "address": "東京都新宿区四谷4-20",
            "access": "東京メトロ丸ノ内線 四谷三丁目駅出口2より徒歩約7分",
            "scale": "小",
            "public_intro": "四谷ひろばグランド（旧四谷第四小）で開かれる、四谷地域の納涼踊り大会。",
            "past_memo": "2025年は7月19日〜20日、第25回 四谷納涼踊り大会として開催記録あり。2026年は7月18日〜19日開催情報あり。",
            "source_url": "https://tokyofesta.com/23ku/31451/",
        },
        "venue_aliases": ["四谷ひろばグラウンド（旧四谷第四小学校）", "四谷ひろばグランド", "旧四谷第四小"],
        "area": "新宿区",
        "date_start": "2026-07-18",
        "date_end": "2026-07-19",
        "source_kind": "third_party_current_year",
        "source_url": "https://tokyofesta.com/23ku/31451/",
        "series_source_url": "https://tokyofesta.com/23ku/31451/",
        "public_intro": "四谷ひろばグランド（旧四谷第四小）で開かれる、四谷地域の納涼踊り大会。",
        "detail": "\n".join(
            [
                "2026年イベント掲載で、開催日時: 2026年7月18日(土)〜19日(日)17:00〜21:00、納涼踊り18:00〜21:00、会場: 四谷ひろばグランド（旧四谷第四小）を確認。",
                "主催: 四谷三丁目商店街振興組合。小雨決行。両日中止の場合のみ7月20日(月祝)に順延。",
                "- 出典URL: https://tokyofesta.com/23ku/31451/",
                "- 関連URL: https://www4.hp-ez.com/hp/fes/page12",
            ]
        ),
        "confidence": "high",
        "reason": "current-year third-party event page has date, time, venue, organizer, and related organizer-page link",
    },
    {
        "event_name": "第46回 巣鴨盆踊り大会",
        "series_name": "巣鴨盆踊り大会",
        "venue": {
            "canonical_name": "巣鴨駅南口ロータリー",
            "area": "豊島区",
            "address": "東京都豊島区巣鴨1丁目16付近",
            "access": "JR山手線・都営三田線 巣鴨駅南口すぐ",
            "scale": "中",
            "public_intro": "巣鴨駅南口ロータリーで開かれる、駅前の盆踊り大会。",
            "past_memo": "2025年7月18日のYouTube実績で巣鴨駅南口ロータリーの盆踊り大会記録あり。2026年は7月17日〜19日開催情報あり。",
            "source_url": "http://suichishoutenkai.com/event/bonodori_2026",
            "latitude": 35.732629922570716,
            "longitude": 139.73731307579,
        },
        "venue_aliases": ["巣鴨南ロータリー", "巣鴨駅南口", "巣鴨駅南口広場"],
        "area": "豊島区",
        "date_start": "2026-07-17",
        "date_end": "2026-07-19",
        "source_kind": "official_current_year",
        "source_url": "http://suichishoutenkai.com/event/bonodori_2026",
        "series_source_url": "http://suichishoutenkai.com/event/bonodori_2026",
        "public_intro": "巣鴨駅南口ロータリーで開かれる、駅前の盆踊り大会。",
        "detail": "\n".join(
            [
                "巣鴨大鳥神社商店街の2026年ページで、2026年7月17日(金)・18日(土)・19日(日)に盆踊り大会を開催する旨を確認。",
                "東京フェスタ掲載で、開催時間18:00〜21:00、会場: 巣鴨駅南口ロータリー、19日雨天の場合は翌日に順延と確認。",
                "- 公式URL: http://suichishoutenkai.com/event/bonodori_2026",
                "- 出典URL: https://tokyofesta.com/23ku/31235/",
            ]
        ),
        "confidence": "confirmed",
        "reason": "organizer/current-year page confirms the three dates; third-party page supplies time, venue, and rain note",
    },
    {
        "event_name": "神楽坂夏まつり 盆踊り in 神楽坂",
        "series_name": "神楽坂夏まつり 盆踊り in 神楽坂",
        "venue_id": "ven_1dc2306906cc0b89",
        "venue_updates": {
            "canonical_name": "りそな銀行神楽坂支店前",
            "area": "新宿区",
            "address": "東京都新宿区神楽坂6丁目付近",
            "access": "東京メトロ東西線 神楽坂駅・飯田橋駅から徒歩圏内",
            "scale": "中",
            "public_intro": "神楽坂通りのりそな銀行神楽坂支店前で開かれる、神楽坂エリアの夏まつり盆踊り。",
            "past_memo": "2025年は第51回 神楽坂まつり 盆踊りとして、りそな銀行神楽坂支店前で7月23日〜24日に開催記録あり。2026年は神楽坂夏まつり 盆踊り in 神楽坂として7月19日〜20日開催情報あり。",
            "source_url": "https://tokyofesta.com/23ku/31347/",
        },
        "venue_aliases": ["神楽坂通り", "りそな銀行神楽坂支店前", "神楽坂まつり盆踊り会場"],
        "area": "新宿区",
        "date_start": "2026-07-19",
        "date_end": "2026-07-20",
        "source_kind": "third_party_current_year",
        "source_url": "https://tokyofesta.com/23ku/31347/",
        "series_source_url": "https://tokyofesta.com/23ku/31347/",
        "public_intro": "神楽坂通りのりそな銀行神楽坂支店前で開かれる、神楽坂エリアの夏まつり盆踊り。",
        "detail": "\n".join(
            [
                "2026年イベント掲載で、開催日時: 2026年7月19日(日)〜20日(月祝)17:30〜20:30、会場: りそな銀行神楽坂支店前を確認。",
                "主催: 神楽坂商店街振興組合。後援: 新宿区。小雨決行。",
                "- 出典URL: https://tokyofesta.com/23ku/31347/",
            ]
        ),
        "confidence": "high",
        "reason": "current-year third-party event page has date, time, venue, organizer, and rain note",
    },
]


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


def ensure_venue(conn, item, now):
    if item.get("venue_id"):
        venue_id = item["venue_id"]
        update = item.get("venue_updates") or {}
        if update:
            conn.execute(
                """
                UPDATE venues
                SET canonical_name = ?,
                    normalized_name = ?,
                    area = ?,
                    address = ?,
                    access = ?,
                    scale = ?,
                    public_intro = ?,
                    past_memo = ?,
                    source_url = ?,
                    review_status = 'active',
                    updated_at = ?
                WHERE venue_id = ?
                """,
                (
                    update["canonical_name"],
                    normalize_text(update["canonical_name"]),
                    update["area"],
                    update["address"],
                    update["access"],
                    update["scale"],
                    update["public_intro"],
                    update["past_memo"],
                    update["source_url"],
                    now,
                    venue_id,
                ),
            )
        created = False
    else:
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
        else:
            venue_id = stable_id("ven", venue["canonical_name"], venue.get("address") or "", venue.get("source_url") or "")
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
            created = True
    aliases = [item.get("venue", {}).get("canonical_name") or item.get("venue_updates", {}).get("canonical_name"), *(item.get("venue_aliases") or [])]
    for alias in [a for a in aliases if a]:
        conn.execute(
            """
            INSERT OR IGNORE INTO venue_aliases(
              venue_id, alias, normalized_alias, source, confidence
            ) VALUES (?, ?, ?, 'july19_2026_public_events', 'manual')
            """,
            (venue_id, alias, normalize_text(alias)),
        )
    return venue_id, created


def ensure_series(conn, item, venue_id, now):
    if item.get("series_id"):
        series_id = item["series_id"]
        conn.execute(
            """
            UPDATE event_series
            SET canonical_name = ?,
                normalized_name = ?,
                usual_venue_id = ?,
                area = ?,
                program_type = '盆踊り',
                annual_months_json = ?,
                public_intro = ?,
                source_url = ?,
                status = 'active',
                updated_at = ?
            WHERE series_id = ?
            """,
            (
                item["series_name"],
                normalize_text(item["series_name"]),
                venue_id,
                item["area"],
                json_text([int(item["date_start"][5:7])]),
                item["public_intro"],
                item["series_source_url"],
                now,
                series_id,
            ),
        )
        created = False
    else:
        series_id = stable_id("ser", item["series_name"], venue_id, item["series_source_url"])
        existing = rows(conn, "SELECT series_id FROM event_series WHERE series_id = ?", (series_id,))
        created = not bool(existing)
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
    return series_id, created


def upsert_occurrence(conn, item, series_id, venue_id, now):
    occurrence_id = stable_id("occ", series_id, 2026, item["event_name"])
    occurrence_date_id = stable_id("odate", occurrence_id, item["date_start"], item["date_end"], item["source_url"])
    before = rows(conn, "SELECT * FROM event_occurrences WHERE occurrence_id = ?", (occurrence_id,))
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
          series_id = excluded.series_id,
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


def main():
    now = now_utc()
    backup = backup_db(now)
    applied = []
    issues = []
    with connect_existing() as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        with conn:
            for item in EVENTS:
                venue_id, venue_created = ensure_venue(conn, item, now)
                series_id, series_created = ensure_series(conn, item, venue_id, now)
                occurrence_id, occurrence_date_id, occurrence_action = upsert_occurrence(conn, item, series_id, venue_id, now)
                applied.append(
                    {
                        "event_name": item["event_name"],
                        "series_id": series_id,
                        "series_created": series_created,
                        "venue_id": venue_id,
                        "venue_created": venue_created,
                        "occurrence_id": occurrence_id,
                        "occurrence_action": occurrence_action,
                        "occurrence_date_id": occurrence_date_id,
                        "date_start": item["date_start"],
                        "date_end": item["date_end"],
                        "source_kind": item["source_kind"],
                        "source_url": item["source_url"],
                        "reason": item["reason"],
                    }
                )
            fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
            if fk_rows:
                issues.append({"issue_type": "foreign_key_check_failed", "rows": [tuple(row) for row in fk_rows[:20]]})
    refresh_manifest_database_state()
    report = {
        "generated_at": now,
        "backup": str(backup),
        "applied": applied,
        "issues": issues,
    }
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# July 19 2026 public events apply report",
        "",
        f"- generated_at: {now}",
        f"- backup: {backup}",
        f"- applied: {len(applied)}",
        f"- issues: {len(issues)}",
        "",
        "| event | date | action | source_kind | source_url |",
        "|---|---:|---|---|---|",
    ]
    for item in applied:
        date_text = item["date_start"] if item["date_start"] == item["date_end"] else f"{item['date_start']}〜{item['date_end']}"
        lines.append(
            f"| {item['event_name']} | {date_text} | {item['occurrence_action']} | {item['source_kind']} | {item['source_url']} |"
        )
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
