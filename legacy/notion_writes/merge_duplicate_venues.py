import argparse
import json
import os

from manual_apply_guards import LEGACY_NOTION_REPAIR_CONFIRMATION, require_confirmation
from notion_support.notion_api import NotionApi
from notion_config import EVENT_DATA_SOURCE_ID


MERGES = [
    {
        "name": "JR苅田駅前広場",
        "old_id": "3748be04-e762-81ca-b721-cabdb8aa8096",
        "keep_id": "3718be04-e762-8184-a8d3-cd0ff6f50d24",
    },
    {
        "name": "旧江別小学校",
        "old_id": "3748be04-e762-814b-a2f8-ca1225631061",
        "keep_id": "3718be04-e762-81e0-86c0-ffc93d88f14e",
    },
    {
        "name": "本住吉神社",
        "old_id": "3748be04-e762-812e-ad56-d0fccee3744a",
        "keep_id": "3718be04-e762-81d2-b8b8-e57ad53374f3",
    },
]


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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        require_confirmation(
            True,
            args.confirm,
            LEGACY_NOTION_REPAIR_CONFIRMATION,
            "legacy duplicate venue merge",
        )
    except ValueError as exc:
        parser.error(str(exc))

    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    events = api.query_data_source(EVENT_DATA_SOURCE_ID)
    actions = []

    for merge in MERGES:
        old_id = merge["old_id"]
        keep_id = merge["keep_id"]
        for event in events:
            relations = event["properties"].get("会場", {}).get("relation", [])
            changed, next_relations = replace_relation_ids(relations, old_id, keep_id)
            if not changed:
                continue
            api.update_page(event["id"], {"会場": {"relation": next_relations}})
            actions.append(
                {
                    "type": "event_relation_updated",
                    "venue": merge["name"],
                    "event_id": event["id"],
                    "event_url": event.get("url"),
                }
            )

        api.request("PATCH", f"/pages/{old_id}", {"archived": True})
        actions.append(
            {
                "type": "venue_archived",
                "venue": merge["name"],
                "old_id": old_id,
                "keep_id": keep_id,
            }
        )

    print(json.dumps(actions, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
