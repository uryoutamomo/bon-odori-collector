#!/usr/bin/env python3
"""Create reviewed retrospective venues/events that have enough local evidence."""

import argparse
import json
import os
from datetime import date
from pathlib import Path

from notion_support.notion_api import NotionApi
from operation_safety.manual_apply_guards import LEGACY_YOUTUBE_NOTION_CONFIRMATION, require_confirmation
from notion_config import EVENT_DATA_SOURCE_ID, VENUE_DATA_SOURCE_ID


OUT = Path("data/retrospective_ready_venue_event_apply_result.json")
TODAY = date(2026, 6, 13)


ITEMS = [
    {
        "venue_name": "辻堂神台公園",
        "aliases": ["辻堂駅北口神台公園", "辻堂神台公園", "神台公園"],
        "region": "藤沢市",
        "address": "神奈川県藤沢市辻堂神台1-6-2",
        "access": "JR辻堂駅北口から徒歩圏内。テラスモール湘南付近",
        "source_url": "https://x.com/honeycutie333/status/2064678013510504823",
        "memo": "retrospective_harvest: 2026-07-04 藤沢七夕まつりの会場。X本文では「辻堂駅北口神台公園」「辻堂神台公園」表記が混在。こと裏取りで住所・プログラム確認済み。",
        "scale": "中",
        "in_tsukiji": False,
        "needs_review": False,
        "update_existing": True,
        "event": {
            "name": "藤沢七夕まつり",
            "date": "2026-07-04",
            "source_url": "https://x.com/honeycutie333/status/2064678013510504823",
            "month": "7月",
            "pattern_detail": "2026-07-04 10:00-20:00。DJ盆踊り大会、こども盆踊り、辻堂あさがお会盆踊り等のプログラムを確認済み。",
        },
    },
    {
        "venue_name": "秋田港フェリーターミナル（中島埠頭）",
        "aliases": ["秋田港フェリーターミナル", "秋田港（中島埠頭）", "中島埠頭"],
        "region": "秋田市",
        "address": "〒011-0945 秋田県秋田市土崎港西1丁目13番地13号 中島埠頭",
        "access": "JR秋田駅より約8km、車で約20分。JR土崎駅より約1.8km、車で約10分",
        "source_url": "https://www.snf.jp/guide/embark/akita/",
        "memo": "新日本海フェリー公式の秋田フェリーターミナル情報。retrospective_harvest: セリオン公式X投稿で2026-06-07 17:30 西馬音内盆踊り、18:00出港。",
        "scale": "中",
        "in_tsukiji": False,
        "needs_review": False,
        "event": {
            "name": "ヘリテージ・アドベンチャラー寄港 西馬音内盆踊り",
            "date": "2026-06-07",
            "source_url": "https://x.com/selion_akitakou/status/2063452243609936037",
            "month": "6月",
            "pattern_detail": "2026-06-07、秋田港ターミナルで17:30西馬音内盆踊り、18:00出港。セリオン公式X投稿より。",
        },
    },
    {
        "venue_name": "エリアなかいち（秋田市にぎわい交流館AU周辺）",
        "aliases": ["エリアなかいち", "秋田市にぎわい交流館AU", "にぎわい交流館AU"],
        "region": "秋田市",
        "address": "秋田市中通一丁目4番1号",
        "access": "秋田駅西口から徒歩約10分",
        "source_url": "https://www.akita-nigiwai-au.jp/access",
        "memo": "秋田市にぎわい交流館AU公式アクセス情報。retrospective_harvest: まるっと秋田博公式X投稿で2026-05-30 19:45から西馬音内盆踊り演舞。",
        "scale": "中",
        "in_tsukiji": False,
        "needs_review": False,
        "event": {
            "name": "まるっと秋田博 西馬音内盆踊り",
            "date": "2026-05-30",
            "source_url": "https://x.com/maru_akitahaku/status/2060657371937153093",
            "month": "5月",
            "pattern_detail": "2026-05-30、エリアなかいち会場で19:45から演舞。まるっと秋田博公式X投稿より。",
        },
    },
    {
        "venue_name": "足寄町民センター前グラウンド・駐車場",
        "aliases": ["足寄町民センター前グラウンド", "足寄町民センター前駐車場", "利別川河川敷両国橋下流", "両国橋下流", "足寄町 利別川河川敷"],
        "region": "北海道足寄郡足寄町",
        "address": "北海道足寄郡足寄町南1条5丁目付近",
        "access": "JR池田駅から十勝バス陸別行きで約60分、足寄停留所下車徒歩5分。道東道足寄ICから車で約10分",
        "source_url": "https://hanabi.walkerplus.com/detail/ar0101e01042/",
        "memo": "第44回 足寄ふるさと盆踊り・両国花火大会の盆踊り本体会場。こと裏取りでは、花火打ち上げは利別川両国橋下流の河川敷、盆踊り・露店・ステージは足寄町民センター前グラウンド＋駐車場。2026日付は要再確認。",
        "scale": "大",
        "in_tsukiji": False,
        "needs_review": True,
        "update_existing": True,
        "event": {
            "name": "第44回 足寄ふるさと盆踊り・両国花火大会",
            "date": "2026-08-15",
            "source_url": "https://hanabi.walkerplus.com/detail/ar0101e01042/",
            "month": "8月",
            "pattern_detail": "2026-08-15候補。盆踊り・露店・ステージは足寄町民センター前グラウンド＋駐車場、花火打ち上げは利別川両国橋下流の河川敷。2026公式発表は要再確認。",
        },
    },
    {
        "venue_name": "ヒューリック浅草橋ビル前",
        "aliases": ["ヒューリック浅草橋ビル前", "浅草橋マロニエ", "浅草橋マロニエまつり会場"],
        "region": "台東区",
        "address": "東京都台東区浅草橋1丁目22-16付近",
        "access": "JR・都営浅草橋駅から徒歩約3分",
        "source_url": "https://x.com/1205uzonke/status/2065200648086487508",
        "memo": "浅草橋マロニエまつり盆踊りの第二部会場。こと裏取りでは第一部は鳥越おかず横丁13:00-14:00、第二部はヒューリック浅草橋ビル前14:30-16:30。過去実績として来年の名寄せ用に保持。",
        "scale": "小",
        "in_tsukiji": True,
        "needs_review": False,
        "event": {
            "name": "浅草橋マロニエまつり盆踊り",
            "date": "2026-05-09",
            "source_url": "https://x.com/1205uzonke/status/2065200648086487508",
            "month": "5月",
            "pattern_detail": "2026-05-09開催済み。第一部は鳥越おかず横丁13:00-14:00、第二部はヒューリック浅草橋ビル前14:30-16:30。たいとう音頭・浅草橋音頭など。",
        },
    },
    {
        "venue_name": "笠間大池公園（笠間ポレポレシティ前）",
        "aliases": ["笠間大池公園", "笠間ポレポレシティ前", "笠間納涼盆踊り花火大会会場"],
        "region": "笠間市",
        "address": "茨城県笠間市赤坂8付近",
        "access": "笠間ポレポレシティ前",
        "source_url": "https://x.com/hitachi773X/status/2065431155575505274",
        "memo": "笠間納涼盆踊り花火大会2026の会場候補。こと裏取りで笠間大池公園（笠間ポレポレシティ前）と確認。23区外のため公開JSONからは除外対象。",
        "scale": "中",
        "in_tsukiji": False,
        "needs_review": True,
        "event": {
            "name": "笠間納涼盆踊り花火大会2026",
            "date": "2026-08-08",
            "source_url": "https://x.com/hitachi773X/status/2065431155575505274",
            "month": "8月",
            "pattern_detail": "2026-08-08開催候補。会場は笠間大池公園（笠間ポレポレシティ前）。2026公式発表は要再確認。",
        },
    },
]


def title_prop(text):
    return {"title": [{"text": {"content": text}}]} if text else {"title": []}


def text_prop(text):
    return {"rich_text": [{"text": {"content": text}}]} if text else {"rich_text": []}


def select_prop(name):
    return {"select": {"name": name}} if name else {"select": None}


def date_prop(value):
    return {"date": {"start": value}} if value else {"date": None}


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
    names = [item["venue_name"]] + item.get("aliases", [])
    for name in names:
        venue = query_title(api, VENUE_DATA_SOURCE_ID, "会場名", name)
        if venue:
            return venue, name
    return None, ""


def find_event(api, name):
    return query_title(api, EVENT_DATA_SOURCE_ID, "イベント名", name)


def create_venue(api, item):
    props = {
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
    return api.request("POST", "/pages", {"parent": {"data_source_id": VENUE_DATA_SOURCE_ID}, "properties": props})


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


def update_venue(api, venue_id, item):
    return api.update_page(venue_id, venue_props(item))


def create_event(api, venue_id, item):
    event = item["event"]
    props = {
        "イベント名": title_prop(event["name"]),
        "会場": {"relation": [{"id": venue_id}]},
        "開催日": date_prop(event["date"]),
        "状態": select_prop(event_status(event["date"])),
        "情報源URL": {"url": event["source_url"]},
        "例年開催月": text_prop(event["month"]),
        "開催パターン種別": select_prop("不明"),
        "開催パターン詳細": text_prop(event["pattern_detail"]),
    }
    return api.request("POST", "/pages", {"parent": {"data_source_id": EVENT_DATA_SOURCE_ID}, "properties": props})


def event_props(venue_id, item):
    event = item["event"]
    return {
        "イベント名": title_prop(event["name"]),
        "会場": {"relation": [{"id": venue_id}]},
        "開催日": date_prop(event["date"]),
        "状態": select_prop(event_status(event["date"])),
        "情報源URL": {"url": event["source_url"]},
        "例年開催月": text_prop(event["month"]),
        "開催パターン種別": select_prop("不明"),
        "開催パターン詳細": text_prop(event["pattern_detail"]),
    }


def update_event(api, event_id, venue_id, item):
    return api.update_page(event_id, event_props(venue_id, item))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    try:
        require_confirmation(
            args.apply,
            args.confirm,
            LEGACY_YOUTUBE_NOTION_CONFIRMATION,
            "legacy retrospective ready venue/event Notion update",
        )
    except ValueError as exc:
        parser.error(str(exc))

    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    results = []
    for item in ITEMS:
        venue, matched_name = find_venue(api, item)
        event = find_event(api, item["event"]["name"])
        result = {
            "venue": item["venue_name"],
            "venue_exists": bool(venue),
            "venue_matched_name": matched_name,
            "venue_created": False,
            "event": item["event"]["name"],
            "event_exists": bool(event),
            "event_created": False,
            "venue_updated": False,
            "event_updated": False,
            "event_date": item["event"]["date"],
            "needs_review": item["needs_review"],
        }
        if args.apply and not venue:
            venue = create_venue(api, item)
            result["venue_created"] = True
        elif args.apply and venue and item.get("update_existing"):
            venue = update_venue(api, venue["id"], item)
            result["venue_updated"] = True
        if args.apply and venue and not event:
            event = create_event(api, venue["id"], item)
            result["event_created"] = True
        elif args.apply and venue and event and item.get("update_existing"):
            event = update_event(api, event["id"], venue["id"], item)
            result["event_updated"] = True
        result["venue_id"] = (venue or {}).get("id", "")
        result["event_id"] = (event or {}).get("id", "")
        results.append(result)

    output = {
        "apply_performed": args.apply,
        "venue_count": len(results),
        "event_count": len(results),
        "created_venues": sum(1 for item in results if item["venue_created"]),
        "created_events": sum(1 for item in results if item["event_created"]),
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
