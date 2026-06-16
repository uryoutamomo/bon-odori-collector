"""Validate high-priority YouTube 2025 official URL candidates."""

import html
import json
import re
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse


DB = Path("data/bon_odori.sqlite")
QUEUE = Path("data/youtube_2025_manual_confirmation_queue.json")
OUT = Path("data/youtube_2025_official_candidate_validation.json")
MD_OUT = Path("data/youtube_2025_official_candidate_validation.md")

TITLE_STOPWORDS = {
    "2025",
    "tokyo",
    "bon",
    "dance",
    "festival",
    "part",
    "第1部",
    "第2部",
    "盆踊り",
    "bonodori",
}


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def rows(conn, sql, params=()):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(sql, params)]


def md_escape(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def domain(url):
    host = (urlparse(url or "").netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def normalize_text(value):
    text = html.unescape(value or "")
    text = re.sub(r"<script\b.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def fetch_url(url):
    if not url:
        return {"ok": False, "status": "missing_url", "text": ""}
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; bon-odori-collector/1.0)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read(1_500_000)
            charset = response.headers.get_content_charset() or "utf-8"
            return {"ok": True, "status": str(response.status), "text": normalize_text(raw.decode(charset, errors="replace"))}
    except (urllib.error.URLError, TimeoutError, UnicodeError) as exc:
        return {"ok": False, "status": exc.__class__.__name__, "text": str(exc)}


def date_variants(date_value):
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_value or ""):
        return []
    year, month, day = date_value.split("-")
    month_i = str(int(month))
    day_i = str(int(day))
    return [
        date_value,
        f"{year}/{month}/{day}",
        f"{year}/{month_i}/{day_i}",
        f"{year}.{month}.{day}",
        f"{year}.{month_i}.{day_i}",
        f"{year}年{month_i}月{day_i}日",
        f"{month_i}月{day_i}日",
        f"{month_i}/{day_i}",
    ]


def source_mentions_dates(source_text, dates):
    compact_text = re.sub(r"(?<=\d)\s+(?=[年月日])|(?<=[年月日])\s+(?=\d)", "", source_text or "")
    matches = {}
    for date_value in dates:
        matched = [
            variant for variant in date_variants(date_value)
            if variant and (variant in source_text or variant in compact_text)
        ]
        if matched:
            matches[date_value] = matched[:5]
    return matches


def title_tokens(titles):
    text = " ".join(titles or [])
    tokens = re.findall(r"[一-龯ぁ-んァ-ンーA-Za-z0-9]+", text)
    useful = []
    for token in tokens:
        lower = token.lower()
        if len(token) <= 1 or lower in TITLE_STOPWORDS:
            continue
        if re.fullmatch(r"\d+", token):
            continue
        if token not in useful:
            useful.append(token)
    return useful[:20]


def all_events(db_path):
    with sqlite3.connect(db_path) as conn:
        return rows(
            conn,
            """
            SELECT event_id, event_name, start_date, end_date, status, source_url, detail
            FROM events
            ORDER BY event_name
            """,
        )


def event_score(item, event):
    score = 0
    reasons = []
    primary_url = item.get("primary_url") or ""
    if primary_url and primary_url == (event.get("source_url") or ""):
        score += 100
        reasons.append("source_url_exact")
    host = domain(primary_url)
    event_host = domain(event.get("source_url") or "")
    if host and event_host and host == event_host:
        score += 20
        reasons.append("source_domain_match")
    dates = set(item.get("detected_dates") or [])
    event_dates = {event.get("start_date") or "", event.get("end_date") or ""}
    if dates & event_dates:
        score += 35
        reasons.append("date_overlap")
    name = event.get("event_name") or ""
    matched_tokens = [token for token in title_tokens(item.get("titles") or []) if token in name]
    if matched_tokens:
        score += min(40, len(matched_tokens) * 10)
        reasons.append("title_token:" + ",".join(matched_tokens[:5]))
    return score, reasons


def best_event_matches(item, events):
    scored = []
    for event in events:
        score, reasons = event_score(item, event)
        if score > 0:
            scored.append({"score": score, "reasons": reasons, **event})
    scored.sort(key=lambda row: (-row["score"], row["event_name"]))
    return scored[:5]


def classify(item, source_result, date_matches, matches):
    best = matches[0] if matches else {}
    reasons = best.get("reasons") or []
    has_identity_match = any(not reason.startswith("date_overlap") for reason in reasons)
    if source_result.get("ok") and date_matches and has_identity_match and best.get("score", 0) >= 80:
        return "existing_event_append_ready", "公式URL本文の日付と既存イベント候補が一致"
    if source_result.get("ok") and date_matches and has_identity_match and best.get("score", 0) >= 35:
        return "existing_event_review", "日付は公式URL本文で確認。既存イベント候補はあるが確度は中"
    if source_result.get("ok") and date_matches:
        return "new_event_review", "日付は公式URL本文で確認。既存イベント候補が弱い"
    if not source_result.get("ok"):
        return "source_fetch_hold", f"公式URL本文取得不可: {source_result.get('status')}"
    return "source_date_hold", "公式URL本文で検出日付を確認できない"


def official_candidates(queue):
    return [
        row for row in queue.get("rows") or []
        if row.get("queue") == "needs_official_confirmation"
        and row.get("category") == "official_url_candidate"
    ]


def build_validation(db_path=DB, queue_path=QUEUE, fetch_sources=True):
    queue = load_json(queue_path, {"rows": []})
    events = all_events(db_path)
    fetch_cache = {}
    output_rows = []
    for item in official_candidates(queue):
        url = item.get("primary_url") or ""
        source_result = fetch_cache.get(url)
        if source_result is None:
            source_result = fetch_url(url) if fetch_sources else {"ok": False, "status": "not_fetched", "text": ""}
            fetch_cache[url] = source_result
        date_matches = source_mentions_dates(source_result.get("text") or "", item.get("detected_dates") or [])
        matches = best_event_matches(item, events)
        status, reason = classify(item, source_result, date_matches, matches)
        output_rows.append(
            {
                "status": status,
                "reason": reason,
                "primary_url": url,
                "primary_domain": domain(url),
                "video_count": item.get("video_count") or 0,
                "detected_dates": item.get("detected_dates") or [],
                "source_check": {
                    "ok": bool(source_result.get("ok")),
                    "status": source_result.get("status") or "",
                    "date_matches": date_matches,
                },
                "best_existing_matches": matches,
                "titles": item.get("titles") or [],
                "videos": item.get("videos") or [],
            }
        )
    output_rows.sort(key=lambda row: (row["status"], -row["video_count"], row["primary_url"]))
    counts = {}
    for row in output_rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    return {
        "generated_by": "export_youtube_2025_official_candidate_validation.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_db": str(db_path),
        "source_queue": str(queue_path),
        "candidate_count": len(output_rows),
        "candidate_video_count": sum(row["video_count"] for row in output_rows),
        "status_counts": counts,
        "rows": output_rows,
    }


def render_markdown(report):
    lines = [
        "# YouTube 2025 公式URL候補検証",
        "",
        f"- 生成: {report['generated_at']}",
        f"- candidates: {report['candidate_count']}",
        f"- videos: {report['candidate_video_count']}",
        "",
        "## status counts",
        "",
        "| status | items |",
        "| --- | ---: |",
    ]
    for status, count in sorted(report["status_counts"].items()):
        lines.append(f"| {md_escape(status)} | {count} |")
    lines.extend([
        "",
        "## candidates",
        "",
        "| status | url | dates | videos | best match | score | reason |",
        "| --- | --- | --- | ---: | --- | ---: | --- |",
    ])
    for row in report["rows"]:
        best = (row.get("best_existing_matches") or [{}])[0]
        lines.append(
            f"| {md_escape(row['status'])} | {md_escape(row['primary_url'])} | "
            f"{md_escape(', '.join(row['detected_dates']))} | {row['video_count']} | "
            f"{md_escape(best.get('event_name') or '')} | {best.get('score', 0)} | "
            f"{md_escape(row['reason'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    report = build_validation()
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MD_OUT.write_text(render_markdown(report), encoding="utf-8")
    print(
        "[youtube-2025-official-candidate-validation] "
        f"candidates={report['candidate_count']} videos={report['candidate_video_count']} "
        f"statuses={report['status_counts']} -> {OUT}"
    )


if __name__ == "__main__":
    main()
