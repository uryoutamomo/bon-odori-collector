"""Build a review queue for promoting useful observed occurrences.

This is a dry-run helper for the master-RDB migration. It reads observed
occurrences and song_occurrences evidence, then proposes historical-reference
promotion candidates without writing to Notion or public JSON.
"""

import argparse
import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from master_rdb.master_db import MASTER_DB, MASTER_MANIFEST, connect_existing, normalize_text


DATA = Path("data")
SONG_OCCURRENCES = DATA / "song_occurrences.json"
OUT_JSON = DATA / "observed_promotion_candidates.json"
OUT_MD = DATA / "observed_promotion_candidates.md"

TOKYO_23_HINT_RE = re.compile(
    r"(東京都)?("
    r"千代田区|中央区|港区|新宿区|文京区|台東区|墨田区|江東区|品川区|目黒区|大田区|世田谷区|"
    r"渋谷区|中野区|杉並区|豊島区|北区|荒川区|板橋区|練馬区|足立区|葛飾区|江戸川区"
    r")"
)
DATE_RE = re.compile(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})日?")
EVENT_WORD_RE = re.compile(r"(盆踊り大会|盆おどり大会|盆踊り|盆おどり|納涼盆踊り大会|納涼盆踊り|夏祭り|まつり)")
NOISE_PREFIX_RE = re.compile(
    r"^(?:【[^】]{1,40}】|「[^」]{1,40}」|\[[^\]]{1,40}\]|[A-Za-z0-9 .,'!~・ー（）()]+(?:音頭|節|ヒーロー|ママ|ブギ|カンカン娘)[^ ]*)\s*"
)
GENERIC_TOKENS = {
    normalize_text(value)
    for value in [
        "盆踊り大会",
        "盆おどり大会",
        "盆踊り",
        "盆おどり",
        "納涼盆踊り大会",
        "納涼盆踊り",
        "夏祭り",
        "まつり",
        "祭り",
    ]
}


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rows(db_path, query, params=()):
    with connect_existing(db_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(query, params)]


def iso_date(match):
    y, m, d = [int(part) for part in match.groups()]
    return f"{y:04d}-{m:02d}-{d:02d}"


def all_dates(occurrence):
    dates = []
    for song in occurrence.get("songs") or []:
        for ev in song.get("evidence") or []:
            for key in ("date", "event_start", "detected_event_date"):
                value = ev.get(key)
                if isinstance(value, str) and re.match(r"^20\d{2}-\d{2}-\d{2}$", value):
                    dates.append(value)
            text = ev.get("text") or ""
            dates.extend(iso_date(match) for match in DATE_RE.finditer(text))
    return sorted(set(dates))


def strip_song_prefix(text):
    value = str(text or "").strip()
    previous = None
    while previous != value:
        previous = value
        value = NOISE_PREFIX_RE.sub("", value).strip()
    return value


def extract_event_name(raw):
    value = strip_song_prefix(raw)
    value = re.sub(r"^\d{4}年?", "", value).strip()
    # Stop before common venue/address tails when they are clearly separated.
    value = re.split(r"\s+(?:東京都|中央区|港区|新宿区|台東区|豊島区|京橋プラザ|中央区京橋プラザ)", value, maxsplit=1)[0]
    value = re.sub(r"[0-9０-９]{1,3}(?:終)?$", "", value).strip()
    # Keep parenthetical organizer text when it is part of disambiguation.
    return value[:120]


def extract_organizers(raw):
    organizers = []
    for value in re.findall(r"[（(]([^）)]+)[）)]", raw or ""):
        if "町会" in value or "自治会" in value or "商店会" in value:
            organizers.append(re.sub(r"\s+", " ", value).strip())
    return sorted(set(organizers))


def extract_venue(raw):
    text = raw or ""
    known = [
        "中央区京橋プラザ",
        "京橋プラザ",
        "京橋プラザ区民館",
        "京橋公園",
        "隅田公園山谷堀広場",
        "新宿太宗寺",
        "太宗寺境内",
        "大正大学",
        "銀座通り 3丁目交差点",
        "銀座3丁目交差点",
        "銀座SIX",
    ]
    for venue in known:
        if venue in text:
            if venue == "中央区京橋プラザ":
                return "京橋プラザ"
            return venue
    # Tail after organizer parentheses often holds the venue.
    match = re.search(r"[（(][^）)]*(?:町会|自治会|商店会)[^）)]*[）)]\s*([^ ]{2,30})", text)
    if match:
        venue = match.group(1).strip()
        venue = re.sub(r"^(東京都|中央区|港区|新宿区|台東区|豊島区)", "", venue)
        venue = re.sub(r"[0-9０-９]{1,3}(?:終)?$", "", venue)
        if venue and not EVENT_WORD_RE.search(venue):
            return venue[:40]
    return ""


def token_set(text):
    tokens = set()
    for part in re.split(r"[・\s　/／（）()「」『』【】,、]+", text or ""):
        part = part.strip()
        if len(part) >= 3:
            tokens.add(normalize_text(part))
    return {token for token in tokens if token and token not in GENERIC_TOKENS}


def load_curated_events(db_path):
    data = rows(
        db_path,
        """
        SELECT o.occurrence_id, o.series_id, s.canonical_name, o.event_year, o.date_start,
               o.venue_id, v.canonical_name AS venue
        FROM event_occurrences o
        JOIN event_series s ON s.series_id = o.series_id
        LEFT JOIN venues v ON v.venue_id = o.venue_id
        WHERE o.origin = 'curated'
        """,
    )
    for row in data:
        row["tokens"] = token_set(row["canonical_name"])
        row["needs_enrichment"] = (not row.get("date_start")) or (not row.get("venue_id"))
    return data


def best_curated_match(raw_text, extracted_event, curated_events):
    raw_norm = normalize_text(raw_text)
    event_norm = normalize_text(extracted_event)
    best = None
    for row in curated_events:
        score = 0
        matched_tokens = []
        for token in row["tokens"]:
            if token and token in raw_norm:
                score += 2 if len(token) >= 6 else 1
                matched_tokens.append(token)
        canonical_norm = normalize_text(row["canonical_name"])
        if (
            canonical_norm
            and canonical_norm not in GENERIC_TOKENS
            and len(canonical_norm) >= 8
            and (canonical_norm in raw_norm or event_norm in canonical_norm or canonical_norm in event_norm)
        ):
            score += 4
        if not row["needs_enrichment"]:
            score -= 1
        if score <= 0 or not matched_tokens and score < 4:
            continue
        candidate = {**row, "match_score": score, "matched_tokens": matched_tokens}
        if best is None or candidate["match_score"] > best["match_score"]:
            best = candidate
    return best


def occurrence_by_id(path):
    data = load_json(path, {})
    return {
        row.get("occurrence_id"): row
        for row in data.get("occurrences") or []
        if row.get("occurrence_id")
    }


def build_candidates(db_path, song_occurrences_path):
    observed = rows(
        db_path,
        """
        SELECT observed_occurrence_id, source_occurrence_id, raw_event_name, raw_venue_name,
               event_year, quality_status, quality_flags_json
        FROM observed_occurrences
        WHERE quality_status IN ('review', 'discard_candidate')
        """,
    )
    curated_events = load_curated_events(db_path)
    song_by_id = occurrence_by_id(song_occurrences_path)
    grouped = {}
    skipped = Counter()

    for row in observed:
        source = song_by_id.get(row["source_occurrence_id"]) or {}
        dates = all_dates(source)
        raw_text = " ".join([row.get("raw_event_name") or "", row.get("raw_venue_name") or ""])
        tokyo_hint = bool(TOKYO_23_HINT_RE.search(raw_text)) or "tokyo_23_hint" in (row.get("quality_flags_json") or "")
        if not dates:
            skipped["missing_date"] += 1
            continue
        if not tokyo_hint:
            skipped["no_tokyo_23_hint"] += 1
            continue
        extracted_event = extract_event_name(row.get("raw_event_name") or "")
        extracted_venue = extract_venue(row.get("raw_venue_name") or row.get("raw_event_name") or "")
        organizers = extract_organizers(raw_text)
        match = best_curated_match(raw_text, extracted_event, curated_events)
        if not match:
            skipped["no_curated_match"] += 1
            continue

        key = (
            match["occurrence_id"],
            dates[0],
            extracted_venue,
            normalize_text(" ".join(organizers)),
        )
        candidate = grouped.setdefault(key, {
            "candidate_key": "|".join(str(item or "") for item in key),
            "target_occurrence_id": match["occurrence_id"],
            "target_event_name": match["canonical_name"],
            "target_event_year": match["event_year"],
            "target_current_date": match.get("date_start") or "",
            "target_current_venue": match.get("venue") or "",
            "proposed_event_name": extracted_event,
            "proposed_venue": extracted_venue,
            "proposed_dates": set(),
            "organizers": set(),
            "match_score": match["match_score"],
            "matched_tokens": set(match["matched_tokens"]),
            "source_occurrence_ids": set(),
            "source_rows": [],
            "song_titles": set(),
            "evidence_urls": set(),
            "quality_statuses": Counter(),
        })
        candidate["proposed_dates"].update(dates)
        candidate["organizers"].update(organizers)
        candidate["source_occurrence_ids"].add(row["source_occurrence_id"])
        candidate["quality_statuses"][row["quality_status"]] += 1
        for song in source.get("songs") or []:
            if song.get("song_name"):
                candidate["song_titles"].add(song["song_name"])
            for ev in song.get("evidence") or []:
                if ev.get("url"):
                    candidate["evidence_urls"].add(ev["url"])
        candidate["source_rows"].append({
            "observed_occurrence_id": row["observed_occurrence_id"],
            "source_occurrence_id": row["source_occurrence_id"],
            "raw_event_name": row["raw_event_name"],
            "raw_venue_name": row["raw_venue_name"],
            "quality_status": row["quality_status"],
            "quality_flags_json": row["quality_flags_json"],
        })

    candidates = []
    for item in grouped.values():
        dates = sorted(item.pop("proposed_dates"))
        source_ids = sorted(item.pop("source_occurrence_ids"))
        songs = sorted(item.pop("song_titles"))
        urls = sorted(item.pop("evidence_urls"))
        organizers = sorted(item.pop("organizers"))
        matched_tokens = sorted(item.pop("matched_tokens"))
        quality_statuses = dict(item.pop("quality_statuses"))
        item.update({
            "proposed_date_start": dates[0] if dates else "",
            "proposed_date_end": dates[-1] if len(dates) > 1 else "",
            "proposed_date_values": dates,
            "organizers": organizers,
            "matched_tokens": matched_tokens,
            "source_occurrence_ids": source_ids,
            "source_occurrence_count": len(source_ids),
            "song_titles_sample": songs[:20],
            "song_title_count": len(songs),
            "evidence_urls_sample": urls[:10],
            "evidence_url_count": len(urls),
            "quality_status_counts": quality_statuses,
            "promotion_confidence": "high" if item["match_score"] >= 4 else "medium" if item["match_score"] >= 3 else "low",
            "recommended_action": (
                "review_then_promote_historical_reference"
                if item["match_score"] >= 3
                else "manual_review_low_confidence"
            ),
        })
        candidates.append(item)
    candidates.sort(
        key=lambda row: (
            -row["match_score"],
            -row["source_occurrence_count"],
            row["target_event_name"],
            row["proposed_date_start"],
        )
    )
    return candidates, skipped


def render_markdown(data):
    lines = [
        "# Observed occurrence promotion candidates",
        "",
        f"- generated_at: {data['generated_at']}",
        f"- candidate_count: {data['summary']['candidate_count']}",
        f"- skipped: {data['summary']['skipped']}",
        "",
        "| score | target | proposed event | venue | date | sources | songs | action |",
        "| ---: | --- | --- | --- | --- | ---: | ---: | --- |",
    ]
    for row in data["candidates"][:120]:
        lines.append(
            f"| {row['match_score']} | {row['target_event_name']} | {row['proposed_event_name']} | "
            f"{row['proposed_venue']} | {row['proposed_date_start']} | "
            f"{row['source_occurrence_count']} | {row['song_title_count']} | {row['recommended_action']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(MASTER_DB))
    parser.add_argument("--song-occurrences", default=str(SONG_OCCURRENCES))
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    parser.add_argument("--manifest", default=str(MASTER_MANIFEST))
    args = parser.parse_args()

    candidates, skipped = build_candidates(Path(args.db), Path(args.song_occurrences))
    data = {
        "generated_by": "build_observed_promotion_candidates.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "db": str(args.db),
            "song_occurrences": str(args.song_occurrences),
        },
        "summary": {
            "candidate_count": len(candidates),
            "candidates_by_confidence": dict(Counter(row["promotion_confidence"] for row in candidates)),
            "skipped": dict(skipped),
        },
        "candidates": candidates,
    }
    write_json(args.out_json, data)
    Path(args.out_md).write_text(render_markdown(data), encoding="utf-8")

    manifest_path = Path(args.manifest)
    if manifest_path.exists():
        with manifest_path.open(encoding="utf-8") as f:
            manifest = json.load(f)
        manifest.setdefault("post_build_outputs", {})
        manifest["post_build_outputs"]["observed_promotion_candidates"] = str(args.out_json)
        manifest.setdefault("post_build_steps", [])
        if "build_observed_promotion_candidates.py" not in manifest["post_build_steps"]:
            manifest["post_build_steps"].append("build_observed_promotion_candidates.py")
        write_json(manifest_path, manifest)

    print(
        "observed promotion candidates: "
        f"candidates={len(candidates)} skipped={dict(skipped)}"
    )


if __name__ == "__main__":
    main()
