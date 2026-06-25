#!/usr/bin/env python3
"""Build review decisions for Notion snapshot -> master drift rows.

The output separates safe master-preserve rows from rows that still need human
review. It does not mutate the master DB.
"""

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


DATA = Path("data")
DRIFT_REPORT = DATA / "notion_snapshot_master_drift.json"
OUT_JSON = DATA / "notion_snapshot_master_drift_decisions.json"
OUT_MD = DATA / "notion_snapshot_master_drift_decisions.md"


CONFIRMED_STATE_FIELDS = {"date_status", "lifecycle_status"}
NOTION_EMPTY_VALUES = {"", None, "unknown", "predicted", "未確認"}
MASTER_CONFIRMED_VALUES = {"confirmed", "published"}
REVIEWED_PRESERVE_MASTER_CONFLICTS = {
    ("event_occurrence", "新橋こいち祭", "source_url"),
    ("event_occurrence", "品川区民まつり 荏原第五地区", "venue_id"),
    ("event_occurrence", "品川区民まつり 八潮地区", "source_url"),
}


def load_json(path):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def decision_for(row):
    recommendation = row.get("recommendation") or ""
    field = row.get("field") or ""
    master = row.get("master_value")
    notion = row.get("notion_snapshot_value")

    if recommendation == "preserve_master":
        return {
            "decision": "preserve_master",
            "apply_ready": False,
            "reason": "Master DB has reviewed value while Notion snapshot is empty.",
        }

    if (
        recommendation == "review_conflict"
        and field in CONFIRMED_STATE_FIELDS
        and master in MASTER_CONFIRMED_VALUES
        and notion in NOTION_EMPTY_VALUES
    ):
        return {
            "decision": "preserve_master_confirmed_state",
            "apply_ready": False,
            "reason": "Master DB already records reviewed confirmed/published state; Notion snapshot is weaker.",
        }

    if (
        recommendation == "review_conflict"
        and (row.get("entity_type"), row.get("title"), field) in REVIEWED_PRESERVE_MASTER_CONFLICTS
    ):
        return {
            "decision": "preserve_master_reviewed_conflict",
            "apply_ready": False,
            "reason": "Reviewed conflict; keep the more specific/current Master RDB value and do not write Notion.",
        }

    if (
        recommendation == "review_before_copy_from_notion"
        and row.get("entity_type") == "event_series"
        and field == "public_intro"
        and not master
        and notion
    ):
        return {
            "decision": "candidate_copy_notion_public_intro",
            "apply_ready": True,
            "reason": "Notion has public_intro text and master is empty; local DB copy is low risk but still separate from Notion/public deploy.",
        }

    return {
        "decision": "hold_for_manual_review",
        "apply_ready": False,
        "reason": "Conflict needs source review before changing master DB.",
    }


def build_decisions(report):
    rows = []
    for index, drift in enumerate(report.get("diffs") or [], start=1):
        decision = decision_for(drift)
        rows.append(
            {
                "decision_id": f"notion_drift_{index:03d}",
                "entity_type": drift.get("entity_type") or "",
                "entity_id": drift.get("entity_id") or "",
                "title": drift.get("title") or "",
                "field": drift.get("field") or "",
                "drift_kind": drift.get("drift_kind") or "",
                "recommendation": drift.get("recommendation") or "",
                "master_value": drift.get("master_value"),
                "notion_snapshot_value": drift.get("notion_snapshot_value"),
                **decision,
            }
        )
    by_decision = Counter(row["decision"] for row in rows)
    by_apply = Counter("apply_ready" if row["apply_ready"] else "not_apply_ready" for row in rows)
    return {
        "generated_by": "build_notion_snapshot_drift_decisions.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_report": report.get("generated_by") or str(DRIFT_REPORT),
        "source_report_generated_at": report.get("generated_at", ""),
        "source_diff_count": len(report.get("diffs") or []),
        "status": "apply_candidates_ready" if by_apply.get("apply_ready") else "review_only",
        "policy": {
            "preserve_master_empty_notion": True,
            "preserve_reviewed_confirmed_state_over_weaker_notion": True,
            "copy_notion_public_intro_when_master_empty": "candidate_only",
            "conflicting_source_url_or_venue": "hold_for_manual_review_unless_reviewed_preserve_master",
        },
        "summary": {
            "decision_count": len(rows),
            "by_decision": dict(sorted(by_decision.items())),
            "by_apply_readiness": dict(sorted(by_apply.items())),
        },
        "decisions": rows,
    }


def md_escape(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(result):
    lines = [
        "# Notion snapshot drift decisions",
        "",
        f"- generated_at: {result['generated_at']}",
        f"- status: {result['status']}",
        f"- source_diff_count: {result['source_diff_count']}",
        f"- by_decision: {result['summary']['by_decision']}",
        f"- by_apply_readiness: {result['summary']['by_apply_readiness']}",
        "",
        "## Policy",
        "",
    ]
    for key, value in result["policy"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## Decisions",
            "",
            "| decision | title | field | apply | reason | master | notion snapshot |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for row in result["decisions"]:
        lines.append(
            "| {decision} | {title} | {field} | {apply_ready} | {reason} | {master} | {notion} |".format(
                decision=md_escape(row["decision"]),
                title=md_escape(row["title"]),
                field=md_escape(row["field"]),
                apply_ready="yes" if row["apply_ready"] else "no",
                reason=md_escape(row["reason"]),
                master=md_escape(row["master_value"]),
                notion=md_escape(row["notion_snapshot_value"]),
            )
        )
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--drift-report", type=Path, default=DRIFT_REPORT)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    args = parser.parse_args()

    result = build_decisions(load_json(args.drift_report))
    write_json(args.out_json, result)
    Path(args.out_md).write_text(render_markdown(result), encoding="utf-8")
    print(
        "notion snapshot drift decisions: "
        f"status={result['status']} "
        f"decisions={result['summary']['decision_count']} "
        f"apply_ready={result['summary']['by_apply_readiness'].get('apply_ready', 0)} "
        f"out={args.out_json}"
    )


if __name__ == "__main__":
    main()
