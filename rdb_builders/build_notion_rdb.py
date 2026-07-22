"""Build a local SQLite snapshot of the main Notion databases."""

import argparse
import json
import os
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import urllib.request

import notion_support.notion_config as notion_config
from notion_support.notion_config import load_local_env


load_local_env()

NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")
NOTION_API = notion_config.NOTION_API_BASE
DATA_SOURCE_VERSION = notion_config.NOTION_API_VERSION
DATABASE_VERSION = "2022-06-28"
OUT_DB = Path("data/notion_snapshot.sqlite")
OUT_SUMMARY = Path("data/notion_rdb_summary.json")


TARGETS = [
    {
        "source_key": "venues",
        "source_name": "会場マスタ",
        "api_kind": "data_source",
        "notion_id": notion_config.VENUE_DATA_SOURCE_ID,
        "title_property": "会場名",
    },
    {
        "source_key": "events",
        "source_name": "イベントDB",
        "api_kind": "data_source",
        "notion_id": notion_config.EVENT_DATA_SOURCE_ID,
        "title_property": "イベント名",
    },
    {
        "source_key": "plans",
        "source_name": "予定管理DB",
        "api_kind": "data_source",
        "notion_id": notion_config.PLAN_DATA_SOURCE_ID,
        "title_property": "名前",
    },
    {
        "source_key": "songs",
        "source_name": "曲マスタ",
        "api_kind": "database",
        "notion_id": notion_config.SONG_MASTER_DATABASE_ID,
        "title_property": "曲名",
    },
    {
        "source_key": "glossary_v2",
        "source_name": "用語集V2",
        "api_kind": "database",
        "notion_id": notion_config.GLOSSARY_V2_DATABASE_ID,
        "title_property": "使用語",
    },
]


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE notion_sources (
  source_key TEXT PRIMARY KEY,
  source_name TEXT NOT NULL,
  api_kind TEXT NOT NULL,
  notion_id TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  row_count INTEGER NOT NULL
);

CREATE TABLE notion_pages (
  page_id TEXT PRIMARY KEY,
  source_key TEXT NOT NULL,
  url TEXT,
  archived INTEGER NOT NULL DEFAULT 0,
  created_time TEXT,
  last_edited_time TEXT,
  title TEXT,
  properties_json TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  FOREIGN KEY (source_key) REFERENCES notion_sources(source_key)
);

CREATE TABLE notion_properties (
  page_id TEXT NOT NULL,
  property_name TEXT NOT NULL,
  property_type TEXT NOT NULL,
  plain_value TEXT,
  json_value TEXT NOT NULL,
  PRIMARY KEY (page_id, property_name),
  FOREIGN KEY (page_id) REFERENCES notion_pages(page_id)
);

CREATE TABLE notion_relations (
  page_id TEXT NOT NULL,
  property_name TEXT NOT NULL,
  related_page_id TEXT NOT NULL,
  PRIMARY KEY (page_id, property_name, related_page_id),
  FOREIGN KEY (page_id) REFERENCES notion_pages(page_id)
);

CREATE TABLE notion_events (
  page_id TEXT PRIMARY KEY,
  event_name TEXT,
  venue_ids_json TEXT NOT NULL DEFAULT '[]',
  start_date TEXT,
  end_date TEXT,
  status TEXT,
  annual_months TEXT,
  detail TEXT,
  public_intro TEXT,
  source_url TEXT,
  FOREIGN KEY (page_id) REFERENCES notion_pages(page_id)
);

CREATE TABLE notion_venues (
  page_id TEXT PRIMARY KEY,
  venue_name TEXT,
  area TEXT,
  address TEXT,
  access TEXT,
  scale TEXT,
  public_intro TEXT,
  past_memo TEXT,
  FOREIGN KEY (page_id) REFERENCES notion_pages(page_id)
);

CREATE TABLE notion_songs (
  page_id TEXT PRIMARY KEY,
  song_name TEXT,
  category TEXT,
  status TEXT,
  evidence_count REAL,
  source_url TEXT,
  memo TEXT,
  venue_ids_json TEXT NOT NULL DEFAULT '[]',
  FOREIGN KEY (page_id) REFERENCES notion_pages(page_id)
);

CREATE TABLE notion_plans (
  page_id TEXT PRIMARY KEY,
  plan_title TEXT,
  event_ids_json TEXT NOT NULL DEFAULT '[]',
  venue_ids_json TEXT NOT NULL DEFAULT '[]',
  start_date TEXT,
  end_date TEXT,
  status TEXT,
  memo TEXT,
  FOREIGN KEY (page_id) REFERENCES notion_pages(page_id)
);

CREATE TABLE notion_glossary_terms (
  page_id TEXT PRIMARY KEY,
  term TEXT,
  interpretation TEXT,
  kind TEXT,
  state TEXT,
  confidence TEXT,
  aliases TEXT,
  related_song_ids_json TEXT NOT NULL DEFAULT '[]',
  FOREIGN KEY (page_id) REFERENCES notion_pages(page_id)
);

CREATE INDEX idx_notion_pages_source ON notion_pages(source_key);
CREATE INDEX idx_notion_properties_name ON notion_properties(property_name);
CREATE INDEX idx_notion_relations_related ON notion_relations(related_page_id);
CREATE INDEX idx_notion_events_date ON notion_events(start_date);
CREATE INDEX idx_notion_venues_area ON notion_venues(area);
CREATE INDEX idx_notion_songs_name ON notion_songs(song_name);
CREATE INDEX idx_notion_plans_date ON notion_plans(start_date);
CREATE INDEX idx_notion_glossary_term ON notion_glossary_terms(term);
"""


def json_text(value):
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def notion_request(method, path, payload=None, version=DATA_SOURCE_VERSION):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{NOTION_API}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {NOTION_TOKEN}")
    req.add_header("Notion-Version", version)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def query_all(target):
    rows = []
    cursor = None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        if target["api_kind"] == "data_source":
            path = f"/data_sources/{target['notion_id']}/query"
            version = DATA_SOURCE_VERSION
        else:
            path = f"/databases/{target['notion_id']}/query"
            version = DATABASE_VERSION
        data = notion_request("POST", path, payload, version=version)
        rows.extend(data.get("results", []))
        if not data.get("has_more"):
            return rows
        cursor = data.get("next_cursor")


def rich_plain(items):
    return "".join(item.get("plain_text", "") for item in (items or [])).strip()


def prop_type(prop):
    return (prop or {}).get("type") or "unknown"


def prop_plain(prop):
    if not prop:
        return ""
    kind = prop_type(prop)
    if kind in ("title", "rich_text"):
        return rich_plain(prop.get(kind) or [])
    if kind == "select":
        return (prop.get("select") or {}).get("name", "")
    if kind == "status":
        return (prop.get("status") or {}).get("name", "")
    if kind == "multi_select":
        return ", ".join(item.get("name", "") for item in prop.get("multi_select", []))
    if kind == "date":
        date = prop.get("date") or {}
        start = date.get("start") or ""
        end = date.get("end") or ""
        return f"{start}..{end}" if end else start
    if kind == "url":
        return prop.get("url") or ""
    if kind == "number":
        value = prop.get("number")
        return "" if value is None else str(value)
    if kind == "checkbox":
        return "true" if prop.get("checkbox") else "false"
    if kind == "email":
        return prop.get("email") or ""
    if kind == "phone_number":
        return prop.get("phone_number") or ""
    if kind == "relation":
        return ", ".join(item.get("id", "") for item in prop.get("relation", []))
    if kind == "formula":
        formula = prop.get("formula") or {}
        return prop_plain({"type": formula.get("type"), formula.get("type", ""): formula.get(formula.get("type", ""))})
    if kind == "rollup":
        return json_text(prop.get("rollup") or {})
    return json_text(prop)


def prop_date(prop):
    if not prop or prop_type(prop) != "date":
        return "", ""
    date = prop.get("date") or {}
    return date.get("start") or "", date.get("end") or ""


def prop_number(prop):
    if not prop or prop_type(prop) != "number":
        return None
    return prop.get("number")


def relation_ids(prop):
    if not prop or prop_type(prop) != "relation":
        return []
    return [item.get("id") for item in prop.get("relation", []) if item.get("id")]


def first_prop(props, names):
    for name in names:
        if name in props:
            return props[name]
    return None


def plain_prop(props, names):
    return prop_plain(first_prop(props, names))


def title_for_page(page, title_property=""):
    props = page.get("properties") or {}
    if title_property and title_property in props:
        return prop_plain(props[title_property])
    for prop in props.values():
        if prop_type(prop) == "title":
            return prop_plain(prop)
    return ""


def build_rows(fetched):
    fetched_at = datetime.now(timezone.utc).isoformat()
    sources = []
    pages = []
    properties = []
    relations = []
    events = []
    venues = []
    songs = []
    plans = []
    glossary = []

    for target, rows in fetched:
        sources.append({
            "source_key": target["source_key"],
            "source_name": target["source_name"],
            "api_kind": target["api_kind"],
            "notion_id": target["notion_id"],
            "fetched_at": fetched_at,
            "row_count": len(rows),
        })
        for page in rows:
            page_id = page.get("id") or ""
            props = page.get("properties") or {}
            pages.append({
                "page_id": page_id,
                "source_key": target["source_key"],
                "url": page.get("url") or "",
                "archived": 1 if page.get("archived") else 0,
                "created_time": page.get("created_time") or "",
                "last_edited_time": page.get("last_edited_time") or "",
                "title": title_for_page(page, target.get("title_property") or ""),
                "properties_json": json_text(props),
                "raw_json": json_text(page),
            })
            for name, prop in props.items():
                properties.append({
                    "page_id": page_id,
                    "property_name": name,
                    "property_type": prop_type(prop),
                    "plain_value": prop_plain(prop),
                    "json_value": json_text(prop),
                })
                for related_id in relation_ids(prop):
                    relations.append({
                        "page_id": page_id,
                        "property_name": name,
                        "related_page_id": related_id,
                    })

            if target["source_key"] == "events":
                start, end = prop_date(first_prop(props, ["開催日", "日付", "Date"]))
                events.append({
                    "page_id": page_id,
                    "event_name": plain_prop(props, ["イベント名", "名前", "Name"]),
                    "venue_ids_json": json_text(relation_ids(first_prop(props, ["会場", "Venue"]))),
                    "start_date": start,
                    "end_date": end,
                    "status": plain_prop(props, ["状態", "ステータス", "Status"]),
                    "annual_months": plain_prop(props, ["例年開催月", "開催月"]),
                    "detail": plain_prop(props, ["開催パターン詳細", "詳細", "メモ"]),
                    "public_intro": plain_prop(props, ["公開紹介文", "紹介文"]),
                    "source_url": plain_prop(props, ["情報源URL", "URL", "公式URL"]),
                })
            elif target["source_key"] == "venues":
                venues.append({
                    "page_id": page_id,
                    "venue_name": plain_prop(props, ["会場名", "名前", "Name"]),
                    "area": plain_prop(props, ["所在区・市", "エリア", "区市町村"]),
                    "address": plain_prop(props, ["住所", "所在地"]),
                    "access": plain_prop(props, ["アクセス", "最寄り"]),
                    "scale": plain_prop(props, ["規模"]),
                    "public_intro": plain_prop(props, ["公開紹介文", "紹介文"]),
                    "past_memo": plain_prop(props, ["過去メモ", "メモ"]),
                })
            elif target["source_key"] == "songs":
                songs.append({
                    "page_id": page_id,
                    "song_name": plain_prop(props, ["曲名", "名前", "Name"]),
                    "category": plain_prop(props, ["分類", "種別"]),
                    "status": plain_prop(props, ["状態", "ステータス"]),
                    "evidence_count": prop_number(first_prop(props, ["証拠数", "evidence_count"])),
                    "source_url": plain_prop(props, ["出典・音源URL", "URL", "音源URL"]),
                    "memo": plain_prop(props, ["メモ", "説明"]),
                    "venue_ids_json": json_text(relation_ids(first_prop(props, ["会場", "Venue"]))),
                })
            elif target["source_key"] == "plans":
                start, end = prop_date(first_prop(props, ["日付", "開催日", "予定日", "Date"]))
                plans.append({
                    "page_id": page_id,
                    "plan_title": plain_prop(props, ["名前", "予定名", "イベント名", "Name"]),
                    "event_ids_json": json_text(relation_ids(first_prop(props, ["イベント", "イベントDB", "Event"]))),
                    "venue_ids_json": json_text(relation_ids(first_prop(props, ["会場", "会場マスタ", "Venue"]))),
                    "start_date": start,
                    "end_date": end,
                    "status": plain_prop(props, ["状態", "ステータス", "Status"]),
                    "memo": plain_prop(props, ["メモ", "備考", "詳細"]),
                })
            elif target["source_key"] == "glossary_v2":
                glossary.append({
                    "page_id": page_id,
                    "term": plain_prop(props, ["使用語", "用語", "Name"]),
                    "interpretation": plain_prop(props, ["解釈", "正規語/表示名", "説明"]),
                    "kind": plain_prop(props, ["種別", "分類"]),
                    "state": plain_prop(props, ["状態", "ステータス"]),
                    "confidence": plain_prop(props, ["確度"]),
                    "aliases": plain_prop(props, ["別表記", "表記ゆれ", "Aliases"]),
                    "related_song_ids_json": json_text(relation_ids(first_prop(props, ["ヒント先曲", "曲", "Song"]))),
                })

    return {
        "sources": sources,
        "pages": pages,
        "properties": properties,
        "relations": relations,
        "events": events,
        "venues": venues,
        "songs": songs,
        "plans": plans,
        "glossary": glossary,
    }


def create_db(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".tmp-notion-rdb-", suffix=".sqlite", delete=False) as handle:
        tmp_path = Path(handle.name)
    try:
        with sqlite3.connect(tmp_path) as conn:
            conn.executescript(SCHEMA)
            conn.executemany(
                "INSERT INTO notion_sources VALUES (:source_key, :source_name, :api_kind, :notion_id, :fetched_at, :row_count)",
                rows["sources"],
            )
            conn.executemany(
                """
                INSERT INTO notion_pages VALUES (
                  :page_id, :source_key, :url, :archived, :created_time, :last_edited_time,
                  :title, :properties_json, :raw_json
                )
                """,
                rows["pages"],
            )
            conn.executemany(
                "INSERT INTO notion_properties VALUES (:page_id, :property_name, :property_type, :plain_value, :json_value)",
                rows["properties"],
            )
            conn.executemany(
                "INSERT OR IGNORE INTO notion_relations VALUES (:page_id, :property_name, :related_page_id)",
                rows["relations"],
            )
            conn.executemany(
                """
                INSERT INTO notion_events VALUES (
                  :page_id, :event_name, :venue_ids_json, :start_date, :end_date,
                  :status, :annual_months, :detail, :public_intro, :source_url
                )
                """,
                rows["events"],
            )
            conn.executemany(
                """
                INSERT INTO notion_venues VALUES (
                  :page_id, :venue_name, :area, :address, :access, :scale, :public_intro, :past_memo
                )
                """,
                rows["venues"],
            )
            conn.executemany(
                """
                INSERT INTO notion_songs VALUES (
                  :page_id, :song_name, :category, :status, :evidence_count,
                  :source_url, :memo, :venue_ids_json
                )
                """,
                rows["songs"],
            )
            conn.executemany(
                """
                INSERT INTO notion_plans VALUES (
                  :page_id, :plan_title, :event_ids_json, :venue_ids_json,
                  :start_date, :end_date, :status, :memo
                )
                """,
                rows["plans"],
            )
            conn.executemany(
                """
                INSERT INTO notion_glossary_terms VALUES (
                  :page_id, :term, :interpretation, :kind, :state,
                  :confidence, :aliases, :related_song_ids_json
                )
                """,
                rows["glossary"],
            )
            conn.commit()
        tmp_path.replace(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def table_counts(path):
    with sqlite3.connect(path) as conn:
        return {
            name: conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
            for name in [
                "notion_sources",
                "notion_pages",
                "notion_properties",
                "notion_relations",
                "notion_events",
                "notion_venues",
                "notion_songs",
                "notion_plans",
                "notion_glossary_terms",
            ]
        }


def build_notion_rdb(out_db=OUT_DB, out_summary=OUT_SUMMARY, targets=TARGETS):
    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    fetched = [(target, query_all(target)) for target in targets]
    rows = build_rows(fetched)
    create_db(out_db, rows)
    summary = {
        "generated_by": "build_notion_rdb.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": str(out_db),
        "targets": [
            {
                "source_key": target["source_key"],
                "source_name": target["source_name"],
                "api_kind": target["api_kind"],
                "notion_id": target["notion_id"],
                "row_count": len(rows),
            }
            for target, rows in fetched
        ],
        "table_counts": table_counts(out_db),
    }
    Path(out_summary).parent.mkdir(parents=True, exist_ok=True)
    Path(out_summary).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-db", default=str(OUT_DB))
    parser.add_argument("--out-summary", default=str(OUT_SUMMARY))
    args = parser.parse_args()

    summary = build_notion_rdb(out_db=Path(args.out_db), out_summary=Path(args.out_summary))
    print(
        "notion RDB snapshot: "
        + ", ".join(f"{name}={count}" for name, count in summary["table_counts"].items())
    )


if __name__ == "__main__":
    main()
