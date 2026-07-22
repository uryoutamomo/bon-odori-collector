import argparse
import json
import os
from datetime import date
from pathlib import Path

from operation_safety.manual_apply_guards import LEGACY_NOTION_REPAIR_CONFIRMATION, require_confirmation
from notion_api import NotionApi, plain_text
from notion_config import EVENT_DATA_SOURCE_ID, VENUE_DATA_SOURCE_ID


INPUT = Path("data/fallback_event_candidates.json")
TODAY = date(2026, 6, 10)


def title_prop(text):
    return {"title": [{"text": {"content": text}}]} if text else {"title": []}


def text_prop(text):
    return {"rich_text": [{"text": {"content": text}}]} if text else {"rich_text": []}


def select_prop(name):
    return {"select": {"name": name}}


def date_prop(value):
    return {"date": {"start": value}} if value else {"date": None}


def find_venue(api, name):
    rows = api.query_data_source(
        VENUE_DATA_SOURCE_ID,
        {"filter": {"property": "会場名", "title": {"equals": name}}, "page_size": 5},
    )
    if not rows:
        raise ValueError(f"venue not found: {name}")
    return rows[0]


def find_event(api, name):
    rows = api.query_data_source(
        EVENT_DATA_SOURCE_ID,
        {"filter": {"property": "イベント名", "title": {"equals": name}}, "page_size": 5},
    )
    return rows[0] if rows else None


def public_date(item):
    value = item.get("date")
    if not value or not value.startswith("2026-"):
        return None
    return value


def event_status(start):
    if not start:
        return "未確認"
    y, m, d = [int(part) for part in start.split("-")]
    return "終了" if date(y, m, d) < TODAY else "確認済み"


def intro_for(item):
    venue = item["venue"]
    name = item["name"]
    if item.get("estimated"):
        return f"{venue}で開催される地域の盆踊り。名称は会場名と過去の開催情報からの推定。"
    if "品川区民まつり" in name:
        return f"{venue}を会場に行われる品川区民まつりの地域イベント。模擬店や盆踊りを楽しめる地区行事。"
    if "奉納" in name or "例大祭" in name:
        return f"{venue}周辺で行われる祭礼にあわせた奉納踊り。地域の町会が支える昔ながらの盆踊り。"
    return f"{venue}で行われる地域の盆踊りイベント。過去の開催実績をもとに掲載。"


def event_props(venue_id, item, include_relation=True):
    start = public_date(item)
    detail = item.get("detail") or ""
    if item.get("estimated") and not item.get("date"):
        detail = "名称推定。開催日程は未確認。"
    elif item.get("date") and not start:
        detail = f"{item['date']} 開催実績。{detail}"
    props = {
        "イベント名": title_prop(item["name"]),
        "開催日": date_prop(start),
        "状態": select_prop(event_status(start)),
        "情報源URL": {"url": item["source_url"]},
        "例年開催月": text_prop(item.get("month") or ""),
        "開催パターン種別": select_prop("不明"),
        "開催パターン詳細": text_prop(detail),
        "公開紹介文": text_prop(intro_for(item)),
    }
    if include_relation:
        props["会場"] = {"relation": [{"id": venue_id}]}
    return props


def ensure_relation(api, event, venue_id):
    props = event.get("properties", {})
    relation = props.get("会場", {}).get("relation", [])
    ids = [r["id"] for r in relation]
    if venue_id in ids:
        return False
    ids.append(venue_id)
    api.update_page(event["id"], {"会場": {"relation": [{"id": i} for i in ids]}})
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        require_confirmation(
            True,
            args.confirm,
            LEGACY_NOTION_REPAIR_CONFIRMATION,
            "legacy fallback event registration",
        )
    except ValueError as exc:
        parser.error(str(exc))

    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    items = json.loads(INPUT.read_text(encoding="utf-8"))["items"]
    results = []
    for item in items:
        venue = find_venue(api, item["venue"])
        event = find_event(api, item["name"])
        if event:
            relation_updated = ensure_relation(api, event, venue["id"])
            api.update_page(event["id"], event_props(venue["id"], item, include_relation=False))
            created = False
        else:
            event = api.request(
                "POST",
                "/pages",
                {
                    "parent": {"data_source_id": EVENT_DATA_SOURCE_ID},
                    "properties": event_props(venue["id"], item),
                },
            )
            relation_updated = False
            created = True
        results.append({
            "venue": item["venue"],
            "event": item["name"],
            "created": created,
            "relation_updated": relation_updated,
            "event_id": event["id"],
        })
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print(
        "created="
        + str(sum(1 for r in results if r["created"]))
        + " relation_updated="
        + str(sum(1 for r in results if r["relation_updated"]))
    )


if __name__ == "__main__":
    main()
