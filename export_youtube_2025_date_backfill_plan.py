"""Build a conservative Notion date backfill plan for YouTube 2025 candidates."""

import argparse
import html
import json
import re
import sqlite3
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


DB = Path("data/bon_odori.sqlite")
SECOND_PASS = Path("data/youtube_2025_second_pass_event_groups.json")
OUT = Path("data/youtube_2025_date_backfill_plan.json")
MD_OUT = Path("data/youtube_2025_date_backfill_plan.md")


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
        f"{month}/{day_i}",
        f"{month_i}/{day_i}",
    ]


def normalize_text(value):
    text = html.unescape(value or "")
    text = re.sub(r"<script\b.*?</script>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def fetch_url(url):
    if not url or "youtube.com/" in url or "youtu.be/" in url:
        return {"ok": False, "status": "skipped_youtube_url", "text": ""}
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
            text = raw.decode(charset, errors="replace")
            return {"ok": True, "status": str(response.status), "text": normalize_text(text)}
    except (urllib.error.URLError, TimeoutError, UnicodeError) as exc:
        return {"ok": False, "status": exc.__class__.__name__, "text": str(exc)}


def source_mentions_dates(source_text, dates):
    compact_text = re.sub(r"(?<=\d)\s+(?=[年月日])|(?<=[年月日])\s+(?=\d)", "", source_text)
    matches = {}
    for date_value in dates:
        variants = date_variants(date_value)
        matched = [
            variant for variant in variants
            if variant and (variant in source_text or variant in compact_text)
        ]
        if matched:
            matches[date_value] = matched[:5]
    return matches


def group_video_urls(db_path, event_ids):
    if not event_ids:
        return {}
    with sqlite3.connect(db_path) as conn:
        placeholders = ",".join("?" for _ in event_ids)
        result = rows(
            conn,
            f"""
            SELECT e.event_id, i.url, i.title, i.account_key, i.detected_event_date
            FROM event_evidence_links l
            JOIN events e ON e.event_id = l.event_id
            JOIN evidence_items i ON i.evidence_id = l.evidence_id
            WHERE e.event_id IN ({placeholders})
              AND l.link_status = 'matched_existing_event'
              AND i.platform = 'youtube'
              AND i.published_at LIKE '2025%'
            ORDER BY e.event_id, i.detected_event_date, i.title
            """,
            event_ids,
        )
    grouped = {}
    for row in result:
        grouped.setdefault(row["event_id"], []).append(row)
    return grouped


def classify(group, source_result, source_date_matches):
    if not group.get("detected_dates") or len(group["detected_dates"]) != 1:
        if (
            group["category"] == "date_backfill_candidate_multi_date"
            and source_result["ok"]
            and len(source_date_matches) == 1
        ):
            return "ready", "source_url本文で複数日候補のうち1日だけ確認済み。確認済み日付だけ反映"
        if group["category"] != "date_backfill_candidate_single_date":
            return "hold", "単日候補以外。複数日/混入確認を先に行う"
        return "hold", "検出日付が単一ではない"
    if group["category"] != "date_backfill_candidate_single_date":
        return "hold", "単日候補以外。複数日/混入確認を先に行う"
    if not source_result["ok"]:
        return "hold", f"source_url未確認: {source_result['status']}"
    detected_date = group["detected_dates"][0]
    if detected_date not in source_date_matches:
        return "hold", "source_url本文で検出日付を確認できない"
    return "ready", "source_url本文で単一検出日付を確認済み"


def build_plan(db_path=DB, second_pass_path=SECOND_PASS, fetch_sources=True):
    report = load_json(second_pass_path, {"groups": []})
    candidate_groups = [
        group for group in report.get("groups") or []
        if group.get("category", "").startswith("date_backfill_candidate")
    ]
    videos_by_event = group_video_urls(db_path, [group["event_id"] for group in candidate_groups])
    rows_out = []
    source_cache = {}
    for group in candidate_groups:
        source_url = group.get("event_source_url") or ""
        source_result = source_cache.get(source_url)
        if source_result is None:
            source_result = fetch_url(source_url) if fetch_sources else {"ok": False, "status": "not_fetched", "text": ""}
            source_cache[source_url] = source_result
        date_matches = source_mentions_dates(source_result.get("text") or "", group.get("detected_dates") or [])
        status, reason = classify(group, source_result, date_matches)
        detected_dates = group.get("detected_dates") or []
        if status == "ready" and date_matches:
            target_date = sorted(date_matches.keys())[0]
        else:
            target_date = detected_dates[0] if status == "ready" else ""
        plan_videos = [
            {
                "url": row["url"],
                "title": row["title"],
                "channel": row["account_key"],
                "detected_event_date": row["detected_event_date"],
            }
            for row in videos_by_event.get(group["event_id"], [])
            if not target_date or row["detected_event_date"] == target_date
        ]
        rows_out.append(
            {
                "status": status,
                "reason": reason,
                "target_event_name": group["event_name"],
                "target_page_id": group["event_id"],
                "target_page_url": group.get("event_source_url") or "",
                "current_date_range": {"start": group.get("start_date") or "", "end": group.get("end_date") or ""},
                "proposed_date_range": {"start": target_date, "end": target_date},
                "detected_dates": detected_dates,
                "video_count": len(plan_videos),
                "group_video_count": group.get("video_count", 0),
                "source_check": {
                    "url": source_url,
                    "ok": bool(source_result["ok"]),
                    "status": source_result["status"],
                    "date_matches": date_matches,
                },
                "videos": plan_videos,
            }
        )
    rows_out.sort(key=lambda row: (row["status"] != "ready", -row["video_count"], row["target_event_name"]))
    return {
        "generated_by": "export_youtube_2025_date_backfill_plan.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_db": str(db_path),
        "source_second_pass": str(second_pass_path),
        "ready_count": sum(1 for row in rows_out if row["status"] == "ready"),
        "ready_video_count": sum(row["video_count"] for row in rows_out if row["status"] == "ready"),
        "hold_count": sum(1 for row in rows_out if row["status"] != "ready"),
        "rows": rows_out,
    }


def render_markdown(plan):
    lines = [
        "# YouTube 2025 日付補正計画",
        "",
        f"- 生成: {plan['generated_at']}",
        f"- ready: {plan['ready_count']}イベント / {plan['ready_video_count']}動画",
        f"- hold: {plan['hold_count']}イベント",
        "",
        "| status | event | proposed date | detected dates | videos | source | reason |",
        "| --- | --- | --- | --- | ---: | --- | --- |",
    ]
    for row in plan["rows"]:
        lines.append(
            f"| {row['status']} | {md_escape(row['target_event_name'])} | "
            f"{md_escape(row['proposed_date_range']['start'])} | "
            f"{md_escape(', '.join(row['detected_dates']))} | {row['video_count']} | "
            f"{md_escape(row['source_check']['url'])} | {md_escape(row['reason'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-fetch", action="store_true")
    args = parser.parse_args()
    plan = build_plan(fetch_sources=not args.no_fetch)
    OUT.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    MD_OUT.write_text(render_markdown(plan), encoding="utf-8")
    print(
        "[youtube-2025-date-backfill-plan] "
        f"ready={plan['ready_count']} ready_videos={plan['ready_video_count']} "
        f"hold={plan['hold_count']} -> {OUT}"
    )


if __name__ == "__main__":
    main()
