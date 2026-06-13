#!/usr/bin/env python3
"""Fill missing public intro text for the Yoimatsuri public site.

The Notion property `公開紹介文` is the canonical source for card descriptions.
This script only fills empty values for public Tokyo-23-ward venues/events.
"""

import argparse
import os
import re

from notion_api import NotionApi, plain_text
import notion_config
from export_public_venues import (
    clean_public_text,
    normalize_ward,
    _prop,
    _query_all,
)


SPACES_RE = re.compile(r"\s+")
DATE_TAIL_RE = re.compile(
    r"(?:\s|　)*(?:\d{1,2}月\d{1,2}日|\d{1,2}/\d{1,2}|"
    r"\d{1,2}月[上中下]旬|\d{1,2}月|\d{1,2}日\(|"
    r"\d{1,2}:\d{2}|午後\d{1,2}時|午前\d{1,2}時).*$"
)


def rich_text(value):
    return {"rich_text": [{"type": "text", "text": {"content": value}}]}


def compact(value):
    value = clean_public_text(value or "")
    value = value.replace("\n", " ").replace("　", " ")
    value = SPACES_RE.sub(" ", value).strip()
    return value


def short_name(name):
    name = compact(name)
    name = DATE_TAIL_RE.sub("", name)
    name = name.replace("「", " ").replace("」", " ")
    name = name.replace("『", " ").replace("』", " ")
    name = SPACES_RE.sub(" ", name)
    name = name.strip(" -ｰ〜～、。")
    return name or compact(name)


def public_access(access):
    access = compact(access)
    if not access:
        return ""
    if "出典URL" in access or re.fullmatch(r".+区内。?", access):
        return ""
    return access.rstrip("。")


def month_label(date_value, month_text):
    if date_value:
        month = int(date_value[5:7])
        return f"{month}月"
    month_text = compact(month_text)
    match = re.search(r"(\d{1,2})月", month_text)
    if match:
        return f"{int(match.group(1))}月"
    return ""


def event_intro(name, venue, area, date_value, month_text, detail):
    name = compact(name)
    display = short_name(name)
    venue = compact(venue)
    area = compact(area)
    month = month_label(date_value, month_text)
    detail = compact(detail)

    if name.startswith("イベント名未確認"):
        prefix = f"{venue}で行われる地域の盆踊り。"
    elif "例大祭" in name or "奉納" in name or "神社" in venue or "寺" in venue:
        prefix = f"{display}は、{venue}を舞台にした祭礼・地域行事にあわせた踊りの場。"
    elif "商店街" in name or "駅前" in venue or "ロータリー" in venue:
        prefix = f"{display}は、{venue}周辺で開かれる街なかの踊りイベント。"
    elif "公園" in venue or "広場" in venue:
        prefix = f"{display}は、{venue}で開かれる屋外型の盆踊り・夏の地域イベント。"
    elif "小学校" in venue or "学校" in venue:
        prefix = f"{display}は、{venue}を会場にした地域密着の盆踊り・夏祭り。"
    elif "盆踊り" in name or "盆おどり" in name or "盆踊" in name:
        prefix = f"{display}は、{area}の{venue}で行われる盆踊り。"
    elif "輪おどり" in name or "輪踊り" in name or "民踊" in name or "民謡" in name:
        prefix = f"{display}は、{area}で民踊や輪踊りを楽しめる地域イベント。"
    else:
        prefix = f"{display}は、{area}の{venue}で行われる踊りのある地域イベント。"

    if month:
        suffix = f"{month}開催の情報をもとに、公開サイト用に掲載しています。"
    elif detail:
        suffix = "開催実績や公開情報をもとに、公開サイト用に掲載しています。"
    else:
        suffix = "詳しい開催日は確認中ですが、会場情報をもとに掲載しています。"

    return (prefix + suffix)[:450]


def venue_intro(name, area, access, address, scale):
    name = compact(name)
    area = compact(area)
    access = compact(access)
    address = compact(address)
    scale = compact(scale)

    if "神社" in name or "寺" in name:
        prefix = f"{name}は、{area}にある祭礼や地域行事の拠点。"
    elif "公園" in name or "広場" in name:
        prefix = f"{name}は、{area}の屋外で踊りの輪を作りやすい会場。"
    elif "小学校" in name or "学校" in name:
        prefix = f"{name}は、地域の夏祭りや盆踊りで使われる{area}の学校会場。"
    elif "商店街" in name or "駅" in name:
        prefix = f"{name}は、駅前や商店街のにぎわいと一緒に楽しめる{area}の会場。"
    else:
        prefix = f"{name}は、{area}で盆踊りや地域イベントの会場として使われる場所。"

    details = []
    if scale in {"大", "中", "小"}:
        details.append(f"規模は「{scale}」として整理しています")
    access = public_access(access)
    if access:
        details.append(f"アクセスは{access}")
    elif address:
        details.append(f"所在地は{address}")
    if details:
        return (prefix + " " + "、".join(details) + "。")[:450]
    return prefix[:450]


def load_public_venues():
    venues = {}
    for row in _query_all(notion_config.VENUE_DATA_SOURCE_ID):
        props = row.get("properties", {})
        name = _prop(props, "会場名")
        area = normalize_ward(_prop(props, "所在区・市"))
        if not name or not area:
            continue
        venues[row["id"]] = {
            "id": row["id"],
            "name": name,
            "area": area,
            "access": _prop(props, "アクセス"),
            "address": _prop(props, "住所"),
            "scale": _prop(props, "規模"),
            "intro": plain_text(props.get("公開紹介文")),
        }
    return venues


def event_rows(venues):
    for row in _query_all(notion_config.EVENT_DATA_SOURCE_ID):
        props = row.get("properties", {})
        name = _prop(props, "イベント名")
        venue_ids = [vid for vid in (_prop(props, "会場") or []) if vid in venues]
        if not name or not venue_ids:
            continue
        intro = plain_text(props.get("公開紹介文"))
        date = (props.get("開催日", {}).get("date") or {}).get("start")
        for venue_id in venue_ids:
            yield row, props, venues[venue_id], intro, date


def build_updates(kind):
    venues = load_public_venues()
    updates = []

    if kind in {"venues", "all"}:
        for venue in venues.values():
            if venue["intro"]:
                continue
            updates.append({
                "kind": "venue",
                "page_id": venue["id"],
                "name": venue["name"],
                "intro": venue_intro(
                    venue["name"],
                    venue["area"],
                    venue["access"],
                    venue["address"],
                    venue["scale"],
                ),
            })

    if kind in {"events", "all"}:
        seen = set()
        for row, props, venue, intro, date in event_rows(venues):
            if intro or row["id"] in seen:
                continue
            seen.add(row["id"])
            updates.append({
                "kind": "event",
                "page_id": row["id"],
                "name": _prop(props, "イベント名"),
                "intro": event_intro(
                    _prop(props, "イベント名"),
                    venue["name"],
                    venue["area"],
                    date,
                    _prop(props, "例年開催月"),
                    _prop(props, "開催パターン詳細"),
                ),
            })

    return updates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=("events", "venues", "all"), default="all")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    updates = build_updates(args.kind)
    if args.limit:
        updates = updates[:args.limit]

    print(f"public intro updates: {len(updates)} apply={args.apply}")
    for update in updates[:20]:
        print(f"- {update['kind']}: {update['name']} -> {update['intro']}")
    if len(updates) > 20:
        print(f"... and {len(updates) - 20} more")

    if not args.apply or not updates:
        return

    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    for index, update in enumerate(updates, 1):
        api.update_page(update["page_id"], {"公開紹介文": rich_text(update["intro"])})
        print(f"[{index}/{len(updates)}] updated {update['kind']}: {update['name']}")


if __name__ == "__main__":
    main()
