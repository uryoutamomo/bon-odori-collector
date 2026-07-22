import argparse
import json
import os

from manual_apply_guards import LEGACY_NOTION_REPAIR_CONFIRMATION, require_confirmation
from notion_support.notion_api import NotionApi, plain_text
from notion_support.notion_config import VENUE_DATA_SOURCE_ID


UPDATES = {
    "山王パークタワー公開空地": {
        "access": "東京メトロ銀座線・南北線 溜池山王駅 7番出口直結。東京メトロ丸ノ内線・千代田線 国会議事堂前駅から地下通路で接続",
        "scale": "中",
        "note": "アクセス・規模補完: 溜池山王駅/国会議事堂前駅直結の公開空地で、山王祭関連の民踊大会会場のため中規模扱い。",
    },
    "秩父宮ラグビー場駐車場": {
        "access": "東京メトロ銀座線 外苑前駅 3番出口から徒歩約5分。都営大江戸線 国立競技場駅、JR千駄ケ谷駅・信濃町駅から徒歩約15分",
    },
    "網代公園": {
        "address": "東京都港区麻布十番2-15-1",
        "access": "東京メトロ南北線・都営大江戸線 麻布十番駅から徒歩約3分",
    },
    "新宿住友ビル三角広場": {
        "access": "都営大江戸線 都庁前駅 A6出口直結。東京メトロ丸ノ内線 西新宿駅 2番出口から徒歩4分。JR・小田急線・京王線 新宿駅西口から徒歩8分",
    },
    "田原小学校": {
        "access": "東京メトロ銀座線 田原町駅から徒歩約3分。都営浅草線 浅草駅から徒歩約8分",
        "scale": "中",
        "note": "アクセス・規模補完: 小学校校庭を使う地域行事のため中規模扱い。",
    },
    "小梅児童遊園": {
        "access": "東武スカイツリーライン とうきょうスカイツリー駅から徒歩約4分。都営浅草線 本所吾妻橋駅から徒歩約5分",
    },
    "横川小学校": {
        "access": "都営浅草線 本所吾妻橋駅から徒歩約8分。東武スカイツリーライン とうきょうスカイツリー駅から徒歩約10分",
        "scale": "中",
        "note": "アクセス・規模補完: 小学校会場の地域盆踊りとして中規模扱い。",
    },
    "平塚中央公園": {
        "access": "東急池上線 戸越銀座駅から徒歩約6分。都営浅草線 戸越駅から徒歩約8分",
    },
    "旧杜松小学校": {
        "access": "東急大井町線 戸越公園駅から徒歩約5分。都営浅草線 中延駅から徒歩約8分",
    },
    "東品川海上公園": {
        "access": "りんかい線・東京モノレール 天王洲アイル駅から徒歩約5分。京急本線 新馬場駅から徒歩約15分",
    },
    "第一日野小学校": {
        "address": "東京都品川区西五反田6-5-32",
        "access": "東急目黒線 不動前駅から徒歩約7分。JR五反田駅から徒歩約15分",
    },
    "第二延山小学校": {
        "access": "東急池上線 荏原中延駅から徒歩約6分。東急大井町線・池上線 旗の台駅から徒歩約8分",
    },
    "第四日野小学校": {
        "address": "東京都品川区西五反田4-29-9",
        "access": "東急目黒線 不動前駅から徒歩約4分。JR目黒駅から徒歩約15分",
    },
    "五反野コミュニティ公園": {
        "access": "東武スカイツリーライン 五反野駅から徒歩約7分。東武スカイツリーライン 小菅駅から徒歩約10分",
    },
    "靖国神社": {
        "scale": "大",
        "note": "規模補完: みたままつり等の大規模催事会場のため大規模扱い。",
    },
    "日本橋小学校": {
        "scale": "小",
        "note": "規模補完: 小学校会場かつ単独開催証拠は未確認のため小規模扱い。",
    },
    "六本木天祖神社": {
        "scale": "中",
        "note": "規模補完: 六本木地区の神社例大祭・地域盆踊り会場のため中規模扱い。",
    },
    "赤坂氷川神社": {
        "scale": "中",
        "note": "規模補完: 赤坂地区の神社例大祭・地域盆踊り会場のため中規模扱い。",
    },
    "麻布氷川神社": {
        "scale": "中",
        "note": "規模補完: 麻布地区の神社例大祭・地域盆踊り会場のため中規模扱い。",
    },
    "隅田公園": {
        "scale": "大",
        "note": "規模補完: 隅田川沿いの広域公園・大型催事会場のため大規模扱い。",
    },
    "すみだ公園（隅田公園・墨田区側）": {
        "scale": "大",
        "note": "規模補完: 隅田川沿いの広域公園・大型催事会場のため大規模扱い。",
    },
    "牛嶋神社": {
        "scale": "中",
        "note": "規模補完: 墨田区の神社例大祭・地域奉納踊り会場のため中規模扱い。",
    },
    "江東天祖神社（亀戸天祖神社）": {
        "scale": "中",
        "note": "規模補完: 亀戸地区の神社例大祭・地域盆踊り会場のため中規模扱い。",
    },
    "大井蔵王権現神社": {
        "scale": "小",
        "note": "規模補完: 町会・神社境内中心の地域行事として小規模扱い。",
    },
    "戸越八幡神社": {
        "scale": "中",
        "note": "規模補完: 戸越地区の神社例大祭・奉納盆踊り会場のため中規模扱い。",
    },
    "旗岡八幡神社": {
        "scale": "中",
        "note": "規模補完: 旗の台地区の神社例大祭・地域盆踊り会場のため中規模扱い。",
    },
}


def text_prop(text):
    return {"rich_text": [{"text": {"content": text}}]} if text else {"rich_text": []}


def select_prop(name):
    return {"select": {"name": name}}


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


def append_note(memo, note):
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
            "legacy venue access/scale repair",
        )
    except ValueError as exc:
        parser.error(str(exc))

    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    results = []
    for name, update in UPDATES.items():
        row = find_venue(api, name)
        props = row.get("properties", {})
        memo = plain_text(props.get("過去メモ"))
        properties = {"要レビュー": {"checkbox": False}}
        if "address" in update:
            properties["住所"] = text_prop(update["address"])
        if "access" in update:
            properties["アクセス"] = text_prop(update["access"])
        if "scale" in update:
            properties["規模"] = select_prop(update["scale"])
        next_memo = append_note(memo, update.get("note"))
        if next_memo != memo:
            properties["過去メモ"] = text_prop(next_memo)
        api.update_page(row["id"], properties)
        results.append({"venue": name, "updates": sorted(properties)})
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
