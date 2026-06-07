#!/usr/bin/env python3
import argparse
from difflib import SequenceMatcher
import json
import os
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

from notion_api import NotionApi, plain_text, validate_data_source
from notion_config import (
    EVENT_DATA_SOURCE_ID,
    VENUE_DATA_SOURCE_ID,
    load_local_env,
)


EVENT_SCHEMA = {
    "イベント名": {"type": "title"},
    "会場": {"type": "relation", "data_source_id": VENUE_DATA_SOURCE_ID},
    "開催日": {"type": "date"},
    "状態": {"type": "select"},
    "情報源URL": {"type": "url"},
}


def normalize_event_name(name):
    normalized = unicodedata.normalize("NFKC", name or "").casefold()
    return re.sub(r"[\s・･\-ー‐－（）()【】「」『』]+", "", normalized)


def normalize_source_url(url):
    if not url:
        return ""
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(
        (parts.scheme.casefold(), parts.netloc.casefold(), path, "", "")
    )


def duplicate_groups(rows):
    indexes = {"name": {}, "url": {}}
    for row in rows:
        props = row.get("properties", {})
        name = plain_text(props.get("イベント名"))
        url = plain_text(props.get("情報源URL"))
        keys = {
            "name": normalize_event_name(name),
            "url": normalize_source_url(url),
        }
        record = {
            "id": row.get("id"),
            "name": name,
            "url": url,
        }
        for kind, key in keys.items():
            if key:
                indexes[kind].setdefault(key, []).append(record)
    name_groups = [
        {"key": key, "pages": pages}
        for key, pages in indexes["name"].items()
        if len(pages) > 1
    ]
    suspicious_url_groups = []
    shared_url_groups = []
    for key, pages in indexes["url"].items():
        if len(pages) < 2:
            continue
        names = [normalize_event_name(page["name"]) for page in pages]
        max_similarity = max(
            SequenceMatcher(None, left, right).ratio()
            for index, left in enumerate(names)
            for right in names[index + 1:]
        )
        group = {
            "key": key,
            "name_similarity": round(max_similarity, 3),
            "pages": pages,
        }
        target = (
            suspicious_url_groups
            if max_similarity >= 0.75
            else shared_url_groups
        )
        target.append(group)
    return {
        "name": name_groups,
        "url_name_match": suspicious_url_groups,
        "shared_url": shared_url_groups,
    }


def blocking_duplicate_count(duplicates):
    return len(duplicates["name"]) + len(duplicates["url_name_match"])


def run_audit(api):
    validate_data_source(api, EVENT_DATA_SOURCE_ID, EVENT_SCHEMA)
    rows = api.query_data_source(EVENT_DATA_SOURCE_ID)
    duplicates = duplicate_groups(rows)
    return {
        "data_source_id": EVENT_DATA_SOURCE_ID,
        "total": len(rows),
        "duplicates": duplicates,
        "duplicate_group_count": blocking_duplicate_count(duplicates),
    }


def main():
    load_local_env()
    parser = argparse.ArgumentParser(
        description="Audit the canonical Notion event data source."
    )
    parser.add_argument(
        "--fail-on-duplicates",
        action="store_true",
        help="Exit non-zero when duplicate groups are found.",
    )
    args = parser.parse_args()
    report = run_audit(NotionApi(os.environ.get("NOTION_API_TOKEN")))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.fail_on_duplicates and report["duplicate_group_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
