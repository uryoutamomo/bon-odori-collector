"""Master RDBから、Web一般公開サイト用のイベント一覧（東京23区）を
エクスポートするスクリプト。

公開サイトのメインカードは会場ではなく**イベント名**（内田さん指示 2026-06-10）。
- `data/bon_odori_master.sqlite` の event_occurrences を1カードとして出力
- Notion経路は `BON_ODORI_PUBLIC_SOURCE=notion` の明示指定時だけ使う

23区判定・区名正規化・文字化け置換・内部フィールド除去は
venues/export_public_venues.py と同じ方針。出力は data/public/events_public.json。
                                                    — こと（Claude Code）2026-06-10
"""

import argparse
import json
import os
import re
import sqlite3
import unicodedata
import urllib.error
import urllib.request

from song_processing.bon_odori_songs import extract_song_hints
from event_model.event_series_normalization import public_series_name
from event_model.year_context import normalize_target_year
from master_rdb.master_db import MASTER_DB, connect_existing
from public_json_postprocessors.apply_public_date_predictions import (
    OUT_REPORT as DATE_PREDICTION_REPORT,
    PREDICTIONS as DATE_PREDICTIONS,
    apply_predictions as apply_public_date_predictions,
    load_json as load_public_date_prediction_json,
    write_json as write_public_date_prediction_json,
)
from public_json_postprocessors.apply_public_display_tiers import apply_display_tiers
import notion_support.notion_config as notion_config
from public_export_support.score_event_recurrence import build_rows, enrich_public_events
from venues.export_public_venues import (
    MONTH_DAY_RE,
    MONTH_RE,
    clean_public_text,
    _geo_key,
    load_venue_geo,
    months_from_memo,
    normalize_ward,
    WARD_ORDER,
    _notion_request,  # noqa: F401  (同一API利用)
    _prop,
    _query_all,
)

OUT_DIR = os.environ.get(
    "BON_ODORI_PUBLIC_OUT_DIR",
    os.path.join(os.path.dirname(__file__), "data", "public"),
)
OUT_JSON = os.path.join(OUT_DIR, "events_public.json")
OUT_JS = os.path.join(OUT_DIR, "events_public.js")
OUT_SONGS_JSON = os.path.join(OUT_DIR, "event_songs_public.json")
OUT_SONG_OCCURRENCES_JSON = os.environ.get(
    "BON_ODORI_SONG_OCCURRENCES_JSON",
    os.path.join(OUT_DIR, "event_song_occurrences_public.json"),
)
PUBLIC_EVENT_SOURCE_MAP_JSON = os.environ.get(
    "BON_ODORI_PUBLIC_EVENT_SOURCE_MAP_JSON",
    os.path.join(os.path.dirname(__file__), "data", "public_event_source_map.json"),
)
DATE_PREDICTION_REPORT = os.environ.get(
    "BON_ODORI_PUBLIC_DATE_PREDICTION_REPORT",
    DATE_PREDICTION_REPORT,
)
SERIES_SPLIT_REVIEW_JSON = os.path.join(
    os.path.dirname(__file__), "data", "public_event_series_split_review.json"
)
SERIES_SPLIT_REVIEW_MD = os.path.join(
    os.path.dirname(__file__), "data", "public_event_series_split_review.md"
)
DATE_CANDIDATES_JSON = os.path.join(os.path.dirname(__file__), "data", "event_date_update_candidates.json")
PUBLIC_EVENT_OVERRIDES_JSON = os.path.join(os.path.dirname(__file__), "data", "public_event_overrides.json")
PUBLIC_SOURCE = os.environ.get("BON_ODORI_PUBLIC_SOURCE", "master_rdb").strip().lower()
PUBLIC_WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]
FALLBACK_SUPPRESSED_VENUES = {
    # 例大祭名の由来となる神社。実際の奉納踊り会場は青葉公園（港区立）なので、
    # 未整備会場フォールバックとして「青山熊野神社の盆踊り」を出さない。
    "青山熊野神社",
    # 公開前チェックで「名前と区以外の情報が薄い不完全レコード」として除外。
    "あかつき公園",
    "有馬小学校",
    "羽根木公園",
}
NON_SONG_LABELS = {
    # ジャンル/イベント名であって曲名ではないため、曲目タグには出さない。
    "郡上おどり",
}
AMBIGUOUS_SONG_LABELS = {
    # 曲名にもなり得るが、イベント本文では一般語として誤抽出されやすい。
    "まつり",
}
SCHEDULE_FRAGMENT_RE = re.compile(
    r"\s*(?:"
    r"\d{4}\s*)?"
    r"(?:"
    r"\d{1,2}月\d{1,2}日?"
    r"|\d{1,2}月\d{1,2}\s*[（(]"
    r")"
    r"(?:[^\n]*)$"
)
TRAILING_EVENT_NAME_PUNCT_RE = re.compile(r"[\s。．、,・／/＝=\-~]+$")
QUOTE_TRANSLATION = str.maketrans({
    "｢": "「",
    "｣": "」",
    "『": "「",
    "』": "」",
})

# 日付未確定イベントの「並び位置」を決めるヒント（内田さん指示 2026-06-10）：
# 旬がわかれば 上旬≒5日 / 中旬≒15日 / 下旬≒25日、それも無ければ昨年実績の
# 月日、最後は月のみ（≒15日）で近似する。
JUN_DAY = {"上旬": 5, "中旬": 15, "下旬": 25, "初": 3, "末": 27}
MONTH_JUN_RE = re.compile(r"(\d{1,2})月(上旬|中旬|下旬|末|初)?")
ISO_DATE_RE = re.compile(r"\d{4}-(\d{1,2})-(\d{1,2})")
# 編集署名・確認日（「（2026-06-10 こと）」「こと2026-06-10追記」「おと（Codex）2026-06-09」）。
# 実イベントの日付と誤認して並び順を壊すため、ヒント抽出前に取り除く。
SIGNATURE_RE = re.compile(
    r"（\d{4}-\d{1,2}-\d{1,2}[^）]*）"
    r"|(?:こと|おと)（?[A-Za-z]*）?\s*\d{4}-\d{1,2}-\d{1,2}(?:追記|時点)?")
YOUTUBE_EVIDENCE_RE = re.compile(
    r"(?s)\n*\[youtube[^\]]*].*?(?=\n\[[a-z_]+]|\Z)",
)
FIXED_DATE_INTERNAL_NOTE_RE = re.compile(
    r"(?s)\n*(?:\[fixed_date_rule]\s*)?"
    r"(?:おと（Codex）|こと（Claude Code）)\s*固定日ルール記録"
    r".*?(?=\n\[[a-z_]+]|\Z)",
)
URL_RE = re.compile(r"https?://[^\s）)」』】]+")
PUBLIC_SOURCE_KEYS = (
    "公式確認URL",
    "公式URL",
    "公式サイト",
    "公式HP",
    "出典URL",
    "参照URL",
    "YouTube検出元URL",
)
PUBLIC_SOURCE_EXCLUDED_HOSTS = (
    "youtube.com",
    "youtu.be",
)
PUBLIC_SOURCE_EXCLUDED_URLS = {
    # 2026-06-17 official source review: URL now returns 404, so keep it out of
    # public "official evidence" links even if it remains in older evidence text.
    "https://tsukijihongwanji.jp/news/10279/",
    "https://www.city.setagaya.lg.jp/documents/891/163gou_2.pdf",
}
NOTICE_HOSTS = (
    "x.com",
    "twitter.com",
    "t.co",
)
OFFICIAL_SOURCE_KEYS = (
    "公式URL",
    "公式サイト",
    "公式HP",
    "YouTube検出元URL",
)

def _url_host(url):
    match = re.match(r"https?://([^/]+)", url or "")
    return match.group(1).lower() if match else ""


def _is_public_source_url(url):
    host = _url_host(url)
    return (
        bool(host)
        and url not in PUBLIC_SOURCE_EXCLUDED_URLS
        and not any(blocked in host for blocked in PUBLIC_SOURCE_EXCLUDED_HOSTS)
    )


def _is_notice_url(url):
    host = _url_host(url)
    return any(notice_host in host for notice_host in NOTICE_HOSTS)


def _source_item(key, url):
    key = (key or "").strip()
    if any(source_key in key for source_key in OFFICIAL_SOURCE_KEYS):
        return {"label": "公式告知あり", "url": url, "kind": "official"}
    return {"label": "告知HPあり", "url": url, "kind": "web"}


def extract_public_source_urls(text):
    """Extract public-facing source URLs while excluding video/internal evidence links."""
    official = []
    web = []
    seen = set()
    notice_seen = set()
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        key = ""
        body = stripped
        is_bullet = stripped.startswith("- ")
        if is_bullet:
            body = stripped[2:].strip()
            if ":" in body:
                key, _, body = body.partition(":")
            elif "：" in body:
                key, _, body = body.partition("：")
        key = key.strip()
        is_source_line = any(source_key in key for source_key in PUBLIC_SOURCE_KEYS)
        # Keep ordinary announcement URLs from the visible note, but do not expose
        # video links or arbitrary URLs buried in internal evidence lines.
        if not is_source_line and is_bullet:
            continue
        for url in URL_RE.findall(body):
            if _is_notice_url(url):
                notice_seen.add(url)
                continue
            if not _is_public_source_url(url) or url in seen:
                continue
            seen.add(url)
            item = _source_item(key if is_source_line else "", url)
            if item["kind"] == "official":
                official.append(item)
            else:
                web.append(item)
    sources = []
    if official:
        sources.append(official[0])
    if web:
        sources.append({"label": "告知HPあり", "url": "", "kind": "web", "count": len(web)})
    if notice_seen:
        sources.append({"label": "告知投稿あり", "url": "", "kind": "post", "count": len(notice_seen)})
    return sources


def _source_rank(source):
    url = source.get("url") or ""
    generic = bool(re.search(r"/(?:news|info|event)/?$", url.rstrip("/")))
    return (
        1 if source.get("kind") == "official" else 0,
        0 if generic else 1,
        len(url),
    )


def _number_prop(props, name):
    prop = props.get(name) or {}
    if prop.get("type") != "number":
        return None
    value = prop.get("number")
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number


def fixed_date_rule_from_props(props):
    """Read machine-usable fixed-date columns from the event DB when present."""
    month = _number_prop(props, "固定日開始月")
    day = _number_prop(props, "固定日開始日")
    if not month or not day:
        return None
    end_month = _number_prop(props, "固定日終了月") or month
    end_day = _number_prop(props, "固定日終了日") or day
    if not (1 <= month <= 12 and 1 <= end_month <= 12):
        return None
    if not (1 <= day <= 31 and 1 <= end_day <= 31):
        return None
    source_url = _prop(props, "固定日根拠URL") or ""
    return {
        "rule_type": "fixed_date_range",
        "month": month,
        "day": day,
        "end_month": end_month,
        "end_day": end_day,
        "source_url": source_url,
        "basis": "イベントDBの固定日カラムに記録",
    }


def collapse_public_source_urls(sources):
    """Keep public evidence buttons compact; one official button is enough."""
    best_official = None
    note_counts = {}
    note_labels = {}
    note_first = {}
    for source in sources or []:
        if source.get("kind") == "official":
            if best_official is None or _source_rank(source) > _source_rank(best_official):
                best_official = source
            continue
        kind = source.get("kind") or "web"
        note_counts[kind] = note_counts.get(kind, 0) + int(source.get("count") or 1)
        note_labels.setdefault(kind, source.get("label") or "告知HPあり")
        note_first.setdefault(kind, source)
    notes = [
        {
            "label": note_labels[kind],
            "url": (note_first.get(kind) or {}).get("url", "") if count == 1 else "",
            "kind": kind,
            "count": count,
        }
        for kind, count in note_counts.items()
    ]
    return ([best_official] if best_official else []) + notes


def public_detail_text(text):
    """Return a general-reader summary, without internal evidence blocks."""
    if not text:
        return ""
    public = YOUTUBE_EVIDENCE_RE.sub("", text)
    public = FIXED_DATE_INTERNAL_NOTE_RE.sub("", public)
    public = re.split(r"\s*追加証拠\s*", public, maxsplit=1)[0]
    public = re.sub(
        r"(?m)^\s*-\s*(?:公式確認URL|公式URL|公式サイト|公式HP|出典URL|参照URL|補足URL|会場URL|YouTube検出元URL)[:：].*$",
        "",
        public,
    )
    public = re.sub(r"\[[A-Z]\d+\]\s*", "", public)
    public = re.sub(r"\[[a-z_]+\]\s*", "", public)
    public = re.sub(r"https?://\S+", "", public)
    public = re.sub(r"(?:公式URL|根拠URL|参照URL|出典URL)[:：]\s*(?=$|[。．])", "", public)
    public = re.sub(r"\s+", " ", public).strip()
    return public


def clean_public_event_name(name):
    """Remove schedule fragments accidentally captured in public event names."""
    original = str(name or "")
    cleaned = original.translate(QUOTE_TRANSLATION)
    cleaned = SCHEDULE_FRAGMENT_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+([」）)])", r"\1", cleaned)
    cleaned = re.sub(r"([「（(])\s+", r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = TRAILING_EVENT_NAME_PUNCT_RE.sub("", cleaned).strip()
    if cleaned.startswith("「") and cleaned.endswith("」") and cleaned.count("「") == 1 and cleaned.count("」") == 1:
        cleaned = cleaned[1:-1].strip()
    elif cleaned.startswith("「") and cleaned.count("「") == 1 and cleaned.count("」") == 0:
        cleaned = cleaned[1:].strip()
    return cleaned or original.strip()


def apply_public_event_name_cleanup(events):
    """Normalize public names and add display labels for same-name different-venue rows."""
    cleaned = []
    for event in events:
        item = dict(event)
        before = item.get("name") or ""
        after = public_series_name(clean_public_event_name(before))
        if after and after != before:
            item["name"] = after
            if item.get("display_name") == before:
                item.pop("display_name", None)
        cleaned.append(item)

    by_name = {}
    for item in cleaned:
        by_name.setdefault(item.get("name") or "", []).append(item)
    for name, rows in by_name.items():
        if not name or len(rows) < 2:
            continue
        venues = {row.get("venue") or "" for row in rows}
        if len(venues) < 2:
            continue
        for row in rows:
            venue = row.get("venue") or row.get("area") or ""
            row["display_name"] = f"{name}（{venue}）" if venue else name
    return cleaned


def confidence_for_candidate(score, source, reasons):
    reasons = reasons or []
    venue_supported = "venue_exact" in reasons or "structured_blog_venue" in reasons
    if score >= 18 and venue_supported:
        return {"level": "high", "label": "有力候補", "description": "複数の手がかりが一致しています"}
    if score >= 14 and venue_supported:
        return {"level": "medium", "label": "候補", "description": "イベント名や会場名などの手がかりがあります"}
    return {"level": "low", "label": "参考情報", "description": "日付の手がかりはありますが確認が必要です"}


def confirmed_confidence():
    return {"level": "confirmed", "label": "確認済み", "description": "開催日として確認済みです"}


def unknown_confidence():
    return {"level": "unknown", "label": "未確認", "description": "開催日はまだ確認できていません"}


def has_confirmed_date_status(status):
    return status in {"確認済み", "終了"}


def parse_youtube_evidence(detail):
    """Extract structured YouTube evidence from public detail text."""
    rows = []
    for block in YOUTUBE_EVIDENCE_RE.findall(detail or ""):
        block = block.strip()
        row = {
            "label": block.splitlines()[0].replace("[youtube_evidence]", "").strip() or "YouTube証拠",
            "event_name": "",
            "detected_date": "",
            "video_url": "",
            "channel": "",
            "thumbnail_url": "",
            "songs": [],
        }
        for line in block.splitlines()[1:]:
            line = line.strip()
            if not line.startswith("- "):
                continue
            key, sep, value = line[2:].partition(":")
            if not sep:
                key, sep, value = line[2:].partition("：")
            if not sep:
                continue
            key = key.strip()
            value = clean_public_text(value.strip())
            if key == "対象イベント":
                row["event_name"] = value
            elif key == "検出日付":
                row["detected_date"] = value
            elif key == "動画":
                row["video_url"] = value
            elif key == "チャンネル":
                row["channel"] = value
            elif key == "サムネイル":
                row["thumbnail_url"] = value
            elif key == "曲目候補":
                row["songs"] = [song.strip() for song in value.split(",") if song.strip()]
        if row["video_url"]:
            rows.append(row)
    return rows


def fill_youtube_evidence_defaults(rows, event_name, event_date):
    filled = []
    for row in rows or []:
        item = dict(row)
        if not item.get("event_name"):
            item["event_name"] = event_name or ""
        if not item.get("detected_date"):
            item["detected_date"] = event_date or ""
        filled.append(item)
    return filled


def load_date_candidates():
    if not os.path.exists(DATE_CANDIDATES_JSON):
        return {}
    with open(DATE_CANDIDATES_JSON, encoding="utf-8") as f:
        raw = json.load(f)
    grouped = {}
    for item in raw.get("candidates", []):
        event_id = item.get("event_id")
        start = item.get("new_date")
        if not event_id or not start:
            continue
        confidence = confidence_for_candidate(
            int(item.get("score") or 0),
            item.get("source"),
            item.get("reasons") or [],
        )
        grouped.setdefault(event_id, []).append({
            "date": start,
            "date_end": item.get("new_date_end"),
            "confidence": confidence,
            "score": item.get("score"),
            "source": item.get("source"),
            "source_url": item.get("url"),
            "raw_date": clean_public_text(item.get("raw_date")),
        })
    for event_id, items in grouped.items():
        items.sort(key=lambda c: (-(c.get("score") or 0), c["date"]))
        grouped[event_id] = items[:3]
    return grouped


def _song_occurrence_key(event_name, venue, year):
    return (
        re.sub(r"\s+", "", public_series_name(event_name)).casefold(),
        re.sub(r"\s+", "", venue or "").casefold(),
        int(year),
    )


def load_song_occurrences():
    if not os.path.exists(OUT_SONG_OCCURRENCES_JSON):
        return {}
    with open(OUT_SONG_OCCURRENCES_JSON, encoding="utf-8") as f:
        raw = json.load(f)
    grouped = {}
    for row in raw.get("occurrences", []):
        event_name = row.get("event_name")
        venue = row.get("venue")
        year = row.get("year")
        if not event_name or not venue or not year:
            continue
        grouped[_song_occurrence_key(event_name, venue, year)] = row
    return grouped


def _json_list(value):
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _public_status_from_rdb(date_status, lifecycle_status):
    if date_status in {"confirmed", "ended"}:
        return "確認済み"
    if lifecycle_status == "published" and date_status == "unknown":
        return "未確認"
    return "未確認"


def _public_confidence_from_rdb(date, date_status):
    if date and date_status in {"confirmed", "ended"}:
        return confirmed_confidence()
    return unknown_confidence()


def _rdb_source_urls(detail, source_url, source_kind):
    sources = extract_public_source_urls(detail)
    if source_url and _is_public_source_url(source_url):
        if any(source.get("url") == source_url for source in sources):
            return collapse_public_source_urls(sources)
        if (
            len(sources) == 1
            and sources[0].get("kind") != "official"
            and not sources[0].get("url")
            and int(sources[0].get("count") or 1) == 1
        ):
            sources[0]["url"] = source_url
            return collapse_public_source_urls(sources)
        key = "公式URL" if source_kind == "official_current_year" else "出典URL"
        sources.append(_source_item(key, source_url))
    return collapse_public_source_urls(sources)


def _song_from_rdb(row):
    probability = row["probability"]
    if probability is not None:
        probability = int(probability) if float(probability).is_integer() else float(probability)
    basis = "past_evidence"
    basis_label = "過去実績"
    if row["evidence_status"] == "announced":
        basis = "current_announced"
        basis_label = "今年告知"
    elif row["evidence_status"] == "observed":
        basis = "current_observed"
        basis_label = "実測"
    elif row["evidence_status"] == "predicted" and not row["inherited_from_year"]:
        # predicted は observed/announced 以外の証拠(hint等)しかないケース。
        # inherited_from_year が無ければ過去年からの継承ではなく今年ヒント
        # (legacy JSON時代のbasis="current_hint"に相当。RDB移行時に
        # evidence_status='predicted'の行だけこの分岐が抜けており、直下の
        # inherited_from_yearチェックにも掛からず「過去実績」に誤表示していた)。
        basis = "current_hint"
        basis_label = "今年ヒント"
    elif row["inherited_from_year"]:
        # inherit_song_probabilities_rdb.py が notes.source_kind に継承元の証拠種別
        # (告知/実測/ヒント)を記録している。ここを見ずに「年ヒント」固定にすると、
        # 前年に実測された曲まで「ヒント」表示になり信頼度の印象を下げてしまう。
        source_kind_label = "ヒント"
        try:
            notes = json.loads(row["notes"] or "{}")
        except (TypeError, ValueError):
            notes = {}
        source_kind = notes.get("source_kind")
        if source_kind == "announced":
            source_kind_label = "告知"
        elif source_kind == "observed":
            source_kind_label = "実測"
        basis_label = f"{row['inherited_from_year']}年{source_kind_label}"
    song = {
        "name": row["song_title_raw"],
        "confidence": "confirmed" if (probability or 0) >= 95 or row["confidence"] == "high" else "hint",
        "probability": probability,
        "basis": basis,
        "basis_label": basis_label,
        "evidence_count": row["evidence_count"],
        "source_count": row["source_count"],
    }
    return {key: value for key, value in song.items() if value not in (None, "", [])}


def load_rdb_occurrence_songs(conn):
    grouped = {}
    rows = conn.execute(
        """
        SELECT
          occurrence_id,
          song_title_raw,
          evidence_status,
          probability,
          confidence,
          source_count,
          evidence_count,
          inherited_from_year,
          notes
        FROM occurrence_songs
        ORDER BY occurrence_id, probability DESC, song_title_raw
        """
    ).fetchall()
    for row in rows:
        grouped.setdefault(row["occurrence_id"], []).append(_song_from_rdb(row))
    return grouped


def merge_song_occurrence_hints(existing_songs, occurrence):
    songs = {}
    for song in existing_songs or []:
        if not song.get("name"):
            continue
        key = _song_dedupe_key(song.get("name", ""))
        if not key:
            continue
        current = songs.get(key)
        candidate = dict(song)
        if current is None or _song_score(candidate) > _song_score(current):
            songs[key] = candidate
    for song in (occurrence or {}).get("songs", []):
        key = _song_dedupe_key(song.get("name", ""))
        if not key:
            continue
        merged = songs.setdefault(key, {
            "name": song["name"],
            "confidence": "hint",
            "source_count": 0,
        })
        merged["probability"] = song.get("probability")
        merged["basis"] = song.get("basis")
        merged["basis_label"] = song.get("basis_label")
        merged["evidence_count"] = song.get("evidence_count")
        merged["speaker_count"] = song.get("speaker_count")
        merged["setlist_complete"] = song.get("setlist_complete")
        if song.get("confidence") == "confirmed":
            merged["confidence"] = "confirmed"
        if song.get("evidence_urls"):
            merged["evidence_urls"] = song.get("evidence_urls")
        if song.get("probability", 0) >= 95:
            merged["confidence"] = "confirmed"
        merged["source_count"] = max(
            int(merged.get("source_count") or 0),
            int(song.get("evidence_count") or 0),
        )
    return sorted(
        songs.values(),
        key=lambda row: (-(row.get("probability") or 0), row.get("name") or ""),
    )


def strip_song_internal_fields(songs):
    best_by_key = {}
    order = []
    for song in songs or []:
        if isinstance(song, str):
            candidate = {"name": song, "confidence": "hint"}
        else:
            candidate = dict(song)
        name = _song_name(candidate).strip()
        key = _song_dedupe_key(name)
        if not key:
            continue
        if key not in best_by_key:
            order.append(key)
            best_by_key[key] = candidate
            continue
        if _song_score(candidate) > _song_score(best_by_key[key]):
            best_by_key[key] = candidate
    return [_public_song(best_by_key[key]) for key in order if _song_name(best_by_key[key]).strip()]


def parse_months(text):
    return {int(m) for m in MONTH_RE.findall(text or "") if 1 <= int(m) <= 12}


def hints_from_text(text):
    """テキストから {月: (日, 優先度)} を抽出。旬(1) > 具体日(2) > 月のみ(3)。"""
    text = SIGNATURE_RE.sub(" ", text or "")
    out = {}

    def put(m, d, rank):
        if 1 <= m <= 12 and 1 <= d <= 31 and (m not in out or rank < out[m][1]):
            out[m] = (d, rank)

    for m, jun in MONTH_JUN_RE.findall(text or ""):
        m = int(m)
        if jun:
            put(m, JUN_DAY[jun], 1)
        else:
            put(m, 15, 3)
    for mo, d in ISO_DATE_RE.findall(text or ""):
        put(int(mo), int(d), 2)
    for mo, d in MONTH_DAY_RE.findall(text or ""):
        put(int(mo), int(d), 2)
    return out


def jun_labels(text):
    """例年開催月テキストから {月: 旬ラベル} を抜く（カード表示用）。"""
    out = {}
    for m, jun in MONTH_JUN_RE.findall(text or ""):
        m = int(m)
        if jun in ("上旬", "中旬", "下旬") and 1 <= m <= 12 and m not in out:
            out[m] = jun
    return out


def jun_from_day(day):
    if day <= 10:
        return "上旬"
    if day <= 20:
        return "中旬"
    return "下旬"


def jun_labels_from_hints(hints):
    """具体日ヒントから {月: 上旬/中旬/下旬} を作る。"""
    out = {}
    for m, d in hints:
        out.setdefault(m, jun_from_day(d))
    return out


def jun_labels_from_date_range(start, end=None):
    if not start:
        return {}
    labels = {}
    labels[int(start[5:7])] = jun_from_day(int(start[8:10]))
    if end:
        labels[int(end[5:7])] = jun_from_day(int(end[8:10]))
    return labels


def hints_from_date_range(start, end=None):
    if not start:
        return []
    hints = [[int(start[5:7]), int(start[8:10])]]
    if end:
        end_hint = [int(end[5:7]), int(end[8:10])]
        if end_hint not in hints:
            hints.append(end_hint)
    return hints


def merge_jun_labels(*label_dicts):
    merged = {}
    for labels in label_dicts:
        for m, label in labels.items():
            merged.setdefault(m, label)
    return merged


def merge_hints(*hint_dicts, months=()):
    """複数ソースのヒントを優先度で統合し、months の不足分は15日で補う。"""
    merged = {}
    for hints in hint_dicts:
        for m, (d, rank) in hints.items():
            if m not in merged or rank < merged[m][1]:
                merged[m] = (d, rank)
    for m in months:
        merged.setdefault(m, (15, 4))
    return sorted([m, d] for m, (d, _) in merged.items())


def fetch_public_venues():
    """23区の公開対象会場を venue_page_id -> dict で返す。"""
    venues = {}
    geo_by_venue = load_venue_geo()
    for row in _query_all(notion_config.VENUE_DATA_SOURCE_ID):
        props = row.get("properties", {})
        name = _prop(props, "会場名")
        ward = normalize_ward(_prop(props, "所在区・市"))
        if not name or not ward:
            continue
        scale = _prop(props, "規模")
        memo = _prop(props, "過去メモ")
        address = clean_public_text(_prop(props, "住所"))
        entry = {
            "venue": clean_public_text(name),
            "area": ward,
            "scale": scale if scale in ("大", "中", "小") else None,
            "access": clean_public_text(_prop(props, "アクセス")),
            "address": address,
            "memo_months": sorted(months_from_memo(memo)),
            "memo_hints": hints_from_text(memo),
            "memo_jun": jun_labels(memo),
            "intro": clean_public_text(_prop(props, "公開紹介文")),
        }
        geo = geo_by_venue.get(_geo_key(name, address))
        if geo:
            entry.update(geo)
        venues[row["id"]] = entry
    return venues


def build_public_events_from_notion(*, target_year):
    target_year = normalize_target_year(target_year)
    venues = fetch_public_venues()
    date_candidates_by_event = load_date_candidates()
    song_occurrences = load_song_occurrences()
    events, covered, skipped = [], set(), 0

    for row in _query_all(notion_config.EVENT_DATA_SOURCE_ID):
        props = row.get("properties", {})
        name = _prop(props, "イベント名")
        venue_ids = [v for v in (_prop(props, "会場") or []) if v in venues]
        if not name or not venue_ids:
            skipped += 1
            continue
        month_text = _prop(props, "例年開催月")
        detail_text = _prop(props, "開催パターン詳細")
        months = parse_months(month_text)
        date_obj = props.get("開催日", {}).get("date") or {}
        date = date_obj.get("start")
        date_end = date_obj.get("end")
        if date:
            months.add(int(date[5:7]))
        status = _prop(props, "状態")
        date_candidates = date_candidates_by_event.get(row["id"], [])
        if not date:
            for candidate in date_candidates:
                months.add(int(candidate["date"][5:7]))
        if date:
            hints = hints_from_date_range(date, date_end)
            jun = merge_jun_labels(
                jun_labels(month_text),
                jun_labels_from_date_range(date, date_end),
            )
        else:
            candidate_hints = {
                int(c["date"][5:7]): (int(c["date"][8:10]), 0)
                for c in date_candidates
            }
            hints = merge_hints(
                candidate_hints, hints_from_text(month_text), hints_from_text(detail_text),
                months=months)
            jun = merge_jun_labels(jun_labels(month_text), jun_labels_from_hints(hints))
        for vid in venue_ids:
            v = venues[vid]
            covered.add(vid)
            public_name = public_series_name(clean_public_text(name))
            description = clean_public_text(_prop(props, "公開紹介文"))
            raw_detail = clean_public_text(detail_text)
            detail = public_detail_text(raw_detail)
            source_urls = extract_public_source_urls(raw_detail)
            songs = extract_song_hints(description, raw_detail)
            occurrence_year = int(date[:4]) if date else target_year
            occurrence = song_occurrences.get(
                _song_occurrence_key(public_name, v["venue"], occurrence_year)
            )
            songs = merge_song_occurrence_hints(songs, occurrence)
            songs = strip_song_internal_fields(songs)
            event_months = sorted(months)
            if not event_months and "名称推定" not in public_name:
                event_months = v["memo_months"]
            events.append({
                "name": public_name,
                "name_confirmed": True,
                "venue": v["venue"],
                "area": v["area"],
                "months": event_months,
                "scale": v["scale"],
                "access": v["access"],
                "address": v["address"],
                "lat": v.get("lat"),
                "lng": v.get("lng"),
                "date": date,
                "date_end": date_end,
                "status": status,
                "date_confidence": confirmed_confidence() if date and has_confirmed_date_status(status) else unknown_confidence(),
                "date_candidates": [] if date else date_candidates,
                # 並び順用の近似月日 [[月, 日], ...] と、表示用の旬ラベル {月: 旬}
                "hints": hints,
                "jun": {str(m): j for m, j in jun.items()},
                # カードに出す特徴文（公開用に書いたものだけ。内部メモは出さない）
                "description": description,
                # 詳細モーダル用：直近の開催実績（日時の記録）
                "detail": detail,
                # 一般閲覧者に見せる公式・準公式の根拠URL。内部ログや動画列挙は公開しない。
                "source_urls": source_urls,
                # 会場で流れる/踊られる曲の候補。公開時は「曲目ヒント」として扱う。
                "songs": songs,
            })

    # イベント未整備の会場はフォールバックカード（名称確認中）
    fallback = 0
    for vid, v in venues.items():
        if vid in covered:
            continue
        if v["venue"] in FALLBACK_SUPPRESSED_VENUES:
            continue
        fallback += 1
        events.append({
            "name": f"{v['venue']}の盆踊り",
            "name_confirmed": False,
            "venue": v["venue"],
            "area": v["area"],
            "months": v["memo_months"],
            "scale": v["scale"],
            "access": v["access"],
            "address": v["address"],
            "lat": v.get("lat"),
            "lng": v.get("lng"),
            "date": None,
            "date_end": None,
            "status": None,
            "date_confidence": unknown_confidence(),
            "date_candidates": [],
            "hints": merge_hints(v["memo_hints"], months=v["memo_months"]),
            "jun": {
                str(m): j for m, j in merge_jun_labels(
                    v["memo_jun"],
                    jun_labels_from_hints(merge_hints(v["memo_hints"], months=v["memo_months"])),
                ).items()
            },
            "description": v["intro"],
            "detail": None,
            "source_urls": [],
            "songs": [],
        })

    events.sort(key=lambda e: (WARD_ORDER[e["area"]], e["venue"], e["name"]))
    return events, len(covered), fallback, skipped


def build_public_events_from_master(db_path=MASTER_DB, *, target_year):
    target_year = normalize_target_year(target_year)
    previous_year = target_year - 1
    song_occurrences = load_song_occurrences()
    date_candidates_by_event = load_date_candidates()
    events, covered = [], set()
    with connect_existing(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rdb_songs = load_rdb_occurrence_songs(conn)
        occurrence_columns = {
            row[1] for row in conn.execute("PRAGMA table_info(event_occurrences)")
        }
        has_canonical_axes = {
            "current_event_state",
            "date_certainty_tier",
        }.issubset(occurrence_columns)
        axis_select = (
            "o.current_event_state, o.date_certainty_tier,"
            if has_canonical_axes
            else "NULL AS current_event_state, NULL AS date_certainty_tier,"
        )
        ward_placeholders = ",".join("?" for _ in WARD_ORDER)
        rows = conn.execute(
            f"""
            SELECT
              o.occurrence_id,
              s.series_id,
              o.display_name,
              o.event_year,
              o.date_start,
              o.date_end,
              o.date_status,
              o.lifecycle_status,
              {axis_select}
              o.confidence,
              o.source_kind,
              o.source_url,
              o.public_intro_override,
              o.detail,
              (
                SELECT od.date_start
                FROM occurrence_dates od
                WHERE od.occurrence_id = o.occurrence_id
                  AND od.date_type = 'historical_reference'
                  AND od.date_start >= ?
                  AND od.date_start < ?
                ORDER BY od.date_start DESC
                LIMIT 1
              ) AS historical_reference_date_start,
              (
                SELECT od.date_end
                FROM occurrence_dates od
                WHERE od.occurrence_id = o.occurrence_id
                  AND od.date_type = 'historical_reference'
                  AND od.date_start >= ?
                  AND od.date_start < ?
                ORDER BY od.date_start DESC
                LIMIT 1
              ) AS historical_reference_date_end,
              s.canonical_name AS series_name,
              s.annual_months_json,
              s.public_intro AS series_intro,
              v.venue_id,
              v.canonical_name AS venue,
              v.area,
              v.scale,
              v.access,
              v.address,
              v.past_memo,
              v.public_intro AS venue_intro,
              v.latitude,
              v.longitude
            FROM event_occurrences o
            JOIN event_series s ON s.series_id = o.series_id
            JOIN venues v ON v.venue_id = o.venue_id
            WHERE v.area IN ({ward_placeholders})
              AND v.review_status = 'active'
              AND o.origin = 'curated'
              AND s.status = 'active'
              AND o.lifecycle_status NOT IN ('merged', 'duplicate', 'rejected', 'superseded_by_curated')
            ORDER BY v.area, v.canonical_name, o.display_name, o.event_year
            """,
            [
                f"{previous_year:04d}-01-01",
                f"{target_year:04d}-01-01",
                f"{previous_year:04d}-01-01",
                f"{target_year:04d}-01-01",
                *WARD_ORDER,
            ],
        ).fetchall()

    for row in rows:
        if row["date_start"]:
            date = row["date_start"]
            date_end = row["date_end"] or None
        elif row["historical_reference_date_start"]:
            date = row["historical_reference_date_start"]
            date_end = row["historical_reference_date_end"] or None
        else:
            date = None
            date_end = None
        annual_months = [
            int(month)
            for month in _json_list(row["annual_months_json"])
            if isinstance(month, int) or str(month).isdigit()
        ]
        months = {month for month in annual_months if 1 <= int(month) <= 12}
        if date:
            months.add(int(date[5:7]))
        raw_detail = clean_public_text(row["detail"])
        description = clean_public_text(row["public_intro_override"] or row["series_intro"] or row["venue_intro"])
        public_name = public_series_name(clean_public_text(row["display_name"] or row["series_name"]))
        if date:
            hints = hints_from_date_range(date, date_end)
            jun = jun_labels_from_date_range(date, date_end)
        else:
            hints = merge_hints(
                hints_from_text(raw_detail),
                hints_from_text(row["past_memo"]),
                months=months,
            )
            jun = merge_jun_labels(jun_labels(raw_detail), jun_labels(row["past_memo"]), jun_labels_from_hints(hints))
        songs = extract_song_hints(description, raw_detail)
        rdb_song_hints = rdb_songs.get(row["occurrence_id"])
        if rdb_song_hints:
            # RDB is authoritative once it has song data for this occurrence: the
            # legacy song_occurrences.json snapshot is frozen (2026-06-20) and would
            # otherwise unconditionally overwrite RDB-computed probabilities with
            # stale values (see calibrate_song_probabilities_rdb.py).
            songs = merge_song_occurrence_hints(songs, {"songs": rdb_song_hints})
        else:
            occurrence = song_occurrences.get(
                _song_occurrence_key(public_name, row["venue"], int(row["event_year"] or target_year))
            )
            songs = merge_song_occurrence_hints(songs, occurrence)
        songs = strip_song_internal_fields(songs)
        date_candidates = [] if date else date_candidates_by_event.get(row["occurrence_id"], [])
        events.append({
            "name": public_name,
            "_source": "master_rdb",
            "_occurrence_id": row["occurrence_id"],
            "_series_id": row["series_id"],
            "_event_year": int(row["event_year"] or target_year),
            "_venue_id": row["venue_id"],
            "_canonical_state_axes": has_canonical_axes,
            "name_confirmed": True,
            "venue": clean_public_text(row["venue"]),
            "area": row["area"],
            "months": sorted(int(month) for month in months),
            "scale": row["scale"] if row["scale"] in ("大", "中", "小") else None,
            "access": clean_public_text(row["access"]),
            "address": clean_public_text(row["address"]),
            "lat": row["latitude"],
            "lng": row["longitude"],
            "date": date,
            "date_end": date_end,
            "status": _public_status_from_rdb(row["date_status"], row["lifecycle_status"]),
            "date_confidence": _public_confidence_from_rdb(date, row["date_status"]),
            "date_candidates": date_candidates,
            "hints": hints,
            "jun": {str(m): j for m, j in jun.items()},
            "description": description,
            "detail": public_detail_text(raw_detail),
            "source_urls": _rdb_source_urls(raw_detail, row["source_url"], row["source_kind"]),
            "songs": songs,
        })
        if has_canonical_axes:
            events[-1]["current_event_state"] = row["current_event_state"]
            events[-1]["date_certainty_tier"] = row["date_certainty_tier"]
        covered.add(row["venue_id"])

    events.sort(key=lambda e: (WARD_ORDER[e["area"]], e["venue"], e["name"]))
    return events, len(covered), 0, 0


def build_public_events(*, target_year):
    if PUBLIC_SOURCE in {"notion", "legacy_notion"}:
        return build_public_events_from_notion(target_year=target_year)
    return build_public_events_from_master(target_year=target_year)


def write_public_js(path, events):
    with open(path, "w", encoding="utf-8") as f:
        f.write("// Auto-generated by export_public_events.py. Do not edit by hand.\n")
        f.write("const EVENTS = ")
        json.dump(events, f, ensure_ascii=False, indent=2)
        f.write(";\n")


def public_export_today(value=None):
    """Return the date used by date-sensitive public postprocessors."""
    value = value or os.environ.get("BON_ODORI_PUBLIC_TODAY")
    if not value:
        raise ValueError("public export today is required")
    parsed = parse_iso_public_date(value)
    if not parsed:
        raise ValueError(f"invalid public export today: {value}")
    return parsed


def parse_iso_public_date(value):
    if not value:
        return None
    try:
        year, month, day = [int(part) for part in str(value).split("-")]
        from datetime import date

        return date(year, month, day)
    except Exception:
        return None


def apply_public_recurrence_metadata(events, *, target_year, today):
    """Attach public category and recurrence fields to the production export."""
    return enrich_public_events(
        events,
        build_rows(
            events,
            target_year=target_year,
            today=public_export_today(today),
        ),
    )


def apply_public_site_postprocessors(
    events, *, target_year, today, prefer_existing_axes=False
):
    """Apply the public-site-only fields that used to be run as separate steps."""
    from public_json_postprocessors.apply_public_historical_references import (
        apply_historical_references,
        load_fixed_date_rules,
    )
    from public_json_postprocessors.apply_public_season_hints import apply_season_hints

    events = apply_historical_references(
        events,
        target_year=target_year,
        today=public_export_today(today),
        fixed_date_rules=load_fixed_date_rules(),
    )["events"]
    events = apply_display_tiers(
        events, prefer_existing_axes=prefer_existing_axes, target_year=target_year
    )
    events = apply_season_hints(events, target_year=target_year)["events"]
    return apply_display_tiers(
        events, prefer_existing_axes=prefer_existing_axes, target_year=target_year
    )


def sanitize_public_event_details(events):
    """Strip internal evidence logs from detail text in already-built public rows."""
    cleaned = []
    for event in events:
        item = dict(event)
        item["name"] = public_series_name(clean_public_event_name(item.get("name")))
        item["detail"] = public_detail_text(item.get("detail"))
        item["source_urls"] = collapse_public_source_urls(item.get("source_urls"))
        item.pop("youtube_evidence", None)
        item["songs"] = [
            _public_song(song) for song in item.get("songs") or []
            if _song_name(song).strip() not in NON_SONG_LABELS
            and not _is_weak_ambiguous_song(song)
        ]
        item = strip_internal_public_fields(item)
        if is_public_event_complete_enough(item):
            cleaned.append(item)
    return apply_public_event_name_cleanup(cleaned)


def _load_json_file(path, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _weekday_label(value):
    parsed = parse_iso_public_date(value)
    return PUBLIC_WEEKDAYS[parsed.weekday()] if parsed else ""


def _rdb_prediction_payload(row):
    try:
        payload = json.loads(row.get("source_payload_json") or "{}")
    except json.JSONDecodeError:
        payload = {}
    evidence_years = payload.get("evidence_years") or []
    start = row.get("date_start") or payload.get("predicted_date_start") or ""
    end = row.get("date_end") or payload.get("predicted_date_end") or start
    prediction = {
        "rule_type": row.get("rule_type") or payload.get("rule_type") or "",
        "predicted_date_start": start,
        "predicted_date_end": end,
        "predicted_weekday_start": payload.get("predicted_weekday_start") or _weekday_label(start),
        "predicted_weekday_end": payload.get("predicted_weekday_end") or _weekday_label(end),
        "duration_days": payload.get("duration_days"),
        "score": row.get("score") if row.get("score") is not None else payload.get("score"),
        "confidence": row.get("confidence") or payload.get("confidence") or "unknown",
        "basis": row.get("basis") or payload.get("basis") or "",
        "evidence_years": evidence_years,
        "evidence_count": payload.get("evidence_count") or len(evidence_years),
        "evidence_rows": payload.get("evidence_rows") or [],
    }
    return {
        "series_key": payload.get("series_key") or row.get("target_series_id") or "",
        "event_name": payload.get("event_name") or row.get("target_event_name") or "",
        "venue": payload.get("venue") or "",
        "target_year": row.get("predicted_year"),
        "prediction": prediction,
        "candidate_rules": payload.get("candidate_rules") or [prediction],
        "actual_observations": payload.get("actual_observations") or [],
        "rdb_prediction": {
            "predicted_date_id": row.get("predicted_date_id"),
            "application_status": row.get("application_status"),
            "source": row.get("source"),
        },
    }


def _prediction_key(row):
    return (str(row.get("event_name") or "").strip(), str(row.get("venue") or "").strip())


def load_rdb_public_date_predictions(db_path=MASTER_DB, *, target_year):
    db_path = os.fspath(db_path)
    if not os.path.exists(db_path):
        return None
    conn = connect_existing(db_path)
    try:
        conn.row_factory = sqlite3.Row
        try:
            rows = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT predicted_date_id, historical_candidate_id, target_series_id,
                           target_occurrence_id, target_event_name, predicted_year,
                           date_start, date_end, date_status, rule_type, basis,
                           confidence, score, application_status, source,
                           source_payload_json
                    FROM predicted_occurrence_dates
                    WHERE predicted_year = ?
                      AND date_status = 'predicted'
                    ORDER BY target_event_name, date_start, predicted_date_id
                    """,
                    (target_year,),
                )
            ]
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            rows = []
    finally:
        conn.close()
    if not rows:
        return None
    predictions = [_rdb_prediction_payload(row) for row in rows]
    predictions = [row for row in predictions if row.get("event_name") and row.get("venue")]
    if not predictions:
        return None
    counts = {}
    for row in predictions:
        source = ((row.get("rdb_prediction") or {}).get("source") or "unknown")
        counts[source] = counts.get(source, 0) + 1
    return {
        "generated_by": "export_public_events.py",
        "source": "master_rdb.predicted_occurrence_dates",
        "target_year": target_year,
        "summary": {
            "prediction_count": len(predictions),
            "source_counts": counts,
        },
        "predictions": predictions,
    }


def merge_prediction_payloads(primary, fallback):
    primary = primary or {}
    fallback = fallback or {}
    merged = dict(primary)
    predictions = list(primary.get("predictions") or [])
    seen = {_prediction_key(row) for row in predictions}
    fallback_used = []
    for row in fallback.get("predictions") or []:
        key = _prediction_key(row)
        if key in seen:
            continue
        predictions.append(row)
        fallback_used.append({"event_name": row.get("event_name"), "venue": row.get("venue")})
        seen.add(key)
    merged["predictions"] = predictions
    summary = dict(merged.get("summary") or {})
    summary["prediction_count"] = len(predictions)
    summary["json_fallback_count"] = len(fallback_used)
    summary["json_fallback"] = fallback_used
    merged["summary"] = summary
    return merged


def require_no_prediction_json_fallback(payload):
    summary = payload.get("summary") or {}
    fallback_count = int(summary.get("json_fallback_count") or 0)
    if fallback_count:
        fallback_names = ", ".join(
            row.get("event_name") or "(unknown)"
            for row in summary.get("json_fallback") or []
        )
        raise RuntimeError(
            f"public date prediction JSON fallback is forbidden for {fallback_count} event(s): {fallback_names}"
        )
    return payload


def prediction_payload_for_target_year(payload, *, target_year):
    """Discard stale JSON predictions from a different projection year."""
    target_year = normalize_target_year(target_year)
    payload = payload or {}
    predictions = [
        row
        for row in payload.get("predictions") or []
        if row.get("target_year") == target_year
    ]
    filtered = dict(payload)
    filtered["target_year"] = target_year
    filtered["predictions"] = predictions
    summary = dict(filtered.get("summary") or {})
    summary["prediction_count"] = len(predictions)
    filtered["summary"] = summary
    return filtered


def load_public_date_predictions_for_export(*, target_year, db_path=MASTER_DB):
    rdb_payload = load_rdb_public_date_predictions(db_path, target_year=target_year)
    json_payload = prediction_payload_for_target_year(
        load_public_date_prediction_json(DATE_PREDICTIONS, {}),
        target_year=target_year,
    )
    return require_no_prediction_json_fallback(merge_prediction_payloads(rdb_payload, json_payload))


def _override_matches(event, match):
    if event.get("name") != match.get("name"):
        return False
    venues = match.get("venues")
    if venues is not None:
        return event.get("venue") in venues
    if match.get("venue") is not None:
        return event.get("venue") == match.get("venue")
    return True


def apply_public_event_overrides(events, overrides=None):
    """Apply reviewed public-only patches that are not yet in the Notion source."""
    payload = overrides if overrides is not None else _load_json_file(PUBLIC_EVENT_OVERRIDES_JSON, {})
    rules = payload.get("overrides") or []
    if not rules:
        return events

    patched = []
    for event in events:
        item = dict(event)
        skip = False
        for rule in rules:
            if not _override_matches(item, rule.get("match") or {}):
                continue
            if rule.get("skip"):
                skip = True
                break
            for field in rule.get("remove") or []:
                item.pop(field, None)
            item.update(rule.get("set") or {})
        if not skip:
            patched.append(item)
    return apply_public_event_name_cleanup(patched)


def is_public_event_complete_enough(event):
    """Drop empty fallback rows that have no useful public date, venue, or geo signal."""
    if event.get("name_confirmed"):
        return True
    useful_fields = [
        event.get("date"),
        event.get("status"),
        event.get("months"),
        event.get("hints"),
        event.get("lat"),
        event.get("lng"),
        event.get("address"),
        event.get("access"),
        event.get("description"),
        event.get("source_urls"),
        event.get("songs"),
    ]
    return any(value not in (None, "", [], {}) for value in useful_fields)


def public_series_key(event):
    """Return the RDB series identity used to suppress replaced last-year cards.

    This intentionally has no text/venue-based fallback. Matching on
    normalized name and venue strings is fragile against edition-number
    prefixes, sub-event suffixes, venue name drift, and placeholder names
    (all seen in production), and a coincidental text match could merge two
    unrelated events and silently drop one. Without a trustworthy
    `_series_id`, an event is simply left unsuppressed (both cards shown)
    rather than risk a wrong merge.
    """
    series_id = event.get("_series_id")
    return f"series:{series_id}" if series_id else None


def _song_name(song):
    return song if isinstance(song, str) else str(song.get("name") or "")


def _song_dedupe_key(name):
    normalized = unicodedata.normalize("NFKC", str(name or "")).casefold()
    chars = []
    for char in normalized:
        if char.isspace():
            continue
        if unicodedata.category(char)[0] in {"P", "S"}:
            continue
        chars.append(char)
    return "".join(chars)


def _public_song(song):
    if isinstance(song, str):
        return {"name": song, "confidence": "hint"}
    return {
        key: song[key]
        for key in ["name", "confidence", "probability", "basis", "basis_label"]
        if key in song and song[key] not in (None, "", [])
    }


def strip_internal_public_fields(value):
    if isinstance(value, list):
        cleaned = []
        for item in value:
            if isinstance(item, str) and "youtube.com" in item:
                continue
            cleaned.append(strip_internal_public_fields(item))
        return cleaned
    if not isinstance(value, dict):
        return value

    cleaned = {}
    skip_keys = {
        "youtube_evidence",
        "occurrences",
        "evidence_urls",
        "media_urls",
        "video_urls",
        "source_count",
        "speaker_count",
        "fixed_date_rule",
    }
    for key, item in value.items():
        if key in skip_keys:
            continue
        if key in {"url", "source_url"} and isinstance(item, str) and "youtube.com" in item:
            continue
        cleaned[key] = strip_internal_public_fields(item)
    return cleaned


def public_event_identity_key(event):
    return "|".join(
        str(event.get(key) or "")
        for key in ("name", "venue", "date", "date_end")
    )


def public_event_source_map(events):
    rows = []
    for event in events:
        occurrence_id = event.get("_occurrence_id")
        if not occurrence_id:
            continue
        rows.append(
            {
                "public_event_key": public_event_identity_key(event),
                "name": event.get("name") or "",
                "venue": event.get("venue") or "",
                "date": event.get("date") or "",
                "date_end": event.get("date_end") or "",
                "source": event.get("_source") or "master_rdb",
                "occurrence_id": occurrence_id,
                "series_id": event.get("_series_id") or "",
                "event_year": event.get("_event_year"),
                "venue_id": event.get("_venue_id") or "",
            }
        )
    return {
        "generated_by": "export_public_events.py",
        "scope": "internal_public_event_source_map",
        "public_event_count": len(events),
        "mapped_count": len(rows),
        "rows": rows,
    }


def strip_public_internal_event_fields(events):
    cleaned = []
    for event in events:
        item = strip_internal_public_fields(event)
        for key in (
            "_source",
            "_occurrence_id",
            "_series_id",
            "_event_year",
            "_venue_id",
            "_canonical_state_axes",
        ):
            item.pop(key, None)
        cleaned.append(item)
    return cleaned


def _song_score(song):
    if isinstance(song, str):
        return (0, 0, 0)
    return (
        int(song.get("probability") or 0),
        int(song.get("source_count") or 0),
        int(song.get("evidence_count") or 0),
    )


def _is_weak_ambiguous_song(song):
    name = _song_name(song).strip()
    if name not in AMBIGUOUS_SONG_LABELS:
        return False
    if isinstance(song, str):
        return True
    return (
        int(song.get("evidence_count") or 0) <= 1
        and song.get("basis") in {None, "current_hint", "past_evidence"}
    )


def merge_replacement_songs(current, recurring, *, previous_year):
    """Move useful last-year song evidence onto the current-year replacement card.

    current always wins over recurring for the same song name, rather than the
    higher _song_score() winning: current's songs already reflect RDB-native
    year-over-year inheritance (inherit_song_probabilities_rdb.py) when it applies,
    with an accurate basis_label (e.g. "2025年実測"). Letting recurring's raw
    probability outscore that and win just to have its basis flattened to
    "past_evidence"/"○○年ヒント" below regressed a correctly-labeled inherited
    row back to a less accurate one (found 2026-07-24 auditing 第71回恵比寿駅前盆踊り大会:
    RDB inheritance said "おてもやん 60% 2025年実測", this function's old score-wins
    logic replaced it with "おてもやん 99% 2025年ヒント" from the recurring card).
    recurring only fills in songs current doesn't have at all.
    """
    merged = {}
    for raw_song in current.get("songs") or []:
        name = _song_name(raw_song).strip()
        if not name or name in NON_SONG_LABELS:
            continue
        song = {"name": name, "confidence": "hint", "source_count": 0} if isinstance(raw_song, str) else dict(raw_song)
        merged[_song_dedupe_key(name)] = song
    for raw_song in recurring.get("songs") or []:
        name = _song_name(raw_song).strip()
        if not name or name in NON_SONG_LABELS:
            continue
        if _is_weak_ambiguous_song(raw_song):
            continue
        key = _song_dedupe_key(name)
        if key in merged:
            continue
        song = {"name": name, "confidence": "hint", "source_count": 0} if isinstance(raw_song, str) else dict(raw_song)
        if str(recurring.get("date") or "").startswith(f"{previous_year}-"):
            song["basis"] = "past_evidence"
            song["basis_label"] = f"{previous_year}年ヒント"
            if song.get("probability") is None:
                song["probability"] = 80
        merged[key] = song
    current["songs"] = sorted(
        strip_song_internal_fields(merged.values()),
        key=lambda song: (-_song_score(song)[0], _song_name(song)),
    )


def suppress_replaced_recurring_events(events, *, target_year):
    """Hide previous-year cards when the same RDB series has a target-year card."""
    target_year = normalize_target_year(target_year)
    for event in events:
        event["name"] = public_series_name(event.get("name"))
    current_by_key = {}
    for event in events:
        if not str(event.get("date") or "").startswith(f"{target_year}-"):
            continue
        if event.get("public_category") not in {"upcoming", "ended"}:
            continue
        key = public_series_key(event)
        if key is not None:
            current_by_key[key] = event
    if not current_by_key:
        return events
    for event in events:
        if event.get("public_category") != "recurring_last_year":
            continue
        key = public_series_key(event)
        current = current_by_key.get(key) if key is not None else None
        if current:
            merge_replacement_songs(current, event, previous_year=target_year - 1)
    return [
        event for event in events
        if not (
            event.get("public_category") == "recurring_last_year"
            and public_series_key(event) is not None
            and public_series_key(event) in current_by_key
        )
    ]


def _name_trigram_similarity(name_a, name_b):
    """Rough same-name signal for review sorting only (not a match decision)."""
    def trigrams(text):
        compact = re.sub(r"\s+", "", str(text or ""))
        if len(compact) < 3:
            return {compact} if compact else set()
        return {compact[i:i + 3] for i in range(len(compact) - 2)}

    a, b = trigrams(name_a), trigrams(name_b)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _same_or_adjacent_month(date_a, date_b):
    a, b = parse_iso_public_date(date_a), parse_iso_public_date(date_b)
    if not a or not b:
        return False
    diff = abs(a.month - b.month)
    return diff <= 1 or diff >= 11


def find_series_split_review_candidates(events, *, target_year):
    """Flag same-venue occurrence pairs that look like one series split across
    two RDB series_id values (an earlier-year card and a target-year card
    that suppress_replaced_recurring_events can't merge because their
    series_id differs).

    This only ever reports candidates for a human to review and fix in the
    RDB; it must never merge events on its own. A coincidental venue+month
    match between two genuinely different events is a cheap false positive
    to dismiss by eye, but a wrong automatic merge could silently drop a
    real event from the public site.
    """
    target_year = normalize_target_year(target_year)
    past = [
        e for e in events
        if e.get("_venue_id")
        and e.get("_series_id")
        and isinstance(e.get("_event_year"), int)
        and e["_event_year"] < target_year
        and e.get("public_category") in {"recurring_last_year", "ended"}
    ]
    current = [
        e for e in events
        if e.get("_venue_id")
        and e.get("_series_id")
        and e.get("_event_year") == target_year
        and e.get("public_category") in {"upcoming", "ended"}
    ]
    candidates = []
    for p in past:
        for c in current:
            if p["_venue_id"] != c["_venue_id"] or p["_series_id"] == c["_series_id"]:
                continue
            if not _same_or_adjacent_month(p.get("date"), c.get("date")):
                continue
            candidates.append({
                "area": p.get("area"),
                "venue": p.get("venue"),
                "name_similarity": round(_name_trigram_similarity(p.get("name"), c.get("name")), 3),
                "past_occurrence_id": p.get("_occurrence_id"),
                "past_series_id": p["_series_id"],
                "past_name": p.get("name"),
                "past_date": p.get("date"),
                "past_date_end": p.get("date_end"),
                "current_occurrence_id": c.get("_occurrence_id"),
                "current_series_id": c["_series_id"],
                "current_name": c.get("name"),
                "current_date": c.get("date"),
                "current_date_end": c.get("date_end"),
            })
    candidates.sort(key=lambda item: -item["name_similarity"])
    return candidates


def write_series_split_review(candidates, *, json_path, md_path):
    os.makedirs(os.path.dirname(json_path), exist_ok=True)
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"candidates": candidates}, f, ensure_ascii=False, indent=2)
    lines = [
        "# 系列分裂レビュー候補",
        "",
        "同じ会場・近い時期だが RDB 上で series_id が別々になっている過去年×今年ペア。",
        "本当に同一系列なら series_id を統合してください。無関係な別イベントなら無視してください。",
        "",
    ]
    if not candidates:
        lines.append("候補なし。")
    for item in candidates:
        lines.append(
            f"- [{item['name_similarity']}] {item['area']} / {item['venue']}: "
            f"「{item['past_name']}」({item['past_date']}, {item['past_series_id']}) ⇔ "
            f"「{item['current_name']}」({item['current_date']}, {item['current_series_id']})"
        )
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def project_public_events(events, *, target_year, db_path=MASTER_DB, today):
    """Run the production public-event projection without writing output files."""
    projection_today = public_export_today(today)
    events = apply_public_event_overrides(sanitize_public_event_details(events))
    events = suppress_replaced_recurring_events(
        apply_public_recurrence_metadata(
            events, target_year=target_year, today=projection_today
        ),
        target_year=target_year,
    )
    prediction_payload = load_public_date_predictions_for_export(
        target_year=target_year,
        db_path=db_path,
    )
    prediction_result = apply_public_date_predictions(events, prediction_payload)
    prediction_result["report"]["prediction_input"] = {
        "source": prediction_payload.get("source") or str(DATE_PREDICTIONS),
        "summary": prediction_payload.get("summary") or {},
    }
    prefer_existing_axes = bool(events) and all(
        event.get("_canonical_state_axes")
        and event.get("current_event_state")
        and event.get("date_certainty_tier")
        for event in prediction_result["events"]
    )
    events = apply_display_tiers(
        prediction_result["events"],
        prefer_existing_axes=prefer_existing_axes,
        target_year=target_year,
    )
    events = apply_public_site_postprocessors(
        events,
        target_year=target_year,
        today=projection_today,
        prefer_existing_axes=prefer_existing_axes,
    )
    return {
        "events": events,
        "public_events": strip_public_internal_event_fields(events),
        "source_map": public_event_source_map(events),
        "prediction_report": prediction_result["report"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--today",
        required=True,
        help="JST date used for public historical-reference expiry checks (YYYY-MM-DD).",
    )
    parser.add_argument("--target-year", type=int, required=True)
    args = parser.parse_args(argv)

    if PUBLIC_SOURCE in {"notion", "legacy_notion"} and not os.environ.get("NOTION_API_TOKEN"):
        print("Notion未設定 (NOTION_API_TOKEN) のためイベント公開エクスポートをスキップ")
        return
    try:
        events, covered, fallback, skipped = build_public_events(
            target_year=args.target_year
        )
    except urllib.error.HTTPError as e:
        print(f"イベント公開エクスポート失敗 (HTTP {e.code})。スキップ")
        return
    projection = project_public_events(
        events,
        target_year=args.target_year,
        db_path=MASTER_DB,
        today=args.today,
    )
    events = projection["events"]
    source_map = projection["source_map"]
    public_events = projection["public_events"]
    write_public_date_prediction_json(DATE_PREDICTION_REPORT, projection["prediction_report"])

    series_split_candidates = find_series_split_review_candidates(
        events, target_year=args.target_year
    )
    write_series_split_review(
        series_split_candidates,
        json_path=SERIES_SPLIT_REVIEW_JSON,
        md_path=SERIES_SPLIT_REVIEW_MD,
    )
    if series_split_candidates:
        print(
            f"  系列分裂レビュー候補: {len(series_split_candidates)} 件 "
            f"→ {SERIES_SPLIT_REVIEW_MD}（要目視レビュー）"
        )

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(public_events, f, ensure_ascii=False, indent=2)
    write_public_js(OUT_JS, public_events)
    os.makedirs(os.path.dirname(PUBLIC_EVENT_SOURCE_MAP_JSON), exist_ok=True)
    with open(PUBLIC_EVENT_SOURCE_MAP_JSON, "w", encoding="utf-8") as f:
        json.dump(source_map, f, ensure_ascii=False, indent=2)
    song_rows = [
        {
            "name": e["name"],
            "venue": e["venue"],
            "area": e["area"],
            "date": e["date"],
            "songs": e["songs"],
        }
        for e in public_events
        if e.get("songs")
    ]
    with open(OUT_SONGS_JSON, "w", encoding="utf-8") as f:
        json.dump(song_rows, f, ensure_ascii=False, indent=2)

    named = sum(1 for e in public_events if e["name_confirmed"])
    no_month = sum(1 for e in public_events if not e["months"])
    with_songs = sum(1 for e in public_events if e.get("songs"))
    print(f"イベント公開エクスポート完了: {len(public_events)} 件 → {OUT_JSON}")
    print(f"  Claude Design貼り付け用JS: {OUT_JS}")
    print(f"  イベント名あり: {named} 件（{covered} 会場）/ 名称確認中フォールバック: {fallback} 件")
    print(f"  月情報なし: {no_month} 件 / 23区外・会場なしで除外したイベント: {skipped} 件")
    print(f"  曲目ヒントあり: {with_songs} 件 → {OUT_SONGS_JSON}")


if __name__ == "__main__":
    main()
