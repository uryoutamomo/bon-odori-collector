#!/usr/bin/env python3
"""Apply venue-song review decisions to local reviewed datasets."""

import argparse
import json
from collections import Counter
from pathlib import Path


SOURCE = Path("data/retrospective_venue_song_associations.json")
DECISIONS = Path("data/retrospective_venue_song_review_decisions.json")
OUT_JSON = Path("data/retrospective_venue_song_review_apply_result.json")
OUT_MD = Path("data/retrospective_venue_song_review_apply_result.md")
ACCEPTED_JSON = Path("data/retrospective_venue_song_associations_accepted.json")

ACCEPT = {"採用"}
REJECT = {"不採用"}
HOLD = {"保留"}
FIX = {"修正"}


def load_json(path, default=None):
    if not Path(path).exists():
        if default is not None:
            return default
        raise FileNotFoundError(path)
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def decision_rows(path):
    data = load_json(path)
    rows = data.get("rows", data if isinstance(data, list) else [])
    return [row for row in rows if isinstance(row, dict) and row.get("decision")]


def association_index(source):
    return {
        item.get("association_id"): item
        for item in source.get("associations", [])
        if item.get("association_id")
    }


def id_from_decision(row):
    key = row.get("key") or ""
    return key.split("||")[-1] if "||" in key else ""


def apply_decisions(source, decisions):
    by_id = association_index(source)
    accepted = []
    rejected = []
    held = []
    fix_needed = []
    skipped = []

    for decision in decisions:
        association_id = id_from_decision(decision)
        source_row = by_id.get(association_id)
        if not source_row:
            skipped.append({"decision": decision, "reason": "source association not found"})
            continue
        value = decision.get("decision") or ""
        merged = dict(source_row)
        merged["review_decision"] = value
        merged["review_note"] = decision.get("note") or ""
        if value in ACCEPT:
            accepted.append(merged)
        elif value in REJECT:
            rejected.append(merged)
        elif value in HOLD:
            held.append(merged)
        elif value in FIX:
            fix_needed.append(merged)
        else:
            skipped.append({"decision": decision, "reason": "unknown decision"})

    accepted.sort(key=lambda item: (item["venue"], item["song_name"]))
    rejected.sort(key=lambda item: (item["venue"], item["song_name"]))
    held.sort(key=lambda item: (item["venue"], item["song_name"]))
    fix_needed.sort(key=lambda item: (item["venue"], item["song_name"]))

    return {
        "source": str(SOURCE),
        "decisions": str(DECISIONS),
        "decision_count": len(decisions),
        "counts": {
            "accepted": len(accepted),
            "rejected": len(rejected),
            "held": len(held),
            "fix_needed": len(fix_needed),
            "skipped": len(skipped),
            "by_decision": dict(Counter(row.get("decision") or "" for row in decisions)),
        },
        "accepted": accepted,
        "rejected": rejected,
        "held": held,
        "fix_needed": fix_needed,
        "skipped": skipped,
    }


def table(rows):
    if not rows:
        return "_なし_"
    lines = [
        "| 会場 | 曲 | 確率 | 確信度 | 証拠 | 話者 | フラグ | URL |",
        "|---|---|---:|---|---:|---:|---|---|",
    ]
    for row in rows:
        flags = ", ".join(row.get("flags") or [])
        url = (row.get("source_urls") or [""])[0]
        lines.append(
            f"| {row.get('venue', '')} | {row.get('song_name', '')} | {row.get('probability', '')} | "
            f"{row.get('confidence', '')} | {row.get('evidence_count', '')} | {row.get('speaker_count', '')} | "
            f"{flags} | {url} |"
        )
    return "\n".join(lines)


def render_markdown(result):
    lines = [
        "# 会場×曲レビュー反映結果",
        "",
        f"- 判定数: {result['decision_count']}",
        f"- 採用: {result['counts']['accepted']}",
        f"- 不採用: {result['counts']['rejected']}",
        f"- 保留: {result['counts']['held']}",
        f"- 修正待ち: {result['counts']['fix_needed']}",
        f"- スキップ: {result['counts']['skipped']}",
        "",
        "## 採用",
        "",
        table(result["accepted"]),
        "",
        "## 修正待ち",
        "",
        table(result["fix_needed"]),
        "",
        "## 保留",
        "",
        table(result["held"]),
    ]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--decisions", type=Path, default=DECISIONS)
    parser.add_argument("--out", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    parser.add_argument("--accepted-out", type=Path, default=ACCEPTED_JSON)
    args = parser.parse_args()

    source = load_json(args.source)
    decisions = decision_rows(args.decisions)
    result = apply_decisions(source, decisions)
    result["source"] = str(args.source)
    result["decisions"] = str(args.decisions)

    write_json(args.out, result)
    write_json(
        args.accepted_out,
        {
            "generated_by": "apply_retrospective_venue_song_review_decisions.py",
            "source": str(args.source),
            "decisions": str(args.decisions),
            "count": len(result["accepted"]),
            "associations": result["accepted"],
        },
    )
    args.out_md.write_text(render_markdown(result), encoding="utf-8")
    print(
        "done: accepted={accepted} rejected={rejected} held={held} "
        "fix_needed={fix_needed} skipped={skipped}".format(**result["counts"])
    )


if __name__ == "__main__":
    main()
