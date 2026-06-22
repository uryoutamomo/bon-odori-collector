"""Build a structured pre-cutover P0 apply plan.

This is read-only review material. It does not write to Notion or public JSON.
The plan separates current-year official updates from historical references and
investigation-only rows so that Ph2 dual-write work can apply a small batch.
"""

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from master_db import MASTER_DB


DATA = Path("data")
QUEUE_JSON = DATA / "registered_event_investigation_queue.json"
OUT_JSON = DATA / "pre_cutover_p0_apply_plan.json"
OUT_MD = DATA / "pre_cutover_p0_apply_plan.md"

SHINAGAWA_2026_SOURCE = "https://www.city.shinagawa.tokyo.jp/PC/shisetsu/shisetsu-kuyakusyo/shisetsu-kuyakusyo-chiiki/hpg000017088.html"

P0_CLASSIFICATIONS = {
    "品川区民まつり 品川第二地区": {
        "bucket": "current_2026_apply_candidate",
        "recommended_action": "review_then_apply_split_or_venue_correction",
        "proposed_date_start": "2026-07-25",
        "proposed_date_end": "2026-07-26",
        "proposed_venue": "天妙国寺境内",
        "confidence": "high",
        "source_url": SHINAGAWA_2026_SOURCE,
        "source_checked_at": "2026-06-21",
        "notes": "Official 2026 page has a child-corner slot at 城南小学校体育館 and the bon-odori slot at 天妙国寺境内. Do not overwrite blindly; either correct the existing venue or split occurrences.",
        "requires_human_review": True,
    },
    "品川区民まつり 荏原第一地区": {
        "bucket": "current_2026_apply_candidate",
        "recommended_action": "apply_current_2026_date_after_dual_write_ready",
        "proposed_date_start": "2026-10-10",
        "proposed_date_end": "",
        "proposed_venue": "小山台小学校",
        "confidence": "high",
        "source_url": SHINAGAWA_2026_SOURCE,
        "source_checked_at": "2026-06-21",
        "notes": "Single current-year official date/venue. Straightforward after the Ph2 write boundary is ready.",
        "requires_human_review": False,
    },
    "品川区民まつり 荏原第五地区": {
        "bucket": "current_2026_apply_candidate",
        "recommended_action": "apply_current_2026_date_and_review_venue_name",
        "proposed_date_start": "2026-07-18",
        "proposed_date_end": "2026-07-19",
        "proposed_venue": "杜松ホーム",
        "confidence": "high",
        "source_url": SHINAGAWA_2026_SOURCE,
        "source_checked_at": "2026-06-21",
        "notes": "Current registered venue is 旧杜松小学校. Official 2026 page says 杜松ホーム, so preserve the venue-change rationale.",
        "requires_human_review": True,
    },
    "濱町音頭盆踊り大会": {
        "bucket": "historical_reference_only",
        "recommended_action": "promote_2025_historical_reference_only",
        "historical_date_start": "2025-09-27",
        "historical_date_end": "",
        "historical_venue": "浜町公園中央広場",
        "confidence": "medium",
        "source_url": "https://tokyofesta.com/23ku/25652/",
        "notes": "Useful 2025 evidence; do not copy as a 2026 date.",
        "requires_human_review": True,
    },
    "銀座一丁目東町会・新富町会 納涼盆踊り大会": {
        "bucket": "historical_reference_only",
        "recommended_action": "review_then_promote_2025_historical_reference_only",
        "historical_date_start": "2025-07-19",
        "historical_date_end": "",
        "historical_venue": "京橋プラザ",
        "confidence": "medium",
        "source_url": "https://www.chuo-kanko.or.jp/pages/other_details/115655",
        "notes": "Observed evidence is useful, but source row needs review before apply.",
        "requires_human_review": True,
    },
    "ゐの市盆踊り～不忍夢～": {
        "bucket": "historical_reference_only",
        "recommended_action": "promote_2025_historical_reference_only",
        "historical_date_start": "2025-08-09",
        "historical_date_end": "2025-08-11",
        "historical_venue": "上野恩賜公園",
        "confidence": "medium",
        "source_url": "https://www.uenopark.info/2025/inoichi-bonodori-2025/",
        "notes": "Historical reference only.",
        "requires_human_review": True,
    },
    "京橋盆踊り": {
        "bucket": "historical_reference_only",
        "recommended_action": "promote_2025_historical_reference_only",
        "historical_date_start": "2025-08-29",
        "historical_date_end": "2025-08-30",
        "historical_venue": "京橋中央ひろば（ガレリア）",
        "confidence": "high",
        "source_url": "https://www.edogrand.tokyo/event/6924",
        "notes": "Historical reference only; source describes an ended event.",
        "requires_human_review": False,
    },
    "新宿中央公園夏祭り 納涼盆踊り大会": {
        "bucket": "historical_reference_only",
        "recommended_action": "promote_2025_historical_reference_only",
        "historical_date_start": "2025-08-23",
        "historical_date_end": "2025-08-24",
        "historical_venue": "新宿中央公園 ファンモアタイムひろば",
        "confidence": "medium",
        "source_url": "https://tokyofesta.com/23ku/24845/",
        "notes": "Historical reference only.",
        "requires_human_review": True,
    },
    "森下二丁目盆踊り": {
        "bucket": "historical_reference_only",
        "recommended_action": "keep_2026_unknown_and_promote_2025_historical_reference_only",
        "historical_date_start": "2025-07-19",
        "historical_date_end": "2025-07-20",
        "historical_venue": "森下公園",
        "confidence": "medium",
        "source_url": "https://minamisuna1.com/26743/",
        "notes": "2026 latest page did not expose this row in the previous pass.",
        "requires_human_review": True,
    },
    "赤坂夏おどり（旧 赤坂盆踊り）": {
        "bucket": "historical_reference_only",
        "recommended_action": "promote_2025_historical_reference_only",
        "historical_date_start": "2025-08-29",
        "historical_date_end": "2025-08-30",
        "historical_venue": "TBS赤坂サカス広場",
        "confidence": "medium",
        "source_url": "https://sacas.tokyoevent.net/natsuodori.html",
        "notes": "Historical reference only.",
        "requires_human_review": True,
    },
    "都の辰巳深川 臨海ぼんおどり": {
        "bucket": "historical_reference_only",
        "recommended_action": "keep_2026_unknown_and_promote_2025_historical_reference_only",
        "historical_date_start": "2025-07-19",
        "historical_date_end": "",
        "historical_venue": "臨海小学校校庭",
        "confidence": "medium",
        "source_url": "https://minamisuna1.com/26743/",
        "notes": "2026 latest page did not expose this row in the previous pass.",
        "requires_human_review": True,
    },
    "増上寺 地蔵尊盆踊り大会": {
        "bucket": "keep_investigation_queue",
        "recommended_action": "keep_as_date_research_task",
        "confidence": "low",
        "source_url": "https://www.zojoji.or.jp/event/ev_bonodori.html",
        "source_checked_at": "2026-06-22",
        "notes": "Official annual page was rechecked: it confirms the event name and directs inquiries to 安国殿, but still does not publish a usable 2026 date.",
        "requires_human_review": False,
    },
    "旗岡八幡神社例大祭": {
        "bucket": "keep_investigation_queue",
        "recommended_action": "keep_as_date_research_task",
        "confidence": "low",
        "source_url": "https://hatagaokahachiman-jinja.jp/",
        "source_checked_at": "2026-06-22",
        "notes": "Homepage was rechecked: latest visible festival news remains 令和7年/2025例大祭 material, with no usable 2026 date or bon-odori row.",
        "requires_human_review": False,
    },
    "盆☆Dance 夏休み最後の土曜は校庭で踊ろう！": {
        "bucket": "keep_investigation_queue",
        "recommended_action": "source_specific_follow_up",
        "confidence": "low",
        "source_url": "https://minato-bon-odori.blogspot.com/",
        "source_checked_at": "2026-06-22",
        "notes": "Current 東京内外の盆踊りマップ upcoming-all page was rechecked and did not expose 盆☆Dance/横川小学校; keep as source-specific follow-up.",
        "requires_human_review": False,
    },
    "品川区民まつり 大崎第一地区": {
        "bucket": "keep_investigation_queue",
        "recommended_action": "keep_as_occurrence_split_task",
        "confidence": "medium",
        "source_url": SHINAGAWA_2026_SOURCE,
        "source_checked_at": "2026-06-21",
        "notes": "Multiple dates and venues. This is a split task, not a single date fill.",
        "requires_human_review": True,
    },
}


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def existing_historical_reference_keys(master_db):
    master_db = Path(master_db)
    if not master_db.exists():
        return set()
    with sqlite3.connect(master_db) as conn:
        return {
            (row[0], row[1], row[2] or "")
            for row in conn.execute(
                """
                SELECT occurrence_id, date_start, COALESCE(date_end, '')
                FROM occurrence_dates
                WHERE date_type = 'historical_reference'
                """
            )
        }


def build(args):
    queue = load_json(args.queue_json, {})
    historical_reference_keys = existing_historical_reference_keys(args.master_db)
    p0_tasks = [
        task
        for task in queue.get("tasks") or []
        if task.get("scope") == "primary_unconfirmed" and task.get("priority_label") == "P0"
    ]
    plan_rows = []
    for task in p0_tasks:
        classification = dict(P0_CLASSIFICATIONS.get(task["event_name"]) or {})
        if not classification:
            classification = {
                "bucket": "unclassified",
                "recommended_action": "manual_classification_required",
                "confidence": "unknown",
                "notes": "No pre-cutover classification is recorded.",
                "requires_human_review": True,
            }
        row = {
            "event_name": task["event_name"],
            "task_id": task["task_id"],
            "occurrence_id": task.get("occurrence_id") or "",
            "notion_page_id": task["notion_page_id"],
            "event_year": task.get("event_year"),
            "current_known_venues": task.get("known_venue_names") or [],
            "current_source_url": task.get("source_url") or "",
            "queue_priority_score": task["priority_score"],
            "queue_reason_codes": task.get("reason_codes") or [],
        }
        row.update(classification)
        historical_key = (
            row["occurrence_id"],
            row.get("historical_date_start") or "",
            row.get("historical_date_end") or "",
        )
        if row.get("bucket") == "historical_reference_only" and historical_key in historical_reference_keys:
            row["bucket"] = "historical_reference_recorded"
            row["recommended_action_before_recorded"] = row["recommended_action"]
            row["recommended_action"] = "already_recorded_historical_reference"
            row["historical_reference_recorded"] = True
        plan_rows.append(row)

    by_bucket = Counter(row["bucket"] for row in plan_rows)
    by_action = Counter(row["recommended_action"] for row in plan_rows)
    data = {
        "generated_by": "build_pre_cutover_p0_apply_plan.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": "read_only_local_review_material",
        "source_queue": str(args.queue_json),
        "source_master_db": str(args.master_db),
        "write_policy": {
            "notion_write": "do_not_write_before_dual_write_boundary_or_explicit_go",
            "public_json_write": "do_not_deploy; local review only",
            "historical_dates": "never_copy_historical_dates_as_2026_confirmed_dates",
        },
        "summary": {
            "p0_task_count": len(p0_tasks),
            "planned_row_count": len(plan_rows),
            "by_bucket": dict(by_bucket),
            "by_action": dict(by_action),
            "human_review_required_count": sum(1 for row in plan_rows if row.get("requires_human_review")),
        },
        "rows": plan_rows,
    }
    write_json(args.out_json, data)
    Path(args.out_md).write_text(render_markdown(data), encoding="utf-8")
    return data


def date_range(row, prefix):
    start = row.get(f"{prefix}_date_start") or ""
    end = row.get(f"{prefix}_date_end") or ""
    if start and end and end != start:
        return f"{start} to {end}"
    return start


def render_markdown(data):
    lines = [
        "# Pre-cutover P0 apply plan",
        "",
        f"- generated_at: {data['generated_at']}",
        f"- source_queue: `{data['source_queue']}`",
        f"- source_master_db: `{data['source_master_db']}`",
        f"- p0_task_count: {data['summary']['p0_task_count']}",
        f"- by_bucket: {data['summary']['by_bucket']}",
        f"- human_review_required_count: {data['summary']['human_review_required_count']}",
        "",
        "## Current 2026 Apply Candidates",
        "",
        "| event | proposed date | proposed venue | action | review | source |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in data["rows"]:
        if row["bucket"] != "current_2026_apply_candidate":
            continue
        lines.append(
            f"| {row['event_name']} | {date_range(row, 'proposed')} | {row.get('proposed_venue', '')} | "
            f"{row['recommended_action']} | {'yes' if row.get('requires_human_review') else ''} | {row.get('source_url', '')} |"
        )
    lines.extend(
        [
            "",
            "## Historical Reference Only",
            "",
            "| event | historical date | historical venue | action | review | source |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in data["rows"]:
        if row["bucket"] != "historical_reference_only":
            continue
        lines.append(
            f"| {row['event_name']} | {date_range(row, 'historical')} | {row.get('historical_venue', '')} | "
            f"{row['recommended_action']} | {'yes' if row.get('requires_human_review') else ''} | {row.get('source_url', '')} |"
        )
    lines.extend(
        [
            "",
            "## Historical References Already Recorded",
            "",
            "| event | historical date | historical venue | source |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in data["rows"]:
        if row["bucket"] != "historical_reference_recorded":
            continue
        lines.append(
            f"| {row['event_name']} | {date_range(row, 'historical')} | "
            f"{row.get('historical_venue', '')} | {row.get('source_url', '')} |"
        )
    lines.extend(
        [
            "",
            "## Keep In Investigation Queue",
            "",
            "| event | action | review | checked | source | note |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in data["rows"]:
        if row["bucket"] != "keep_investigation_queue":
            continue
        lines.append(
            f"| {row['event_name']} | {row['recommended_action']} | "
            f"{'yes' if row.get('requires_human_review') else ''} | "
            f"{row.get('source_checked_at', '')} | {row.get('source_url', '')} | {row.get('notes', '')} |"
        )
    lines.extend(
        [
            "",
            "## Write Policy",
            "",
        ]
    )
    for key, value in data["write_policy"].items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue-json", default=str(QUEUE_JSON))
    parser.add_argument("--master-db", default=str(MASTER_DB))
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    args = parser.parse_args()
    data = build(args)
    print(
        "pre-cutover p0 apply plan: "
        f"rows={data['summary']['planned_row_count']} "
        f"buckets={data['summary']['by_bucket']} "
        f"review={data['summary']['human_review_required_count']}"
    )


if __name__ == "__main__":
    main()
