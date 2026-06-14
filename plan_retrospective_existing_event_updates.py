#!/usr/bin/env python3
"""Plan dry-run updates for retrospective rows that match existing events."""

import argparse
import json
from pathlib import Path


QUEUE = Path("data/retrospective_existing_event_update_queue.json")
AUDIT = Path("data/retrospective_event_apply_audit.json")
DRY_RUN = Path("data/retrospective_occurrence_dry_run.json")
OUT = Path("data/retrospective_existing_event_update_plan.json")
OUT_MD = Path("data/retrospective_existing_event_update_plan.md")


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def candidate_map(dry_run):
    return {row.get("candidate_key"): row for row in dry_run.get("new_event_candidates") or []}


def audit_map(audit):
    return {row.get("candidate_key"): row for row in audit.get("rows") or []}


def evidence_samples(candidate):
    samples = []
    for ev in (candidate.get("evidence") or [])[:5]:
        samples.append({
            "url": ev.get("url") or "",
            "account": ev.get("account") or "",
            "dancer_key": ev.get("dancer_key") or "",
            "observed_at": ev.get("observed_at") or "",
            "text": ev.get("text") or "",
        })
    return samples


def update_action(row, duplicate, target=None):
    event_name = row.get("event_name") or ""
    target = target or (duplicate[0] if duplicate else {})
    if target:
        reasons = set(target.get("reasons") or [])
        if "event_name_contains" in reasons or "event_name_exact" in reasons or "event_name_normalized" in reasons:
            return "append_evidence_to_existing"
        if "manual_text_name_match" in reasons:
            return "append_evidence_to_existing"
        return "manual_duplicate_review"
    if "西綾瀬" in event_name or "最も早い" in event_name:
        return "append_evidence_to_existing"
    return "manual_duplicate_review"


def manual_target(row):
    event_name = row.get("event_name") or ""
    source = row.get("source_url") or ""
    if "最も早い" in event_name or "2065082668396827008" in source:
        return {
            "name": "西綾瀬町会 夏祭り盆踊り大会",
            "venue": "五反野コミュニティ公園",
            "date": "2026-06-20",
            "status": "確認済み",
            "reasons": ["manual_text_name_match", "date_overlap"],
        }
    return {}


def build_plan(queue, audit, dry_run):
    candidates = candidate_map(dry_run)
    audits = audit_map(audit)
    rows = []
    counts = {}
    for row in queue.get("rows") or []:
        candidate = candidates.get(row.get("candidate_key"), {})
        audit_row = audits.get(row.get("candidate_key"), {})
        duplicates = audit_row.get("duplicate_matches") or []
        target = duplicates[0] if duplicates else manual_target(row)
        action = update_action(row, duplicates, target=target)
        counts[action] = counts.get(action, 0) + 1
        rows.append({
            "candidate_key": row.get("candidate_key"),
            "candidate_event_name": row.get("event_name"),
            "candidate_venue": row.get("venue"),
            "candidate_date": row.get("estimated_date"),
            "candidate_source_url": row.get("source_url"),
            "action": action,
            "target_event_name": target.get("name") or "",
            "target_venue": target.get("venue") or "",
            "target_date": target.get("date") or "",
            "target_status": target.get("status") or "",
            "match_reasons": target.get("reasons") or [],
            "suggested_updates": {
                "do_not_create_new_event": True,
                "append_evidence_url": bool(row.get("source_url")),
                "append_alias_note": bool(row.get("event_name") and row.get("event_name") != target.get("name")),
                "candidate_alias": row.get("event_name") or "",
                "candidate_date": row.get("estimated_date") or "",
            },
            "evidence": evidence_samples(candidate),
        })
    return {
        "generated_by": "plan_retrospective_existing_event_updates.py",
        "mode": "dry_run",
        "apply_performed": False,
        "input_count": len(queue.get("rows") or []),
        "counts": dict(sorted(counts.items())),
        "rows": rows,
    }


def markdown(plan):
    lines = [
        "# Retrospective existing event update plan",
        "",
        f"- input_count: {plan['input_count']}",
        f"- apply_performed: {plan['apply_performed']}",
        "",
        "## Counts",
        "",
    ]
    for key, value in plan.get("counts", {}).items():
        lines.append(f"- {key}: {value}")
    lines += [
        "",
        "## Rows",
        "",
        "| action | candidate | target | candidate date | target date | reason |",
        "|---|---|---|---|---|---|",
    ]
    for row in plan.get("rows") or []:
        lines.append(
            "| {action} | {candidate} / {candidate_venue} | {target} / {target_venue} | {candidate_date} | {target_date} | {reasons} |".format(
                action=row.get("action") or "",
                candidate=(row.get("candidate_event_name") or "").replace("|", " "),
                candidate_venue=(row.get("candidate_venue") or "").replace("|", " "),
                target=(row.get("target_event_name") or "").replace("|", " "),
                target_venue=(row.get("target_venue") or "").replace("|", " "),
                candidate_date=row.get("candidate_date") or "",
                target_date=row.get("target_date") or "",
                reasons=", ".join(row.get("match_reasons") or []),
            )
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue", type=Path, default=QUEUE)
    parser.add_argument("--audit", type=Path, default=AUDIT)
    parser.add_argument("--dry-run", type=Path, default=DRY_RUN)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--md-out", type=Path, default=OUT_MD)
    args = parser.parse_args()

    plan = build_plan(load_json(args.queue, {}), load_json(args.audit, {}), load_json(args.dry_run, {}))
    write_json(args.out, plan)
    write_text(args.md_out, markdown(plan))
    print(f"existing event update plan: input={plan['input_count']} counts={plan['counts']} -> {args.out}")


if __name__ == "__main__":
    main()
