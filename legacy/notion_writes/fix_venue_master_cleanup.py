import argparse
import json
import os

from notion_support.notion_api import NotionApi, plain_text
from operation_safety.manual_apply_guards import LEGACY_NOTION_REPAIR_CONFIRMATION, require_confirmation
from notion_config import EVENT_DATA_SOURCE_ID, VENUE_DATA_SOURCE_ID


OLD_SAKAMOTO_ID = "3718be04-e762-8194-9bfb-dabd7fc79f20"
KEEP_SAKAMOTO_ID = "37b8be04-e762-8151-a094-f54ad28b462d"

TEXT_REPLACEMENTS = {
    "海岹": "海岸",
    "大瀬橋線": "大江戸線",
    "辰巯": "辰巳",
    "児童遷園": "児童遊園",
    "隔田公園": "隅田公園",
    "隊田川": "隅田川",
    "牛嵌神社": "牛嶋神社",
    "三田納涵カーニバル": "三田納涼カーニバル",
}


def text_prop(text):
    return {"rich_text": [{"text": {"content": text}}]} if text else {"rich_text": []}


def replace_text(value):
    if not value:
        return value
    for before, after in TEXT_REPLACEMENTS.items():
        value = value.replace(before, after)
    return value


def replace_relation_ids(relations, old_id, keep_id):
    changed = False
    next_ids = []
    seen = set()
    for relation in relations:
        relation_id = relation["id"]
        if relation_id == old_id:
            relation_id = keep_id
            changed = True
        if relation_id not in seen:
            next_ids.append({"id": relation_id})
            seen.add(relation_id)
    return changed, next_ids


def merge_sakamoto(api):
    keep = api.retrieve_page(KEEP_SAKAMOTO_ID)
    old = api.retrieve_page(OLD_SAKAMOTO_ID)
    keep_props = keep.get("properties", {})
    old_props = old.get("properties", {})

    keep_memo = plain_text(keep_props.get("過去メモ"))
    old_memo = plain_text(old_props.get("過去メモ"))
    merged_memo = keep_memo
    if old_memo and old_memo not in keep_memo:
        merged_memo = (
            f"{keep_memo}\n"
            "【統合メモ】旧坂本小学校ページから統合: "
            f"{old_memo}"
        )

    updates = {"過去メモ": text_prop(merged_memo)}
    keep_access = plain_text(keep_props.get("アクセス"))
    old_access = plain_text(old_props.get("アクセス"))
    if keep_access == "入谷駅・鶯谷駅から徒歩圏内" and old_access:
        updates["アクセス"] = text_prop(old_access)
    api.update_page(KEEP_SAKAMOTO_ID, updates)

    changed_events = []
    for event in api.query_data_source(EVENT_DATA_SOURCE_ID):
        relations = event["properties"].get("会場", {}).get("relation", [])
        changed, next_relations = replace_relation_ids(
            relations, OLD_SAKAMOTO_ID, KEEP_SAKAMOTO_ID
        )
        if changed:
            api.update_page(event["id"], {"会場": {"relation": next_relations}})
            changed_events.append(event["id"])

    api.request("PATCH", f"/pages/{OLD_SAKAMOTO_ID}", {"archived": True})
    return {
        "type": "merged_duplicate",
        "name": "旧坂本小学校 -> さかもと朝顔広場（旧坂本小学校跡地）",
        "changed_event_ids": changed_events,
    }


def clean_venue_text(api):
    changed = []
    for row in api.query_data_source(VENUE_DATA_SOURCE_ID):
        props = row.get("properties", {})
        updates = {}
        for prop_name in ("住所", "アクセス", "過去メモ"):
            before = plain_text(props.get(prop_name))
            after = replace_text(before)
            if after != before:
                updates[prop_name] = text_prop(after)
        if updates:
            api.update_page(row["id"], updates)
            changed.append(
                {
                    "id": row["id"],
                    "name": plain_text(props.get("会場名")),
                    "updates": list(updates),
                }
            )
    return {"type": "cleaned_text", "changed": changed}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        require_confirmation(
            True,
            args.confirm,
            LEGACY_NOTION_REPAIR_CONFIRMATION,
            "legacy venue master cleanup",
        )
    except ValueError as exc:
        parser.error(str(exc))

    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    actions = [merge_sakamoto(api), clean_venue_text(api)]
    print(json.dumps(actions, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
