#!/usr/bin/env python3
"""Apply downloaded glossary review decisions to the merged candidate report."""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


MERGED = Path("data/glossary_v2_oto123_merged_terms.json")
OUT_JSON = Path("data/glossary_v2_oto123_review_result.json")
OUT_MD = Path("data/glossary_v2_oto123_review_result.md")


def load_json(path):
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def key(row):
    return (
        row.get("term", ""),
        row.get("category", ""),
        row.get("type", ""),
        row.get("evidence_url", ""),
    )


def merge_decisions(decisions_paths):
    merged = load_json(MERGED)
    by_key = {}
    for decisions_path in decisions_paths:
        decisions = load_json(decisions_path)
        for row in decisions.get("rows", []):
            by_key[key(row)] = row

    reviewed = []
    for row in merged.get("candidates", []):
        decision_row = by_key.get(key(row))
        if not decision_row:
            continue
        out = dict(row)
        out["decision"] = decision_row.get("decision", "")
        out["review_note"] = decision_row.get("note", "")
        reviewed.append(out)

    counts = Counter(row["decision"] for row in reviewed)
    accepted = [row for row in reviewed if row["decision"] == "採用"]
    rejected = [row for row in reviewed if row["decision"] == "不採用"]
    held = [row for row in reviewed if row["decision"] == "保留"]
    merge = [row for row in reviewed if row["decision"] == "まとめ"]

    duplicate_accepts = []
    accepted_by_term = defaultdict(list)
    for row in accepted:
        accepted_by_term[row["term"]].append(row)
    for term, rows in sorted(accepted_by_term.items()):
        if len(rows) > 1:
            duplicate_accepts.append({
                "term": term,
                "count": len(rows),
                "categories": sorted({row["category"] for row in rows}),
            })

    result = {
        "generated_by": "おと1（Codex）",
        "generated_at": "2026-06-11",
        "decisions_source": [str(path) for path in decisions_paths],
        "reviewed_count": len(reviewed),
        "counts": dict(counts),
        "duplicate_accepted_terms": duplicate_accepts,
        "accepted": accepted,
        "rejected": rejected,
        "held": held,
        "merge": merge,
    }
    return result


def table(rows):
    lines = ["| 語 | 分類 | 解釈 | メモ |", "|---|---|---|---|"]
    for row in rows:
        lines.append(
            "| {term} | {category} | {interpretation} | {note} |".format(
                term=row["term"].replace("|", "｜"),
                category=row["category"].replace("|", "｜"),
                interpretation=row["interpretation"].replace("\n", " ").replace("|", "｜"),
                note=(row.get("review_note") or "").replace("\n", " ").replace("|", "｜"),
            )
        )
    return "\n".join(lines)


def write_outputs(result):
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# 用語集v2 第1レビュー判定結果",
        "",
        f"判定元: `{result['decisions_source']}`",
        "",
        "## 件数",
        "",
    ]
    for label in ("採用", "不採用", "保留", "まとめ"):
        lines.append(f"- {label}: {result['counts'].get(label, 0)}件")
    lines.extend(["", "## 注意点", ""])
    if result["duplicate_accepted_terms"]:
        for item in result["duplicate_accepted_terms"]:
            lines.append(
                f"- `{item['term']}` は採用が {item['count']} 件あります"
                f"（分類: {', '.join(item['categories'])}）。統合時に代表行を決めます。"
            )
    else:
        lines.append("- 採用語の完全一致重複はありません。")
    lines.extend(["", "## 採用", "", table(result["accepted"])])
    lines.extend(["", "## 保留", "", table(result["held"])])
    lines.extend(["", "## 不採用", "", table(result["rejected"])])
    if result["merge"]:
        lines.extend(["", "## まとめ", "", table(result["merge"])])
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("decisions", nargs="+", type=Path)
    args = parser.parse_args()

    result = merge_decisions(args.decisions)
    write_outputs(result)
    print(
        "reviewed={reviewed} accepted={accepted} rejected={rejected} held={held} merge={merge}".format(
            reviewed=result["reviewed_count"],
            accepted=result["counts"].get("採用", 0),
            rejected=result["counts"].get("不採用", 0),
            held=result["counts"].get("保留", 0),
            merge=result["counts"].get("まとめ", 0),
        )
    )
    print(f"wrote {OUT_JSON} and {OUT_MD}")


if __name__ == "__main__":
    main()
