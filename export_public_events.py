"""Notion「🎆 イベントDB」＋「🏮 会場マスタ」から、Web一般公開サイト用の
イベント一覧（東京23区）をエクスポートするスクリプト。

公開サイトのメインカードは会場ではなく**イベント名**（内田さん指示 2026-06-10）。
- イベントDBの各行（東京23区の会場に紐づくもの）を1カードとして出力
- イベントが未整備の公開会場は「○○の盆踊り」のフォールバックカードを出力
  （name_confirmed=false。イベント登録が進むと自動的に置き換わる）

23区判定・区名正規化・文字化け置換・内部フィールド除去は
export_public_venues.py と同じ方針。出力は data/public/events_public.json。
                                                    — こと（Claude Code）2026-06-10
"""

import json
import os
import re
import urllib.error
import urllib.request

from bon_odori_songs import extract_song_hints
import notion_config
from score_event_recurrence import build_rows, enrich_public_events
from export_public_venues import (
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

OUT_DIR = os.path.join(os.path.dirname(__file__), "data", "public")
OUT_JSON = os.path.join(OUT_DIR, "events_public.json")
OUT_JS = os.path.join(OUT_DIR, "events_public.js")
OUT_SONGS_JSON = os.path.join(OUT_DIR, "event_songs_public.json")
OUT_SONG_OCCURRENCES_JSON = os.path.join(OUT_DIR, "event_song_occurrences_public.json")
DATE_CANDIDATES_JSON = os.path.join(os.path.dirname(__file__), "data", "event_date_update_candidates.json")
FALLBACK_SUPPRESSED_VENUES = {
    # 例大祭名の由来となる神社。実際の奉納踊り会場は青葉公園（港区立）なので、
    # 未整備会場フォールバックとして「青山熊野神社の盆踊り」を出さない。
    "青山熊野神社",
}

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
    r"\[youtube_evidence\][^\n]*(?:\n(?!\[youtube_evidence\]).*)*",
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
    return bool(host) and not any(blocked in host for blocked in PUBLIC_SOURCE_EXCLUDED_HOSTS)


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
    has_notice = False
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
                has_notice = True
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
        sources.append({"label": "告知HPあり", "url": "", "kind": "web"})
    if has_notice:
        sources.append({"label": "告知投稿あり", "url": "", "kind": "post"})
    return sources


def public_detail_text(text):
    """Return a general-reader summary, without internal evidence blocks."""
    if not text:
        return ""
    public = YOUTUBE_EVIDENCE_RE.sub("", text)
    public = re.sub(r"https?://\S+", "", public)
    public = re.sub(r"\s+", " ", public).strip()
    return public


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
        re.sub(r"\s+", "", event_name or "").casefold(),
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


def merge_song_occurrence_hints(existing_songs, occurrence):
    songs = {
        re.sub(r"\s+", "", song.get("name", "")).casefold(): dict(song)
        for song in existing_songs or []
        if song.get("name")
    }
    for song in (occurrence or {}).get("songs", []):
        key = re.sub(r"\s+", "", song.get("name", "")).casefold()
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
    public_songs = []
    for song in songs or []:
        if not isinstance(song, dict):
            public_songs.append(song)
            continue
        item = dict(song)
        item.pop("evidence_urls", None)
        public_songs.append(item)
    return public_songs


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


def build_public_events():
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
            public_name = clean_public_text(name)
            description = clean_public_text(_prop(props, "公開紹介文"))
            raw_detail = clean_public_text(detail_text)
            detail = public_detail_text(raw_detail)
            source_urls = extract_public_source_urls(raw_detail)
            songs = extract_song_hints(description, raw_detail)
            occurrence_year = int(date[:4]) if date else 2026
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


def write_public_js(path, events):
    with open(path, "w", encoding="utf-8") as f:
        f.write("// Auto-generated by export_public_events.py. Do not edit by hand.\n")
        f.write("const EVENTS = ")
        json.dump(events, f, ensure_ascii=False, indent=2)
        f.write(";\n")


def apply_public_recurrence_metadata(events):
    """Attach public category and recurrence fields to the production export."""
    return enrich_public_events(events, build_rows(events))


def main():
    if not os.environ.get("NOTION_API_TOKEN"):
        print("Notion未設定 (NOTION_API_TOKEN) のためイベント公開エクスポートをスキップ")
        return
    try:
        events, covered, fallback, skipped = build_public_events()
    except urllib.error.HTTPError as e:
        print(f"イベント公開エクスポート失敗 (HTTP {e.code})。スキップ")
        return
    events = apply_public_recurrence_metadata(events)

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False, indent=2)
    write_public_js(OUT_JS, events)
    song_rows = [
        {
            "name": e["name"],
            "venue": e["venue"],
            "area": e["area"],
            "date": e["date"],
            "songs": e["songs"],
        }
        for e in events
        if e.get("songs")
    ]
    with open(OUT_SONGS_JSON, "w", encoding="utf-8") as f:
        json.dump(song_rows, f, ensure_ascii=False, indent=2)

    named = sum(1 for e in events if e["name_confirmed"])
    no_month = sum(1 for e in events if not e["months"])
    with_songs = sum(1 for e in events if e.get("songs"))
    print(f"イベント公開エクスポート完了: {len(events)} 件 → {OUT_JSON}")
    print(f"  Claude Design貼り付け用JS: {OUT_JS}")
    print(f"  イベント名あり: {named} 件（{covered} 会場）/ 名称確認中フォールバック: {fallback} 件")
    print(f"  月情報なし: {no_month} 件 / 23区外・会場なしで除外したイベント: {skipped} 件")
    print(f"  曲目ヒントあり: {with_songs} 件 → {OUT_SONGS_JSON}")


if __name__ == "__main__":
    main()
