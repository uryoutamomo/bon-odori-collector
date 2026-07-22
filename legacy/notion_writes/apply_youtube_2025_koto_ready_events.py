#!/usr/bin/env python3
"""Apply Koto-reviewed YouTube 2025 event candidates to Notion."""

import argparse
import json
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from notion_support.notion_api import NotionApi, plain_text
from operation_safety.manual_apply_guards import LEGACY_YOUTUBE_NOTION_CONFIRMATION, require_confirmation
from notion_support.notion_config import EVENT_DATA_SOURCE_ID, VENUE_DATA_SOURCE_ID, load_local_env


OUT = Path("data/youtube_2025_koto_ready_apply_result.json")
MD_OUT = Path("data/youtube_2025_koto_ready_apply_result.md")
TODAY = date(2026, 6, 16)


ITEMS = [
    {
        "event_name": "第15回 鴨台盆踊り",
        "venue_name": "大正大学",
        "venue_aliases": ["大正大学巣鴨キャンパス"],
        "area": "豊島区",
        "address": "東京都豊島区西巣鴨3-20-1",
        "access": "都営三田線西巣鴨駅から徒歩圏内",
        "scale": "大",
        "date": "2025-07-04",
        "date_end": "2025-07-05",
        "month": "7月",
        "source_url": "https://www.tais.ac.jp/guide/latest_news/20250627/92922/",
        "secondary_url": "https://prtimes.jp/main/html/rd/p/000000346.000054969.html",
        "reason": "こと裏取りで大正大学公式とPR TIMESを確認。第15回、2025-07-04〜2025-07-05、大正大学開催。",
    },
    {
        "event_name": "第51回 神楽坂まつり 盆踊り",
        "venue_name": "りそな銀行神楽坂支店前",
        "venue_aliases": ["神楽坂通り", "神楽坂まつり盆踊り会場"],
        "area": "新宿区",
        "address": "東京都新宿区神楽坂6丁目付近",
        "access": "東京メトロ神楽坂駅・飯田橋駅から徒歩圏内",
        "scale": "大",
        "date": "2025-07-23",
        "date_end": "2025-07-24",
        "month": "7月",
        "source_url": "https://www.kagurazaka.in/event/%E7%AC%AC51%E5%9B%9E%E7%A5%9E%E6%A5%BD%E5%9D%82%E3%81%BE%E3%81%A4%E3%82%8A/",
        "secondary_url": "https://www.kanko-shinjuku.jp/event/history/article_4567.html",
        "reason": "こと裏取りで神楽坂通り商店会公式と新宿観光振興協会を確認。2025-07-23〜2025-07-24、18:00〜20:30。",
    },
    {
        "event_name": "花園神社 盆踊り",
        "venue_name": "花園神社",
        "venue_aliases": ["新宿花園神社"],
        "area": "新宿区",
        "address": "東京都新宿区新宿5-17-3",
        "access": "新宿三丁目駅から徒歩圏内",
        "scale": "中",
        "date": "2025-08-01",
        "date_end": "2025-08-02",
        "month": "8月",
        "source_url": "https://yokoso-shinjuku.com/shinjuku-event/hanazono-bonodori-2/",
        "secondary_url": "",
        "reason": "こと裏取りで2025-08-01〜2025-08-02、19:00〜21:00の開催情報を確認。",
    },
    {
        "event_name": "第70回 恵比寿駅前盆踊り大会",
        "venue_name": "JR恵比寿駅西口広場",
        "venue_aliases": ["恵比寿駅前西口ロータリー", "恵比寿駅西口広場", "アトレ恵比寿前"],
        "area": "渋谷区",
        "address": "東京都渋谷区恵比寿南1丁目付近",
        "access": "JR恵比寿駅西口すぐ",
        "scale": "大",
        "date": "2025-07-25",
        "date_end": "2025-07-26",
        "month": "7月",
        "source_url": "https://ebisubondance.jp/about/",
        "secondary_url": "",
        "reason": "こと裏取りで公式サイトを確認。第70回、2025-07-25〜2025-07-26、17:30〜21:30。",
    },
    {
        "event_name": "赤坂浄土寺盆踊り大会",
        "venue_name": "浄土寺",
        "venue_aliases": ["赤坂浄土寺"],
        "area": "港区",
        "address": "東京都港区赤坂4-3-5",
        "access": "赤坂見附駅・赤坂駅から徒歩圏内",
        "scale": "中",
        "date": "2025-07-24",
        "date_end": "2025-07-25",
        "month": "7月",
        "source_url": "https://x.com/nsPFhl5JW382058/status/1939266951391613148",
        "secondary_url": "https://kaginokanai.com/2025/07/10/akasaka-jodoji-bonnodori-202507/",
        "reason": "こと裏取りで赤坂あかね会Xと地域ブログを確認。2025-07-24〜2025-07-25、18:30〜22:00頃。",
    },
    {
        "event_name": "第11回 にっぽり炭坑節まつり",
        "venue_name": "JR日暮里駅前広場",
        "venue_aliases": ["日暮里駅前イベント広場", "日暮里駅前広場"],
        "area": "荒川区",
        "address": "東京都荒川区西日暮里2-6付近",
        "access": "JR日暮里駅前",
        "scale": "大",
        "date": "2025-09-14",
        "date_end": "2025-09-15",
        "month": "9月",
        "source_url": "https://www.city.arakawa.tokyo.jp/a022/event/eventkouenmeigi/nipporitannkoubushimaturir791415.html",
        "secondary_url": "https://bon-odori.net/nippori-tankoubushi2025/",
        "reason": "こと裏取りで荒川区公式と日本盆踊り協会サイトを確認。第11回、2025-09-14〜2025-09-15。",
    },
]


def text_prop(text):
    if not text:
        return {"rich_text": []}
    return {"rich_text": [{"text": {"content": text[:1900]}}]}


def rich_text_prop(text):
    if not text:
        return {"rich_text": []}
    chunks = [text[i:i + 1900] for i in range(0, len(text), 1900)]
    return {"rich_text": [{"text": {"content": chunk}} for chunk in chunks[:100]]}


def title_prop(text):
    return {"title": [{"text": {"content": text[:200]}}]} if text else {"title": []}


def select_prop(name):
    return {"select": {"name": name}} if name else {"select": None}


def date_prop(start, end=None):
    value = {"start": start}
    if end:
        value["end"] = end
    return {"date": value}


def event_status(date_value):
    y, m, d = [int(part) for part in date_value.split("-")]
    return "終了" if date(y, m, d) < TODAY else "確認済み"


def query_title(api, data_source_id, property_name, title):
    rows = api.query_data_source(
        data_source_id,
        {"filter": {"property": property_name, "title": {"equals": title}}, "page_size": 5},
    )
    return rows[0] if rows else None


def find_event(api, item):
    return query_title(api, EVENT_DATA_SOURCE_ID, "イベント名", item["event_name"])


def find_venue(api, item):
    for name in [item["venue_name"]] + item.get("venue_aliases", []):
        venue = query_title(api, VENUE_DATA_SOURCE_ID, "会場名", name)
        if venue:
            return venue, name
    return None, ""


def current_detail(page):
    return plain_text((page.get("properties") or {}).get("開催パターン詳細"))


def evidence_note(item):
    lines = [
        "[youtube_evidence] こと（Claude Code）2025裏取り反映",
        f"- 対象イベント: {item['event_name']}",
        f"- 開催日: {item['date']}" + (f"〜{item['date_end']}" if item.get("date_end") else ""),
        f"- 会場: {item['venue_name']}",
        f"- 根拠URL: {item['source_url']}",
        f"- 判断: {item['reason']}",
    ]
    if item.get("secondary_url"):
        lines.append(f"- 補助URL: {item['secondary_url']}")
    return "\n".join(lines)


def merged_detail(existing, note):
    if note in (existing or ""):
        return existing or ""
    return ((existing or "").rstrip() + "\n\n" + note).strip()


def venue_props(item):
    return {
        "会場名": title_prop(item["venue_name"]),
        "所在区・市": text_prop(item["area"]),
        "住所": text_prop(item["address"]),
        "アクセス": text_prop(item["access"]),
        "出典URL": {"url": item["source_url"]},
        "過去メモ": text_prop(item["reason"]),
        "規模": select_prop(item["scale"]),
        "築地30分圏内": {"checkbox": True},
        "要レビュー": {"checkbox": False},
    }


def event_props(item, venue_id, note):
    return {
        "イベント名": title_prop(item["event_name"]),
        "会場": {"relation": [{"id": venue_id}]},
        "開催日": date_prop(item["date"], item.get("date_end")),
        "状態": select_prop(event_status(item["date"])),
        "情報源URL": {"url": item["source_url"]},
        "例年開催月": text_prop(item["month"]),
        "開催パターン種別": select_prop("不明"),
        "開催パターン詳細": rich_text_prop(note),
    }


def create_venue(api, item):
    return api.request("POST", "/pages", {"parent": {"data_source_id": VENUE_DATA_SOURCE_ID}, "properties": venue_props(item)})


def create_event(api, item, venue_id, note):
    return api.request("POST", "/pages", {"parent": {"data_source_id": EVENT_DATA_SOURCE_ID}, "properties": event_props(item, venue_id, note)})


def build_results(api, apply=False):
    rows = []
    for item in ITEMS:
        note = evidence_note(item)
        venue, matched_name = find_venue(api, item)
        event = find_event(api, item)
        old_detail = current_detail(event) if event else ""
        new_detail = merged_detail(old_detail, note) if event else note
        row = {
            "event_name": item["event_name"],
            "venue_name": item["venue_name"],
            "date": item["date"],
            "date_end": item.get("date_end") or "",
            "source_url": item["source_url"],
            "venue_exists": bool(venue),
            "venue_matched_name": matched_name,
            "event_exists": bool(event),
            "changed": not bool(event) or new_detail != old_detail,
            "event_created": False,
            "venue_created": False,
            "note": note,
        }
        if apply and not venue:
            venue = create_venue(api, item)
            row["venue_created"] = True
        if venue:
            row["venue_page_id"] = venue.get("id") or ""
        if apply and venue and not event:
            event = create_event(api, item, venue["id"], note)
            row["event_created"] = True
        elif apply and event and new_detail != old_detail:
            api.update_page(event["id"], {"開催パターン詳細": rich_text_prop(new_detail)})
        if event:
            row["event_page_id"] = event.get("id") or ""
        rows.append(row)
    return rows


def atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=".tmp-", suffix=".json", delete=False) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        tmp_name = handle.name
    Path(tmp_name).replace(path)


def md_escape(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(output):
    lines = [
        "# YouTube 2025 こと裏取り ready反映",
        "",
        f"- 生成: {output['generated_at']}",
        f"- mode: {output['mode']}",
        f"- rows: {len(output['rows'])}",
        f"- changed: {output['changed_count']}",
        f"- event_created: {output['event_created_count']}",
        f"- venue_created: {output['venue_created_count']}",
        "",
        "| event | date | venue | changed | event_exists | event_created | venue_created | source |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in output["rows"]:
        date_text = row["date"] + (f"〜{row['date_end']}" if row.get("date_end") else "")
        lines.append(
            f"| {md_escape(row['event_name'])} | {md_escape(date_text)} | {md_escape(row['venue_name'])} | "
            f"{'yes' if row['changed'] else 'no'} | {'yes' if row['event_exists'] else 'no'} | "
            f"{'yes' if row['event_created'] else 'no'} | {'yes' if row['venue_created'] else 'no'} | {md_escape(row['source_url'])} |"
        )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--markdown-out", type=Path, default=MD_OUT)
    args = parser.parse_args()
    try:
        require_confirmation(
            args.apply,
            args.confirm,
            LEGACY_YOUTUBE_NOTION_CONFIRMATION,
            "legacy YouTube 2025 koto-ready Notion update",
        )
    except ValueError as exc:
        parser.error(str(exc))

    load_local_env()
    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    rows = build_results(api, apply=args.apply)
    output = {
        "generated_by": "apply_youtube_2025_koto_ready_events.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if args.apply else "dry_run",
        "apply_performed": bool(args.apply),
        "changed_count": sum(1 for row in rows if row["changed"]),
        "event_created_count": sum(1 for row in rows if row["event_created"]),
        "venue_created_count": sum(1 for row in rows if row["venue_created"]),
        "rows": rows,
    }
    atomic_write_json(args.out, output)
    args.markdown_out.write_text(render_markdown(output), encoding="utf-8")
    print(
        "youtube 2025 koto ready events: "
        f"mode={output['mode']} changed={output['changed_count']} "
        f"events_created={output['event_created_count']} venues_created={output['venue_created_count']} -> {args.out}"
    )


if __name__ == "__main__":
    main()
