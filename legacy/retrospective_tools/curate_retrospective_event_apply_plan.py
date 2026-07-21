#!/usr/bin/env python3
"""Curate reviewed retrospective event rows into apply-safe action buckets."""

import argparse
import json
import re
from pathlib import Path


DEFAULT_PLAN = Path("data/retrospective_event_apply_plan.json")
DEFAULT_AUDIT = Path("data/retrospective_event_apply_audit.json")
DEFAULT_DRY_RUN = Path("data/retrospective_occurrence_dry_run.json")
DEFAULT_OUT = Path("data/retrospective_event_apply_curation.json")
DEFAULT_MD = Path("data/retrospective_event_apply_curation.md")


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


def evidence_text(candidate):
    return "\n".join(ev.get("text") or "" for ev in candidate.get("evidence") or [])


def action_for(row, audit_row, candidate):
    text = evidence_text(candidate)
    duplicates = audit_row.get("duplicate_matches") or []
    name = row.get("event_name") or ""

    if duplicates:
        return {
            "action": "update_existing_or_skip_create",
            "reason": "既存イベント候補と重複。新規作成しない。",
            "existing_candidates": duplicates,
        }
    if "練習会" in text or "公開練習会" in text:
        return {
            "action": "do_not_create_event",
            "reason": "証拠本文が盆踊り本番ではなく練習会。event_songs/observations側の証拠として扱う。",
        }
    if "西綾瀬町会盆踊り" in text:
        return {
            "action": "update_existing_or_skip_create",
            "reason": "本文中の正式名は西綾瀬町会盆踊り。既存の西綾瀬町会 夏祭り盆踊り大会と重複確認対象。",
            "suggested_event_name": "西綾瀬町会 夏祭り盆踊り大会",
        }
    if "百万石踊り流し" in text:
        return {
            "action": "do_not_create_event",
            "reason": "金沢百万石まつり内の踊り流し参加記録。今回の新規イベント正本化対象からは除外。",
        }
    if "ぎふマルシェ" in text or "コーヒー" in text:
        return {
            "action": "do_not_create_event",
            "reason": "証拠本文がマルシェ告知で、盆踊りイベントではない。",
        }
    if re.match(r"^\d+月\d+日", name):
        return {
            "action": "needs_research",
            "reason": "イベント名に日付が混入。正式名と会場の補完が必要。",
        }
    if not row.get("venue"):
        return {
            "action": "needs_research",
            "reason": "会場未確定。登録前に venue_master への名寄せまたは新規会場登録が必要。",
        }
    if "venue_not_in_master" in (audit_row.get("flags") or []):
        return {
            "action": "needs_venue_master",
            "reason": "会場が会場マスタ未登録。イベント作成前に会場ページ作成/名寄せが必要。",
        }
    return {
        "action": "create_event_candidate",
        "reason": "重複・会場リスクなし。実apply候補。",
    }


def build_curation(plan, audit, dry_run):
    candidates = {row.get("candidate_key"): row for row in dry_run.get("new_event_candidates") or []}
    audits = {row.get("candidate_key"): row for row in audit.get("rows") or []}
    rows = []
    counts = {}
    for row in plan.get("ready_for_apply") or []:
        candidate = candidates.get(row.get("candidate_key"), {})
        audit_row = audits.get(row.get("candidate_key"), {})
        action = action_for(row, audit_row, candidate)
        counts[action["action"]] = counts.get(action["action"], 0) + 1
        rows.append({
            "candidate_key": row.get("candidate_key"),
            "event_name": row.get("event_name"),
            "venue": row.get("venue"),
            "estimated_date": row.get("estimated_date"),
            "source_url": row.get("source_url"),
            "action": action["action"],
            "reason": action["reason"],
            "suggested_event_name": action.get("suggested_event_name", ""),
            "existing_candidates": action.get("existing_candidates", []),
        })
    return {
        "generated_by": "curate_retrospective_event_apply_plan.py",
        "mode": "dry_run",
        "apply_performed": False,
        "ready_for_apply_input_count": len(plan.get("ready_for_apply") or []),
        "counts": dict(sorted(counts.items())),
        "rows": rows,
    }


def markdown(curation):
    lines = [
        "# Retrospective event apply curation",
        "",
        f"- ready_for_apply_input_count: {curation['ready_for_apply_input_count']}",
        f"- apply_performed: {curation['apply_performed']}",
        "",
        "## Counts",
        "",
    ]
    for key, value in curation.get("counts", {}).items():
        lines.append(f"- {key}: {value}")
    lines += [
        "",
        "## Rows",
        "",
        "| action | event | venue | date | reason |",
        "|---|---|---|---|---|",
    ]
    for row in curation.get("rows") or []:
        lines.append(
            "| {action} | {event} | {venue} | {date} | {reason} |".format(
                action=row.get("action", ""),
                event=(row.get("event_name") or "").replace("|", " "),
                venue=(row.get("venue") or "").replace("|", " "),
                date=row.get("estimated_date") or "",
                reason=(row.get("reason") or "").replace("|", " "),
            )
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--dry-run", type=Path, default=DEFAULT_DRY_RUN)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--md-out", type=Path, default=DEFAULT_MD)
    args = parser.parse_args()

    curation = build_curation(
        load_json(args.plan, {}),
        load_json(args.audit, {}),
        load_json(args.dry_run, {}),
    )
    write_json(args.out, curation)
    write_text(args.md_out, markdown(curation))
    print(f"retrospective event curation: input={curation['ready_for_apply_input_count']} counts={curation['counts']} -> {args.out}")


if __name__ == "__main__":
    main()
