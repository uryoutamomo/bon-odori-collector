"""Extract structured YouTube setlist occurrences from voices.json."""

import argparse
import hashlib
import json
import re
import tempfile
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from song_processing.song_occurrences import parse_event_date


DATA = Path("data")
VOICES = DATA / "voices.json"
YOUTUBE_REVIEW = DATA / "youtube_song_candidates_review.json"
PUBLIC_EVENTS = DATA / "public" / "events_public.json"
OUT = DATA / "youtube_setlist_occurrences.json"

URL_RE = re.compile(r"https?://(?:youtu\.be|www\.youtube\.com)[^\s、。，)）]+")
SETLIST_ITEM_RE = re.compile(
    r"(?:^|\n|\s)([0-9０-９]{1,2})\s*([^\n\r]+?)\s+"
    r"(https?://(?:youtu\.be|www\.youtube\.com)[^\s、。，)）]+)"
)
EVENT_LINE_STOP_RE = re.compile(r"^[0-9０-９]{1,2}\s*")
PARENS_RE = re.compile(r"[「」『』【】\[\]（）()]")
SPACE_RE = re.compile(r"\s+")
COMPACT_DATE_RE = re.compile(r"(20\d{2})(\d{2})(\d{2})")
DOT_DATE_RE = re.compile(r"(20\d{2})\.(\d{1,2})\.(\d{1,2})")
BON_CONTEXT_RE = re.compile(r"(盆踊り|輪踊り|郡上おどり|民踊|民謡|音頭|踊り)")
EVENT_CONTEXT_RE = re.compile(
    r"(盆踊り|輪踊り|Bon\s*Odori|Bon\s*Dance|Bondance|納涼踊り|夏祭り|祭り|Festival)",
    re.I,
)
TITLE_DECORATION_RE = re.compile(r"^\s*(?:\[[^\]]*(?:4K|HDR)[^\]]*\]|【[^】]*(?:4K|HDR)[^】]*】)\s*", re.I)
TITLE_HASH_RE = re.compile(r"#\S+")
TITLE_DATE_RE = re.compile(
    r"(?:20\d{2}年\d{1,2}月\d{1,2}日|20\d{2}[./]\d{1,2}[./]\d{1,2}|20\d{6})"
)
TITLE_TRAILING_PLACE_RE = re.compile(r"\s+(?:in|at)\s+(?:Tokyo|Japan|Tokyo Japan|Shinjuku,?\s*Tokyo).*$", re.I)
TITLE_SONG_QUOTES_RE = re.compile(r"[「『\"“]([^」』\"”]{1,80})[」』\"”]")
TITLE_NUMBER_RE = re.compile(r"(?:^|\s)(?:part|pt\.?|第)?\s*[0-9０-９]{1,2}(?:部|曲目?|終)?(?:\s|[:：])", re.I)
KNOWN_TITLE_EVENT_PATTERNS = (
    r"GMOシブヤエンタメ祭",
    r"SHIBUYA MIYASHITA PARK BON DANCE",
    r"Kabukicho Bon Odori",
    r"Jiyugaoka Bon Odori(?: Festival)?",
    r"Oku-?Asakusa Bon (?:Dance|Odori)(?: Festival)?",
    r"OkuAsakusa Bon Dance",
    r"Ohdai Bon Odori",
    r"鴨台盆踊り",
    r"大正大学盆踊り",
    r"戸田ふるさと祭り",
    r"恵比寿駅前盆踊り大会",
    r"飛鳥山盆踊り",
    r"飛鳥山公園輪踊り",
    r"横浜開港祭 BON ODORI",
    r"山王音頭と民踊大会",
    r"赤坂日枝神社山王祭盆踊り",
    r"浅草夜祭・アキバ盆踊り",
    r"国立旭通りジューンフェスタ盆踊り",
    r"千住・人情芸術祭",
)
TRAILING_NOISE_HEADING_RE = re.compile(
    r"^\s*(?:▽?\s*)?(?:Related Videos?\b|関連動画\b|backgrou?d music\b|BGM\b|Opening Music\b|Ending Music\b|【(?:AI songs|4K [^】]+)】)",
    re.I,
)


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=".tmp-", suffix=".json", delete=False
    ) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        tmp_name = handle.name
    Path(tmp_name).replace(path)


def normalize_text(value):
    return SPACE_RE.sub(" ", unicodedata.normalize("NFKC", str(value or ""))).strip()


def normalize_key(value):
    value = normalize_text(value)
    value = PARENS_RE.sub("", value)
    return re.sub(r"\W+", "", value).casefold()


def compact_url(url):
    url = str(url or "").strip()
    if "youtu.be/" in url:
        video_id = url.split("youtu.be/", 1)[1].split("?", 1)[0].split("&", 1)[0]
        return f"https://www.youtube.com/watch?v={video_id}"
    return url


def primary_description_text(text):
    lines = []
    for line in str(text or "").splitlines():
        if TRAILING_NOISE_HEADING_RE.search(line):
            break
        lines.append(line)
    return "\n".join(lines)


def occurrence_key(venue, event_date):
    raw = f"{normalize_key(venue)}\0{event_date or ''}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def parse_youtube_event_date(*texts):
    parsed = parse_event_date(*texts)
    if parsed:
        return parsed
    for text in texts:
        dot_match = DOT_DATE_RE.search(str(text or ""))
        if dot_match:
            year, month, day = [int(part) for part in dot_match.groups()]
            if 1 <= month <= 12 and 1 <= day <= 31:
                return f"{year:04d}-{month:02d}-{day:02d}"
        match = COMPACT_DATE_RE.search(str(text or ""))
        if not match:
            continue
        year, month, day = [int(part) for part in match.groups()]
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    return None


def extract_setlist(text):
    rows = []
    seen = set()
    for match in SETLIST_ITEM_RE.finditer(primary_description_text(text)):
        number = int(unicodedata.normalize("NFKC", match.group(1)))
        title = normalize_text(match.group(2))
        title = URL_RE.sub("", title).strip(" 　-:：、。")
        if re.fullmatch(r"[0-9０-９]+", title):
            continue
        url = compact_url(match.group(3))
        if not title or len(title) > 80:
            continue
        key = (number, normalize_key(title), url)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"number": number, "title": title, "url": url})
    rows.sort(key=lambda row: (row["number"], row["title"]))
    return rows


def has_bon_context(voice, setlist):
    text = "\n".join([voice.get("title") or "", primary_description_text(voice.get("text") or "")])
    if BON_CONTEXT_RE.search(text):
        return True
    return sum(1 for item in setlist if BON_CONTEXT_RE.search(item.get("title") or "")) >= 2


def first_setlist_line_index(lines):
    for idx, line in enumerate(lines):
        if EVENT_LINE_STOP_RE.match(normalize_text(line)):
            return idx
    return -1


def event_label_from_text(text):
    lines = [normalize_text(line) for line in primary_description_text(text).splitlines()]
    lines = [line for line in lines if line]
    idx = first_setlist_line_index(lines)
    if idx > 0:
        for line in reversed(lines[:idx]):
            if len(line) <= 80 and not URL_RE.search(line) and not re.search(r"チャンネル登録|高評価|コメント", line):
                return line
    return ""


def title_prefix_before_date(title):
    title = normalize_text(title)
    match = re.search(r"20\d{2}年\d{1,2}月\d{1,2}日", title)
    if not match:
        return title
    return normalize_text(title[:match.start()])


def clean_title_piece(value):
    value = normalize_text(value)
    value = TITLE_DECORATION_RE.sub("", value)
    value = TITLE_HASH_RE.sub("", value)
    value = TITLE_DATE_RE.sub("", value)
    value = TITLE_TRAILING_PLACE_RE.sub("", value)
    value = re.sub(r"^[|｜/／:：・\-\s]+|[|｜/／:：・\-\s]+$", "", value)
    return normalize_text(value)


def clean_event_title(value):
    value = clean_title_piece(value)
    value = re.sub(r"^(?:第[0-9０-９]+回\s*)", "", value)
    value = re.sub(r"\s*20\d{2}\s*$", "", value)
    value = re.sub(r"\s+[0-9０-９]{1,2}(?:部|終)?$", "", value)
    return clean_title_piece(value)


def clean_song_from_title(value):
    value = clean_title_piece(value)
    value = re.sub(r"^[^0-9A-Za-z一-龥ぁ-んァ-ヶー「『\"“]+", "", value)
    value = re.sub(r"^(?:終|ラスト|最後)\s*", "", value)
    value = re.sub(r"\s*(?:激盛り|盛り上がり|大盛況|大熱狂).*$", "", value)
    value = re.sub(r"\s+で盆踊り.*$", "", value)
    value = re.sub(r"\s+Bon dance to .*$", "", value, flags=re.I)
    value = re.sub(r"\s+(?:盆踊り|Bon Odori|Bon Dance)\s*$", "", value, flags=re.I)
    return clean_title_piece(value)


def title_looks_like_song(value):
    value = clean_song_from_title(value)
    if not value or len(value) > 80:
        return False
    if EVENT_CONTEXT_RE.search(value) and not re.search(r"^JAME盆踊り\s+", value, re.I):
        return False
    if TITLE_NUMBER_RE.search(value):
        return False
    return bool(re.search(r"[A-Za-z一-龥ぁ-んァ-ヶー]", value))


def known_event_match(title):
    best = None
    for pattern in KNOWN_TITLE_EVENT_PATTERNS:
        match = re.search(pattern, title, re.I)
        if not match:
            continue
        event_name = clean_event_title(match.group(0))
        if not event_name:
            continue
        if best is None or len(event_name) > len(best["event_name"]):
            best = {
                "event_name": event_name,
                "start": match.start(),
                "end": match.end(),
            }
    return best


def split_title_event_song(title):
    raw_title = normalize_text(title)
    if not raw_title or not EVENT_CONTEXT_RE.search(raw_title):
        return None

    title = clean_title_piece(raw_title)
    quoted = TITLE_SONG_QUOTES_RE.search(title)
    bracket_event = re.search(r"【([^】]*(?:盆踊り|Bon\s*Odori|Bon\s*Dance|Bondance)[^】]*)】", title, re.I)
    known_event = known_event_match(title)
    if quoted and bracket_event:
        return {
            "event_name": clean_event_title(bracket_event.group(1)),
            "song_title": clean_song_from_title(quoted.group(1)),
            "method": "bracket_event_and_quote",
        }
    if quoted and known_event:
        return {
            "event_name": known_event["event_name"],
            "song_title": clean_song_from_title(quoted.group(1)),
            "method": "quote_and_known_event",
        }

    if quoted:
        before = clean_event_title(title[:quoted.start()])
        after = clean_event_title(title[quoted.end():])
        event_name = after if EVENT_CONTEXT_RE.search(after) else before
        if event_name:
            return {
                "event_name": event_name,
                "song_title": clean_song_from_title(quoted.group(1)),
                "method": "quoted_song",
            }

    at_match = re.search(r"\s+(?:at|in)\s+(.+)$", title, re.I)
    if at_match:
        event_name = clean_event_title(at_match.group(1))
        song_title = clean_song_from_title(title[:at_match.start()])
        if event_name and title_looks_like_song(song_title):
            return {"event_name": event_name, "song_title": song_title, "method": "at_event"}

    if known_event:
        before = clean_song_from_title(title[:known_event["start"]])
        after = clean_song_from_title(title[known_event["end"]:])
        song_title = before if title_looks_like_song(before) else after
        if title_looks_like_song(song_title):
            return {
                "event_name": known_event["event_name"],
                "song_title": song_title,
                "method": "known_event",
            }

    slash_parts = [clean_title_piece(part) for part in re.split(r"\s*[|｜/／]\s*", title)]
    event_parts = [part for part in slash_parts if EVENT_CONTEXT_RE.search(part)]
    song_parts = [part for part in slash_parts if title_looks_like_song(part)]
    if event_parts and song_parts:
        return {
            "event_name": clean_event_title(event_parts[-1]),
            "song_title": clean_song_from_title(song_parts[0]),
            "method": "slash_parts",
        }

    parts = [clean_title_piece(part) for part in re.split(r"\s{2,}|　+", title)]
    event_parts = [part for part in parts if EVENT_CONTEXT_RE.search(part)]
    song_parts = [part for part in parts if title_looks_like_song(part)]
    if event_parts and song_parts:
        return {
            "event_name": clean_event_title(event_parts[-1]),
            "song_title": clean_song_from_title(song_parts[0]),
            "method": "space_parts",
        }

    return None


def is_title_fragment_setlist(setlist):
    return bool(setlist) and all(item.get("evidence_type") == "title_song_fragment" for item in setlist)


def infer_event_and_venue(voice, review_map):
    url = compact_url(voice.get("url"))
    if url in review_map:
        return review_map[url]["event_name"], review_map[url]["venue"], review_map[url]["event_key"]

    text_label = event_label_from_text(voice.get("text") or "")
    parsed_title = split_title_event_song(voice.get("title") or "")
    title_prefix = (
        voice.get("title_event_name_hint")
        or (parsed_title["event_name"] if parsed_title else "")
        or title_prefix_before_date(voice.get("title") or "")
    )
    event_name = title_prefix if voice.get("title_event_name_hint") else text_label or title_prefix or normalize_text(voice.get("title") or "")
    venue = ""

    title = voice.get("title") or ""
    if "赤坂日枝神社" in title or "日枝神社" in event_name:
        venue = "赤坂日枝神社"
        if "山王音頭と民踊大会" in title:
            event_name = "山王音頭と民踊大会"
    elif "飛鳥山公園" in event_name or "飛鳥山公園" in (voice.get("title") or ""):
        venue = "飛鳥山公園"
    elif "国立" in event_name and "ジューンフェスタ" in event_name:
        venue = "国立旭通り"
    elif "横浜開港祭" in event_name or "パシフィコ横浜" in (voice.get("title") or ""):
        venue = "パシフィコ横浜プラザ広場"
    elif "日本民謡会館" in event_name or "Min-Yoi" in event_name:
        venue = "日本民謡会館"
    elif "マロニエまつり" in event_name:
        venue = "ヒューリック浅草橋前"
    elif "晴盆" in event_name or "おおさきHappy Olive Festival" in event_name:
        venue = "大崎駅周辺"

    if not venue:
        venue = event_name
    event_key = re.sub(r"-+", "-", normalize_key(event_name)[:48]) or "youtube-event"
    return event_name, venue, event_key


def build_review_url_map(review):
    mapping = {}
    for event in review.get("events", []):
        payload = {
            "event_key": event.get("event_key") or "",
            "event_name": event.get("event_name") or "",
            "venue": event.get("venue") or "",
        }
        for song in event.get("songs", []):
            for url in song.get("urls") or []:
                mapping[compact_url(url)] = payload
    return mapping


def confidence_for(row):
    setlist_count = len(row["setlist"])
    has_date = bool(row.get("event_date"))
    has_urls = all(item.get("url") for item in row["setlist"])
    if has_date and setlist_count >= 3 and has_urls:
        return "high"
    if has_date and setlist_count >= 2:
        return "medium"
    return "low"


def song_dedupe_key(title):
    title = normalize_text(title)
    title = re.sub(r"^(?:終|ラスト|最後)\s*", "", title)
    title = re.sub(r"[\(（][^\)）]*(?:部|回目|終)[^\)）]*[\)）]", "", title)
    return normalize_key(title)


def merge_setlist(target, source):
    by_title = {song_dedupe_key(item["title"]): item for item in target}
    for item in source:
        key = song_dedupe_key(item["title"])
        if not key:
            continue
        if key not in by_title:
            by_title[key] = dict(item)
        elif not by_title[key].get("url") and item.get("url"):
            by_title[key]["url"] = item["url"]
    return sorted(by_title.values(), key=lambda row: (row["number"], row["title"]))


def setlist_from_title(voice):
    parsed = split_title_event_song(voice.get("title") or "")
    if not parsed:
        return []
    song_title = clean_song_from_title(parsed.get("song_title") or "")
    if not title_looks_like_song(song_title):
        return []
    return [{
        "number": 1,
        "title": song_title,
        "url": compact_url(voice.get("url")),
        "evidence_type": "title_song_fragment",
        "event_name_hint": parsed.get("event_name") or "",
        "title_parse_method": parsed.get("method") or "",
    }]


def event_hint_is_better(current, candidate, current_key="", candidate_key=""):
    if not candidate:
        return False
    if candidate_key and candidate_key != current_key:
        return True
    current = normalize_text(current)
    candidate = normalize_text(candidate)
    if not current:
        return True
    if len(candidate) < len(current) and not re.search(r"\d+終?$", candidate):
        return True
    return False


def event_date_matches(occurrence_date, event):
    if not occurrence_date:
        return False
    start = event.get("date")
    end = event.get("date_end") or start
    if not start:
        return False
    return start <= occurrence_date <= end


def score_public_event_match(occurrence, event):
    if not event_date_matches(occurrence.get("event_date"), event):
        return 0, []
    reasons = ["date"]
    score = 50
    occ_name = normalize_key(occurrence.get("event_name_hint"))
    event_name = normalize_key(event.get("name"))
    occ_venue = normalize_key(occurrence.get("venue"))
    event_venue = normalize_key(event.get("venue"))
    if occ_name and event_name:
        if occ_name == event_name:
            score += 45
            reasons.append("event_name_exact")
        elif occ_name in event_name or event_name in occ_name:
            score += 30
            reasons.append("event_name_partial")
    if occ_venue and event_venue:
        if occ_venue == event_venue:
            score += 35
            reasons.append("venue_exact")
        elif occ_venue in event_venue or event_venue in occ_venue:
            score += 18
            reasons.append("venue_partial")
    if occurrence.get("event_key_hint") and normalize_key(occurrence["event_key_hint"]) == event_name:
        score += 10
        reasons.append("event_key_hint")
    return score, reasons


def match_public_event(occurrence, public_events):
    best = None
    for event in public_events:
        score, reasons = score_public_event_match(occurrence, event)
        if score <= 0:
            continue
        candidate = {
            "name": event.get("name") or "",
            "venue": event.get("venue") or "",
            "date": event.get("date") or "",
            "date_end": event.get("date_end") or "",
            "score": score,
            "reasons": reasons,
        }
        if best is None or score > best["score"]:
            best = candidate
    if best and best["score"] >= 80:
        return best
    return None


def attach_public_event_matches(occurrences, public_events):
    for occurrence in occurrences:
        match = match_public_event(occurrence, public_events)
        if not match:
            occurrence["matched_public_event"] = None
            continue
        occurrence["matched_public_event"] = match
        occurrence["canonical_event_name"] = match["name"]
        occurrence["canonical_venue"] = match["venue"]
    return occurrences


def extract_occurrences(voices, review=None):
    review_map = build_review_url_map(review or {})
    grouped = {}
    skipped = []
    youtube_voices = [v for v in voices if v.get("source") == "youtube"]

    for voice in youtube_voices:
        primary_text = primary_description_text(voice.get("text") or "")
        event_date = parse_youtube_event_date(primary_text, voice.get("title"))
        setlist = extract_setlist(primary_text)
        if len(setlist) < 2:
            setlist = setlist_from_title({**voice, "text": primary_text})
            if not setlist:
                skipped.append({
                    "url": voice.get("url"),
                    "title": voice.get("title"),
                    "reason": "no_numbered_setlist",
                })
                continue
            if not event_date:
                skipped.append({
                    "url": voice.get("url"),
                    "title": voice.get("title"),
                    "reason": "title_song_without_event_date",
                })
                continue
        if not has_bon_context({**voice, "text": primary_text}, setlist):
            skipped.append({
                "url": voice.get("url"),
                "title": voice.get("title"),
                "reason": "not_bon_odori_setlist",
            })
            continue

        title_event_name_hint = setlist[0].get("event_name_hint") if is_title_fragment_setlist(setlist) else ""
        event_name, venue, event_key = infer_event_and_venue(
            {**voice, "text": primary_text, "title_event_name_hint": title_event_name_hint},
            review_map,
        )
        account = voice.get("account") or "youtube"
        key = occurrence_key(venue, event_date)
        row = grouped.setdefault(key, {
            "occurrence_key": key,
            "event_key_hint": event_key,
            "event_name_hint": event_name,
            "venue": venue,
            "event_date": event_date,
            "accounts": [],
            "setlist": [],
            "source_videos": [],
            "source_video_count": 0,
            "song_count": 0,
            "confidence": "low",
            "role": "result",
            "act": "observe",
            "reliability_key": "complete_numbered_video",
        })
        if event_hint_is_better(
            row.get("event_name_hint"), event_name, row.get("event_key_hint"), event_key
        ):
            row["event_key_hint"] = event_key
            row["event_name_hint"] = event_name
            row["venue"] = venue
        row["setlist"] = merge_setlist(row["setlist"], setlist)
        if account not in row["accounts"]:
            row["accounts"].append(account)
        source_video = {
            "url": compact_url(voice.get("url")),
            "account": account,
            "title": voice.get("title") or "",
            "published_at": voice.get("date") or "",
            "thumbnail_url": voice.get("thumbnail_url") or "",
            "text_length": len(voice.get("text") or ""),
            "media_url_count": len(voice.get("media_urls") or []),
        }
        if source_video["url"] and all(v["url"] != source_video["url"] for v in row["source_videos"]):
            row["source_videos"].append(source_video)

    rows = []
    for row in grouped.values():
        row["source_videos"].sort(key=lambda item: (item.get("published_at") or "", item.get("url") or ""))
        row["accounts"].sort()
        row["source_video_count"] = len(row["source_videos"])
        row["song_count"] = len(row["setlist"])
        row["confidence"] = confidence_for(row)
        rows.append(row)
    rows.sort(key=lambda row: (row.get("event_date") or "", row.get("venue") or ""))
    return rows, skipped, youtube_voices


def backfill_options(youtube_voices):
    stale = [v for v in youtube_voices if len(v.get("text") or "") <= 500]
    missing_media = [v for v in youtube_voices if not v.get("media_urls")]
    return {
        "current_youtube_voice_count": len(youtube_voices),
        "voices_at_or_below_500_chars": len(stale),
        "voices_without_media_urls": len(missing_media),
        "options": [
            {
                "method": "youtube_data_api_videos_list",
                "summary": "video idを抽出して videos.list(part=snippet) で description 全文を取得する",
                "cost": "quota 1 unit/request。50 ids/request なら約4 requestで199本を取得可能",
                "pros": ["公式API", "HTML変更に強い", "説明文の取得が安定"],
                "cons": ["API key設定が必要", "削除・非公開動画は取得不可"],
                "recommendation": "preferred",
            },
            {
                "method": "youtube_watch_page_fetch",
                "summary": "動画個別ページを取得して初期データ内の description を抽出する",
                "cost": "API quota不要。約199 HTTP GET",
                "pros": ["追加API key不要", "小規模なら実装は軽い"],
                "cons": ["YouTubeのHTML変更に弱い", "レート制限・同意画面・bot判定の影響を受けやすい"],
                "recommendation": "fallback",
            },
        ],
    }


def build_output(voices_path=VOICES, review_path=YOUTUBE_REVIEW, public_events_path=PUBLIC_EVENTS):
    voices = load_json(voices_path, [])
    review = load_json(review_path, {})
    public_events = load_json(public_events_path, [])
    occurrences, skipped, youtube_voices = extract_occurrences(voices, review)
    occurrences = attach_public_event_matches(occurrences, public_events)
    return {
        "generated_by": "extract_youtube_setlists.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(voices_path),
        "review_hint_source": str(review_path),
        "public_event_match_source": str(public_events_path),
        "youtube_voice_count": len(youtube_voices),
        "occurrence_count": len(occurrences),
        "matched_public_event_count": sum(1 for row in occurrences if row.get("matched_public_event")),
        "setlist_song_count": sum(row["song_count"] for row in occurrences),
        "occurrences": occurrences,
        "skipped_count": len(skipped),
        "skipped_samples": skipped[:30],
        "backfill_options": backfill_options(youtube_voices),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--voices", default=str(VOICES))
    parser.add_argument("--review", default=str(YOUTUBE_REVIEW))
    parser.add_argument("--public-events", default=str(PUBLIC_EVENTS))
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    output = build_output(Path(args.voices), Path(args.review), Path(args.public_events))
    atomic_write_json(args.out, output)
    print(
        "[youtube-setlists] "
        f"voices={output['youtube_voice_count']} "
        f"occurrences={output['occurrence_count']} "
        f"songs={output['setlist_song_count']} "
        f"skipped={output['skipped_count']} -> {args.out}"
    )


if __name__ == "__main__":
    main()
