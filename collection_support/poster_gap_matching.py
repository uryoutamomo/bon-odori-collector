#!/usr/bin/env python3
"""Match poster/flyer posts against events whose date is still unknown.

The poster OCR queue on its own only says "this post has an image and mentions
盆踊り", which was ~1800 items and unreadable in practice. What actually moves
the public site forward is a much smaller set: posts that mention an event we
already know about but whose 開催日 we could not confirm (`date_start` empty),
because those are the ones stuck off the map.

Matching keys are deliberately conservative. Generic names like「盆踊り大会」or
「納涼盆踊り大会」appear in hundreds of unrelated posts, so they are dropped and
only distinctive venue/series names of 4+ characters are used.
"""

import re
import sqlite3

# 「盆踊り大会」「第3回 納涼盆踊り」など、それ単体では会場を特定できない一般名。
GENERIC_NAME_RE = re.compile(
    r"^(?:第?\s*\d+\s*回?\s*)?(?:納涼)?(?:盆踊り|盆おどり|ぼんおどり|盆踊)(?:大会|の夕べ|の会)?$"
    r"|^夏祭り$|^納涼祭$|^納涼大会$"
)
# 「〇〇の盆踊り（名称推定）」は会場名から機械生成した仮名なので、名前としては使わない。
PRESUMED_NAME_RE = re.compile(r"の盆踊り（名称推定）$")
PAREN_RE = re.compile(r"（.*?）|\(.*?\)")

MIN_KEY_LENGTH = 4


def _clean(name):
    return PAREN_RE.sub("", str(name or "")).strip()


def keywords_for(venue_name=None, display_name=None, series_name=None):
    """Distinctive keywords identifying one event. May be empty."""
    keys = set()
    for raw in (venue_name, display_name, series_name):
        name = _clean(raw)
        if not name or len(name) < MIN_KEY_LENGTH:
            continue
        if GENERIC_NAME_RE.match(name) or PRESUMED_NAME_RE.search(name):
            continue
        keys.add(name)
    return keys


def load_date_gap_events(conn, event_year):
    """Read events of `event_year` that still have no confirmed start date."""
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT o.occurrence_id,
               o.display_name,
               s.canonical_name AS series_name,
               v.canonical_name AS venue_name
          FROM event_occurrences o
          LEFT JOIN event_series s ON s.series_id = o.series_id
          LEFT JOIN venues v ON v.venue_id = o.venue_id
         WHERE o.event_year = ?
           AND (o.date_start IS NULL OR o.date_start = '')
        """,
        (event_year,),
    ).fetchall()
    gaps = []
    for row in rows:
        keys = keywords_for(
            venue_name=row["venue_name"],
            display_name=row["display_name"],
            series_name=row["series_name"],
        )
        if not keys:
            continue
        gaps.append({
            "occurrence_id": row["occurrence_id"],
            "event_name": row["display_name"] or row["series_name"] or "",
            "venue_name": row["venue_name"] or "",
            "keywords": sorted(keys),
        })
    return gaps


def match_text(text, gaps):
    """Return [{occurrence_id, event_name, venue_name, matched_keyword}] for one post."""
    text = str(text or "")
    if not text:
        return []
    matches = []
    for gap in gaps:
        for key in gap["keywords"]:
            if key in text:
                matches.append({
                    "occurrence_id": gap["occurrence_id"],
                    "event_name": gap["event_name"],
                    "venue_name": gap["venue_name"],
                    "matched_keyword": key,
                })
                break
    return matches


def annotate(items, gaps):
    """Attach `matched_date_gap_events` to queue items. Returns matched count."""
    matched = 0
    for item in items:
        text = f"{item.get('title') or ''}\n{item.get('text') or ''}"
        found = match_text(text, gaps)
        if found:
            item["matched_date_gap_events"] = found
            matched += 1
    return matched
