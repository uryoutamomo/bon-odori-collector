"""Group remaining YouTube 2025 backfill candidates for a second pass."""

import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


DB = Path("data/bon_odori.sqlite")
APPLY_PLAN = Path("data/rdb_event_apply_plan.json")
OUT_JSON = Path("data/youtube_2025_second_pass_event_groups.json")
OUT_MD = Path("data/youtube_2025_second_pass_event_groups.md")


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def rows(conn, sql):
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(sql)]


def md_escape(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def date_in_range(value, start, end):
    if not value or not start:
        return False
    end = end or start
    return start <= value <= end


def title_years(group):
    years = []
    for video in group.get("sample_videos") or []:
        for year in re.findall(r"20\d{2}", video.get("title") or ""):
            if year not in years:
                years.append(year)
    return sorted(years)


def classify_group(group):
    start_date = group["start_date"]
    end_date = group["end_date"] or start_date
    detected_dates = [d for d in group["detected_dates"] if d]
    years_in_titles = title_years(group)
    if years_in_titles and "2025" not in years_in_titles:
        return {
            "category": "prior_year_video_uploaded_in_2025",
            "recommended_action": "動画公開日は2025年だがタイトル上は過去年実績。2025イベント証拠としては反映しない",
        }
    if not start_date:
        if len(set(detected_dates)) == 1:
            return {
                "category": "date_backfill_candidate_single_date",
                "recommended_action": "公式/既存ソースで日付確認後、Notion日付補正とYouTube証拠反映を検討",
            }
        if detected_dates:
            return {
                "category": "date_backfill_candidate_multi_date",
                "recommended_action": "複数日開催または誤混入を確認し、日付範囲を補正候補にする",
            }
        return {
            "category": "needs_date_extraction_or_manual_review",
            "recommended_action": "タイトル/説明欄から日付を再抽出する。補えない場合は手動レビュー",
        }
    if not start_date.startswith("2025"):
        return {
            "category": "year_mismatch_or_recurring_event_review",
            "recommended_action": "2025動画を2026イベントへ入れず、過去年実績または2025イベント別ページとして扱うか確認",
        }
    if not detected_dates:
        return {
            "category": "notion_date_present_missing_detected_date",
            "recommended_action": "Notion日付はあるが動画側の日付抽出が空。抽出ルール改善後に安全反映候補へ再判定",
        }
    in_range = [d for d in detected_dates if date_in_range(d, start_date, end_date)]
    if in_range:
        return {
            "category": "partial_summary_remainder",
            "recommended_action": "既に要約反映済みの可能性を確認。代表動画だけで十分なら追記しない",
        }
    return {
        "category": "notion_date_conflict",
        "recommended_action": "Notion日付と動画検出日付が不一致。反映せず日付/イベント一致を再確認",
    }


def build_groups(db_path=DB, apply_plan_path=APPLY_PLAN):
    plan = load_json(apply_plan_path, {"rows": []})
    review_keys = {
        (row.get("target_page_id") or "", ((row.get("videos") or [{}])[0].get("url") or ""))
        for row in plan.get("rows") or []
        if row.get("status") == "review_batch_2025_backfill"
    }
    with sqlite3.connect(db_path) as conn:
        matched = rows(
            conn,
            """
            SELECT
              e.event_id,
              e.event_name,
              e.start_date,
              e.end_date,
              e.source_url AS event_source_url,
              i.evidence_id,
              i.account_key,
              i.title,
              i.url,
              i.published_at,
              i.detected_event_date,
              l.confidence,
              l.link_source
            FROM event_evidence_links l
            JOIN events e ON e.event_id = l.event_id
            JOIN evidence_items i ON i.evidence_id = l.evidence_id
            WHERE l.link_status = 'matched_existing_event'
              AND i.platform = 'youtube'
              AND i.published_at LIKE '2025%'
            ORDER BY e.event_name, i.published_at, i.title
            """,
        )
    remaining = [
        row for row in matched
        if (row["event_id"], row["url"]) in review_keys
    ]
    grouped = {}
    for row in remaining:
        group = grouped.setdefault(
            row["event_id"],
            {
                "event_id": row["event_id"],
                "event_name": row["event_name"],
                "start_date": row["start_date"] or "",
                "end_date": row["end_date"] or "",
                "event_source_url": row["event_source_url"] or "",
                "video_count": 0,
                "channels": [],
                "detected_dates": [],
                "title_years": [],
                "published_range": {"first": "", "last": ""},
                "sample_videos": [],
            },
        )
        group["video_count"] += 1
        if row["account_key"] and row["account_key"] not in group["channels"]:
            group["channels"].append(row["account_key"])
        if row["detected_event_date"] and row["detected_event_date"] not in group["detected_dates"]:
            group["detected_dates"].append(row["detected_event_date"])
        published = row["published_at"] or ""
        if published:
            if not group["published_range"]["first"] or published < group["published_range"]["first"]:
                group["published_range"]["first"] = published
            if not group["published_range"]["last"] or published > group["published_range"]["last"]:
                group["published_range"]["last"] = published
        if len(group["sample_videos"]) < 8:
            group["sample_videos"].append({
                "title": row["title"],
                "url": row["url"],
                "published_at": row["published_at"],
                "detected_event_date": row["detected_event_date"],
                "channel_id": row["account_key"],
            })
    output_groups = []
    for group in grouped.values():
        group["detected_dates"].sort()
        group["title_years"] = title_years(group)
        classification = classify_group(group)
        group.update(classification)
        output_groups.append(group)
    output_groups.sort(key=lambda row: (row["category"], -row["video_count"], row["event_name"]))

    category_counts = defaultdict(lambda: {"event_count": 0, "video_count": 0})
    for group in output_groups:
        category_counts[group["category"]]["event_count"] += 1
        category_counts[group["category"]]["video_count"] += group["video_count"]

    return {
        "generated_by": "export_youtube_2025_second_pass_event_groups.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_db": str(db_path),
        "source_apply_plan": str(apply_plan_path),
        "remaining_review_batch_rows": len(remaining),
        "event_group_count": len(output_groups),
        "category_counts": [
            {"category": category, **counts}
            for category, counts in sorted(category_counts.items())
        ],
        "groups": output_groups,
    }


def render_markdown(report):
    lines = [
        "# YouTube 2025 二次分類",
        "",
        f"- 生成: {report['generated_at']}",
        f"- 残り候補: {report['remaining_review_batch_rows']}動画",
        f"- イベントグループ: {report['event_group_count']}件",
        "",
        "## カテゴリ別",
        "",
        "| category | events | videos |",
        "| --- | ---: | ---: |",
    ]
    for row in report["category_counts"]:
        lines.append(f"| {md_escape(row['category'])} | {row['event_count']} | {row['video_count']} |")
    lines.extend([
        "",
        "## イベント別",
        "",
        "| category | event | Notion date | detected dates | videos | action |",
        "| --- | --- | --- | --- | ---: | --- |",
    ])
    for group in report["groups"]:
        date_range = group["start_date"] or "(未設定)"
        if group["end_date"] and group["end_date"] != group["start_date"]:
            date_range += f"..{group['end_date']}"
        detected = ", ".join(group["detected_dates"]) if group["detected_dates"] else "(未抽出)"
        lines.append(
            f"| {md_escape(group['category'])} | {md_escape(group['event_name'])} | "
            f"{md_escape(date_range)} | {md_escape(detected)} | {group['video_count']} | "
            f"{md_escape(group['recommended_action'])} |"
        )
    lines.extend(["", "## サンプル動画", ""])
    for group in report["groups"]:
        lines.extend([
            f"### {group['event_name']}",
            "",
            f"- category: {group['category']}",
            f"- videos: {group['video_count']}",
            f"- action: {group['recommended_action']}",
            "",
        ])
        for video in group["sample_videos"]:
            lines.append(
                f"- {video.get('detected_event_date') or 'date?'} / "
                f"{video.get('title')} / {video.get('url')}"
            )
        lines.append("")
    return "\n".join(lines)


def main():
    report = build_groups()
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    OUT_MD.write_text(render_markdown(report), encoding="utf-8")
    print(
        "[youtube-2025-second-pass] "
        f"rows={report['remaining_review_batch_rows']} "
        f"events={report['event_group_count']} -> {OUT_MD}"
    )


if __name__ == "__main__":
    main()
