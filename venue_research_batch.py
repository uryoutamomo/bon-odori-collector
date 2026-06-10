import json
import os
from pathlib import Path

from notion_api import NotionApi, plain_text
from notion_config import EVENT_DATA_SOURCE_ID, VENUE_DATA_SOURCE_ID


STATE_PATH = Path(__file__).parent / "data" / "venue_review_state.json"


VENUES = [
    {
        "queue_name": "日本民謡会館",
        "venue_name": "日本民謡会館",
        "aliases": ["日本民謡会館", "日本民謡協会ホール"],
        "region": "品川区",
        "address": "東京都品川区南品川6-8-20",
        "access": "大井町駅から徒歩圏内",
        "source_url": "https://www.youtube.com/watch?v=9lkufMdYu2c",
        "memo": "2026-05-31に日本民謡協会ホールでMin-Yoi's盆踊り開催記録あり。",
        "in_tsukiji": True,
        "event": {
            "name": "Min-Yoi's盆踊り",
            "date": "2026-05-31",
            "status": "終了",
            "source_url": "https://www.youtube.com/watch?v=9lkufMdYu2c",
            "month": "5月",
            "pattern_type": "不明",
            "pattern_detail": "2026-05-31（日）開催記録。次回日程は未確認。",
        },
    },
    {
        "queue_name": "鮫洲入江広場",
        "venue_name": "鮫洲入江広場公園",
        "aliases": ["鮫洲入江広場", "鮫洲入江広場公園", "鮫洲入江公園"],
        "region": "品川区",
        "address": "東京都品川区東大井1-16-15",
        "access": "京急 鮫洲駅から徒歩約5分",
        "source_url": "https://x.com/mizu516AforReal/status/2062799802266710143",
        "memo": "2026-06-06のゆり園イベント内で晴盆の盆踊り枠あり。",
        "in_tsukiji": True,
        "event": {
            "name": "鮫洲入江広場公園 ゆり園盆踊り",
            "date": "2026-06-06",
            "status": "終了",
            "source_url": "https://x.com/mizu516AforReal/status/2062799802266710143",
            "month": "6月",
            "pattern_type": "不明",
            "pattern_detail": "2026-06-06（土）14:30から晴盆の盆踊り枠。次回日程は未確認。",
        },
    },
    {
        "queue_name": "西大井広場",
        "venue_name": "西大井広場公園",
        "aliases": ["西大井広場", "西大井広場公園"],
        "region": "品川区",
        "address": "東京都品川区西大井1丁目4-10",
        "access": "横須賀線・湘南新宿ライン 西大井駅から徒歩約5分",
        "source_url": "https://bonmaru.zenmin-odori.jp/archives/202668",
        "memo": "2025-09-27に品川区民まつりの盆踊りの部として開催記録あり。",
        "in_tsukiji": True,
        "event": {
            "name": "品川区民まつり 西大井広場公園 盆踊り",
            "date": "2025-09-27",
            "status": "終了",
            "source_url": "https://bonmaru.zenmin-odori.jp/archives/202668",
            "month": "9月",
            "pattern_type": "不明",
            "pattern_detail": "2025-09-27 17:40～18:30の開催記録。通常は9月のどこか1日。2026年日程は未確認。",
        },
    },
]


def title_prop(text):
    return {"title": [{"text": {"content": text}}]}


def text_prop(text):
    return {"rich_text": [{"text": {"content": text}}]} if text else {"rich_text": []}


def select_prop(name):
    return {"select": {"name": name}}


def date_prop(date):
    return {"date": {"start": date}}


def find_venue(api, aliases):
    for alias in aliases:
        rows = api.query_data_source(
            VENUE_DATA_SOURCE_ID,
            {
                "filter": {"property": "会場名", "title": {"contains": alias}},
                "page_size": 10,
            },
        )
        if rows:
            return rows[0]
    return None


def find_event(api, event_name):
    rows = api.query_data_source(
        EVENT_DATA_SOURCE_ID,
        {
            "filter": {"property": "イベント名", "title": {"contains": event_name}},
            "page_size": 10,
        },
    )
    return rows[0] if rows else None


def create_venue(api, item):
    props = {
        "会場名": title_prop(item["venue_name"]),
        "所在区・市": text_prop(item["region"]),
        "住所": text_prop(item["address"]),
        "アクセス": text_prop(item["access"]),
        "出典URL": {"url": item["source_url"]},
        "過去メモ": text_prop(item["memo"]),
        "規模": select_prop("小"),
        "築地30分圏内": {"checkbox": item["in_tsukiji"]},
        "要レビュー": {"checkbox": False},
    }
    return api.request(
        "POST",
        "/pages",
        {"parent": {"data_source_id": VENUE_DATA_SOURCE_ID}, "properties": props},
    )


def create_event(api, venue_page_id, item):
    event = item["event"]
    props = {
        "イベント名": title_prop(event["name"]),
        "会場": {"relation": [{"id": venue_page_id}]},
        "開催日": date_prop(event["date"]),
        "状態": select_prop(event["status"]),
        "情報源URL": {"url": event["source_url"]},
        "例年開催月": text_prop(event["month"]),
        "開催パターン種別": select_prop(event["pattern_type"]),
        "開催パターン詳細": text_prop(event["pattern_detail"]),
    }
    return api.request(
        "POST",
        "/pages",
        {"parent": {"data_source_id": EVENT_DATA_SOURCE_ID}, "properties": props},
    )


def update_state(results):
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    done = state.setdefault("research_done_2026_06_10", [])
    later = state.get("research_later", [])
    by_name = {item["queue_name"]: item for item in results}

    new_later = []
    for entry in later:
        name = entry.get("venue")
        if name not in by_name:
            new_later.append(entry)
            continue
        updated = dict(entry)
        result = by_name[name]
        updated["result"] = result["result"]
        updated["notion_url"] = result["notion_url"]
        updated["event_url"] = result["event_url"]
        done.append(updated)

    state["research_later"] = new_later
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main():
    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    results = []
    for item in VENUES:
        venue = find_venue(api, item["aliases"])
        venue_created = False
        if not venue:
            venue = create_venue(api, item)
            venue_created = True

        event = find_event(api, item["event"]["name"])
        event_created = False
        if not event:
            event = create_event(api, venue["id"], item)
            event_created = True

        venue_name = plain_text(venue["properties"].get("会場名"))
        results.append(
            {
                "queue_name": item["queue_name"],
                "result": (
                    f"登録済み: {venue_name}／{item['event']['name']}"
                    if venue_created or event_created
                    else f"既存確認: {venue_name}／{item['event']['name']}"
                ),
                "notion_url": venue.get("url"),
                "event_url": event.get("url"),
            }
        )

    update_state(results)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
