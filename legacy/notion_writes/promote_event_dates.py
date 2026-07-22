import argparse
import json
import os
import re
from datetime import date
from pathlib import Path

from manual_apply_guards import require_confirmation
from notion_support.notion_api import NotionApi, date_value, plain_text
from notion_support.notion_config import EVENT_DATA_SOURCE_ID, VENUE_DATA_SOURCE_ID


VOICES = Path("data/voices.json")
BLOG_ROWS = Path("data/blog_venue_rows.json")
OUT = Path("data/event_date_update_candidates.json")
TODAY = date(2026, 6, 10)
TARGET_YEAR = 2026
CONFIRM_PHRASE = "APPLY EVENT DATES TO NOTION"

EVENT_WORDS = (
    "盆踊り", "盆おどり", "盆踊", "納涼", "夏祭り", "まつり", "祭り", "音頭", "輪踊り",
    "BON ODORI", "Bon Odori", "BONODORI", "Bon Dance",
)
SCHEDULE_WORDS = ("開催", "予定", "日程", "決定", "発表", "お知らせ", "告知", "開場", "開始")
NEGATIVE_WORDS = ("中止", "延期", "順延", "雨天中止")
GENERIC_EVENT_NAMES = {
    "盆踊り大会",
    "盆おどり大会",
    "盆踊り",
    "盆おどり",
    "納涼大会",
    "夏祭り",
    "まつり",
    "祭り",
    "桜まつり",
}
DATE_SEP = r"(?:-|〜|~|ー|－|–|—|から|・)"

JP_YEAR_MD_RE = re.compile(
    r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日"
    r"(?:[^0-9]{0,12}" + DATE_SEP + r"[^0-9]{0,12}(?:(20\d{2})年\s*)?(?:(\d{1,2})月\s*)?(\d{1,2})日)?"
)
SLASH_MD_RE = re.compile(
    r"(?<![\d:/])(?:(20\d{2})[/-])?(\d{1,2})[/-](\d{1,2})(?![\d:/])"
    r"(?:[^0-9]{0,12}" + DATE_SEP + r"[^0-9]{0,12}(?:(20\d{2})[/-])?(?:(\d{1,2})[/-])?(\d{1,2}))?"
)
SAME_MONTH_RANGE_RE = re.compile(
    r"(?<![\d:/])(?:(20\d{2})[/-])?(\d{1,2})[/-](\d{1,2})(?![\d:/])"
    r"[^0-9]{0,12}(?:〜|~|-|ー|－|–|—|から|・|、|,)[^0-9]{0,6}"
    r"(\d{1,2})(?=日|[月火水木金土日祝]|\D|$)"
)
EVENT_RE = re.compile(
    r"([一-龥ぁ-んァ-ヶーA-Za-z0-9・☆！! ]{2,48}"
    r"(?:盆踊り大会|盆おどり大会|盆踊り|盆おどり|納涼大会|夏祭り|まつり|祭り|音頭))"
)


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def norm(text):
    text = re.sub(r"\s+", "", text or "")
    text = re.sub(r"第?\d+回", "", text)
    text = text.replace("（名称推定）", "")
    text = text.replace("集い", "つどい")
    text = text.replace("踊り", "おどり")
    return text.casefold()


def is_generic_event_name(text):
    value = norm(text)
    if value in GENERIC_EVENT_NAMES:
        return True
    return value in {"盆おどり", "納涼", "夏まつり", "さくらまつり"}


def text_prop(text):
    return {"rich_text": [{"text": {"content": text[:1900]}}]} if text else {"rich_text": []}


def select_prop(name):
    return {"select": {"name": name}}


def date_prop(start, end=None):
    value = {"start": start}
    if end and end != start:
        value["end"] = end
    return {"date": value}


def event_status(start):
    y, m, d = [int(part) for part in start.split("-")]
    return "終了" if date(y, m, d) < TODAY else "確認済み"


def iso(year, month, day):
    try:
        y, m, d = int(year), int(month), int(day)
        date(y, m, d)
        return f"{y:04d}-{m:02d}-{d:02d}"
    except (TypeError, ValueError):
        return None


def parse_dates(text, spoken_year=None, target_year=TARGET_YEAR):
    results = []
    for match in JP_YEAR_MD_RE.finditer(text or ""):
        y1, m1, d1, y2, m2, d2 = match.groups()
        start = iso(y1, m1, d1)
        end = iso(y2 or y1, m2 or m1, d2) if d2 else None
        if start and start.startswith(f"{target_year}-"):
            results.append({"start": start, "end": end, "explicit_year": True, "raw": match.group(0)})

    for match in SAME_MONTH_RANGE_RE.finditer(text or ""):
        y1, m1, d1, d2 = match.groups()
        year = int(y1 or spoken_year or target_year)
        start = iso(year, m1, d1)
        end = iso(year, m1, d2)
        if start and start.startswith(f"{target_year}-"):
            results.append({"start": start, "end": end, "explicit_year": bool(y1), "raw": match.group(0)})

    for match in SLASH_MD_RE.finditer(text or ""):
        y1, m1, d1, y2, m2, d2 = match.groups()
        year = int(y1 or spoken_year or target_year)
        explicit = bool(y1)
        start = iso(year, m1, d1)
        end_year = int(y2 or year)
        end = iso(end_year, m2 or m1, d2) if d2 else None
        if start and start.startswith(f"{target_year}-"):
            results.append({"start": start, "end": end, "explicit_year": explicit, "raw": match.group(0)})

    unique = {}
    for item in results:
        key = item["start"]
        if key not in unique or (item.get("end") and not unique[key].get("end")):
            unique[key] = item
    return list(unique.values())


def year_hint(text):
    match = re.search(r"(20\d{2})", text or "")
    return int(match.group(1)) if match else None


def extract_event_names(text):
    names = []
    for match in EVENT_RE.finditer(text or ""):
        value = re.sub(r"^[【「『\s]+|[】」』\s]+$", "", match.group(1))
        value = re.sub(r"^\d{4}年", "", value)
        value = re.sub(r"^[\d/年月日（）()水木金土日祝・〜~ -]+", "", value)
        if value and value not in names:
            names.append(value[:80])
    return names


def score_match(event, voice_text, extracted_names, source=None):
    event_name = event["name"]
    venue_names = event["venues"]
    text_norm = norm(voice_text)
    name_norm = norm(event_name)
    score = 0
    reasons = []
    generic_name = is_generic_event_name(event_name)
    venue_exact = any(norm(venue) and norm(venue) in text_norm for venue in venue_names)
    name_matched = bool(name_norm and name_norm in text_norm and not generic_name)
    extracted_matched = False
    if name_matched:
        score += 8
        reasons.append("event_name_exact")
    for extracted in extracted_names:
        ex_norm = norm(extracted)
        if ex_norm and not is_generic_event_name(extracted) and (ex_norm in name_norm or name_norm in ex_norm):
            extracted_matched = True
            score += 6
            reasons.append("extracted_event_name")
            break
    if venue_exact:
        score += 4
        reasons.append("venue_exact")
    elif generic_name:
        return 0, ["generic_name_without_venue"]
    if source == "blog_row" and not (name_matched or extracted_matched):
        score -= 6
        reasons.append("structured_without_event_name:-6")
    if any(word in voice_text for word in SCHEDULE_WORDS):
        score += 2
        reasons.append("schedule_word")
    if source == "blog_row" and venue_exact:
        score += 4
        reasons.append("structured_blog_venue")
    if any(word in voice_text for word in NEGATIVE_WORDS):
        score -= 4
        reasons.append("negative_word")
    return score, reasons


def date_context_matches(event, voice_text, date_info, extracted_names, source=None):
    if source == "blog_row":
        return True

    raw = date_info.get("raw") or ""
    if not raw:
        return True

    lines = (voice_text or "").splitlines()
    raw_line_indexes = [idx for idx, line in enumerate(lines) if raw in line]
    if not raw_line_indexes:
        return True

    tokens = [event.get("name") or ""]
    tokens.extend(event.get("venues") or [])
    tokens.extend(
        name for name in (extracted_names or [])
        if name and not is_generic_event_name(name)
    )
    token_norms = [norm(token) for token in tokens if norm(token)]
    if not token_norms:
        return False

    for idx in raw_line_indexes:
        start = max(0, idx - 1)
        end = min(len(lines), idx + 2)
        window_norm = norm("\n".join(lines[start:end]))
        if any(token in window_norm or window_norm in token for token in token_norms):
            return True
    return False


def load_source_items():
    items = []
    if VOICES.exists():
        for voice in load_json(VOICES):
            item = dict(voice)
            item.setdefault("source", "voice")
            items.append(item)
    if BLOG_ROWS.exists():
        for row in load_json(BLOG_ROWS):
            text = "\n".join(
                part for part in (
                    row.get("date_text") or "",
                    row.get("venue") or "",
                    row.get("description") or "",
                ) if part
            )
            items.append({
                "source": "blog_row",
                "account": "東京盆踊りマップ",
                "name": "東京盆踊りマップ",
                "text": text,
                "date_hint_text": row.get("date_text") or "",
                "url": row.get("detail_url") or row.get("source_url") or "",
                "date": "",
                "row_venue": row.get("venue") or "",
                "region_hint": row.get("region_hint") or "",
            })
    return items


def fetch_events(api):
    venue_rows = api.query_data_source(VENUE_DATA_SOURCE_ID)
    venues = {
        row["id"]: plain_text(row.get("properties", {}).get("会場名"))
        for row in venue_rows
    }
    events = []
    for row in api.query_data_source(EVENT_DATA_SOURCE_ID):
        props = row.get("properties", {})
        relations = props.get("会場", {}).get("relation", [])
        venue_names = [venues.get(rel["id"], "") for rel in relations if venues.get(rel["id"])]
        events.append({
            "id": row["id"],
            "name": plain_text(props.get("イベント名")),
            "venues": venue_names,
            "date": date_value(props.get("開催日")) or {},
            "status": plain_text(props.get("状態")),
            "detail": plain_text(props.get("開催パターン詳細")),
            "url": plain_text(props.get("情報源URL")),
        })
    return [event for event in events if event["name"] and event["venues"]]


def build_candidates(events, voices, target_year=TARGET_YEAR):
    candidates = []
    for voice in voices:
        text = voice.get("text") or ""
        if not any(word in text for word in EVENT_WORDS):
            continue
        date_text = voice.get("date_hint_text") or text
        spoken_year = year_hint(date_text) or year_hint(text)
        if voice.get("date"):
            try:
                spoken_year = spoken_year or int(voice["date"][:4])
            except ValueError:
                pass
        dates = parse_dates(date_text, spoken_year=spoken_year, target_year=target_year)
        if not dates:
            continue
        names = extract_event_names(text)
        for event in events:
            score, reasons = score_match(event, text, names, source=voice.get("source"))
            if score < 10:
                continue
            for date_info in dates:
                if not date_context_matches(event, text, date_info, names, source=voice.get("source")):
                    continue
                current_start = event.get("date", {}).get("start")
                current_end = event.get("date", {}).get("end")
                start = date_info["start"]
                end = date_info.get("end")
                same_date = current_start == start and (current_end or None) == (end or None)
                refresh_only = (
                    same_date
                    and voice.get("source") == "blog_row"
                    and (
                        "X投稿から確定日として反映" in (event.get("detail") or "")
                        or (event.get("detail") or "").startswith("更新前開催日:")
                    )
                )
                date_end_completion = (
                    current_start == start
                    and not current_end
                    and end
                    and end != start
                )
                if same_date and not refresh_only:
                    continue
                if (
                    current_start
                    and current_start <= start <= (current_end or current_start)
                    and not refresh_only
                    and not date_end_completion
                ):
                    continue
                candidates.append({
                    "event_id": event["id"],
                    "event_name": event["name"],
                    "venues": event["venues"],
                    "current_date": current_start,
                    "current_date_end": current_end,
                    "new_date": start,
                    "new_date_end": end,
                    "score": score,
                    "reasons": reasons,
                    "source": voice.get("source"),
                    "account": voice.get("account"),
                    "spoken_at": voice.get("date"),
                    "url": voice.get("url"),
                    "text": text,
                    "raw_date": date_info.get("raw"),
                    "extracted_event_names": names,
                    "refresh_only": refresh_only,
                })
    best = {}
    for item in candidates:
        key = (item["event_id"], item["new_date"])
        if (
            key not in best
            or item["score"] > best[key]["score"]
            or (
                item["score"] == best[key]["score"]
                and item.get("new_date_end")
                and not best[key].get("new_date_end")
            )
        ):
            best[key] = item
    return sorted(best.values(), key=lambda c: (-c["score"], c["event_name"], c["new_date"]))


def apply_candidates(api, candidates, min_score):
    applied = []
    for item in candidates:
        if item["score"] < min_score:
            continue
        detail_lines = []
        date_end_completion = (
            item.get("current_date") == item.get("new_date")
            and not item.get("current_date_end")
            and item.get("new_date_end")
            and item.get("new_date_end") != item.get("new_date")
        )
        if item.get("current_date") and not item.get("refresh_only") and not date_end_completion:
            detail_lines.append(f"更新前開催日: {item['current_date']}")
        source_label = "東京盆踊りマップ" if item.get("source") == "blog_row" else "X投稿"
        detail_lines.append(
            f"{item['new_date']}{'〜' + item['new_date_end'] if item.get('new_date_end') else ''} "
            f"開催予定。{source_label}から確定日として反映。"
        )
        if item.get("text"):
            detail_lines.append(item["text"])
        props = {
            "開催日": date_prop(item["new_date"], item.get("new_date_end")),
            "状態": select_prop(event_status(item["new_date"])),
            "開催パターン種別": select_prop("不明"),
            "開催パターン詳細": text_prop("\n".join(detail_lines)),
        }
        if item.get("url"):
            props["情報源URL"] = {"url": item["url"]}
        api.update_page(item["event_id"], props)
        applied.append(item)
    return applied


def filter_candidates(candidates, event_name=None, event_id=None):
    rows = candidates
    if event_name:
        rows = [item for item in rows if item.get("event_name") == event_name]
    if event_id:
        rows = [item for item in rows if item.get("event_id") == event_id]
    return rows


def main():
    parser = argparse.ArgumentParser(description="Promote confirmed event dates from local X/voice evidence.")
    parser.add_argument("--apply", action="store_true", help="Update Notion for high-confidence candidates.")
    parser.add_argument("--confirm", default="")
    parser.add_argument("--min-score", type=int, default=18, help="Minimum score for --apply.")
    parser.add_argument("--target-year", type=int, default=TARGET_YEAR)
    parser.add_argument("--event-name", help="Only show/apply candidates for this exact event name.")
    parser.add_argument("--event-id", help="Only show/apply candidates for this exact Notion page id.")
    args = parser.parse_args()
    try:
        require_confirmation(args.apply, args.confirm, CONFIRM_PHRASE, "event-date Notion promotion")
    except ValueError as exc:
        parser.error(str(exc))

    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    events = fetch_events(api)
    voices = load_source_items()
    candidates = build_candidates(events, voices, target_year=args.target_year)
    filtered = filter_candidates(candidates, event_name=args.event_name, event_id=args.event_id)
    OUT.write_text(json.dumps({"candidates": filtered}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"candidates={len(filtered)} total={len(candidates)} -> {OUT}")
    high = [c for c in filtered if c["score"] >= args.min_score]
    print(f"high_confidence={len(high)} min_score={args.min_score}")
    for item in high[:20]:
        end = f"〜{item['new_date_end']}" if item.get("new_date_end") else ""
        print(f"{item['score']}\t{item['event_name']}\t{item['new_date']}{end}\t{item.get('current_date') or ''}\t{item.get('url') or ''}")
    if args.apply:
        applied = apply_candidates(api, high, args.min_score)
        print(f"applied={len(applied)}")


if __name__ == "__main__":
    main()
