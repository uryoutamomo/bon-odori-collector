#!/usr/bin/env python3
"""Create reviewed YouTube-derived events after official confirmation."""

import argparse
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

from notion_api import NotionApi
from notion_config import EVENT_DATA_SOURCE_ID, VENUE_DATA_SOURCE_ID


OUT = Path("data/youtube_reviewed_new_event_apply_result.json")
TODAY = date(2026, 6, 15)

ITEMS = [
    {
        "candidate_key": "yt-event:afaa6dfcf53ef3f9",
        "review_decision": "official_confirmed_register",
        "venue_name": "行幸通り",
        "aliases": ["東京駅丸の内口・行幸通り", "行幸通り（丸の内）"],
        "region": "千代田区",
        "address": "東京都千代田区丸の内2-2",
        "access": "JR東京駅丸の内口から徒歩圏内。東京駅と皇居を結ぶ行幸通り",
        "source_url": "https://www.marunouchi.com/pickup/event/6763/",
        "memo": (
            "Marunouchi.com公式ページで「丸の内夏祭り2025」in 行幸通りを確認。"
            "YouTube候補では丸の内de盆踊りの曲目映像あり。"
        ),
        "scale": "大",
        "in_tsukiji": True,
        "needs_review": False,
        "event": {
            "name": "丸の内de盆踊り",
            "date": "2025-07-25",
            "date_end": "2025-07-26",
            "source_url": "https://www.marunouchi.com/pickup/event/6763/",
            "month": "7月",
            "pattern_detail": (
                "2025-07-25〜2025-07-26、行幸通りで開催。"
                "公式ページ「丸の内夏祭り2025」in 行幸通り内の丸の内de盆踊り。"
                "7/25 盆踊り 17:00-18:15 / 19:00-19:40 / 20:00-21:00、"
                "7/26 盆踊り 18:00-19:00 / 19:20-20:10 / 20:40-21:00。"
                "\n\n[youtube_evidence] 2025実績証拠"
                "\n- 動画: https://www.youtube.com/watch?v=_cggqDBTu20"
                "\n- チャンネル: shu channel"
                "\n- サムネイル: https://i.ytimg.com/vi/_cggqDBTu20/maxresdefault.jpg"
                "\n- 曲目候補: 丸の内音頭, 東京音頭, 大東京音頭, ドンパン節, 炭坑節, お江戸日本橋, 八木節"
            ),
        },
    }
]


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def title_prop(text):
    return {"title": [{"text": {"content": text[:200]}}]} if text else {"title": []}


def text_prop(text):
    return {"rich_text": [{"text": {"content": text[:1900]}}]} if text else {"rich_text": []}


def select_prop(name):
    return {"select": {"name": name}} if name else {"select": None}


def date_prop(start, end=None):
    if not start:
        return {"date": None}
    value = {"start": start}
    if end:
        value["end"] = end
    return {"date": value}


def event_status(date_value):
    if not date_value:
        return "確認済み"
    y, m, d = [int(part) for part in date_value.split("-")]
    return "終了" if date(y, m, d) < TODAY else "確認済み"


def query_title(api, data_source_id, property_name, title):
    rows = api.query_data_source(
        data_source_id,
        {"filter": {"property": property_name, "title": {"equals": title}}, "page_size": 5},
    )
    return rows[0] if rows else None


def find_venue(api, item):
    for name in [item["venue_name"]] + item.get("aliases", []):
        venue = query_title(api, VENUE_DATA_SOURCE_ID, "会場名", name)
        if venue:
            return venue, name
    return None, ""


def find_event(api, name):
    return query_title(api, EVENT_DATA_SOURCE_ID, "イベント名", name)


def venue_props(item):
    return {
        "会場名": title_prop(item["venue_name"]),
        "所在区・市": text_prop(item["region"]),
        "住所": text_prop(item["address"]),
        "アクセス": text_prop(item["access"]),
        "出典URL": {"url": item["source_url"]},
        "過去メモ": text_prop(item["memo"]),
        "規模": select_prop(item["scale"]),
        "築地30分圏内": {"checkbox": item["in_tsukiji"]},
        "要レビュー": {"checkbox": item["needs_review"]},
    }


def event_props(venue_id, item):
    event = item["event"]
    return {
        "イベント名": title_prop(event["name"]),
        "会場": {"relation": [{"id": venue_id}]},
        "開催日": date_prop(event["date"], event.get("date_end")),
        "状態": select_prop(event_status(event["date"])),
        "情報源URL": {"url": event["source_url"]},
        "例年開催月": text_prop(event["month"]),
        "開催パターン種別": select_prop("不明"),
        "開催パターン詳細": text_prop(event["pattern_detail"]),
    }


def create_venue(api, item):
    return api.request("POST", "/pages", {"parent": {"data_source_id": VENUE_DATA_SOURCE_ID}, "properties": venue_props(item)})


def create_event(api, venue_id, item):
    return api.request("POST", "/pages", {"parent": {"data_source_id": EVENT_DATA_SOURCE_ID}, "properties": event_props(venue_id, item)})


def build_results(api, apply=False):
    results = []
    for item in ITEMS:
        venue, matched_name = find_venue(api, item)
        event = find_event(api, item["event"]["name"])
        result = {
            "candidate_key": item["candidate_key"],
            "review_decision": item["review_decision"],
            "venue": item["venue_name"],
            "venue_exists": bool(venue),
            "venue_matched_name": matched_name,
            "venue_created": False,
            "event": item["event"]["name"],
            "event_exists": bool(event),
            "event_created": False,
            "event_date": item["event"]["date"],
            "event_date_end": item["event"].get("date_end") or "",
            "source_url": item["source_url"],
        }
        if apply and not venue:
            venue = create_venue(api, item)
            result["venue_created"] = True
            result["venue_page_id"] = venue.get("id") or ""
        elif venue:
            result["venue_page_id"] = venue.get("id") or ""
        if apply and venue and not event:
            event = create_event(api, venue["id"], item)
            result["event_created"] = True
            result["event_page_id"] = event.get("id") or ""
        elif event:
            result["event_page_id"] = event.get("id") or ""
        results.append(result)
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    rows = build_results(api, apply=args.apply)
    output = {
        "generated_by": "apply_youtube_reviewed_new_events.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if args.apply else "dry_run",
        "apply_performed": bool(args.apply),
        "input_count": len(rows),
        "venue_created_count": sum(1 for row in rows if row["venue_created"]),
        "event_created_count": sum(1 for row in rows if row["event_created"]),
        "rows": rows,
    }
    write_json(args.out, output)
    print(
        "youtube reviewed new events: "
        f"mode={output['mode']} venues={output['venue_created_count']} "
        f"events={output['event_created_count']} -> {args.out}"
    )


if __name__ == "__main__":
    main()
