#!/usr/bin/env python3
"""Build a deliberately small X queue from gaps in the master RDB.

Unlike the old news digest this is not a discovery inbox: it only emits posts
which can fill a current-year occurrence gap, report a harmful schedule change,
or are from a registered official account and appear to describe a new event.
The unselected X corpus stays in ``voices.json``/evidence.sqlite.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from master_rdb.master_db import MASTER_DB, normalize_text
from collection_support.x_source_officiality import assess_source_officiality
from collection_support.tokyo23_scope import (
    NON_TOKYO_PREF_RE,
    TOKYO_23_RE,
    TOKYO_23_WARDS,
    is_outside_tokyo_23_scope,
)

DATA = Path("data")
VOICES = DATA / "voices.json"
OUT = DATA / "x_gap_candidates.json"
KNOWN_VENUES = DATA / "blog_venue_rows.json"
X_SOURCES = {"x", "x_whitelist", "x_proactive", "x_event_history"}
DATE_RE = re.compile(r"(?:20\d{2}[/-]\d{1,2}[/-]\d{1,2}|\d{1,2}月\d{1,2}日?|\d{1,2}/\d{1,2}|\d{1,2}時)")
# This deliberately excludes times (for example "18時").  It is used for
# future-event discovery, where a time must never be mistaken for a date.
FUTURE_DATE_RE = re.compile(r"(?:(20\d{2})[年/-])?(\d{1,2})月(\d{1,2})日?|(?:(20\d{2})[/-])?(\d{1,2})/(\d{1,2})(?!\d)")
ELIDED_DAY_RANGE_RE = re.compile(
    r"(?:(20\d{2})年)?(\d{1,2})月(\d{1,2})日?"
    r"(?:\([^)]+\))?\s*[・･〜～~\-ー–—]\s*(\d{1,2})日?"
)
BON_RE = re.compile(r"盆踊り|盆おどり|ぼんおどり|民踊|納涼|夏まつり|夏祭り", re.I)
CHANGE_RE = re.compile(r"中止|延期|順延|時間変更|開催時間.*変更|取りやめ")
NON_CHANGE_RE = re.compile(r"(?:順延|延期).{0,12}(?:ない|ありません|ございません)|(?:雨天|少雨)決行|雨天中止")
# Require a declaration-like construction.  A bare word such as a venue's
# "通行止め" note must not turn an ordinary opening announcement into a P0
# schedule-change item.
ACTUAL_CHANGE_RE = re.compile(r"(?:本日|開催|イベント|盆踊り).{0,24}(?:中止|延期|順延)(?:と|に|にな|いた|します|のお知らせ)|(?:中止|延期|順延)(?:とな|にな|いた|します|のお知らせ)|開催時間.{0,8}変更|取りやめ(?:と|に|にな|ます)")
GENERIC_EVENT_RE = re.compile(r"^(?:第\d+回)?(?:納涼|夏)?(?:盆踊り|盆おどり|ぼんおどり)(?:大会)?$")
EXPLICIT_YEAR_RE = re.compile(r"(?<!\d)(20\d{2})年")
EXTRA_OUTSIDE_SCOPE_RE = re.compile(r"神戸|東灘|兵庫|砺波|富山|淀川")
OFFICIAL_NEW_EVENT_CAP = 5
INFORMAL_NEW_EVENT_CAP = 10
PAST_EVENT_REPORT_CAP = 10
EVENTISH_RE = re.compile(r"盆踊り|盆おどり|ぼんおどり|納涼|夏まつり|夏祭り", re.I)
VENUEISH_RE = re.compile(r"会場|公園|神社|寺|学校|商店街|広場|駅前|前(?:\b|で|に)")
TOKYO23_LANDMARK_RE = re.compile(
    r"上野|不忍|十条|王子|飛鳥山|赤羽|船堀|葛西|芝公園|池上本門寺|浅草|"
    r"亀戸|錦糸町|豊洲|月島|神楽坂|高円寺|阿佐ヶ谷|荻窪|中野|巣鴨|"
    r"駒沢|代々木|恵比寿|目黒|品川|大井|蒲田|大森|成増|赤塚|"
    r"練馬|石神井|北千住|綾瀬|青戸|新小岩|小岩|西日暮里|日暮里"
)
CALENDAR_DATE_RE = re.compile(r"(?:(20\d{2})[年/-])?(\d{1,2})月(\d{1,2})日?|(?:(20\d{2})[/-])?(\d{1,2})/(\d{1,2})(?!\d)")
PAST_REPORT_RE = re.compile(r"行(?:ってきた|った|きました)|お伺い|伺(?:い|わせ)|お邪魔|参加(?:した|しました)|楽しかった|ありがとうございました|帰ってきた")
DATE_LIST_LINE_RE = re.compile(
    r"(?:^|\n)\s*(?:(?:20\d{2}[/-])?\d{1,2}[/-]\d{1,2}|(?:20\d{2}年)?\d{1,2}月\d{1,2}日?)"
)
# `北区` is shared by several cities.  These are deliberately concrete
# positive clues, rather than treating a ward token alone as enough.
TOKYO23_PAST_LANDMARK_RE = re.compile(r"板橋|上野|不忍|十条|王子|赤羽|船堀|葛西|芝公園|池上本門寺|浅草|亀戸|錦糸町|豊洲|月島|高円寺|阿佐ヶ谷|荻窪|巣鴨|北千住|綾瀬|新小岩|小岩")
PAST_OUTSIDE_RE = re.compile(r"横浜|名古屋|京都|神戸|明石|軽井沢|佐倉|大阪|三笠")
TOKYO_LOCATION_RE = re.compile(r"東京都|東京23区|都内|東京(?=市|区|駅|[・、])")


def load(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def catalog(db: Path, year: int) -> list[dict[str, str]]:
    """Current-year occurrences and all canonical/alias names for matching."""
    uri = f"file:{db.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
          SELECT o.occurrence_id, o.display_name, o.date_start, o.date_end, o.detail,
                 e.canonical_name, e.area, v.canonical_name AS venue,
                 v.venue_id, v.area AS venue_area, v.address AS venue_address
          FROM event_occurrences o JOIN event_series e ON e.series_id=o.series_id
          LEFT JOIN venues v ON v.venue_id=o.venue_id WHERE o.event_year=?
        """, (year,)).fetchall()
        aliases = conn.execute("""
          SELECT a.series_id, a.alias FROM event_series_aliases a
        """).fetchall()
    by_series: dict[str, list[str]] = {}
    # Associate aliases by joining on occurrence's series in one small second query.
    with sqlite3.connect(uri, uri=True) as conn:
        for row in conn.execute("SELECT occurrence_id, series_id FROM event_occurrences WHERE event_year=?", (year,)):
            by_series.setdefault(row[1], []).append(row[0])
    aliases_by_occ: dict[str, list[str]] = {}
    for alias in aliases:
        for occurrence_id in by_series.get(alias[0], []):
            aliases_by_occ.setdefault(occurrence_id, []).append(alias[1])
    result=[]
    for row in rows:
        names=[row["display_name"], row["canonical_name"], *aliases_by_occ.get(row["occurrence_id"], [])]
        result.append({"occurrence_id":row["occurrence_id"], "event_name":row["display_name"],
                       "venue":row["venue"] or "", "date_start":row["date_start"] or "",
                       "date_end":row["date_end"] or "",
                       "detail":row["detail"] or "", "area":row["area"] or "",
                       "venue_id":row["venue_id"] or "",
                       "venue_area":row["venue_area"] or "",
                       "venue_address":row["venue_address"] or "",
                       "aliases":[n for n in names if n]})
    return result


def matches(text: str, row: dict[str, Any]) -> list[str]:
    normalized=normalize_text(text)
    matched=[]
    for name in row["aliases"]:
        if not discriminative_alias(name):
            continue
        identity=normalize_text(name)
        # Series labels sometimes add a subtitle (e.g. ``～不忍夢～``) while
        # performers publish only the distinctive event name.  An event-word
        # prefix remains safe enough to match, unlike a generic ``盆踊り``.
        prefix=re.match(r"(.{3,}?(?:盆踊り|盆おどり|ぼんおどり|夏まつり|夏祭り|納涼))", identity)
        if identity in normalized or (prefix and len(prefix.group(1)) >= 5 and prefix.group(1) in normalized):
            matched.append(name)
    return matched


def discriminative_alias(name: str) -> bool:
    """Reject generic labels such as ``盆踊り大会`` as identity keys."""
    text=re.sub(r"\s+", "", str(name or ""))
    return len(normalize_text(text)) >= 5 and not GENERIC_EVENT_RE.fullmatch(text)


def actual_schedule_change(text: str) -> bool:
    return bool(CHANGE_RE.search(text) and not NON_CHANGE_RE.search(text) and ACTUAL_CHANGE_RE.search(text))


def master_occurrence_is_in_scope(row: dict[str, Any]) -> bool:
    """Fail closed when explicit master venue metadata is outside Tokyo 23.

    A bare ward suffix is not enough: ``札幌市中央区`` must not be treated as
    Tokyo's ``中央区``.  Venue metadata takes precedence over a stale or empty
    series area because it identifies the actual matched occurrence location.
    """
    series_area = str(row.get("area") or "").strip()
    venue_area = str(row.get("venue_area") or "").strip()
    venue_address = str(row.get("venue_address") or "").strip()

    if NON_TOKYO_PREF_RE.search(f"{venue_area} {venue_address}"):
        return False

    exact_ward = series_area in TOKYO_23_WARDS or venue_area in TOKYO_23_WARDS
    tokyo_address = "東京都" in venue_address and bool(TOKYO_23_RE.search(venue_address))
    tokyo_venue_area = "東京都" in venue_area and bool(TOKYO_23_RE.search(venue_area))

    # An explicit venue area such as 札幌市中央区 or 京都郡苅田町 is outside
    # unless it is an exact Tokyo ward (or explicitly prefixed with 東京都).
    if venue_area and not (venue_area in TOKYO_23_WARDS or tokyo_venue_area):
        return False
    if venue_address and is_outside_tokyo_23_scope(venue_address) and not tokyo_address:
        return False
    if exact_ward or tokyo_address or tokyo_venue_area:
        return True

    # Preserve legacy rows with no structured venue geography unless their
    # existing series/name/venue text carries a concrete outside-scope signal.
    return not is_outside_tokyo_23_scope(
        series_area,
        row.get("event_name"),
        row.get("venue"),
    ) and not EXTRA_OUTSIDE_SCOPE_RE.search(
        f"{series_area} {row.get('event_name', '')} {row.get('venue', '')}"
    )


def source_key(voice: dict[str, Any]) -> str:
    url=str(voice.get("url") or "")
    tweet=str(voice.get("tweet_id") or voice.get("id") or "")
    return "x:" + (tweet or hashlib.sha1(url.encode()).hexdigest()[:16])


def future_dates(text: str, *, year: int, today: date) -> list[date]:
    """Extract actual calendar dates in the requested year that are not past."""
    found: set[date] = set()
    for match in FUTURE_DATE_RE.finditer(text):
        groups = match.groups()
        value_year = int(groups[0] or groups[3] or year)
        month = int(groups[1] or groups[4])
        day = int(groups[2] or groups[5])
        try:
            value = date(value_year, month, day)
        except ValueError:
            continue
        if value.year == year and value >= today:
            found.add(value)
    # Posters often elide the month in the second day: ``8月27日・28日`` or
    # ``8月27日(金)-28日(土)``.  The general matcher sees only the first day.
    for match in ELIDED_DAY_RANGE_RE.finditer(text):
        value_year = int(match.group(1) or year)
        month = int(match.group(2))
        for raw_day in match.group(3, 4):
            try:
                value = date(value_year, month, int(raw_day))
            except ValueError:
                continue
            if value.year == year and value >= today:
                found.add(value)
    return sorted(found)


def has_positive_tokyo23_signal(text: str, voice: dict[str, Any]) -> bool:
    scope_text = " ".join(str(value or "") for value in (text, voice.get("area"), voice.get("region")))
    return bool(TOKYO_23_RE.search(scope_text) or TOKYO23_LANDMARK_RE.search(scope_text))


def known_tokyo23_venue_evidence(
    text: str, venue_rows: list[dict[str, Any]]
) -> dict[str, str] | None:
    """Ground an otherwise ambiguous post in an existing structured venue row.

    A post such as ``京華スクエア（八丁堀3-17-9）`` is clearly local to a
    human, but it contains neither ``東京都`` nor ``中央区``.  The venue feed
    already carries that missing geography.  Reuse it instead of maintaining
    an ever-growing regex of Tokyo neighborhood names.
    """
    normalized_text = normalize_text(text)
    matches: list[dict[str, str]] = []
    for raw in venue_rows:
        if not isinstance(raw, dict):
            continue
        venue = str(raw.get("venue") or "").strip()
        normalized_venue = normalize_text(venue)
        if len(normalized_venue) < 4 or normalized_venue not in normalized_text:
            continue
        region = str(raw.get("region_hint") or raw.get("area") or "").strip()
        address = str(raw.get("address") or "").strip()
        geography = f"{region} {address}"
        if is_outside_tokyo_23_scope(geography):
            continue
        if not (
            region in TOKYO_23_WARDS
            or bool(TOKYO_23_RE.search(geography))
            or ("東京都" in geography and bool(TOKYO_23_RE.search(geography)))
        ):
            continue
        matches.append(
            {
                "venue": venue,
                "region_hint": region,
                "address": address,
                "source_url": str(raw.get("detail_url") or raw.get("source_url") or ""),
            }
        )
    if not matches:
        return None
    # Prefer the longest exact venue label.  This avoids a short nested venue
    # name winning when the post contains a more specific known place.
    return max(matches, key=lambda row: len(normalize_text(row["venue"])))


def known_venue_event_key(evidence: dict[str, str], dates: list[date]) -> str:
    first_date = dates[0].isoformat() if dates else ""
    identity = f"{normalize_text(evidence['venue'])}|{first_date}"
    return "informal-venue:" + hashlib.sha1(identity.encode()).hexdigest()[:16]


def informal_event_key(text: str, dates: list[date]) -> str:
    """A stable, intentionally coarse identity key for an unregistered lead."""
    compact = normalize_text(text)
    compact = re.sub(r"20\d{2}年|\d{1,2}月\d{1,2}日|\d{1,2}/\d{1,2}|\d{1,2}時", "", compact)
    # Prefer the named portion containing an event word.  The venue/date are
    # usually repeated even when performers write very different surrounding
    # copy, so this makes corroborating mentions collapse naturally.
    match = re.search(r".{0,18}?(?:盆踊り|盆おどり|ぼんおどり|夏まつり|夏祭り).{0,12}", compact)
    event = match.group(0) if match else compact[:48]
    venue_match = re.search(r"(?:[^、。\s]{1,16}(?:公園|神社|寺|学校|商店街|広場|駅前))", compact)
    venue = venue_match.group(0) if venue_match else ""
    return "informal:" + hashlib.sha1(f"{event}|{venue}|{dates[0] if dates else ''}".encode()).hexdigest()[:16]


def group_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse many social mentions into one reviewable event-level lead."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        match = candidate.get("matched_occurrence") or {}
        if match and candidate["candidate_kind"] == "date_range_conflict":
            key = "occurrence:" + str(match["occurrence_id"])
        elif candidate["candidate_kind"] == "informal_new_event":
            key = str(candidate["event_group_key"])
        else:
            key = "source:" + str(candidate["source_key"])
        grouped.setdefault(key, []).append(candidate)
    result=[]
    for key, rows in grouped.items():
        rows.sort(key=lambda row: row["source_key"])
        representative = dict(rows[0])
        urls = list(dict.fromkeys(str(row.get("source_url") or "") for row in rows if row.get("source_url")))
        media_urls = list(dict.fromkeys(
            str(url)
            for row in rows
            for url in (
                (row.get("voice") or {}).get("media_urls")
                or (row.get("voice") or {}).get("media")
                or []
            )
            if str(url or "")
        ))
        authors = {str(row.get("source_author") or "").strip() for row in rows if str(row.get("source_author") or "").strip()}
        representative["source_urls"] = urls
        representative["source_media_urls"] = media_urls
        representative["corroboration_count"] = len(authors) or len(rows)
        representative["source_count"] = len(rows)
        representative["candidate_id"] = "xgap_" + hashlib.sha1(key.encode()).hexdigest()[:16]
        representative["priority_score"] += min(representative["corroboration_count"], 20) * 5
        result.append(representative)
    return result


def calendar_dates(text: str, *, year: int) -> list[date]:
    values: set[date] = set()
    for match in CALENDAR_DATE_RE.finditer(text):
        groups=match.groups()
        value_year=int(groups[0] or groups[3] or year)
        month=int(groups[1] or groups[4]); day=int(groups[2] or groups[5])
        try:
            values.add(date(value_year, month, day))
        except ValueError:
            continue
    for match in ELIDED_DAY_RANGE_RE.finditer(text):
        value_year = int(match.group(1) or year)
        month = int(match.group(2))
        for raw_day in match.group(3, 4):
            try:
                values.add(date(value_year, month, int(raw_day)))
            except ValueError:
                continue
    return sorted(values)


def is_strict_tokyo23_past_scope(text: str, voice: dict[str, Any]) -> bool:
    scope_text=" ".join(str(value or "") for value in (text, voice.get("area"), voice.get("region")))
    if PAST_OUTSIDE_RE.search(scope_text) or is_outside_tokyo_23_scope(scope_text):
        return False
    # A song title such as ``東京音頭`` must not turn a Hamamatsu report into
    # a Tokyo lead, hence the geographically qualified Tokyo expression.
    return bool(TOKYO_LOCATION_RE.search(scope_text) or TOKYO23_PAST_LANDMARK_RE.search(scope_text) or ("板橋区" in scope_text))


def is_multi_venue_listing(text: str) -> bool:
    """Do not silently collapse a one-post/many-venues historical report."""
    return len(VENUEISH_RE.findall(text)) >= 2


def is_date_list_itinerary(text: str) -> bool:
    """Detect a multi-stop itinerary without assuming venue-name vocabulary.

    Vendor and performer schedules commonly put one dated stop per line, but
    commercial venue names need not contain our park/shrine/school keywords.
    Three dated lines is deliberately the minimum: a normal two-day event is
    not treated as a listing.
    """
    return len(DATE_LIST_LINE_RE.findall(text)) >= 3


def dates_near_matched_event(
    text: str, names: list[str], *, year: int, today: date, distance: int = 120
) -> list[date]:
    """Return future dates close to the matched event label in a listing post.

    A vendor's itinerary can mention one matched event alongside many unrelated
    date/venue pairs.  This deliberately does *not* replace normal date
    extraction: callers use it only for multi-venue text and fall back when
    there is no nearby date, so an unusual but genuine announcement stays
    reviewable.
    """
    name_spans = [
        match.span()
        for name in names
        if name
        for match in re.finditer(re.escape(name), text)
    ]
    if not name_spans:
        return []
    found: set[date] = set()
    for match in FUTURE_DATE_RE.finditer(text):
        groups = match.groups()
        value_year = int(groups[0] or groups[3] or year)
        month = int(groups[1] or groups[4])
        day = int(groups[2] or groups[5])
        try:
            value = date(value_year, month, day)
        except ValueError:
            continue
        if value.year != year or value < today:
            continue
        start, end = match.span()
        if any(start <= name_end + distance and end >= name_start - distance for name_start, name_end in name_spans):
            found.add(value)
    return sorted(found)


def local_area(row: dict[str, Any]) -> str:
    """Use structured venue geography first; blank geography is not a match."""
    value = str(row.get("venue_area") or row.get("area") or "").strip()
    return normalize_text(value.replace("東京都", ""))


def same_structured_venue(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Match a venue only when its structured locality cannot contradict."""
    left_area, right_area = local_area(left), local_area(right)
    if not left_area or not right_area or left_area != right_area:
        return False
    left_id, right_id = str(left.get("venue_id") or ""), str(right.get("venue_id") or "")
    if left_id and right_id:
        return left_id == right_id
    left_name = normalize_text(str(left.get("venue") or ""))
    right_name = normalize_text(str(right.get("venue") or ""))
    return bool(left_name and left_name == right_name)


def range_is_explained_by_other_occurrence(
    gap: dict[str, Any], gaps: list[dict[str, Any]], observed_dates: list[date]
) -> bool:
    """Whether another same-place occurrence fully accounts for this range."""
    if not observed_dates:
        return False
    observed_start, observed_end = observed_dates[0], observed_dates[-1]
    for other in gaps:
        if other.get("occurrence_id") == gap.get("occurrence_id"):
            continue
        if not same_structured_venue(gap, other):
            continue
        try:
            other_start = date.fromisoformat(str(other.get("date_start") or ""))
            other_end = date.fromisoformat(str(other.get("date_end") or other.get("date_start") or ""))
        except ValueError:
            continue
        if other_start <= observed_start and observed_end <= other_end:
            return True
    return False


def build(
    voices: list[dict[str, Any]],
    db: Path,
    *,
    year: int,
    limit: int = 30,
    today: date | None = None,
    known_venues: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    gaps=catalog(db, year)
    known_venues = known_venues or []
    today=today or date.today()
    candidates=[]; archived=[]; seen=set()
    for voice in voices:
        if not isinstance(voice, dict) or voice.get("source") not in X_SOURCES: continue
        # An old cancellation is historical evidence, not a warning that the
        # current public schedule must be changed.  Keep the gap queue aimed
        # at the current season (undated posts are retained).
        posted = str(voice.get("date") or "")[:4]
        if posted.isdigit() and int(posted) < year:
            continue
        text="\n".join(str(voice.get(k) or "") for k in ("title","text"))
        if not BON_RE.search(text): continue
        explicit_years={int(value) for value in EXPLICIT_YEAR_RE.findall(text)}
        if explicit_years and year not in explicit_years: continue
        if is_outside_tokyo_23_scope(text, voice.get("area"), voice.get("region")) or EXTRA_OUTSIDE_SCOPE_RE.search(text): continue
        key=source_key(voice)
        if key in seen: continue
        officiality=assess_source_officiality({}, voice=voice)
        official=(officiality.get("classification") == "registered_official_social")
        observed_dates=future_dates(text, year=year, today=today)
        venue_evidence=known_tokyo23_venue_evidence(text, known_venues)
        all_found=[(gap, matches(text, gap)) for gap in gaps]
        all_found=[(gap, names) for gap,names in all_found if names]
        found=list(all_found)
        kind=""; priority=0; gap=None; names=[]
        # A matched master row can itself reveal a non-23-ward legacy entry.
        found=[(g,n) for g,n in found if master_occurrence_is_in_scope(g)]
        # Never surface a cancellation/update for an occurrence already in
        # the past.  Its evidence remains in the corpus but cannot correct a
        # current public schedule.
        found=[(g,n) for g,n in found if not g.get("date_start") or date.fromisoformat(g["date_start"]) >= today]
        changes=actual_schedule_change(text)
        report_dates=[value for value in calendar_dates(text, year=year) if date(year, 7, 1) <= value < today]
        posted_on=str(voice.get("date") or "")[:10]
        report_posted=posted_on >= f"{year}-07-15" and posted_on <= today.isoformat()
        past_report=(not all_found and report_posted and report_dates and PAST_REPORT_RE.search(text)
                     and EVENTISH_RE.search(text) and VENUEISH_RE.search(text)
                     and is_strict_tokyo23_past_scope(text, voice))
        if past_report and is_multi_venue_listing(text):
            archived.append({"candidate_id":"xgap_"+hashlib.sha1(key.encode()).hexdigest()[:16], "source_key":key,
                "candidate_kind":"past_event_report", "source_url":voice.get("url") or "", "source_text":text[:500],
                "source_author":voice.get("account") or voice.get("author") or "", "observed_dates":[value.isoformat() for value in report_dates],
                "archive_reason":"multiple_venues_requires_manual_expansion", "voice":voice})
            seen.add(key); continue
        if changes and found:
            kind="schedule_change"; priority=300; gap,names=found[0]
        else:
            missing=[(g,n) for g,n in found if not g["date_start"] and DATE_RE.search(text)]
            if missing: kind="missing_date"; priority=200; gap,names=missing[0]
            elif (official and not found and DATE_RE.search(text) and EVENTISH_RE.search(text)
                  and (VENUEISH_RE.search(text) or venue_evidence)):
                kind="official_new_event"; priority=100
            elif found and observed_dates:
                candidate_gap, candidate_names = found[0]
                itinerary = is_date_list_itinerary(text)
                if itinerary or is_multi_venue_listing(text):
                    nearby_dates = dates_near_matched_event(
                        text,
                        candidate_names,
                        year=year,
                        today=today,
                        distance=40 if itinerary else 120,
                    )
                    if nearby_dates:
                        observed_dates = nearby_dates
                start = candidate_gap.get("date_start") or ""
                end = candidate_gap.get("date_end") or start
                observed_start = observed_dates[0].isoformat()
                observed_end = observed_dates[-1].isoformat()
                if not start or observed_start < start or observed_end > end:
                    if range_is_explained_by_other_occurrence(candidate_gap, gaps, observed_dates):
                        continue
                    kind="date_range_conflict"; priority=250; gap,names=candidate_gap,candidate_names
                else: continue
            elif (not found and not official and observed_dates and EVENTISH_RE.search(text)
                  and (VENUEISH_RE.search(text) or venue_evidence)
                  and (has_positive_tokyo23_signal(text, voice) or venue_evidence)):
                kind="informal_new_event"; priority=80
            elif past_report: kind="past_event_report"; priority=90
            else: continue
        seen.add(key)
        candidates.append({"candidate_id":"xgap_"+hashlib.sha1(key.encode()).hexdigest()[:16], "source_key":key,
          "lane_hint":"lane1" if official and kind in {"missing_date","schedule_change"} else "lane2",
          "candidate_kind":kind, "priority_score":priority + (20 if official else 0), "event_year":year,
          "matched_occurrence": ({"occurrence_id":gap["occurrence_id"],"event_name":gap["event_name"],"venue":gap["venue"],
                                  "area":gap["area"],"venue_area":gap["venue_area"],"venue_address":gap["venue_address"],
                                  "date_start":gap["date_start"],"date_end":gap["date_end"],"detail":gap["detail"],
                                  "matched_aliases":names} if gap else None),
          "source_url":voice.get("url") or "", "source_text":text[:500], "source_author":voice.get("account") or voice.get("author") or "",
          "source_officiality":officiality, "date_hints":DATE_RE.findall(text),
          "observed_dates":([value.isoformat() for value in report_dates] if kind == "past_event_report" else [value.isoformat() for value in observed_dates]),
          "event_group_key":(
              known_venue_event_key(venue_evidence, observed_dates)
              if kind == "informal_new_event" and venue_evidence
              else informal_event_key(text, observed_dates)
              if kind == "informal_new_event"
              else ""
          ),
          "known_venue_evidence":venue_evidence,
          "voice":voice})
    existing_archived=archived
    candidates=group_candidates(candidates)
    candidates.sort(key=lambda x:(-x["priority_score"], x["source_key"]))
    selected=[]; archived=[]; official_new_event_count=0; informal_new_event_count=0; past_event_report_count=0
    for candidate in candidates:
        if candidate['candidate_kind']=='official_new_event':
            if official_new_event_count >= OFFICIAL_NEW_EVENT_CAP:
                candidate={**candidate,'archive_reason':'official_new_event_daily_cap'}
                archived.append(candidate); continue
            official_new_event_count += 1
        if candidate['candidate_kind']=='informal_new_event':
            if informal_new_event_count >= INFORMAL_NEW_EVENT_CAP:
                candidate={**candidate,'archive_reason':'informal_new_event_daily_cap'}
                archived.append(candidate); continue
            informal_new_event_count += 1
        if candidate['candidate_kind']=='past_event_report':
            if past_event_report_count >= PAST_EVENT_REPORT_CAP:
                archived.append({**candidate,'archive_reason':'past_event_report_daily_cap'}); continue
            past_event_report_count += 1
        if len(selected) < limit: selected.append(candidate)
        else: archived.append({**candidate,'archive_reason':'daily_candidate_cap'})
    archived=existing_archived+archived
    return {"generated_by":"build_x_gap_candidates.py", "generated_at":datetime.now(timezone.utc).isoformat(),
            "limit":limit, "official_new_event_limit":OFFICIAL_NEW_EVENT_CAP,
            "informal_new_event_limit":INFORMAL_NEW_EVENT_CAP, "past_event_report_limit":PAST_EVENT_REPORT_CAP,
            "candidate_count":len(selected), "archived_count":len(archived), "candidates":selected,
            "archived_candidates":archived}


def main() -> None:
    p=argparse.ArgumentParser(); p.add_argument("--voices",type=Path,default=VOICES); p.add_argument("--master-db",type=Path,default=MASTER_DB); p.add_argument("--known-venues",type=Path,default=KNOWN_VENUES); p.add_argument("--year",type=int,default=datetime.now().year); p.add_argument("--today",type=date.fromisoformat); p.add_argument("--limit",type=int,default=30); p.add_argument("--out",type=Path,default=OUT); a=p.parse_args()
    if not 1 <= a.limit <= 30: p.error("--limit must be between 1 and 30")
    payload=build(load(a.voices,[]),a.master_db,year=a.year,limit=a.limit,today=a.today,known_venues=load(a.known_venues,[])); a.out.parent.mkdir(parents=True,exist_ok=True); a.out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(f"x gap candidates: {payload['candidate_count']} -> {a.out}")

if __name__ == "__main__": main()
