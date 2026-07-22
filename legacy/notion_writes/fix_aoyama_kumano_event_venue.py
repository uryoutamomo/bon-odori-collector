#!/usr/bin/env python3
"""Limit Aoyama Kumano festival dance event venue to Aoba Park."""

import argparse
import os

from manual_apply_guards import LEGACY_NOTION_REPAIR_CONFIRMATION, require_confirmation
from notion_support.notion_api import NotionApi
from notion_support.notion_config import load_local_env


EVENT_PAGE_ID = "37b8be04-e762-814a-a9af-c9d8490a0a55"
AOBA_PARK_VENUE_ID = "3718be04-e762-814e-a562-d6e460b2e942"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        require_confirmation(
            True,
            args.confirm,
            LEGACY_NOTION_REPAIR_CONFIRMATION,
            "legacy Aoyama Kumano venue repair",
        )
    except ValueError as exc:
        parser.error(str(exc))

    load_local_env()
    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    api.update_page(
        EVENT_PAGE_ID,
        {"会場": {"relation": [{"id": AOBA_PARK_VENUE_ID}]}},
    )
    print(f"aoyama kumano event venue fixed: {EVENT_PAGE_ID} -> {AOBA_PARK_VENUE_ID}")


if __name__ == "__main__":
    main()
