#!/usr/bin/env python3
"""Suggest first-pass review decisions for retrospective event candidates."""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_DRY_RUN = Path("data/retrospective_occurrence_dry_run.json")
DEFAULT_OUT = Path("data/retrospective_event_review_decisions_suggested.json")


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


def has_specific_anchor(row):
    name = row.get("display_name") or ""
    venue = row.get("venue_match_name") or row.get("venue") or ""
    if venue:
        return True
    anchors = (
        "サンシャインシティ",
        "神田明神",
        "雷門",
        "西馬音内",
        "アキバ",
        "真證寺",
        "築地本願寺",
        "日本丸",
    )
    return any(anchor in name for anchor in anchors)


def suggested_decision(row):
    flags = set(row.get("review_flags") or [])
    priority = row.get("review_priority") or ""
    name = row.get("display_name") or ""
    evidence_count = int(row.get("evidence_count") or 0)
    has_venue = bool(row.get("venue_match_name") or row.get("venue"))
    has_date = bool(row.get("estimated_date"))
    descriptive_phrases = (
        "厳かな",
        "伝統的",
        "街が一体",
        "感じながら",
        "活気あふれる",
        "日本の",
        "古くから伝わる",
    )

    if "sentence_fragment" in flags or "long_phrase" in flags:
        return "不採用", "文章断片/説明文の可能性が高い一次判定。"
    if any(phrase in name for phrase in descriptive_phrases):
        return "要調査", "説明文がイベント名化している可能性あり。元証拠確認が必要。"
    if "bad_prefix" in flags and not has_specific_anchor(row):
        return "不採用", "先頭に不要語が残るノイズ疑いの一次判定。"
    if priority == "high" and has_venue and has_date and evidence_count >= 2:
        return "登録", "会場・日付・複数証拠が揃うため登録候補。最終重複確認は必要。"
    if priority == "high" and has_venue and has_date:
        return "要調査", "会場・日付は揃うが証拠が単独。登録前確認が必要。"
    if has_specific_anchor(row) and (has_date or evidence_count >= 2):
        return "要調査", "固有名アンカーがあり本物候補。会場/重複の確認が必要。"
    if has_venue and evidence_count >= 1:
        return "要調査", "会場アンカーあり。イベント名の妥当性確認が必要。"
    if name.endswith(("盆踊り", "盆踊り大会", "夏祭り", "まつり", "祭り")):
        return "保留", "イベント名らしいが会場または証拠が弱い。"
    return "不採用", "登録根拠が弱い一次判定。"


def build_suggestions(dry_run, generated_at=None):
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    rows = []
    counts = {}
    for candidate in dry_run.get("new_event_candidates") or []:
        decision, note = suggested_decision(candidate)
        counts[decision] = counts.get(decision, 0) + 1
        rows.append({
            "key": candidate.get("candidate_key") or "",
            "term": candidate.get("display_name") or "",
            "category": candidate.get("review_priority") or "",
            "decision": decision,
            "note": note,
        })
    return {
        "generated_by": "suggest_retrospective_event_decisions.py",
        "generated_at": generated_at,
        "source": str(DEFAULT_DRY_RUN),
        "total": len(rows),
        "counts": dict(sorted(counts.items())),
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", type=Path, default=DEFAULT_DRY_RUN)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    output = build_suggestions(load_json(args.dry_run, {}))
    output["source"] = str(args.dry_run)
    write_json(args.out, output)
    print(f"suggested retrospective decisions: total={output['total']} counts={output['counts']} -> {args.out}")


if __name__ == "__main__":
    main()
