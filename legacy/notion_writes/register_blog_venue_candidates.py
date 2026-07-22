import argparse
import json
import os
import re
from datetime import date
from pathlib import Path

from manual_apply_guards import LEGACY_NOTION_REPAIR_CONFIRMATION, require_confirmation
from notion_support.notion_api import NotionApi, plain_text
from notion_config import EVENT_DATA_SOURCE_ID, VENUE_DATA_SOURCE_ID


INPUT = Path("data/blog_registration_candidates.json")
TODAY = date(2026, 6, 10)


def title_prop(text):
    return {"title": [{"text": {"content": text}}]} if text else {"title": []}


def text_prop(text):
    return {"rich_text": [{"text": {"content": text}}]} if text else {"rich_text": []}


def select_prop(name):
    return {"select": {"name": name}}


def date_prop(value):
    return {"date": {"start": value}} if value else {"date": None}


def normalize_address(address):
    if not address:
        return ""
    if address.startswith("東京都"):
        return address
    if address.startswith(("世田谷区", "大田区", "中野区", "江戸川区", "葛飾区", "豊島区")):
        return "東京都" + address
    return address


def parse_date(date_text):
    if not date_text:
        return None
    year = re.search(r"(20\d{2})", date_text)
    md = re.search(r"(\d{1,2})/(\d{1,2})", date_text)
    if not year or not md:
        return None
    return f"{year.group(1)}-{int(md.group(1)):02d}-{int(md.group(2)):02d}"


def event_status(date_value):
    if not date_value:
        return "確認済み"
    y, m, d = [int(part) for part in date_value.split("-")]
    return "終了" if date(y, m, d) < TODAY else "確認済み"


def find_venue(api, name):
    rows = api.query_data_source(
        VENUE_DATA_SOURCE_ID,
        {"filter": {"property": "会場名", "title": {"equals": name}}, "page_size": 5},
    )
    return rows[0] if rows else None


def find_event(api, name):
    rows = api.query_data_source(
        EVENT_DATA_SOURCE_ID,
        {"filter": {"property": "イベント名", "title": {"equals": name}}, "page_size": 5},
    )
    return rows[0] if rows else None


def create_venue(api, item):
    props = {
        "会場名": title_prop(item["venue_name"]),
        "所在区・市": text_prop(item["region"]),
        "住所": text_prop(normalize_address(item["address"])),
        "アクセス": text_prop(item["access"]),
        "出典URL": {"url": item["source_url"]},
        "過去メモ": text_prop(item["memo"]),
        "規模": select_prop(item["scale"]),
        "築地30分圏内": {"checkbox": item["in_tsukiji"]},
        "要レビュー": {"checkbox": False},
    }
    return api.request(
        "POST",
        "/pages",
        {"parent": {"data_source_id": VENUE_DATA_SOURCE_ID}, "properties": props},
    )


def create_event(api, venue_id, item):
    event = item["event"]
    start = parse_date(event.get("date_text"))
    props = {
        "イベント名": title_prop(event["name"]),
        "会場": {"relation": [{"id": venue_id}]},
        "開催日": date_prop(start),
        "状態": select_prop(event_status(start)),
        "情報源URL": {"url": event["source_url"]},
        "例年開催月": text_prop(event["month"]),
        "開催パターン種別": select_prop("不明"),
        "開催パターン詳細": text_prop(f"{event.get('date_text') or ''}。次回日程は未確認。"),
    }
    return api.request(
        "POST",
        "/pages",
        {"parent": {"data_source_id": EVENT_DATA_SOURCE_ID}, "properties": props},
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        require_confirmation(
            True,
            args.confirm,
            LEGACY_NOTION_REPAIR_CONFIRMATION,
            "legacy blog venue candidate registration",
        )
    except ValueError as exc:
        parser.error(str(exc))

    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    items = json.loads(INPUT.read_text(encoding="utf-8"))["items"]
    results = []
    for item in items:
        venue = find_venue(api, item["venue_name"])
        venue_created = False
        if not venue:
            venue = create_venue(api, item)
            venue_created = True

        event = find_event(api, item["event"]["name"])
        event_created = False
        if not event:
            event = create_event(api, venue["id"], item)
            event_created = True

        results.append(
            {
                "venue": item["venue_name"],
                "venue_created": venue_created,
                "event": item["event"]["name"],
                "event_created": event_created,
                "venue_id": venue["id"],
                "event_id": event["id"],
            }
        )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(
        "created venues="
        + str(sum(1 for r in results if r["venue_created"]))
        + " events="
        + str(sum(1 for r in results if r["event_created"]))
    )


if __name__ == "__main__":
    main()
