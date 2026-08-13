"""Pure, fail-safe helpers for the v2 official/quasi-official X registry.

The caller supplies venue/event records, so a missing place_nodes migration
cannot prevent venue based linking.
"""
from __future__ import annotations

from datetime import date, timedelta
import json
import sqlite3
import re

from collection_support.tokyo23_scope import is_outside_tokyo_23_scope
from collection_support.x_official_source_accounts import norm_handle

BON_RE = re.compile(r"盆踊り|盆おどり|ぼんおどり|納涼|民踊|音頭|やぐら|櫓", re.I)
ORG_RE = re.compile(r"町会|自治会|商店(?:街|会)|振興組合|実行委員|保存会|神社|寺|観光協会|商工会|連合会|奉賛会|睦|八幡|氷川|稲荷|区議|都議|議員|区役所")


def link_voice_to_events(voice, events):
    """Return venue+ward linked events; rejects generic and out-of-area text."""
    text = " ".join(str(voice.get(k) or "") for k in ("name", "profile_description", "text"))
    if not BON_RE.search(text) or is_outside_tokyo_23_scope(text):
        return []
    matched = []
    for event in events:
        venue = str(event.get("venue") or event.get("canonical_name") or "")
        ward = str(event.get("ward") or "")
        aliases = event.get("venue_surface_forms") or []
        names = [venue, *aliases]
        # Short/common venue strings create incorrect city-to-city links.
        if not any(len(name) >= 5 and name in text for name in names):
            continue
        # Ward omission is normal for a local organiser.  We only reject an
        # explicit conflicting city/prefecture (checked above), not silence.
        matched.append(event)
    return matched


def classify_link_confidence(voices):
    return "confirmed" if any(v.get("date_matches") for v in voices) else (
        "probable" if len(voices) >= 2 else "possible")


def tier_for_account(account, today=None):
    """Apply the ordered active/dormant lifecycle without overriding users."""
    today = today or date.today()
    if account.get("decided_by") == "user" and account.get("tier"):
        return account["tier"]
    linked = [e for e in account.get("linked_events") or []
              if e.get("confidence") in ("confirmed", "probable")]
    if not linked:
        return "pending_review"
    if len(linked) >= 2:
        return "active"
    event = linked[0]
    end = _as_date(event.get("latest_occurrence_end") or event.get("date_end") or event.get("date_start"))
    if end and end >= today - timedelta(days=14):
        return "active"
    wake = _as_date(account.get("wake_after")) or _predicted_wake_after(event)
    if wake and today >= wake:
        return "active"
    return "dormant"


def _as_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _predicted_wake_after(event):
    """Use a supplied forecast, or the same calendar date in the next year."""
    predicted = _as_date(event.get("predicted_occurrence_date"))
    if predicted:
        return predicted - timedelta(days=60)
    previous = _as_date(event.get("latest_occurrence_end") or event.get("date_end") or event.get("date_start"))
    if not previous:
        return None
    try:
        next_date = previous.replace(year=previous.year + 1)
    except ValueError:  # Feb 29
        next_date = previous.replace(year=previous.year + 1, day=28)
    return next_date - timedelta(days=60)


def load_events_from_master_db(db_path):
    """Read venue/occurrence records, deriving wards from address/area.

    Empty or pre-migration databases return []: matching remains fail-safe.
    """
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            rows = conn.execute("""SELECT s.series_id, s.canonical_name, v.canonical_name,
                v.area, v.address, o.date_start, o.date_end
                FROM event_series s JOIN event_occurrences o ON o.series_id=s.series_id
                JOIN venues v ON v.venue_id=COALESCE(o.venue_id,s.usual_venue_id)""").fetchall()
    except (sqlite3.Error, OSError):
        return []
    result = []
    for series_id, series_name, venue, area, address, start, end in rows:
        scope = " ".join(x or "" for x in (area, address))
        ward_match = re.search(r"(?:" + "|".join(["千代田区","中央区","港区","新宿区","文京区","台東区","墨田区","江東区","品川区","目黒区","大田区","世田谷区","渋谷区","中野区","杉並区","豊島区","北区","荒川区","板橋区","練馬区","足立区","葛飾区","江戸川区"]) + r")", scope)
        result.append({"series_id":series_id,"series_name":series_name,"venue":venue,
                       "ward":ward_match.group(0) if ward_match else "", "date_start":start, "date_end":end,
                       "latest_occurrence_end":end or start})
    return result


def registry_candidates(voices, events):
    """Build unreviewed rows only when an organisation has a linked event."""
    grouped = {}
    for voice in voices:
        handle = norm_handle(voice.get("account"))
        if not handle or not ORG_RE.search(str(voice.get("name") or "")):
            continue
        links = link_voice_to_events(voice, events)
        if links:
            grouped.setdefault(handle, []).append((voice, links))
    rows = []
    for handle, pairs in grouped.items():
        by_series = {}
        for voice, links in pairs:
            for event in links:
                series = event.get("series_id") or event.get("series_name")
                by_series.setdefault(series, {**event, "voices": []})["voices"].append(voice)
        linked = [{
            "series_id": event.get("series_id"), "series_name": event.get("series_name", ""),
            "ward": event.get("ward", ""), "confidence": classify_link_confidence(event["voices"]),
            "evidence_urls": sorted({v.get("url") for v in event["voices"] if v.get("url")}),
        } for event in by_series.values()]
        row = {"handle": "@" + handle, "name": pairs[0][0].get("name", ""),
               "source_type": "official", "linked_events": linked, "decided_by": "machine"}
        row["tier"] = tier_for_account(row)
        rows.append(row)
    return rows
