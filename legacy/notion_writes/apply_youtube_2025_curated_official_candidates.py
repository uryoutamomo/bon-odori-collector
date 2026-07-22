#!/usr/bin/env python3
"""Apply curated YouTube 2025 official candidates to Notion."""

import argparse
import json
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from manual_apply_guards import LEGACY_YOUTUBE_NOTION_CONFIRMATION, require_confirmation
from notion_support.notion_api import NotionApi, plain_text
from notion_config import EVENT_DATA_SOURCE_ID, VENUE_DATA_SOURCE_ID, load_local_env


VALIDATION = Path("data/youtube_2025_official_candidate_validation.json")
OUT = Path("data/youtube_2025_curated_official_apply_result.json")
MD_OUT = Path("data/youtube_2025_curated_official_apply_result.md")
TODAY = date(2026, 6, 16)

CURATED = [
    {
        "primary_url": "https://www.jiyugaoka-abc.com/event/2025/bonodori/",
        "decision": "append_existing_event",
        "event_name": "自由が丘納涼盆踊り大会",
        "reason": "自由が丘公式ページで2025-07-19〜2025-07-21開催、YouTube検出日付2025-07-20が範囲内",
    },
    {
        "primary_url": "https://www.roppongihills.com/events/2025/08/0478.html",
        "decision": "create_event",
        "event_name": "六本木ヒルズ盆踊り",
        "venue_name": "六本木ヒルズアリーナ",
        "venue_aliases": [],
        "venue_area": "港区",
        "venue_address": "東京都港区六本木6-10-1",
        "venue_access": "東京メトロ日比谷線 六本木駅直結／都営大江戸線 六本木駅 徒歩4分",
        "venue_scale": "大",
        "date": "2025-08-22",
        "date_end": "2025-08-24",
        "month": "8月",
        "reason": "六本木ヒルズ公式ページで2025-08-22〜2025-08-24開催を確認。22日は前夜祭、盆踊り動画は23/24。",
    },
    {
        "primary_url": "https://ginbura.ginza.jp/",
        "decision": "create_event",
        "event_name": "大銀座盆踊り",
        "venue_name": "中央通り（銀座1丁目〜8丁目）",
        "venue_aliases": ["銀座通り", "銀座通り3丁目交差点"],
        "venue_area": "中央区",
        "venue_address": "東京都中央区銀座1丁目〜8丁目付近",
        "venue_access": "東京メトロ銀座駅・銀座一丁目駅・東銀座駅から徒歩圏内",
        "venue_scale": "大",
        "date": "2025-08-02",
        "date_end": "2025-08-02",
        "month": "8月",
        "reason": "ゆかたで銀ぶら公式ページで中央通り開催と大銀座盆踊りの実施を確認。YouTube動画は2025-08-02。",
    },
    {
        "primary_url": "https://www.jrtk.jp/edonoren/",
        "decision": "create_event",
        "event_name": "-両国- 江戸NOREN 妖怪BON DANCE",
        "venue_name": "-両国-江戸NOREN",
        "venue_aliases": ["両国江戸NOREN", "JR両国駅西口駅舎"],
        "venue_area": "墨田区",
        "venue_address": "東京都墨田区横網1-3-20",
        "venue_access": "JR両国駅西口直結",
        "venue_scale": "中",
        "date": "2025-07-13",
        "date_end": "2025-07-13",
        "month": "7月",
        "reason": "江戸NOREN公式記事に妖怪BON DANCEを確認。掲載日も2025-07-04で、YouTube動画は2025-07-13。",
    },
    {
        "primary_url": "https://www.nouryo-matsuri.com/pages/6314608/page_202208061239",
        "source_url": "https://event-checker.info/kandamyoujin-bonodori/",
        "decision": "create_event",
        "event_name": "神田明神納涼祭り アニソン盆踊り",
        "venue_name": "神田明神境内",
        "venue_aliases": ["神田明神", "神田神社"],
        "venue_area": "千代田区",
        "venue_address": "東京都千代田区外神田2-16-2",
        "venue_access": "御茶ノ水駅・末広町駅・秋葉原駅から徒歩圏内",
        "venue_scale": "大",
        "date": "2025-08-08",
        "date_end": "2025-08-08",
        "month": "8月",
        "reason": "event-checkerで令和7年神田明神納涼祭りを確認。アニソン盆踊りは8/8枠で、YouTube11動画の検出日付と一致。",
    },
    {
        "primary_url": "https://shibuyadogenzaka.com/?p=6827",
        "source_url": "https://tokyofesta.com/23ku/24135/",
        "decision": "create_event",
        "event_name": "第6回 渋谷盆踊り",
        "venue_name": "SHIBUYA109前〜道玄坂・文化村通り一帯",
        "venue_aliases": ["渋谷道玄坂", "文化村通り"],
        "venue_area": "渋谷区",
        "venue_address": "東京都渋谷区道玄坂2丁目周辺",
        "venue_access": "渋谷駅ハチ公口から徒歩すぐ",
        "venue_scale": "大",
        "date": "2025-08-02",
        "date_end": "2025-08-02",
        "month": "8月",
        "reason": "tokyofestaで第6回渋谷盆踊り2025の開催を確認。盆踊りは18:00〜21:30、YouTube動画日付と一致。",
    },
    {
        "primary_url": "https://miyashita-bondance.jp/2025/",
        "decision": "create_event",
        "event_name": "SHIBUYA MIYASHITA PARK BON DANCE 2025",
        "venue_name": "MIYASHITA PARK4階 渋谷区立宮下公園 芝生ひろば",
        "venue_aliases": ["宮下公園", "MIYASHITA PARK"],
        "venue_area": "渋谷区",
        "venue_address": "東京都渋谷区神宮前6-20-10",
        "venue_access": "渋谷駅から徒歩約3分。明治神宮前〈原宿〉駅から徒歩圏内",
        "venue_scale": "大",
        "date": "2025-09-27",
        "date_end": "2025-09-28",
        "month": "9月",
        "detected_dates": ["2025-09-27", "2025-09-28"],
        "video_count": 10,
        "videos": [
            {
                "video_url": "https://www.youtube.com/watch?v=dZp8xUrphEE",
                "detected_event_date": "2025-09-27",
                "title": "[4K]🇯🇵 渋谷でultra soul！B'zで盆踊り！激混み会場で外国人も踊りまくる！！ / SHIBUYA MIYASHITA PARK BON DANCE 2025",
            },
            {
                "video_url": "https://www.youtube.com/watch?v=rCIetLTYOqQ",
                "detected_event_date": "2025-09-28",
                "title": "[4K]🇯🇵 渋谷で盆ジョヴィ 2025 ダンシングヒーロー｜YOASOBI｜Bon Jovi  他 外国人に人気の盆踊り / SHIBUYA MIYASHITA PARK BON DANCE",
            },
            {
                "video_url": "https://www.youtube.com/watch?v=6tYsIFg2Pc8",
                "detected_event_date": "2025-09-27",
                "title": "[4K]🇯🇵 渋谷で阿波踊り！飛鳥連が素晴らしい演舞を披露！外国人も一緒になって阿波踊り！2025 / Awaodori at SHIBUYA MIYASHITA PARK BON DANCE",
            },
            {
                "video_url": "https://www.youtube.com/watch?v=tqN1_Zn1XGQ",
                "detected_event_date": "2025-09-27",
                "title": "”大盛況”「ギザギザハートの子守唄」盆踊り 【渋谷宮下パーク BON DANCE 2025】チェッカーズ SHIBUYA MIYASHITA PARK BON DANCE 2025",
            },
            {
                "video_url": "https://www.youtube.com/watch?v=aICldK2fWJs",
                "detected_event_date": "2025-09-27",
                "title": "【渋谷宮下パーク BON DANCE 2025】「東京音頭」 盆踊り / SHIBUYA MIYASHITA PARK BON DANCE 2025",
            },
            {
                "video_url": "https://www.youtube.com/watch?v=G33WqNK76dk",
                "detected_event_date": "2025-09-27",
                "title": "【渋谷宮下パーク BON DANCE 2025】「ultra soul」B’z 盆踊り / SHIBUYA MIYASHITA PARK BON DANCE 2025",
            },
            {
                "video_url": "https://www.youtube.com/watch?v=t64KZSUomf4",
                "detected_event_date": "2025-09-28",
                "title": "渋谷宮下パークBON DANCE 2025 / 治安の悪い渋谷の公園も今は昔!! 人が集まる一大スポットに!! / SHIBUYA MIYASHITA PARK BON DANCE 2025",
            },
            {
                "video_url": "https://www.youtube.com/watch?v=1sf97ulUVcs",
                "detected_event_date": "2025-09-28",
                "title": "Dancing Hero aka Eat You Up @ Shibuya Miyashita Park Bon Dance 2025 in Tokyo Japan 4kHDR",
            },
            {
                "video_url": "https://www.youtube.com/watch?v=SbCL22zc48s",
                "detected_event_date": "2025-09-28",
                "title": "The Ground Was Shaking! B'z ultra soul @ Shibuya Miyashita Park Bon Dance 2025 in Tokyo 4kHDR",
            },
            {
                "video_url": "https://www.youtube.com/watch?v=AqTZJck5-FA",
                "detected_event_date": "2025-09-28",
                "title": "This Summer's Final Bon Dance Festival! @ Shibuya Miyashita Park 2025 in Tokyo Japan 4kHDR",
            },
        ],
        "reason": "公式アーカイブで2025年9月27日(土)、28日(日) 13:00〜21:00、MIYASHITA PARK4階 渋谷区立宮下公園 芝生ひろば開催を確認。5月/6月のGMOシブヤエンタメ祭系動画とは分離。",
    },
    {
        "primary_url": "https://tsukijihongwanji.jp/news/10279/",
        "source_url": "https://tokyofesta.com/23ku/23763/",
        "decision": "append_existing_event",
        "event_name": "築地本願寺納涼盆踊り大会",
        "reason": "tokyofestaで第78回築地本願寺納涼盆踊り大会の2025-07-30〜2025-08-02開催を確認。YouTube6動画の検出日付は開催初日と一致。",
    },
    {
        "primary_url": "https://www.earthday-tokyo.org/",
        "source_url": "https://www.earthday-tokyo.org/2025/04/01/14597",
        "decision": "create_event",
        "event_name": "アースデイ東京2025 イマジン盆踊り部",
        "venue_name": "代々木公園野外ステージ",
        "venue_aliases": ["代々木公園", "代々木公園イベント広場"],
        "venue_area": "渋谷区",
        "venue_address": "東京都渋谷区神南2-3",
        "venue_access": "原宿駅・明治神宮前駅・代々木公園駅から徒歩圏内",
        "venue_scale": "小",
        "date": "2025-04-19",
        "date_end": "2025-04-19",
        "month": "4月",
        "reason": "アースデイ東京公式ページでイマジン盆踊り部の出演を確認。イベント本体は2025-04-19〜20、盆踊り出演日は動画由来で4/19扱い。",
    },
    {
        "primary_url": "https://kumin.news/kita/articles/1057902",
        "decision": "append_existing_event",
        "event_name": "飛鳥山公園盆踊り会（有志サークル）",
        "date": "2025-04-19",
        "date_end": "2025-04-19",
        "month": "4月",
        "detected_dates": ["2025-04-19"],
        "video_count": 8,
        "reason": "北区民ニュースで2025-04-19の飛鳥山公園盆踊り会記事を確認。YouTube複数動画の日付・会場・イベント名とも一致。",
    },
    {
        "primary_url": "https://omoharareal.com/navi/news/detail/5157",
        "decision": "append_existing_event",
        "event_name": "謝恩納涼盆踊り大会（青山善光寺）",
        "date": "2025-07-27",
        "date_end": "2025-07-28",
        "month": "7月",
        "detected_dates": ["2025-07-28"],
        "video_count": 12,
        "reason": "表参道メディアOMOHARAREALで2025-07-27〜2025-07-28、青山善光寺境内開催を確認。YouTube検出日2025-07-28は開催範囲内。",
    },
    {
        "primary_url": "https://bonmaru.zenmin-odori.jp/archives/419",
        "decision": "append_existing_event",
        "event_name": "青山熊野神社例大祭 奉納踊り",
        "date": "2025-09-26",
        "date_end": "2025-09-27",
        "month": "9月",
        "detected_dates": ["2025-09-26", "2025-09-27"],
        "video_count": 47,
        "reason": "盆まる記事の検出日2025-09-26/27と、9月最終金土の慣例が一致。青葉公園でのYouTube動画群とも一致。",
    },
    {
        "primary_url": "https://tokyofesta.com/23ku/23185/",
        "decision": "create_event",
        "event_name": "GMOシブヤエンタメ祭 × JAME盆踊り",
        "venue_name": "渋谷区立宮下公園 芝生ひろば",
        "venue_aliases": ["MIYASHITA PARK4階 渋谷区立宮下公園 芝生ひろば", "宮下公園", "MIYASHITA PARK"],
        "venue_area": "渋谷区",
        "venue_address": "東京都渋谷区神宮前6-20-10",
        "venue_access": "渋谷駅から徒歩約3分。明治神宮前〈原宿〉駅から徒歩圏内",
        "venue_scale": "大",
        "date": "2025-05-31",
        "date_end": "2025-06-01",
        "month": "5月,6月",
        "detected_dates": ["2025-05-30", "2025-06-01"],
        "video_count": 4,
        "reason": "東京フェスタでGMOシブヤエンタメ祭 × JAME盆踊りの2025-05-31〜2025-06-01開催を確認。SHIBUYA MIYASHITA PARK BON DANCE 2025とは主催・性格が別。",
    },
]


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=".tmp-", suffix=".json", delete=False
    ) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        tmp_name = handle.name
    Path(tmp_name).replace(path)


def atomic_write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=".tmp-", suffix=".md", delete=False
    ) as handle:
        handle.write(text)
        tmp_name = handle.name
    Path(tmp_name).replace(path)


def title_prop(text):
    return {"title": [{"text": {"content": text[:200]}}]} if text else {"title": []}


def text_prop(text):
    if not text:
        return {"rich_text": []}
    return {"rich_text": [{"text": {"content": text[:1900]}}]}


def select_prop(name):
    return {"select": {"name": name}} if name else {"select": None}


def date_prop(start, end=None):
    if not start:
        return {"date": None}
    value = {"start": start}
    if end:
        value["end"] = end
    return {"date": value}


def current_date(page):
    value = ((page.get("properties") or {}).get("開催日") or {}).get("date")
    return value or {}


def event_status(date_value):
    if not date_value:
        return "確認済み"
    y, m, d = [int(part) for part in date_value.split("-")]
    return "終了" if date(y, m, d) < TODAY else "確認済み"


def rich_text_prop(text):
    if not text:
        return {"rich_text": []}
    chunks = [text[i:i + 1900] for i in range(0, len(text), 1900)]
    return {"rich_text": [{"text": {"content": chunk}} for chunk in chunks[:100]]}


def query_title(api, data_source_id, property_name, title):
    rows = api.query_data_source(
        data_source_id,
        {"filter": {"property": property_name, "title": {"equals": title}}, "page_size": 5},
    )
    return rows[0] if rows else None


def find_event(api, name):
    return query_title(api, EVENT_DATA_SOURCE_ID, "イベント名", name)


def find_venue(api, item):
    for name in [item.get("venue_name") or ""] + (item.get("venue_aliases") or []):
        if not name:
            continue
        venue = query_title(api, VENUE_DATA_SOURCE_ID, "会場名", name)
        if venue:
            return venue, name
    return None, ""


def validation_by_url(validation):
    return {row.get("primary_url"): row for row in validation.get("rows") or []}


def current_detail(page):
    return plain_text((page.get("properties") or {}).get("開催パターン詳細"))


def videos_for(row):
    return row.get("videos") or []


def evidence_note(item, row):
    dates = row.get("detected_dates") or item.get("detected_dates") or []
    videos = videos_for(row) or item.get("videos") or []
    source_url = item.get("source_url") or item["primary_url"]
    lines = [
        "[youtube_evidence] YouTube 2025公式URL確認済み証拠",
        f"- 対象イベント: {item['event_name']}",
        f"- 検出日付: {', '.join(dates) if dates else '未抽出'}",
        f"- 動画数: {row.get('video_count') or item.get('video_count') or len(videos)}",
        f"- 公式確認URL: {source_url}",
        f"- 判断: {item['reason']}",
    ]
    if source_url != item["primary_url"]:
        lines.append(f"- YouTube検出元URL: {item['primary_url']}")
    for video in videos:
        lines.append(
            f"- 動画: {video.get('video_url') or ''} / "
            f"{video.get('detected_event_date') or ''} / {video.get('title') or ''}"
        )
    return "\n".join(lines)


def merged_detail(existing, note):
    if not note:
        return existing or ""
    if note in (existing or ""):
        return existing or ""
    if existing:
        return existing.rstrip() + "\n\n" + note
    return note


def venue_props(item):
    source_url = item.get("source_url") or item["primary_url"]
    return {
        "会場名": title_prop(item["venue_name"]),
        "所在区・市": text_prop(item["venue_area"]),
        "住所": text_prop(item["venue_address"]),
        "アクセス": text_prop(item["venue_access"]),
        "出典URL": {"url": source_url},
        "過去メモ": text_prop(item["reason"]),
        "規模": select_prop(item["venue_scale"]),
        "築地30分圏内": {"checkbox": True},
        "要レビュー": {"checkbox": False},
    }


def event_props(venue_id, item, note):
    source_url = item.get("source_url") or item["primary_url"]
    return {
        "イベント名": title_prop(item["event_name"]),
        "会場": {"relation": [{"id": venue_id}]},
        "開催日": date_prop(item["date"], item.get("date_end")),
        "状態": select_prop(event_status(item["date"])),
        "情報源URL": {"url": source_url},
        "例年開催月": text_prop(item["month"]),
        "開催パターン種別": select_prop("不明"),
        "開催パターン詳細": text_prop(note),
    }


def create_venue(api, item):
    return api.request("POST", "/pages", {"parent": {"data_source_id": VENUE_DATA_SOURCE_ID}, "properties": venue_props(item)})


def create_event(api, venue_id, item, note):
    return api.request("POST", "/pages", {"parent": {"data_source_id": EVENT_DATA_SOURCE_ID}, "properties": event_props(venue_id, item, note)})


def build_results(api, validation, apply=False, only=None):
    by_url = validation_by_url(validation)
    results = []
    only = set(only or [])
    for item in CURATED:
        if only and item["event_name"] not in only and item["primary_url"] not in only:
            continue
        row = by_url.get(item["primary_url"]) or {}
        note = evidence_note(item, row)
        result = {
            "decision": item["decision"],
            "event_name": item["event_name"],
            "primary_url": item["primary_url"],
            "source_url": item.get("source_url") or item["primary_url"],
            "video_count": row.get("video_count") or item.get("video_count") or 0,
            "detected_dates": row.get("detected_dates") or item.get("detected_dates") or [],
            "reason": item["reason"],
            "changed": False,
            "event_created": False,
            "venue_created": False,
            "note": note,
        }
        if item["decision"] == "append_existing_event":
            event = find_event(api, item["event_name"])
            result["event_exists"] = bool(event)
            if event:
                old_detail = current_detail(event)
                video_urls = [video.get("video_url") or "" for video in videos_for(row) if video.get("video_url")]
                all_duplicate = bool(video_urls) and all(url in old_detail for url in video_urls)
                new_detail = old_detail if all_duplicate else merged_detail(old_detail, note)
                result.update({
                    "event_page_id": event.get("id") or "",
                    "duplicate_all_video_urls": all_duplicate,
                    "changed": new_detail != old_detail,
                })
                props = {}
                if new_detail != old_detail:
                    props["開催パターン詳細"] = rich_text_prop(new_detail)
                existing_date = current_date(event)
                if item.get("date") and not existing_date.get("start"):
                    props["開催日"] = date_prop(item["date"], item.get("date_end"))
                    props["状態"] = select_prop(event_status(item["date"]))
                    result["changed"] = True
                    result["date_updated"] = True
                if item.get("primary_url"):
                    props["情報源URL"] = {"url": item.get("source_url") or item["primary_url"]}
                if apply and props:
                    api.update_page(event["id"], props)
            results.append(result)
            continue

        venue, matched_venue_name = find_venue(api, item)
        event = find_event(api, item["event_name"])
        event_changed = False
        if event:
            old_detail = current_detail(event)
            video_urls = [video.get("video_url") or "" for video in videos_for(row) if video.get("video_url")]
            all_duplicate = bool(video_urls) and all(url in old_detail for url in video_urls)
            new_detail = old_detail if all_duplicate else merged_detail(old_detail, note)
            event_changed = new_detail != old_detail
            if apply and event_changed:
                api.update_page(event["id"], {"開催パターン詳細": rich_text_prop(new_detail)})
        result.update({
            "venue_exists": bool(venue),
            "venue_matched_name": matched_venue_name,
            "event_exists": bool(event),
            "changed": not bool(event) or event_changed,
        })
        if apply and not venue:
            venue = create_venue(api, item)
            result["venue_created"] = True
        if venue:
            result["venue_page_id"] = venue.get("id") or ""
        if apply and venue and not event:
            event = create_event(api, venue["id"], item, note)
            result["event_created"] = True
        if event:
            result["event_page_id"] = event.get("id") or ""
        results.append(result)
    return results


def md_escape(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(output):
    lines = [
        "# YouTube 2025 curated公式候補 apply結果",
        "",
        f"- 生成: {output['generated_at']}",
        f"- mode: {output['mode']}",
        f"- changed: {output['changed_count']}",
        f"- event_created: {output['event_created_count']}",
        f"- venue_created: {output['venue_created_count']}",
        "",
        "| decision | event | videos | changed | event_created | venue_created | reason |",
        "| --- | --- | ---: | --- | --- | --- | --- |",
    ]
    for row in output["rows"]:
        lines.append(
            f"| {md_escape(row['decision'])} | {md_escape(row['event_name'])} | "
            f"{row['video_count']} | {'yes' if row['changed'] else 'no'} | "
            f"{'yes' if row.get('event_created') else 'no'} | {'yes' if row.get('venue_created') else 'no'} | "
            f"{md_escape(row['reason'])} |"
        )
    for row in output["rows"]:
        lines.extend(["", f"## {row['event_name']}", "", "```text", row["note"], "```"])
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--validation", type=Path, default=VALIDATION)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--markdown-out", type=Path, default=MD_OUT)
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        require_confirmation(
            args.apply,
            args.confirm,
            LEGACY_YOUTUBE_NOTION_CONFIRMATION,
            "legacy YouTube 2025 curated official Notion update",
        )
    except ValueError as exc:
        parser.error(str(exc))

    load_local_env()
    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    validation = load_json(args.validation, {})
    results = build_results(api, validation, apply=args.apply, only=args.only)
    output = {
        "generated_by": "apply_youtube_2025_curated_official_candidates.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if args.apply else "dry_run",
        "apply_performed": bool(args.apply),
        "changed_count": sum(1 for row in results if row.get("changed")),
        "event_created_count": sum(1 for row in results if row.get("event_created")),
        "venue_created_count": sum(1 for row in results if row.get("venue_created")),
        "rows": results,
    }
    atomic_write_json(args.out, output)
    atomic_write_text(args.markdown_out, render_markdown(output))
    print(
        "youtube 2025 curated official candidates: "
        f"mode={output['mode']} changed={output['changed_count']} "
        f"events_created={output['event_created_count']} venues_created={output['venue_created_count']} -> {args.out}"
    )


if __name__ == "__main__":
    main()
