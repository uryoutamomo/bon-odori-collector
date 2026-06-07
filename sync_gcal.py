#!/usr/bin/env python3
"""Sync canonical Notion participation plans to Google Calendar."""

import os
from datetime import date, datetime, timedelta

from event_audit import (
    EVENT_SCHEMA,
    blocking_duplicate_count,
    duplicate_groups,
)
from notion_api import (
    NotionApi,
    date_value,
    plain_text,
    validate_data_source,
)
from notion_config import (
    EVENT_DATA_SOURCE_ID,
    PLAN_DATA_SOURCE_ID,
    VENUE_DATA_SOURCE_ID,
    load_local_env,
)


SCOPES = ["https://www.googleapis.com/auth/calendar"]
CREDS_FILE = os.path.join(os.path.dirname(__file__), "credentials.json")
TOKEN_FILE = os.path.join(os.path.dirname(__file__), "token.json")

PLAN_SCHEMA = {
    "参加計画名": {"type": "title"},
    "イベント": {
        "type": "relation",
        "data_source_id": EVENT_DATA_SOURCE_ID,
    },
    "参加ステータス": {"type": "select"},
    "移動手段": {"type": "select"},
    "個人メモ": {"type": "rich_text"},
    "日付": {"type": "date"},
    "GCal同期ID": {"type": "rich_text"},
}
VENUE_SCHEMA = {
    "会場名": {"type": "title"},
    "住所": {"type": "rich_text"},
    "所在区・市": {"type": "rich_text"},
}


def get_gcal_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                CREDS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)


def validate_notion_setup(api):
    validate_data_source(api, EVENT_DATA_SOURCE_ID, EVENT_SCHEMA)
    validate_data_source(api, PLAN_DATA_SOURCE_ID, PLAN_SCHEMA)
    validate_data_source(api, VENUE_DATA_SOURCE_ID, VENUE_SCHEMA)
    events = api.query_data_source(EVENT_DATA_SOURCE_ID)
    duplicates = duplicate_groups(events)
    duplicate_count = blocking_duplicate_count(duplicates)
    if duplicate_count:
        raise ValueError(
            f"canonical event data source has {duplicate_count} "
            "duplicate group(s); run event_audit.py"
        )
    return events


def build_gcal_event(plan_page, event_page, venue_page=None):
    event_props = event_page["properties"]
    plan_props = plan_page["properties"]
    venue_props = venue_page["properties"] if venue_page else {}

    event_date = date_value(event_props.get("開催日"))
    if not event_date:
        return None

    event_name = plain_text(event_props.get("イベント名"))
    venue_name = plain_text(venue_props.get("会場名"))
    address = plain_text(venue_props.get("住所"))
    area = plain_text(venue_props.get("所在区・市"))
    source_url = plain_text(event_props.get("情報源URL"))
    transport = plain_text(plan_props.get("移動手段"))
    personal_note = plain_text(plan_props.get("個人メモ"))

    start = event_date.get("start")
    end = event_date.get("end")
    is_datetime = "T" in (start or "")
    if is_datetime:
        if not end:
            parsed = datetime.fromisoformat(start.replace("Z", "+00:00"))
            end = (parsed + timedelta(hours=1)).isoformat()
        gcal_start = {"dateTime": start, "timeZone": "Asia/Tokyo"}
        gcal_end = {
            "dateTime": end,
            "timeZone": "Asia/Tokyo",
        }
    else:
        end_date = date.fromisoformat(end or start) + timedelta(days=1)
        gcal_start = {"date": start}
        gcal_end = {"date": end_date.isoformat()}

    description = []
    if venue_name:
        description.append(f"会場: {venue_name}")
    if transport:
        description.append(f"移動手段: {transport}")
    if personal_note:
        description.append(f"メモ: {personal_note}")
    if source_url:
        description.append(f"情報源: {source_url}")

    return {
        "summary": event_name,
        "location": address or f"{venue_name} {area}".strip(),
        "description": "\n".join(description),
        "start": gcal_start,
        "end": gcal_end,
    }


def _calendar_date_property(body):
    start = body["start"].get("dateTime") or body["start"].get("date")
    end = body["end"].get("dateTime") or body["end"].get("date")
    return {
        "date": {
            "start": start,
            "end": end if end != start else None,
            "time_zone": "Asia/Tokyo" if "T" in start else None,
        }
    }


def _delete_calendar_entry(api, gcal, plan_id, gcal_id):
    gcal.events().delete(
        calendarId="primary", eventId=gcal_id
    ).execute()
    api.update_page(
        plan_id,
        {
            "GCal同期ID": {"rich_text": []},
            "日付": {"date": None},
        },
    )


def sync(api, gcal):
    events = validate_notion_setup(api)
    event_cache = {row["id"]: row for row in events}
    venue_cache = {}
    plans = api.query_data_source(PLAN_DATA_SOURCE_ID)
    stats = {"created": 0, "updated": 0, "deleted": 0, "skipped": 0}

    for plan in plans:
        plan_id = plan["id"]
        props = plan["properties"]
        participation = plain_text(props.get("参加ステータス"))
        gcal_id = plain_text(props.get("GCal同期ID"))
        event_relations = props.get("イベント", {}).get("relation", [])

        if participation not in ("参加予定", "検討中"):
            if gcal_id:
                _delete_calendar_entry(
                    api, gcal, plan_id, gcal_id
                )
                stats["deleted"] += 1
            else:
                stats["skipped"] += 1
            continue

        if len(event_relations) != 1:
            stats["skipped"] += 1
            continue
        event_id = event_relations[0]["id"]
        event = event_cache.get(event_id)
        if not event:
            raise ValueError(
                f"plan {plan_id} references a non-canonical event {event_id}"
            )
        event_props = event["properties"]
        if plain_text(event_props.get("状態")) != "確認済み":
            if gcal_id:
                _delete_calendar_entry(
                    api, gcal, plan_id, gcal_id
                )
                stats["deleted"] += 1
            else:
                stats["skipped"] += 1
            continue

        venue = None
        venue_relations = event_props.get("会場", {}).get("relation", [])
        if venue_relations:
            venue_id = venue_relations[0]["id"]
            if venue_id not in venue_cache:
                venue_cache[venue_id] = api.retrieve_page(venue_id)
            venue = venue_cache[venue_id]

        body = build_gcal_event(plan, event, venue)
        if not body:
            if gcal_id:
                _delete_calendar_entry(
                    api, gcal, plan_id, gcal_id
                )
                stats["deleted"] += 1
            else:
                stats["skipped"] += 1
            continue
        date_prop = _calendar_date_property(body)

        if gcal_id:
            gcal.events().update(
                calendarId="primary", eventId=gcal_id, body=body
            ).execute()
            api.update_page(plan_id, {"日付": date_prop})
            stats["updated"] += 1
        else:
            created = gcal.events().insert(
                calendarId="primary", body=body
            ).execute()
            api.update_page(
                plan_id,
                {
                    "GCal同期ID": {
                        "rich_text": [
                            {"text": {"content": created["id"]}}
                        ]
                    },
                    "日付": date_prop,
                },
            )
            stats["created"] += 1
    return stats


def main():
    load_local_env()
    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    stats = sync(api, get_gcal_service())
    print(
        "完了: "
        + " ".join(f"{name}={value}" for name, value in stats.items())
    )


if __name__ == "__main__":
    main()
