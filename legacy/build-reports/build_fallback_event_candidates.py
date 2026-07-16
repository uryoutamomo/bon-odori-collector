import json
import re
from pathlib import Path

from triage_blog_venue_candidates import normalize


EVENTS_PUBLIC = Path("data/public/events_public.json")
VENUE_MASTER = Path("data/venue_master.json")
BLOG_ROWS = Path("data/blog_venue_rows.json")
OUT = Path("data/fallback_event_candidates.json")


NO_EVENT_KEYWORDS = (
    "証拠は確認できず",
    "具体的開催証拠は見つからず",
    "具体的情報は見つからず",
    "具体的情報は確認できず",
    "未確認",
    "要継続調査",
)
EVENT_KEYWORDS = (
    "盆踊り",
    "盆おどり",
    "ぼんおどり",
    "BON",
    "奉納踊り",
    "奉納おどり",
    "輪踊り",
    "民踊",
    "納涼",
    "まつり",
    "祭り",
    "フェス",
)
DATE_RE = re.compile(
    r"\s*(?:20\d{2}\s*)?(?:年)?\d{1,2}月\d{1,2}日[^。]*|"
    r"\s*\d{1,2}/\d{1,2}[^。]*|"
    r"\s*\d{1,2}月\d{1,2}日[^。]*"
)


ALIASES = {
    "青葉公園（港区立）": "区立青葉公園",
    "すみだ公園（隅田公園・墨田区側）": "すみだ公園",
    "中之郷公園（中之郷児童遊園）": "中之郷公園",
    "本四三ツ目児童遊園（三つ目児童公園）": "三つ目児童公園",
    "江東天祖神社（亀戸天祖神社）": "江東亀戸天祖神社",
    "押上二丁目町会会館前 路上": "押上二町目町会",
    "青山熊野神社": "区立青葉公園",
}


MANUAL_NAMES = {
    "小網神社": "小網神社の盆踊り（名称推定）",
    "日本橋小学校": "日本橋小学校の盆踊り（名称推定）",
    "日本橋社会教育会館": "第2回 大盆踊り祭 with 坂崎守寛",
    "すみだ公園（隅田公園・墨田区側）": "すみだ公園の盆踊り（名称推定）",
    "中之郷公園（中之郷児童遊園）": "中之郷公園の盆踊り（名称推定）",
    "本四三ツ目児童遊園（三つ目児童公園）": "本四三ツ目児童遊園の盆踊り（名称推定）",
    "横川小学校": "盆☆Dance 夏休み最後の土曜は校庭で踊ろう！",
    "江東天祖神社（亀戸天祖神社）": "江東天祖神社の盆踊り（名称推定）",
    "大井蔵王権現神社": "大井蔵王権現神社の盆踊り（名称推定）",
    "押上二丁目町会会館前 路上": "押上二町目町会 飛木稲荷神社神幸大祭 奉納おどり",
    "平塚中央公園": "中原共和町会 戸越八幡神社祭礼 盆踊り",
    "青山熊野神社": "青山熊野神社例大祭 奉納踊り",
}


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def clean_name(text):
    text = (text or "").split("\n", 1)[0]
    text = re.sub(r"^[「『]", "", text)
    text = re.sub(r"[」』]$", "", text)
    text = DATE_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" 。、")
    text = text.replace("イベント", "").strip(" 。、")
    return text[:80]


def is_event_like(text):
    return any(k in (text or "") for k in EVENT_KEYWORDS)


def is_strong_event_like(text):
    return any(k in (text or "") for k in ("盆踊", "盆おど", "ぼんおど", "BON", "奉納踊", "奉納おど", "輪踊"))


def has_uncertainty(text):
    return any(k in (text or "") for k in NO_EVENT_KEYWORDS)


def extract_name(description, venue):
    first = clean_name(description)
    quoted = re.findall(r"[「『]([^」』]{4,80})[」』]", description or "")
    for q in quoted:
        q = clean_name(q)
        if is_event_like(q):
            return q, False
    if first and is_event_like(first):
        return first, False
    return f"{venue}の盆踊り", True


def parse_date(date_text):
    year = re.search(r"(20\d{2})", date_text or "")
    md = re.search(r"(\d{1,2})/(\d{1,2})", date_text or "")
    if not year or not md:
        return None
    return f"{year.group(1)}-{int(md.group(1)):02d}-{int(md.group(2)):02d}"


def parse_month(date_text, memo):
    for text in (date_text or "", memo or ""):
        m = re.search(r"(\d{1,2})[/月]", text)
        if m:
            return f"{int(m.group(1))}月"
    return ""


def match_blog_row(rows, venue, area):
    targets = [venue, ALIASES.get(venue, venue)]
    target_norms = [normalize(t) for t in targets if t]
    candidates = []
    for row in rows:
        if area and row.get("region_hint") and row.get("region_hint") != area:
            continue
        row_text = f"{row.get('venue') or ''} {row.get('description') or ''}"
        row_norm = normalize(row_text)
        for target in target_norms:
            if target and (target in row_norm or normalize(row.get("venue")) in target):
                candidates.append(row)
                break
    candidates.sort(key=lambda r: (
        0 if is_strong_event_like(r.get("description")) else 1,
        0 if is_event_like(r.get("description")) else 1,
        0 if parse_date(r.get("date_text")) else 1,
        r.get("date_text") or "",
    ))
    return candidates[0] if candidates else None


def main():
    public_events = load_json(EVENTS_PUBLIC)
    venue_master = {v["venue"]: v for v in load_json(VENUE_MASTER)}
    blog_rows = load_json(BLOG_ROWS) if BLOG_ROWS.exists() else []
    fallback = [e for e in public_events if e.get("name_confirmed") is False]

    items = []
    for event in fallback:
        venue = event["venue"]
        master = venue_master.get(venue, {})
        memo = master.get("memo") or ""
        row = match_blog_row(blog_rows, venue, event.get("area"))
        manual_estimated_without_row = False
        if venue in MANUAL_NAMES:
            name = MANUAL_NAMES[venue]
            estimated = "名称推定" in name
            source = "manual"
            if estimated or not is_strong_event_like(name):
                row = None
            manual_estimated_without_row = estimated and row is None
        elif row:
            extracted, estimated = extract_name(row.get("description"), venue)
            name = extracted + ("（名称推定）" if estimated else "")
            source = "blog_row"
        else:
            extracted, estimated = extract_name(memo, venue)
            if has_uncertainty(memo):
                estimated = True
            name = extracted + ("（名称推定）" if estimated and "名称推定" not in extracted else "")
            source = "memo"

        detail_text = None
        source_url = master.get("source_url") or event.get("source_url")
        date_text = None
        if row:
            detail_text = f"{row.get('date_text') or ''}。{row.get('description') or ''}"
            source_url = row.get("detail_url") or row.get("source_url") or source_url
            date_text = row.get("date_text")
        else:
            detail_text = memo
            date_text = memo if not manual_estimated_without_row and "月の手がかり" in memo else ""

        items.append({
            "venue": venue,
            "area": event.get("area"),
            "name": name,
            "estimated": "名称推定" in name,
            "source": source,
            "source_url": source_url,
            "month": parse_month(date_text, memo),
            "date": parse_date(date_text),
            "detail": detail_text,
        })

    OUT.write_text(json.dumps({"items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {len(items)} -> {OUT}")
    print(f"estimated={sum(1 for i in items if i['estimated'])}")
    for item in items:
        print(f"{item['venue']}\t{item['name']}\t{item['source']}\t{item.get('date') or ''}")


if __name__ == "__main__":
    main()
