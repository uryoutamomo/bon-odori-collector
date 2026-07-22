#!/usr/bin/env python3
"""Create reviewed YouTube blocked events once non-YouTube evidence exists."""

import argparse
import json
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from manual_apply_guards import LEGACY_YOUTUBE_NOTION_CONFIRMATION, require_confirmation
from notion_support.notion_api import NotionApi
from operation_safety.manual_apply_guards import LEGACY_YOUTUBE_NOTION_CONFIRMATION, require_confirmation
from notion_api import NotionApi
from notion_config import EVENT_DATA_SOURCE_ID, VENUE_DATA_SOURCE_ID, load_local_env


OUT = Path("data/youtube_blocked_new_event_apply_result.json")
OUT_MD = Path("data/youtube_blocked_new_event_apply_result.md")
TODAY = date(2026, 6, 15)

ITEMS = [
    {
        "candidate_key": "yt-blocked:kunitachi-june-festa-2026-06-07",
        "review_decision": "register_with_blog_and_youtube_evidence",
        "venue_name": "国立旭通り 弥生ビル東側",
        "aliases": ["国立旭通り", "旭通り商店会", "国立市旭通り商店会"],
        "region": "国立市",
        "address": "東京都国立市東1-7-5付近",
        "access": "JR国立駅南口から徒歩圏内。旭通り商店会エリア",
        "source_url": "https://ahirunoie.shop-pro.jp/apps/note/%E5%9B%BD%E7%AB%8B%E6%97%AD%E9%80%9A%E3%82%8A%E3%82%B8%E3%83%A5%E3%83%BC%E3%83%B3%E3%83%95%E3%82%A7%E3%82%B9%E3%82%BF2026/",
        "memo": (
            "YouTube active既存イベント追記dry-runでblockedになった候補。"
            "ブログ抽出 data/blog_venue_rows.json では、国立旭通り商店会「ジューンフェスタ2026」"
            "6月7日(日)、盆踊り13:00-15:00、会場は国立旭通り 弥生ビル東側。"
            "あひるの家ブログでも2026年6月7日開催と盆踊り企画を確認。"
        ),
        "scale": "中",
        "in_tsukiji": False,
        "needs_review": False,
        "event": {
            "name": "ジューンフェスタ2026 盆踊り（国立市旭通り商店会）",
            "aliases": ["国立旭通りジューンフェスタ盆踊り", "国立ジューンフェスタ盆踊り"],
            "date": "2026-06-07",
            "source_url": "https://ahirunoie.shop-pro.jp/apps/note/%E5%9B%BD%E7%AB%8B%E6%97%AD%E9%80%9A%E3%82%8A%E3%82%B8%E3%83%A5%E3%83%BC%E3%83%B3%E3%83%95%E3%82%A7%E3%82%B9%E3%82%BF2026/",
            "month": "6月",
            "pattern_detail": (
                "2026-06-07 13:00-15:00、国立旭通り商店会「ジューンフェスタ2026」内の盆踊り。"
                "イベント全体は11:00-15:30。ブログ抽出では会場を国立旭通り 弥生ビル東側として確認。"
                "\n\n[youtube_evidence] YouTube実績証拠"
                "\n- 対象イベント: 国立旭通りジューンフェスタ盆踊り"
                "\n- 検出日付: 2026-06-07"
                "\n- 動画数: 6"
                "\n- チャンネル: 和太鼓お祭りCH"
                "\n- 代表動画: https://www.youtube.com/watch?v=KvBfA5BHX8U / 炭坑節"
                "\n- 代表動画: https://www.youtube.com/watch?v=O3YCMn5xfv4 / 国立音頭"
                "\n- 代表動画: https://www.youtube.com/watch?v=WjBGN8Kr4ok / 少年八木節"
                "\n- 曲目候補: 炭坑節, 国立音頭, くにたち囃子, 四季の花踊り, 新しい風, 少年八木節, さくら音頭, 東京音頭, 恋をするなら, らんまん踊り, バハマママ, TOKIO"
            ),
        },
    }
]


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
    chunks = [text[i:i + 1900] for i in range(0, len(text), 1900)]
    return {"rich_text": [{"text": {"content": chunk}} for chunk in chunks[:100]]}


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
    for name in [item["venue_name"]] + item.get("aliases", []):
        venue = query_title(api, VENUE_DATA_SOURCE_ID, "会場名", name)
        if venue:
            return venue, name
    return None, ""


def find_event(api, item):
    names = [item["event"]["name"]] + item["event"].get("aliases", [])
    for name in names:
        event = query_title(api, EVENT_DATA_SOURCE_ID, "イベント名", name)
        if event:
            return event, name
    return None, ""


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
        "開催日": date_prop(event["date"]),
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
    rows = []
    for item in ITEMS:
        venue, venue_matched_name = find_venue(api, item)
        event, event_matched_name = find_event(api, item)
        result = {
            "candidate_key": item["candidate_key"],
            "review_decision": item["review_decision"],
            "venue": item["venue_name"],
            "venue_exists": bool(venue),
            "venue_matched_name": venue_matched_name,
            "venue_created": False,
            "event": item["event"]["name"],
            "event_exists": bool(event),
            "event_matched_name": event_matched_name,
            "event_created": False,
            "event_date": item["event"]["date"],
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
        rows.append(result)
    return rows


def render_markdown(output):
    lines = [
        "# YouTube blocked新規イベント apply結果",
        "",
        f"- 生成: {output['generated_at']}",
        f"- mode: {output['mode']}",
        f"- venues created: {output['venue_created_count']}",
        f"- events created: {output['event_created_count']}",
        "",
        "| event | venue | venue_exists | event_exists | venue_created | event_created |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in output["rows"]:
        lines.append(
            f"| {row['event']} | {row['venue']} | {row['venue_exists']} | {row['event_exists']} | "
            f"{row['venue_created']} | {row['event_created']} |"
        )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--markdown-out", type=Path, default=OUT_MD)
    args = parser.parse_args()
    try:
        require_confirmation(
            args.apply,
            args.confirm,
            LEGACY_YOUTUBE_NOTION_CONFIRMATION,
            "legacy YouTube blocked-new-event Notion update",
        )
    except ValueError as exc:
        parser.error(str(exc))

    load_local_env()
    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    rows = build_results(api, apply=args.apply)
    output = {
        "generated_by": "apply_youtube_blocked_new_events.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if args.apply else "dry_run",
        "apply_performed": bool(args.apply),
        "input_count": len(rows),
        "venue_created_count": sum(1 for row in rows if row["venue_created"]),
        "event_created_count": sum(1 for row in rows if row["event_created"]),
        "rows": rows,
    }
    atomic_write_json(args.out, output)
    atomic_write_text(args.markdown_out, render_markdown(output))
    print(
        "youtube blocked new events: "
        f"mode={output['mode']} venues={output['venue_created_count']} "
        f"events={output['event_created_count']} -> {args.out}"
    )


if __name__ == "__main__":
    main()
