#!/usr/bin/env python3
"""Build an X-derived news digest for Oto review.

This script does not call X, Notion, or any LLM. It turns already collected
X-derived voices into an Oto review queue by comparing event, venue, and
song-like information against the local master/public data. The output is not
treated as Oto interpretation yet; it is a filtered reading list with machine
hints.
"""

import argparse
import hashlib
import json
import re
import sqlite3
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from song_processing.bon_odori_songs import extract_song_candidates
from master_rdb.master_db import MASTER_DB, normalize_text
from collection_support.x_source_officiality import assess_source_officiality, load_account_profiles


DATA = Path("data")
PUBLIC_EVENTS = DATA / "public" / "events_public.json"
VENUE_MASTER = DATA / "venue_master.json"
VOICES = DATA / "voices.json"
X_ACCOUNT_CANDIDATES = DATA / "x_candidate_accounts.json"
IMPORTANT_INFORMANTS = DATA / "x_important_informants.json"
OUT_JSON = DATA / "x_news_digest_for_oto.json"
OUT_MD = DATA / "x_news_digest_for_oto.md"

BON_CONTEXT_RE = re.compile(
    r"盆踊り|盆おどり|ぼんおどり|Bon\s*Odori|BON-ODORI|民踊|音頭|曲目|曲順|踊る曲|やぐら|櫓",
    re.I,
)
DATE_HINT_RE = re.compile(
    r"(?:20\d{2}[/-]\d{1,2}[/-]\d{1,2}|20\d{2}年\d{1,2}月\d{1,2}日?|"
    r"\d{1,2}月\d{1,2}日?|\d{1,2}/\d{1,2}|[午前午後]\d{1,2}時|\d{1,2}:\d{2})"
)
POSTER_IMAGE_HINT_RE = re.compile(r"(?:ポスター|チラシ|フライヤー|掲示|回覧|町会|自治会|お知らせ|告知|案内)")
EVENT_NAME_RE = re.compile(
    r"([一-龥ぁ-んァ-ヶA-Za-z0-9・ーｰ（）()「」『』【】#\s]{2,40}"
    r"(?:盆踊り|盆おどり|ぼんおどり|民踊大会|納涼大会|夏祭り|まつり|BON-ODORI|Bon\s*Odori))",
    re.I,
)
QUOTED_RE = re.compile(r"[「『【]([^」』】]{2,40})[」』】]")
VENUE_HINT_RE = re.compile(r"(?:会場|場所|📍|於|ところ)[：:\s]*([^。\n、,]{2,36})")

X_SOURCES = {"x", "x_whitelist", "x_proactive", "x_event_history"}
INTERNAL_EXCERPT_LIMIT = 180


def load_json(path, default):
    if not Path(path).exists():
        return default
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def text_blob(*values):
    return "\n".join(str(value or "") for value in values if value)


def short_text(value, limit=INTERNAL_EXCERPT_LIMIT):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def candidate_id(row, information_type, summary):
    raw = "\0".join([
        row.get("url") or "",
        row.get("tweet_id") or "",
        information_type or "",
        summary or "",
    ])
    return "xoto_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def unique_names(rows):
    seen = set()
    out = []
    for row in rows:
        name = row.get("name") if isinstance(row, dict) else str(row or "")
        if not name:
            continue
        key = normalize_text(name)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def norm_handle(value):
    return str(value or "").strip().lstrip("@").lower()


def load_important_informant_profiles(path=IMPORTANT_INFORMANTS):
    payload = load_json(path, {})
    profiles = {}
    for row in payload.get("accounts") or []:
        if not isinstance(row, dict) or row.get("collection_enabled") is False:
            continue
        handle = norm_handle(row.get("handle"))
        if handle:
            profiles[handle] = row
    return profiles


def load_master_catalog(master_db=MASTER_DB):
    catalog = {"events": [], "venues": [], "songs": []}
    path = Path(master_db)
    if path.exists():
        uri = f"file:{path.as_posix()}?mode=ro"
        try:
            with closing(sqlite3.connect(uri, uri=True)) as conn:
                conn.row_factory = sqlite3.Row
                for row in conn.execute(
                    """
                    SELECT e.series_id AS id, e.canonical_name AS name,
                           e.area AS area, v.canonical_name AS venue
                    FROM event_series e
                    LEFT JOIN venues v ON v.venue_id = e.usual_venue_id
                    WHERE COALESCE(e.status, 'active') != 'rejected'
                    """
                ):
                    catalog["events"].append(dict(row))
                for row in conn.execute(
                    """
                    SELECT venue_id AS id, canonical_name AS name, area, address
                    FROM venues
                    WHERE COALESCE(review_status, 'active') != 'rejected'
                    """
                ):
                    catalog["venues"].append(dict(row))
                for row in conn.execute(
                    """
                    SELECT song_id AS id, canonical_title AS name, category
                    FROM songs
                    WHERE COALESCE(status, 'active') != 'rejected'
                    """
                ):
                    catalog["songs"].append(dict(row))
            return catalog
        except sqlite3.Error as exc:
            print(f"[x-news-digest] Master RDB read failed, falling back to JSON: {exc}")

    for event in load_json(PUBLIC_EVENTS, []):
        catalog["events"].append({
            "id": event.get("id") or "",
            "name": event.get("name") or "",
            "area": event.get("area") or "",
            "venue": event.get("venue") or "",
        })
        if event.get("venue"):
            catalog["venues"].append({
                "id": "",
                "name": event.get("venue"),
                "area": event.get("area") or "",
                "address": event.get("address") or "",
            })
        for song in event.get("songs") or []:
            name = song.get("name") if isinstance(song, dict) else str(song or "")
            if name:
                catalog["songs"].append({"id": "", "name": name, "category": ""})

    for venue in load_json(VENUE_MASTER, []):
        catalog["venues"].append({
            "id": "",
            "name": venue.get("venue") or "",
            "area": venue.get("region") or "",
            "address": venue.get("address") or "",
        })

    for key in catalog:
        catalog[key] = [{"name": name, **row} for name, row in _dedupe_catalog(catalog[key])]
    return catalog


def _dedupe_catalog(rows):
    seen = set()
    for row in rows:
        name = row.get("name") or ""
        key = normalize_text(name)
        if not key or key in seen:
            continue
        seen.add(key)
        yield name, row


def sorted_index(rows, min_len=3):
    indexed = []
    for row in rows:
        name = row.get("name") or ""
        key = normalize_text(name)
        if len(key) < min_len:
            continue
        indexed.append((key, name, row))
    indexed.sort(key=lambda item: (-len(item[0]), item[1]))
    return indexed


def find_matches(text, index, limit=5):
    normalized = normalize_text(text)
    matches = []
    seen = set()
    for key, name, row in index:
        if key in normalized and key not in seen:
            seen.add(key)
            matches.append({
                "name": name,
                "id": row.get("id") or "",
                "area": row.get("area") or "",
                "venue": row.get("venue") or "",
            })
        if len(matches) >= limit:
            break
    return matches


def clean_candidate_name(value):
    value = re.sub(r"https?://\S+|#\S+|@\S+", "", str(value or ""))
    quoted = QUOTED_RE.findall(value)
    for item in reversed(quoted):
        if BON_CONTEXT_RE.search(item):
            value = item
            break
    value = value.strip(" 「」『』【】（）()[]、,。.!！?？\n\t")
    value = re.sub(
        r"^(?:20\d{2}年?|令和\d+年?)?\s*(?:\d{1,2}[/-]\d{1,2}|\d{1,2}[日月火水木金土曜()（）/-]+)\s*",
        "",
        value,
    )
    value = re.sub(r"^(?:本日|今日|明日|昨日|今週末|こちらの|第\d+回|公式]|公式】)\s*", "", value)
    value = re.sub(r"^[A-Za-z0-9_]{2,24}\s+(?=[一-龥ぁ-んァ-ヶ])", "", value)
    value = re.sub(r"^(?:は|が|を|に|で|の|も|と|や|では|から)\s*", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def plausible_event_name(value):
    name = clean_candidate_name(value)
    if not name:
        return False
    if len(name) < 4 or len(name) > 34:
        return False
    if re.match(r"^(?:私|僕|俺|我が家|その|この|あの|みんな|一緒|最近|毎年|今日|昨日)", name):
        return False
    if re.search(r"(?:イベント|お知らせ|好き|行きたい|行って|踊った|観ないと|やっぱり|一応)", name):
        return False
    if re.fullmatch(r"[A-Za-z0-9_\s・ーｰ]+(?:盆踊り|盆おどり|BON-ODORI)", name, re.I):
        return False
    return bool(BON_CONTEXT_RE.search(name))


def plausible_venue_name(value):
    name = clean_candidate_name(value)
    if not name or len(name) < 3 or len(name) > 28:
        return False
    if re.search(r"[♡💕🥳🐥🏝️✨🪩‼️👆]", name):
        return False
    if re.search(r"(?:開催|スタート|待って|みんな|一体|一緒|イベント)", name):
        return False
    return bool(re.search(r"[一-龥ぁ-んァ-ヶ]", name))


def extract_event_like_names(text):
    names = []
    for match in EVENT_NAME_RE.finditer(text or ""):
        name = clean_candidate_name(match.group(1))
        if plausible_event_name(name):
            names.append(name)
    for match in QUOTED_RE.finditer(text or ""):
        name = clean_candidate_name(match.group(1))
        if plausible_event_name(name):
            names.append(name)
    return unique_names(names)


def extract_venue_like_names(text):
    names = []
    for match in VENUE_HINT_RE.finditer(text or ""):
        value = clean_candidate_name(match.group(1))
        value = re.sub(r"(?:にて|で|開催|から|まで).*$", "", value).strip()
        if plausible_venue_name(value):
            names.append(value)
    return unique_names(names)


def classify_information(event_names, venue_names, song_names, event_matches, venue_matches, song_matches, has_date):
    def is_close_to_match(value, matches):
        key = normalize_text(value)
        if not key:
            return False
        for match in matches:
            match_key = normalize_text(match["name"])
            if key == match_key or key in match_key or match_key in key:
                return True
        return False

    new_songs = [
        song for song in song_names
        if not is_close_to_match(song, song_matches)
    ]
    new_venues = [
        venue for venue in venue_names
        if not is_close_to_match(venue, venue_matches)
    ]
    new_events = [
        event for event in event_names
        if not is_close_to_match(event, event_matches)
    ]
    if new_events:
        return "new_event_candidate", "new", f"既存イベントに完全一致しないイベント名候補: {', '.join(new_events[:3])}"
    if event_matches and has_date:
        return "event_update_candidate", "update", "既存イベントに関連する日付・開催情報の可能性"
    if new_songs:
        return "new_song_candidate", "new", f"既存曲マスタにない曲名候補: {', '.join(new_songs[:3])}"
    if song_matches and event_matches:
        return "song_usage_candidate", "update", "既存曲が既存イベントで使われる可能性"
    if new_venues:
        return "new_venue_candidate", "new", f"既存会場に完全一致しない会場候補: {', '.join(new_venues[:3])}"
    if event_matches or venue_matches or song_matches:
        return "atmosphere_or_scale_evidence", "known", "既存情報に近く、新規候補ではなく証拠追加向き"
    return "noise_or_duplicate", "unclear", "イベント・曲・会場としての照合材料が不足"


def is_poster_image_candidate(row, text, important_profiles):
    media_urls = row.get("media_urls") or []
    if not media_urls:
        return False
    handle = norm_handle(row.get("account") or row.get("author"))
    if handle in important_profiles and BON_CONTEXT_RE.search(text):
        return True
    return bool(BON_CONTEXT_RE.search(text) and (POSTER_IMAGE_HINT_RE.search(text) or DATE_HINT_RE.search(text)))


def machine_digest_summary(info_type, event_names, venue_names, song_names, event_matches, venue_matches, text):
    parts = []
    if event_names:
        parts.append(f"イベント候補「{event_names[0]}」に関するX由来情報")
    elif event_matches:
        parts.append(f"既存イベント「{event_matches[0]['name']}」に関するX由来情報")
    elif song_names:
        parts.append(f"曲候補「{song_names[0]}」に関するX由来情報")
    elif venue_names:
        parts.append(f"会場候補「{venue_names[0]}」に関するX由来情報")
    elif venue_matches:
        parts.append(f"既存会場「{venue_matches[0]['name']}」に関するX由来情報")
    else:
        parts.append("盆踊り関連のX由来情報")
    if info_type == "event_poster_ocr_candidate":
        parts.append("画像内のポスター/チラシに開催日・時間・会場が含まれる可能性が高い")
    elif info_type == "event_update_candidate":
        parts.append("開催日・開催有無・場所などの更新情報の可能性がある")
    elif info_type == "song_usage_candidate":
        parts.append("曲目または踊られた曲の証拠になる可能性がある")
    return "。".join(parts) + "。"


def web_queries(event_names, venue_names, song_names, area):
    seeds = []
    for event in event_names[:2]:
        seeds.append(event)
    for venue in venue_names[:2]:
        seeds.append(venue)
    for song in song_names[:2]:
        seeds.append(song)
    queries = []
    for seed in seeds[:4]:
        suffix = f" {area}" if area else ""
        queries.append(f"{seed}{suffix} 盆踊り")
    return queries


def build_candidates(voices, catalog, limit=None, account_profiles=None, important_profiles=None):
    account_profiles = account_profiles or {}
    important_profiles = important_profiles or {}
    event_index = sorted_index(catalog["events"])
    venue_index = sorted_index(catalog["venues"])
    song_index = sorted_index(catalog["songs"])
    candidates = []
    seen_urls = set()

    for row in voices:
        if not isinstance(row, dict) or row.get("source") not in X_SOURCES:
            continue
        url = row.get("url") or ""
        if url and url in seen_urls:
            continue
        text = text_blob(row.get("title"), row.get("text"))
        if not BON_CONTEXT_RE.search(text):
            continue
        seen_urls.add(url)

        event_matches = find_matches(text, event_index)
        venue_matches = find_matches(text, venue_index)
        song_matches = find_matches(text, song_index)
        event_names = extract_event_like_names(text)
        venue_names = extract_venue_like_names(text)
        song_names = unique_names(extract_song_candidates(text))
        has_date = bool(DATE_HINT_RE.search(text))
        info_type, novelty, reason = classify_information(
            event_names,
            venue_names,
            song_names,
            event_matches,
            venue_matches,
            song_matches,
            has_date,
        )
        poster_candidate = is_poster_image_candidate(row, text, important_profiles)
        if info_type == "noise_or_duplicate" and poster_candidate:
            info_type = "event_poster_ocr_candidate"
            novelty = "review_needed"
            reason = "画像付き投稿。ポスター/チラシOCRでイベント名・開催日・時間・会場を抽出すべき候補"
        if info_type == "noise_or_duplicate":
            continue
        if novelty == "known" and not song_matches:
            continue
        area = row.get("area") or (event_matches[0].get("area") if event_matches else "") or (
            venue_matches[0].get("area") if venue_matches else ""
        )
        summary = machine_digest_summary(
            info_type, event_names, venue_names, song_names, event_matches, venue_matches, text
        )
        source_author = row.get("account") or row.get("author") or ""
        candidate = {
            "candidate_id": candidate_id(row, info_type, summary),
            "detected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source_type": "x_post",
            "source_urls": [url] if url else [],
            "source_authors": [source_author] if source_author else [],
            "source_text_excerpt": short_text(text),
            "source_media_urls": row.get("media_urls") or [],
            "oto_review_status": "pending",
            "machine_digest_summary": summary,
            "oto_interpreted_summary": "",
            "oto_novelty_assessment": "",
            "oto_notes": "",
            "information_type": info_type,
            "possible_event_name": event_names[0] if event_names else "",
            "possible_venue": venue_names[0] if venue_names else "",
            "possible_area": area,
            "possible_date_text": "; ".join(match.group(0) for match in DATE_HINT_RE.finditer(text))[:120],
            "possible_song_names": song_names,
            "matched_existing_events": event_matches,
            "matched_existing_venues": venue_matches,
            "matched_existing_songs": song_matches,
            "novelty_assessment": novelty,
            "novelty_reason": reason,
            "confidence": confidence_label(info_type, novelty, event_matches, venue_matches, song_names, has_date),
            "web_backcheck_queries": web_queries(event_names, venue_names, song_names, area),
            "review_status": "new" if novelty in {"new", "update"} else "hold",
            "promotion_target": promotion_target(info_type),
            "source_tags": row.get("tags") or [],
        }
        if poster_candidate:
            handle = norm_handle(source_author)
            trusted_profile = important_profiles.get(handle, {})
            candidate["confidence"] = "high"
            candidate["poster_image_evidence"] = {
                "status": "needs_ocr",
                "priority": "critical" if trusted_profile else "high",
                "evidence_type": "trusted_field_reporter_poster_image"
                if trusted_profile
                else "poster_or_flyer_image",
                "assumed_source_confidence": "high" if trusted_profile else "medium",
                "trusted_informant": bool(trusted_profile),
                "trusted_informant_rank": trusted_profile.get("usefulness_rank") or "",
                "ocr_target_fields": ["event_name", "date", "time", "venue", "organizer"],
            }
        candidate["source_officiality"] = assess_source_officiality(
            candidate,
            voice=row,
            account_profiles={**account_profiles, **important_profiles},
        )
        candidates.append(candidate)
        if limit and len(candidates) >= limit:
            break

    candidates.sort(key=lambda row: (
        information_type_sort(row["information_type"]),
        confidence_sort(row["confidence"]),
        row["possible_area"] or "",
        row["possible_event_name"] or row["possible_venue"] or "",
    ))
    return candidates


def confidence_label(info_type, novelty, event_matches, venue_matches, song_names, has_date):
    if info_type == "event_poster_ocr_candidate":
        return "high"
    if novelty == "new" and (event_matches or venue_matches or has_date):
        return "medium"
    if info_type == "event_update_candidate" and has_date:
        return "medium"
    if song_names and (event_matches or venue_matches):
        return "medium"
    if novelty in {"new", "update"}:
        return "low"
    return "hold"


def confidence_sort(value):
    return {"high": 0, "medium": 1, "low": 2, "hold": 3}.get(value, 9)


def information_type_sort(value):
    return {
        "event_update_candidate": 0,
        "event_poster_ocr_candidate": 1,
        "new_song_candidate": 2,
        "song_usage_candidate": 3,
        "new_venue_candidate": 4,
        "new_event_candidate": 5,
        "atmosphere_or_scale_evidence": 6,
    }.get(value, 9)


def promotion_target(info_type):
    if info_type in {"new_event_candidate", "event_update_candidate", "event_poster_ocr_candidate"}:
        return "event"
    if info_type in {"new_song_candidate", "song_usage_candidate"}:
        return "song"
    if info_type == "new_venue_candidate":
        return "venue"
    if info_type == "atmosphere_or_scale_evidence":
        return "existing_evidence"
    return "none"


def build(voices_path=VOICES, master_db=MASTER_DB, limit=None):
    voices = load_json(voices_path, [])
    catalog = load_master_catalog(master_db)
    account_profiles = load_account_profiles(X_ACCOUNT_CANDIDATES)
    important_profiles = load_important_informant_profiles()
    candidates = build_candidates(
        voices,
        catalog,
        limit=limit,
        account_profiles=account_profiles,
        important_profiles=important_profiles,
    )
    counts = Counter(row["information_type"] for row in candidates)
    novelty_counts = Counter(row["novelty_assessment"] for row in candidates)
    officiality_counts = Counter(
        (row.get("source_officiality") or {}).get("classification") or "unknown"
        for row in candidates
    )
    return {
        "generated_by": "build_x_news_digest_for_oto.py",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input": {
            "voices": str(voices_path),
            "master_db": str(master_db),
        },
        "summary": {
            "candidate_count": len(candidates),
            "information_type_counts": dict(sorted(counts.items())),
            "novelty_counts": dict(sorted(novelty_counts.items())),
            "source_officiality_counts": dict(sorted(officiality_counts.items())),
        },
        "candidates": candidates,
    }


def md_cell(value):
    text = str(value or "").replace("\n", " ").replace("|", "\\|")
    return text[:180] + "..." if len(text) > 180 else text


def write_markdown(data, path):
    lines = [
        "# X News Digest For Oto",
        "",
        f"- generated_at: {data['generated_at']}",
        f"- digest_count: {data['summary']['candidate_count']}",
        "- status: machine prefilter; Oto interpretation pending",
        "",
        "| confidence | type | machine novelty | target | machine summary | machine reason | backcheck | source |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in data["candidates"]:
        lines.append(
            f"| {md_cell(row['confidence'])} | {md_cell(row['information_type'])} | "
            f"{md_cell(row['novelty_assessment'])} | {md_cell(row['promotion_target'])} | "
            f"{md_cell(row['machine_digest_summary'])} | {md_cell(row['novelty_reason'])} | "
            f"{md_cell('; '.join(row.get('web_backcheck_queries') or []))} | "
            f"{md_cell((row.get('source_urls') or [''])[0])} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--voices", type=Path, default=VOICES)
    parser.add_argument("--master-db", type=Path, default=MASTER_DB)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    data = build(args.voices, args.master_db, limit=args.limit)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(data, args.out_md)
    print(
        f"x news digest for oto: {data['summary']['candidate_count']} "
        f"-> {args.out_json} / {args.out_md}"
    )


if __name__ == "__main__":
    main()
