"""Pure, fail-safe helpers for the v2 official/quasi-official X registry.

The caller supplies venue/event records, so a missing place_nodes migration
cannot prevent venue based linking.
"""
from __future__ import annotations

from datetime import date, timedelta
import re

from collection_support.tokyo23_scope import is_outside_tokyo_23_scope
from collection_support.x_official_source_accounts import norm_handle

BON_RE = re.compile(r"盆踊り|盆おどり|ぼんおどり|納涼|民踊|音頭|やぐら|櫓", re.I)
ORG_RE = re.compile(r"町会|自治会|商店(?:街|会)|振興組合|実行委員|保存会|神社|寺|観光協会|区議|都議|議員|区役所")


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
        if ward and ward not in text:
            continue
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
    wake = _as_date(account.get("wake_after"))
    if wake and today >= wake:
        return "active"
    return "dormant"


def _as_date(value):
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


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
