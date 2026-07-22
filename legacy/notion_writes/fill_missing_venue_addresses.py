import argparse
import json
import os

from manual_apply_guards import LEGACY_NOTION_REPAIR_CONFIRMATION, require_confirmation
from notion_support.notion_api import NotionApi, plain_text
from notion_support.notion_config import VENUE_DATA_SOURCE_ID


UPDATES = {
    "築地本願寺": {
        "address": "東京都中央区築地3-15-1",
        "access": (
            "東京メトロ日比谷線 築地駅 出口1直結。"
            "東京メトロ有楽町線 新富町駅 出口4から徒歩約5分。"
            "都営浅草線 東銀座駅 出口5、都営大江戸線 築地市場駅 A1出口から各徒歩約5分"
        ),
        "source_url": "https://tsukijihongwanji.jp/access/",
        "source_note": "住所・アクセス出典: 築地本願寺公式アクセス",
    },
    "晴海ふ頭公園": {
        "address": "東京都中央区晴海五丁目",
        "access": (
            "都営大江戸線 勝どき駅から徒歩25分。"
            "都営バス 晴海埠頭下車 徒歩2分"
        ),
        "source_url": "https://www.tptc.co.jp/park/02_01",
        "source_note": "住所・アクセス出典: 海上公園なび 晴海ふ頭公園",
    },
    "宮下公園": {
        "address": "東京都渋谷区神宮前6-20-10",
        "access": (
            "渋谷駅から徒歩約3分。"
            "東京メトロ千代田線・副都心線 明治神宮前〈原宿〉駅 7番口から徒歩約8分。"
            "都営バス 宮下公園、ハチ公バス 宮下公園前から徒歩1分"
        ),
        "source_url": "https://www.miyashita-park.tokyo/access/",
        "source_note": "住所・アクセス出典: MIYASHITA PARK公式アクセス",
    },
}


def text_prop(text):
    return {"rich_text": [{"text": {"content": text}}]} if text else {"rich_text": []}


def find_venue(api, name):
    rows = api.query_data_source(
        VENUE_DATA_SOURCE_ID,
        {
            "filter": {"property": "会場名", "title": {"equals": name}},
            "page_size": 5,
        },
    )
    if not rows:
        raise ValueError(f"venue not found: {name}")
    if len(rows) > 1:
        raise ValueError(f"multiple venues found: {name}")
    return rows[0]


def append_source_note(memo, note):
    if not note or note in memo:
        return memo
    return f"{memo}\n{note}" if memo else note


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        require_confirmation(
            True,
            args.confirm,
            LEGACY_NOTION_REPAIR_CONFIRMATION,
            "legacy venue address repair",
        )
    except ValueError as exc:
        parser.error(str(exc))

    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    results = []
    for name, update in UPDATES.items():
        row = find_venue(api, name)
        props = row.get("properties", {})
        memo = plain_text(props.get("過去メモ"))
        next_memo = append_source_note(memo, update["source_note"])
        properties = {
            "住所": text_prop(update["address"]),
            "アクセス": text_prop(update["access"]),
            "出典URL": {"url": update["source_url"]},
            "過去メモ": text_prop(next_memo),
            "要レビュー": {"checkbox": False},
        }
        api.update_page(row["id"], properties)
        results.append(
            {
                "venue": name,
                "id": row["id"],
                "address": update["address"],
                "access": update["access"],
                "source_url": update["source_url"],
            }
        )
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
