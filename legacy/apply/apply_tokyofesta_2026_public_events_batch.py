"""Promote reviewed TokyoFesta 2026 bon-odori candidates to the master RDB.

This batch only uses current-year TokyoFesta pages that include concrete date,
venue, and organizer/context details. TokyoFesta is kept as the source URL so
the public export can show that the evidence is a third-party current-year
listing, not an organizer confirmation.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

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
REPORT_JSON = DATA / "tokyofesta_2026_public_events_batch_apply_report.json"
REPORT_MD = DATA / "tokyofesta_2026_public_events_batch_apply_report.md"
REPORT_TITLE = "TokyoFesta 2026 public events batch apply report"


EVENTS: list[dict[str, Any]] = [
    {
        "event_name": "新宿二丁目太宗寺盆踊り大会",
        "series_name": "新宿二丁目太宗寺盆踊り大会",
        "venue": {
            "canonical_name": "太宗寺",
            "area": "新宿区",
            "address": "東京都新宿区新宿2-9-2",
            "access": "東京メトロ丸ノ内線 新宿御苑前駅から徒歩約2分",
            "scale": "小",
            "public_intro": "新宿二丁目の太宗寺で開かれる、町会主催の盆踊り大会。",
            "past_memo": "2026年は7月13日〜15日、18:30〜21:00開催情報あり。2025年セットリスト掲載あり。",
            "source_url": "https://tokyofesta.com/23ku/31675/",
        },
        "venue_aliases": ["新宿・太宗寺", "太宗寺（新宿区2-9-2）"],
        "area": "新宿区",
        "date_start": "2026-07-13",
        "date_end": "2026-07-15",
        "source_url": "https://tokyofesta.com/23ku/31675/",
        "public_intro": "新宿二丁目の太宗寺で開かれる、町会主催の盆踊り大会。",
        "detail": "2026年イベント掲載で、2026年7月13日(月)〜15日(水) 18:30〜21:00、会場: 太宗寺（新宿区2-9-2）、主催: 新宿二丁目町会を確認。関連URL: https://www.futami23.jp/archives/25976",
    },
    {
        "event_name": "柳ばし納涼盆おどり",
        "series_name": "柳ばし納涼盆おどり",
        "venue": {
            "canonical_name": "柳橋中央通り",
            "area": "台東区",
            "address": "東京都台東区柳橋2丁目付近",
            "access": "都営浅草線 浅草橋駅から徒歩圏内",
            "scale": "小",
            "public_intro": "柳橋中央通りで開かれる、浅草見附会主催の納涼盆おどり。",
            "past_memo": "2026年は7月18日開催情報あり。",
            "source_url": "https://tokyofesta.com/23ku/31748/",
        },
        "venue_aliases": ["江戸通り柳橋2丁目交差点付近"],
        "area": "台東区",
        "date_start": "2026-07-18",
        "date_end": "2026-07-18",
        "source_url": "https://tokyofesta.com/23ku/31748/",
        "public_intro": "柳橋中央通りで開かれる、浅草見附会主催の納涼盆おどり。",
        "detail": "2026年イベント掲載で、開催日: 2026年7月18日(土)、開会式17:45〜、開会18:00〜、会場: 柳橋中央通り（江戸通り柳橋2丁目交差点付近）、主催: 浅草見附会を確認。関連URL: https://asakusabashi.tokyo/event/event2026_001/",
    },
    {
        "event_name": "大和町八幡神社大盆踊り会",
        "series_name": "大和町八幡神社大盆踊り会",
        "venue": {
            "canonical_name": "中野大和町八幡神社",
            "area": "中野区",
            "address": "東京都中野区大和町2丁目付近",
            "access": "JR高円寺駅から徒歩約13分、西武新宿線 野方駅から徒歩約16分",
            "scale": "小",
            "public_intro": "中野大和町八幡神社で開かれる、地域の大盆踊り会。",
            "past_memo": "2026年は7月18日15:00〜20:30開催、雨天翌日情報あり。",
            "source_url": "https://tokyofesta.com/23ku/30956/",
        },
        "venue_aliases": ["大和町八幡神社", "中野区 大和町八幡神社"],
        "area": "中野区",
        "date_start": "2026-07-18",
        "date_end": "2026-07-18",
        "source_url": "https://tokyofesta.com/23ku/30956/",
        "public_intro": "中野大和町八幡神社で開かれる、地域の大盆踊り会。",
        "detail": "2026年イベント掲載で、2026年7月18日(土)15:00〜20:30、会場: 中野大和町八幡神社、雨天翌日を確認。",
    },
    {
        "event_name": "第51回 浄土寺盆踊り大会",
        "series_id": "ser_89245fcd08d4a60b",
        "series_name": "浄土寺盆踊り大会",
        "venue_id": "ven_b0c985dbb1fc06fe",
        "venue_aliases": ["赤坂浄土寺"],
        "area": "港区",
        "date_start": "2026-07-23",
        "date_end": "2026-07-24",
        "source_url": "https://tokyofesta.com/23ku/31687/",
        "public_intro": "赤坂の浄土寺で開かれる、寺院主催の盆踊り大会。",
        "detail": "2026年イベント掲載で、2026年7月23日(木)〜24日(金) 18:30〜、会場: 浄土寺（港区赤坂4-3-5）、主催: 浄土寺、赤坂駅より徒歩3分を確認。関連URL: https://x.com/nsPFhl5JW382058",
    },
    {
        "event_name": "新小岩納涼盆踊り大会",
        "series_name": "新小岩納涼盆踊り大会",
        "venue": {
            "canonical_name": "葛飾区立小松南小学校",
            "area": "葛飾区",
            "address": "東京都葛飾区新小岩2丁目付近",
            "access": "JR新小岩駅から徒歩約7分",
            "scale": "中",
            "public_intro": "小松南小学校校庭で開かれる、新小岩栄通り会主催の納涼盆踊り大会。",
            "past_memo": "2026年は7月25日〜26日、盆踊り18:00〜20:30開催情報あり。",
            "source_url": "https://tokyofesta.com/23ku/31502/",
        },
        "venue_aliases": ["葛飾区立小松南小学校 校庭"],
        "area": "葛飾区",
        "date_start": "2026-07-25",
        "date_end": "2026-07-26",
        "source_url": "https://tokyofesta.com/23ku/31502/",
        "public_intro": "小松南小学校校庭で開かれる、新小岩栄通り会主催の納涼盆踊り大会。",
        "detail": "2026年イベント掲載で、2026年7月25日(土)〜26日(日)16:00〜20:30、盆踊り18:00〜20:30、会場: 葛飾区立小松南小学校 校庭、主催: 新小岩栄通り会を確認。関連URL: https://e-shinkoiwa.com/event/event-99",
    },
    {
        "event_name": "下北沢盆踊り",
        "series_id": "ser_3cd68d5b41d0b1ff",
        "series_name": "下北沢盆踊り",
        "venue_id": "ven_c4237862262b2ee1",
        "venue_aliases": ["下北沢東口駅前広場", "下北沢駅東口広場"],
        "area": "世田谷区",
        "date_start": "2026-07-25",
        "date_end": "2026-07-26",
        "source_url": "https://tokyofesta.com/23ku/31306/",
        "public_intro": "下北沢駅東口広場で開かれる、商店街主催の盆踊り。",
        "detail": "2026年イベント掲載で、2026年7月25日(土)〜26日(日)13:00〜20:00、盆踊り16:00〜20:00、会場: 下北沢東口駅前広場、主催: しもきた商店街振興組合・下北沢東会・下北沢南口商店街振興組合を確認。関連URL: https://shimokitazawa-east.com/archives/8501",
    },
    {
        "event_name": "第71回 恵比寿駅前盆踊り大会",
        "series_id": "ser_854b5ca4993265fa",
        "series_name": "恵比寿駅前盆踊り大会",
        "venue_id": "ven_ce357f30c5fa6ef0",
        "venue_aliases": ["JR恵比寿駅西口広場（アトレ前）"],
        "area": "渋谷区",
        "date_start": "2026-07-31",
        "date_end": "2026-08-01",
        "source_url": "https://tokyofesta.com/23ku/31035/",
        "public_intro": "JR恵比寿駅西口広場で開かれる、駅前の大規模な盆踊り大会。",
        "detail": "2026年イベント掲載で、2026年7月31日(金)・8月1日(土)17:30〜21:30、会場: JR恵比寿駅西口広場（アトレ前）、主催: 全恵比寿納涼盆踊り大会実行委員会・恵比寿地区町会連合会・渋谷区商連恵比寿ブロックを確認。",
    },
    {
        "event_name": "第7回 渋谷盆踊り",
        "series_id": "ser_3873b1682d366b8f",
        "series_name": "渋谷盆踊り",
        "venue": {
            "canonical_name": "渋谷109前",
            "area": "渋谷区",
            "address": "東京都渋谷区道玄坂2丁目付近",
            "access": "JR・東京メトロ・東急・京王 渋谷駅から徒歩圏内",
            "scale": "大",
            "public_intro": "SHIBUYA109前や道玄坂・文化村通り周辺で開かれる、渋谷中心部の盆踊り。",
            "past_memo": "2026年は8月8日18:00〜21:30開催、交通規制16:30〜22:30情報あり。",
            "source_url": "https://tokyofesta.com/23ku/31513/",
        },
        "venue_aliases": ["SHIBUYA109前", "渋谷109イベントスペースおよび道玄坂、文化村通り"],
        "area": "渋谷区",
        "date_start": "2026-08-08",
        "date_end": "2026-08-08",
        "source_url": "https://tokyofesta.com/23ku/31513/",
        "public_intro": "SHIBUYA109前や道玄坂・文化村通り周辺で開かれる、渋谷中心部の盆踊り。",
        "detail": "2026年イベント掲載で、2026年8月8日(土)18:00〜21:30、会場: 渋谷109イベントスペースおよび道玄坂・文化村通り、主催: 渋谷道玄坂商店街振興組合を確認。関連URL: https://shibuyadogenzaka.com/?p=9030",
    },
    {
        "event_name": "東京ソラマチ夏まつり・墨田区民納涼民踊大会",
        "series_name": "東京ソラマチ夏まつり・墨田区民納涼民踊大会",
        "venue": {
            "canonical_name": "東京スカイツリータウン ソラマチひろば",
            "area": "墨田区",
            "address": "東京都墨田区押上1丁目1-2",
            "access": "とうきょうスカイツリー駅・押上駅から徒歩圏内",
            "scale": "大",
            "public_intro": "東京スカイツリータウンのソラマチひろばで開かれる、墨田区民納涼民踊大会。",
            "past_memo": "2026年は8月1日〜3日開催情報あり。候補タイトルには8月4日表記もあるため、本文の民踊大会日程を優先。",
            "source_url": "https://tokyofesta.com/23ku/31239/",
        },
        "venue_aliases": ["東京ソラマチ", "東京スカイツリータウン1階 ソラマチひろば"],
        "area": "墨田区",
        "date_start": "2026-08-01",
        "date_end": "2026-08-03",
        "source_url": "https://tokyofesta.com/23ku/31239/",
        "public_intro": "東京スカイツリータウンのソラマチひろばで開かれる、墨田区民納涼民踊大会。",
        "detail": "2026年イベント掲載で、墨田区民納涼民踊大会は2026年8月1日(土)〜3日(月)、会場: 東京スカイツリータウン1階 ソラマチひろば、主催: 墨田区、参加無料を確認。タイトルには8月4日表記もあるが、本文の民踊大会日程を採用。",
    },
    {
        "event_name": "東本願寺盆踊り",
        "series_id": "ser_056dc17d1e61d432",
        "series_name": "東本願寺盆踊り",
        "venue_id": "ven_d3a554a82cacf6d9",
        "venue_aliases": ["東本願寺境内"],
        "area": "台東区",
        "date_start": "2026-08-19",
        "date_end": "2026-08-20",
        "source_url": "https://tokyofesta.com/23ku/28588/",
        "public_intro": "浅草の東本願寺境内で開かれる盆踊り。",
        "detail": "2026年イベント掲載で、2026年8月19日(水)〜20日(木)、会場: 東本願寺境内（東京都台東区西浅草1-5-5）、東京メトロ銀座線 田原町駅から徒歩約5分を確認。",
    },
    {
        "event_name": "雷門盆踊り",
        "series_id": "ser_57b12dce4d688793",
        "series_name": "雷門盆踊り",
        "venue": {
            "canonical_name": "浅草雷門前 並木通り",
            "area": "台東区",
            "address": "東京都台東区雷門2丁目付近",
            "access": "東京メトロ銀座線・都営浅草線 浅草駅から徒歩圏内",
            "scale": "中",
            "public_intro": "浅草雷門前の並木通り界隈で開かれる盆踊り。",
            "past_memo": "2026年は9月5日17:30〜20:00開催情報あり。2023年動画実績、公式サイトリンクあり。",
            "source_url": "https://tokyofesta.com/23ku/31702/",
        },
        "venue_aliases": ["浅草雷門前並木通り", "並木通り界隈（浅草雷門前）"],
        "area": "台東区",
        "date_start": "2026-09-05",
        "date_end": "2026-09-05",
        "source_url": "https://tokyofesta.com/23ku/31702/",
        "public_intro": "浅草雷門前の並木通り界隈で開かれる盆踊り。",
        "detail": "2026年イベント掲載で、2026年9月5日(土)17:30〜20:00、会場: 並木通り界隈（浅草雷門前）、主催: 雷門東部商店会・雷門一之宮商店会を確認。関連URL: https://www.kaminari-bonodori.com/ / https://x.com/kaminarimonbon",
    },
]


def rows(conn, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    conn.row_factory = None
    cur = conn.execute(query, params)
    columns = [col[0] for col in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def backup_db(now: str) -> Path:
    stamp = now.replace("-", "").replace(":", "").replace("+00:00", "Z")
    backup = BACKUP_DIR / f"{MASTER_DB.stem}.{stamp}{MASTER_DB.suffix}.bak"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(MASTER_DB, backup)
    return backup


def ensure_venue(conn, item: dict[str, Any], now: str) -> tuple[str, bool]:
    if item.get("venue_id"):
        venue_id = item["venue_id"]
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
                ) VALUES (?, 'curated', ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, 'active', ?, ?)
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
                    now,
                    now,
                ),
            )
            created = True
    aliases = [
        item.get("venue", {}).get("canonical_name"),
        *(item.get("venue_aliases") or []),
    ]
    for alias in [a for a in aliases if a]:
        conn.execute(
            """
            INSERT OR IGNORE INTO venue_aliases(
              venue_id, alias, normalized_alias, source, confidence
            ) VALUES (?, ?, ?, 'tokyofesta_2026_public_events_batch', 'manual')
            """,
            (venue_id, alias, normalize_text(alias)),
        )
    return venue_id, created


def ensure_series(conn, item: dict[str, Any], venue_id: str, now: str) -> tuple[str, bool]:
    if item.get("series_id"):
        series_id = item["series_id"]
        before = rows(conn, "SELECT series_id FROM event_series WHERE series_id = ?", (series_id,))
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
                item["source_url"],
                now,
                series_id,
            ),
        )
        return series_id, not bool(before)

    series_id = stable_id("ser", item["series_name"], venue_id, item["source_url"])
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
            item["source_url"],
            now,
            now,
        ),
    )
    return series_id, not bool(before)


def upsert_occurrence(conn, item: dict[str, Any], series_id: str, venue_id: str, now: str) -> tuple[str, str, str]:
    existing = rows(
        conn,
        """
        SELECT occurrence_id
        FROM event_occurrences
        WHERE series_id = ?
          AND event_year = 2026
          AND occurrence_sequence = 1
        """,
        (series_id,),
    )
    occurrence_id = existing[0]["occurrence_id"] if existing else stable_id("occ", series_id, 2026, item["event_name"])
    occurrence_date_id = stable_id("odate", occurrence_id, item["date_start"], item["date_end"], item["source_url"])
    action = "updated" if existing else "inserted"

    conn.execute(
        """
        INSERT INTO event_occurrences(
          occurrence_id, origin, series_id, event_year, occurrence_sequence,
          display_name, venue_id, date_start, date_end, date_status,
          lifecycle_status, confidence, source_kind, source_url,
          inherited_from_occurrence_id, public_intro_override, detail,
          created_at, updated_at
        ) VALUES (?, 'curated', ?, 2026, 1, ?, ?, ?, ?, 'confirmed', 'published',
                  'high', 'third_party_current_year', ?, NULL, ?, ?, ?, ?)
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
        ) VALUES (?, ?, ?, ?, 'confirmed', 'high', NULL, 'third_party_current_year', ?)
        """,
        (occurrence_date_id, occurrence_id, item["date_start"], item["date_end"], now),
    )
    return occurrence_id, occurrence_date_id, action


def main() -> None:
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
                        "source_kind": "third_party_current_year",
                        "source_url": item["source_url"],
                    }
                )
            fk_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
            if fk_rows:
                issues.append({"issue_type": "foreign_key_check_failed", "rows": [tuple(row) for row in fk_rows[:20]]})

    refresh_manifest_database_state()
    report = {"generated_at": now, "backup": str(backup), "applied": applied, "issues": issues}
    REPORT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        f"# {REPORT_TITLE}",
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
