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
from collection_support.tokyo23_scope import is_outside_tokyo_23_scope

DATA = Path("data")
VOICES = DATA / "voices.json"
OUT = DATA / "x_gap_candidates.json"
X_SOURCES = {"x", "x_whitelist", "x_proactive", "x_event_history"}
DATE_RE = re.compile(r"(?:20\d{2}[/-]\d{1,2}[/-]\d{1,2}|\d{1,2}月\d{1,2}日?|\d{1,2}/\d{1,2}|\d{1,2}時)")
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
EVENTISH_RE = re.compile(r"盆踊り|盆おどり|ぼんおどり|納涼|夏まつり|夏祭り", re.I)
VENUEISH_RE = re.compile(r"会場|公園|神社|寺|学校|商店街|広場|駅前|前(?:\b|で|に)")


def load(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def catalog(db: Path, year: int) -> list[dict[str, str]]:
    """Current-year occurrences and all canonical/alias names for matching."""
    uri = f"file:{db.resolve().as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("""
          SELECT o.occurrence_id, o.display_name, o.date_start, e.canonical_name, e.area,
                 v.canonical_name AS venue
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
                       "area":row["area"] or "", "aliases":[n for n in names if n]})
    return result


def matches(text: str, row: dict[str, Any]) -> list[str]:
    normalized=normalize_text(text)
    return [name for name in row["aliases"] if discriminative_alias(name) and normalize_text(name) in normalized]


def discriminative_alias(name: str) -> bool:
    """Reject generic labels such as ``盆踊り大会`` as identity keys."""
    text=re.sub(r"\s+", "", str(name or ""))
    return len(normalize_text(text)) >= 5 and not GENERIC_EVENT_RE.fullmatch(text)


def actual_schedule_change(text: str) -> bool:
    return bool(CHANGE_RE.search(text) and not NON_CHANGE_RE.search(text) and ACTUAL_CHANGE_RE.search(text))


def source_key(voice: dict[str, Any]) -> str:
    url=str(voice.get("url") or "")
    tweet=str(voice.get("tweet_id") or voice.get("id") or "")
    return "x:" + (tweet or hashlib.sha1(url.encode()).hexdigest()[:16])


def build(voices: list[dict[str, Any]], db: Path, *, year: int, limit: int=30, today: date | None=None) -> dict[str, Any]:
    gaps=catalog(db, year)
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
        found=[(gap, matches(text, gap)) for gap in gaps]
        found=[(gap, names) for gap,names in found if names]
        kind=""; priority=0; gap=None; names=[]
        # A matched master row can itself reveal a non-23-ward legacy entry.
        found=[(g,n) for g,n in found if not is_outside_tokyo_23_scope(g.get("area"),g.get("venue")) and not EXTRA_OUTSIDE_SCOPE_RE.search(f"{g.get('area','')} {g.get('venue','')}")]
        # Never surface a cancellation/update for an occurrence already in
        # the past.  Its evidence remains in the corpus but cannot correct a
        # current public schedule.
        found=[(g,n) for g,n in found if not g.get("date_start") or date.fromisoformat(g["date_start"]) >= today]
        changes=actual_schedule_change(text)
        if changes and found:
            kind="schedule_change"; priority=300; gap,names=found[0]
        else:
            missing=[(g,n) for g,n in found if not g["date_start"] and DATE_RE.search(text)]
            if missing: kind="missing_date"; priority=200; gap,names=missing[0]
            elif official and not found and DATE_RE.search(text) and EVENTISH_RE.search(text) and VENUEISH_RE.search(text): kind="official_new_event"; priority=100
            else: continue
        seen.add(key)
        candidates.append({"candidate_id":"xgap_"+hashlib.sha1(key.encode()).hexdigest()[:16], "source_key":key,
          "lane_hint":"lane1" if official and kind in {"missing_date","schedule_change"} else "lane2",
          "candidate_kind":kind, "priority_score":priority + (20 if official else 0), "event_year":year,
          "matched_occurrence": ({"occurrence_id":gap["occurrence_id"],"event_name":gap["event_name"],"venue":gap["venue"],"matched_aliases":names} if gap else None),
          "source_url":voice.get("url") or "", "source_text":text[:500], "source_author":voice.get("account") or voice.get("author") or "",
          "source_officiality":officiality, "date_hints":DATE_RE.findall(text), "voice":voice})
    candidates.sort(key=lambda x:(-x["priority_score"], x["source_key"]))
    selected=[]; archived=[]; official_new_event_count=0
    for candidate in candidates:
        if candidate['candidate_kind']=='official_new_event':
            if official_new_event_count >= OFFICIAL_NEW_EVENT_CAP:
                candidate={**candidate,'archive_reason':'official_new_event_daily_cap'}
                archived.append(candidate); continue
            official_new_event_count += 1
        if len(selected) < limit: selected.append(candidate)
        else: archived.append({**candidate,'archive_reason':'daily_candidate_cap'})
    return {"generated_by":"build_x_gap_candidates.py", "generated_at":datetime.now(timezone.utc).isoformat(),
            "limit":limit, "official_new_event_limit":OFFICIAL_NEW_EVENT_CAP, "candidate_count":len(selected), "archived_count":len(archived), "candidates":selected,
            "archived_candidates":archived}


def main() -> None:
    p=argparse.ArgumentParser(); p.add_argument("--voices",type=Path,default=VOICES); p.add_argument("--master-db",type=Path,default=MASTER_DB); p.add_argument("--year",type=int,default=datetime.now().year); p.add_argument("--limit",type=int,default=30); p.add_argument("--out",type=Path,default=OUT); a=p.parse_args()
    if not 1 <= a.limit <= 30: p.error("--limit must be between 1 and 30")
    payload=build(load(a.voices,[]),a.master_db,year=a.year,limit=a.limit); a.out.parent.mkdir(parents=True,exist_ok=True); a.out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); print(f"x gap candidates: {payload['candidate_count']} -> {a.out}")

if __name__ == "__main__": main()
