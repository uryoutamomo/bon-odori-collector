"""Build a review queue for YouTube-derived past event candidates."""

import argparse
import hashlib
import json
import re
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

try:
    from youtube_backfill.event_aliases import find_event_alias, find_venue_alias
except ModuleNotFoundError:  # Direct execution: python3 youtube_backfill/<script>.py
    from event_aliases import find_event_alias, find_venue_alias


DATA = Path("data")
SOURCE = DATA / "youtube_event_candidates.json"
PUBLIC_EVENTS = DATA / "public" / "events_public.json"
VENUE_MASTER = DATA / "venue_master.json"
OUT = DATA / "youtube_event_review.json"
OUT_MD = DATA / "youtube_event_review.md"


VENUE_SUFFIX_RE = re.compile(
    r"([一-龥ぁ-んァ-ヶーA-Za-z0-9・.（）() ]{2,40}"
    r"(?:神社|寺|本願寺|公園|児童公園|広場|駅前|駅|商店街|会館|学校|小学校|中学校|"
    r"プラザ|センター|ホール|パーク|タワー|ラゾーナ川崎|歌舞伎町|自由が丘|渋谷|奥浅草))"
)
EVENT_SUFFIX_RE = re.compile(
    r"([一-龥ぁ-んァ-ヶーA-Za-z0-9・.（）() ]{2,50}"
    r"(?:盆踊り大会|盆おどり大会|納涼盆踊り大会|納涼盆踊り|盆踊り|盆おどり|"
    r"BON ODORI|Bon Odori|Bon Dance|納涼大会|納涼祭|夏祭り|夏まつり|民踊大会|"
    r"民謡大会|民踊の集い|踊り大会|まつり|祭り))"
)
DATE_PREFIX_RE = re.compile(r"20\d{2}年\d{1,2}月\d{1,2}日(?:に|、| )*")
TITLE_DECOR_RE = re.compile(r"【[^】]{1,40}】|\([^)]{1,40}\)|（[^）]{1,40}）")
SPACE_RE = re.compile(r"\s+")


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


def write_text(path, text):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")


def norm(value):
    value = str(value or "")
    value = re.sub(r"[\s　\"'“”‘’「」『』【】\[\]（）()・、。!！?？:：/／\\|｜~〜\-‐‑–—_]+", "", value)
    value = value.replace("おどり", "踊り").replace("ボンダンス", "盆踊り")
    return value.casefold()


def compact(value):
    return SPACE_RE.sub(" ", str(value or "")).strip()


def clean_hint(value):
    value = compact(value)
    value = TITLE_DECOR_RE.sub("", value)
    value = DATE_PREFIX_RE.sub("", value)
    value = re.sub(r"^\d+\s*", "", value)
    value = re.sub(r"(?:\d+日目|\d+部|第\d+部|\d+終?)", "", value)
    value = re.sub(r"(?:東京都|神奈川県|埼玉県|千葉県|大阪府|福岡県)[^\s、。]*$", "", value)
    return compact(value).strip(" -:：、。")


def candidate_key(row):
    raw = "\0".join(str(row.get(key) or "") for key in ("event_date", "event_name", "venue", "url"))
    return "youtube-event:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def extract_quoted_event(text):
    for match in re.finditer(r"[「『]([^」』]{2,60})[」』]", text or ""):
        value = clean_hint(match.group(1))
        if re.search(r"(盆踊り|盆おどり|BON ODORI|Bon Odori|納涼|民踊|まつり|祭り)", value):
            return value
    return ""


def infer_event_name(row):
    text = "\n".join([
        row.get("description_excerpt") or "",
        row.get("title") or "",
        row.get("event_name_hint") or "",
    ])
    quoted = extract_quoted_event(text)
    if quoted:
        return quoted
    matches = [clean_hint(match.group(1)) for match in EVENT_SUFFIX_RE.finditer(text)]
    matches = [value for value in matches if 3 <= len(value) <= 50]
    if matches:
        matches.sort(key=lambda value: (("盆踊り" not in value and "Bon" not in value), len(value)))
        return matches[0]
    return clean_hint(row.get("event_name_hint") or row.get("title") or "")


def infer_venue(row):
    text = "\n".join([
        row.get("description_excerpt") or "",
        row.get("title") or "",
        row.get("venue_hint") or "",
    ])
    place_match = re.search(r"(?:場所|会場|開催場所)[:：]\s*([^\n。]{2,50})", text)
    if place_match:
        return clean_hint(place_match.group(1))
    held_match = re.search(r"([^\n。]{2,50}?)(?:で行われました|で開催|にて開催|での盆踊り)", text)
    if held_match:
        return clean_hint(held_match.group(1))
    matches = [clean_hint(match.group(1)) for match in VENUE_SUFFIX_RE.finditer(text)]
    matches = [value for value in matches if 2 <= len(value) <= 40]
    if matches:
        matches.sort(key=len)
        return matches[0]
    return clean_hint(row.get("venue_hint") or "")


def date_overlaps(candidate_date, event):
    if not candidate_date:
        return False
    start = event.get("date") or ""
    end = event.get("date_end") or start
    if not start:
        return False
    candidate_md = candidate_date[5:]
    return start[5:] <= candidate_md <= end[5:]


def score_event_match(row, event):
    score = 0
    reasons = []
    event_name_key = norm(row.get("event_name"))
    venue_key = norm(row.get("venue"))
    known_event_key = norm(event.get("name"))
    known_venue_key = norm(event.get("venue"))
    if event_name_key and known_event_key:
        if event_name_key == known_event_key:
            score += 55
            reasons.append("event_exact")
        elif event_name_key in known_event_key or known_event_key in event_name_key:
            score += 38
            reasons.append("event_partial")
        elif find_event_alias(event.get("name"), row.get("event_name"), norm):
            score += 55
            reasons.append("event_alias")
    if venue_key and known_venue_key:
        if venue_key == known_venue_key:
            score += 45
            reasons.append("venue_exact")
        elif venue_key in known_venue_key or known_venue_key in venue_key:
            score += 25
            reasons.append("venue_partial")
        elif find_venue_alias(event.get("venue"), row.get("venue"), norm):
            score += 45
            reasons.append("venue_alias")
    if date_overlaps(row.get("event_date"), event):
        score += 20
        reasons.append("month_day")
    return score, reasons


def match_public_event(row, public_events):
    best = None
    for event in public_events:
        score, reasons = score_event_match(row, event)
        if score <= 0:
            continue
        candidate = {
            "name": event.get("name") or "",
            "venue": event.get("venue") or "",
            "date": event.get("date") or "",
            "date_end": event.get("date_end") or "",
            "status": event.get("status") or "",
            "score": score,
            "reasons": reasons,
        }
        if best is None or score > best["score"]:
            best = candidate
    return best if best and best["score"] >= 55 else None


def match_venue(row, venues):
    venue_key = norm(row.get("venue"))
    if not venue_key:
        return None
    best = None
    for venue in venues:
        known_key = norm(venue.get("venue"))
        if not known_key:
            continue
        score = 0
        reasons = []
        if venue_key == known_key:
            score += 80
            reasons.append("venue_exact")
        elif venue_key in known_key or known_key in venue_key:
            score += 55
            reasons.append("venue_partial")
        if score <= 0:
            continue
        candidate = {
            "venue": venue.get("venue") or "",
            "region": venue.get("region") or venue.get("area") or "",
            "notion_url": venue.get("notion_url") or "",
            "score": score,
            "reasons": reasons,
        }
        if best is None or score > best["score"]:
            best = candidate
    return best if best and best["score"] >= 55 else None


def review_priority(row):
    if row.get("matched_public_event"):
        return "既存補強"
    if row.get("setlist_count", 0) >= 5 and row.get("event_date") and row.get("venue_matched"):
        return "登録候補"
    if row.get("setlist_count", 0) >= 2 and row.get("event_date"):
        return "要確認"
    if row.get("event_date") and row.get("venue"):
        return "日付会場あり"
    return "保留"


def build_rows(payload, public_events, venues):
    rows = []
    seen = {}
    for source in payload.get("event_candidates") or []:
        row = {
            "video_id": source.get("video_id") or "",
            "url": source.get("url") or "",
            "title": source.get("title") or "",
            "channel_id": source.get("channel_id") or "",
            "channel_title": source.get("channel_title") or "",
            "published_at": source.get("published_at") or "",
            "thumbnail_url": source.get("thumbnail_url") or "",
            "event_date": source.get("event_date") or "",
            "event_name": infer_event_name(source),
            "venue": infer_venue(source),
            "setlist_count": source.get("setlist_count") or 0,
            "setlist_sample": source.get("setlist_sample") or [],
            "description_excerpt": source.get("description_excerpt") or "",
            "source": "youtube_discovery",
        }
        row["matched_public_event"] = match_public_event(row, public_events)
        venue_match = match_venue(row, venues)
        row["venue_match"] = venue_match
        row["venue_matched"] = bool(venue_match)
        row["candidate_key"] = candidate_key(row)
        row["review_priority"] = review_priority(row)
        row["recommended_decision"] = "補強" if row["matched_public_event"] else (
            "登録" if row["review_priority"] == "登録候補" else "要確認"
        )
        existing = seen.get(row["candidate_key"])
        if existing:
            if row["setlist_count"] > existing["setlist_count"]:
                seen[row["candidate_key"]] = row
            continue
        seen[row["candidate_key"]] = row
    rows = list(seen.values())
    priority_order = {"既存補強": 0, "登録候補": 1, "要確認": 2, "日付会場あり": 3, "保留": 4}
    rows.sort(key=lambda row: (
        priority_order.get(row["review_priority"], 9),
        -(row.get("setlist_count") or 0),
        row.get("event_date") or "",
        row.get("event_name") or "",
    ))
    return rows


def build_output(source_path=SOURCE, public_events_path=PUBLIC_EVENTS, venue_master_path=VENUE_MASTER):
    payload = load_json(source_path, {})
    public_events = load_json(public_events_path, [])
    venues = load_json(venue_master_path, [])
    rows = build_rows(payload, public_events, venues)
    counts = Counter(row["review_priority"] for row in rows)
    return {
        "generated_by": "build_youtube_event_review.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source_path),
        "public_events_source": str(public_events_path),
        "venue_master_source": str(venue_master_path),
        "candidate_count": len(rows),
        "counts": dict(sorted(counts.items())),
        "rows": rows,
    }


def one_line(value, limit=80):
    value = compact(value)
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def table_row(values):
    return "| " + " | ".join(str(value).replace("|", "\\|") for value in values) + " |"


def render_markdown(output):
    lines = [
        "# YouTubeイベント候補レビュー",
        "",
        f"- 候補: {output.get('candidate_count', 0)}件",
        f"- 内訳: {output.get('counts', {})}",
        "",
        table_row(["優先", "推奨", "日付", "曲数", "イベント", "会場", "既存一致", "動画"]),
        table_row(["---", "---", "---", "---", "---", "---", "---", "---"]),
    ]
    for row in output.get("rows", [])[:80]:
        match = row.get("matched_public_event") or {}
        lines.append(table_row([
            row.get("review_priority") or "",
            row.get("recommended_decision") or "",
            row.get("event_date") or "",
            row.get("setlist_count") or 0,
            one_line(row.get("event_name") or "", 42),
            one_line((row.get("venue_match") or {}).get("venue") or row.get("venue") or "", 36),
            one_line(match.get("name") or "", 30),
            row.get("url") or "",
        ]))
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(SOURCE))
    parser.add_argument("--public-events", default=str(PUBLIC_EVENTS))
    parser.add_argument("--venue-master", default=str(VENUE_MASTER))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--md", default=str(OUT_MD))
    args = parser.parse_args()

    output = build_output(Path(args.source), Path(args.public_events), Path(args.venue_master))
    atomic_write_json(args.out, output)
    write_text(args.md, render_markdown(output))
    print(
        "[youtube-event-review] "
        f"candidates={output['candidate_count']} "
        f"counts={output['counts']} -> {args.out}, {args.md}"
    )


if __name__ == "__main__":
    main()
