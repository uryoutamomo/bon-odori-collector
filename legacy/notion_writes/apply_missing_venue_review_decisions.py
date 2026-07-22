#!/usr/bin/env python3
"""Apply reviewed missing venue decisions from venue-song associations."""

import argparse
import json
import os
from pathlib import Path

from operation_safety.manual_apply_guards import LEGACY_NOTION_REPAIR_CONFIRMATION, require_confirmation
from notion_config import VENUE_DATABASE_ID, load_local_env
from triage_weekly_song_candidates import notion_request, title_index, norm, rich_text


load_local_env()

TOKEN = os.environ.get("NOTION_API_TOKEN")
SOURCE = Path("data/accepted_venue_song_missing_venue_review.json")
DECISIONS = Path("data/accepted_venue_song_missing_venue_decisions.json")
OUT = Path("data/accepted_venue_song_missing_venue_apply_result.json")
OUT_MD = Path("data/accepted_venue_song_missing_venue_apply_result.md")

ADD = {"会場追加"}
MERGE = {"既存に統合"}
REJECT = {"不採用"}
HOLD = {"保留"}

VENUE_REGIONS = {
    "あかつき公園": "中央区",
    "さくら公園": "",
    "尼北小学校": "尼崎市",
    "有馬小学校": "中央区",
    "稲村ケ崎公園": "鎌倉市",
    "羽根木公園": "世田谷区",
}

VENUE_ACCESS = {
    "あかつき公園": "東京メトロ日比谷線 築地駅から徒歩圏内",
    "尼北小学校": "阪急塚口駅・JR塚口駅周辺からアクセス",
    "有馬小学校": "東京メトロ半蔵門線 水天宮前駅、日比谷線/都営浅草線 人形町駅から徒歩圏内",
    "稲村ケ崎公園": "江ノ島電鉄 稲村ヶ崎駅から徒歩圏内",
    "羽根木公園": "小田急線 梅ヶ丘駅、井の頭線 東松原駅から徒歩圏内",
}

MERGE_TARGETS = {
    "日枝神社": "山王パークタワー公開空地",
    "赤坂日枝神社": "山王パークタワー公開空地",
}


def load_json(path):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def source_rows(path):
    data = load_json(path)
    return {row["term"]: row for row in data.get("rows", [])}


def decision_rows(path):
    data = load_json(path)
    rows = data.get("rows", data if isinstance(data, list) else [])
    return [row for row in rows if isinstance(row, dict) and row.get("decision")]


def find_venue(name, venues):
    return venues.get(norm(name))


def title_prop(text):
    return {"title": rich_text(text[:200])}


def text_prop(text):
    return {"rich_text": rich_text(text)}


def checkbox_prop(value):
    return {"checkbox": bool(value)}


def venue_props(row):
    name = row["suggested_venue"]
    source_url = row.get("evidence_url") or ""
    memo = (
        "会場×曲レビューから追加。\n"
        f"元抽出名: {', '.join(row.get('raw_venues') or [])}\n"
        f"関連曲: {row.get('songs_text', '')}\n"
        f"証拠URL: {source_url}\n"
        f"証拠抜粋: {row.get('evidence_text', '')[:900]}"
    )
    return {
        "会場名": title_prop(name),
        "所在区・市": text_prop(VENUE_REGIONS.get(name, "")),
        "アクセス": text_prop(VENUE_ACCESS.get(name, "")),
        "過去メモ": text_prop(memo),
        "築地30分圏内": checkbox_prop(VENUE_REGIONS.get(name) in {"中央区", "世田谷区"}),
        "要レビュー": checkbox_prop(True),
    }


def create_venue(row):
    page = notion_request(
        "POST",
        "/pages",
        {
            "parent": {"database_id": VENUE_DATABASE_ID},
            "properties": venue_props(row),
        },
    )
    return page


def apply_decisions(sources, decisions, apply=False):
    venues = title_index(VENUE_DATABASE_ID)
    created = []
    existing = []
    merged = []
    rejected = []
    held = []
    skipped = []
    for decision in decisions:
        term = decision.get("term") or ""
        row = sources.get(term)
        if not row:
            skipped.append({"term": term, "reason": "source row not found"})
            continue
        value = decision.get("decision") or ""
        if value in ADD:
            found = find_venue(row["suggested_venue"], venues)
            item = {
                "venue": row["suggested_venue"],
                "songs": row.get("songs", []),
                "source_url": row.get("evidence_url", ""),
            }
            if found:
                existing.append({**item, "page_id": found["id"]})
                continue
            if apply:
                page = create_venue(row)
                created.append({**item, "page_id": page["id"]})
                venues[norm(row["suggested_venue"])] = {
                    "id": page["id"],
                    "name": row["suggested_venue"],
                    "page": page,
                }
            else:
                created.append({**item, "dry_run": True})
        elif value in MERGE:
            target = (decision.get("note") or "").strip() or MERGE_TARGETS.get(row["suggested_venue"], "")
            found = find_venue(target, venues) if target else None
            if found:
                merged.append({
                    "venue": row["suggested_venue"],
                    "target": target,
                    "target_page_id": found["id"],
                    "songs": row.get("songs", []),
                    "source_url": row.get("evidence_url", ""),
                })
            else:
                skipped.append({
                    "venue": row["suggested_venue"],
                    "decision": value,
                    "reason": "merge target not found",
                    "target": target,
                })
        elif value in REJECT:
            rejected.append({"venue": row["suggested_venue"], "songs": row.get("songs", [])})
        elif value in HOLD:
            held.append({"venue": row["suggested_venue"], "songs": row.get("songs", [])})
        else:
            skipped.append({"venue": row["suggested_venue"], "decision": value, "reason": "unknown decision"})
    return created, existing, merged, rejected, held, skipped


def table(rows):
    if not rows:
        return "_なし_"
    lines = ["| 会場 | 曲 | URL | 補足 |", "|---|---|---|---|"]
    for row in rows:
        lines.append(
            f"| {row.get('venue', '')} | {'、'.join(row.get('songs') or [])} | "
            f"{row.get('source_url', '')} | {row.get('target') or row.get('reason') or row.get('page_id') or ''} |"
        )
    return "\n".join(lines)


def render_markdown(result):
    return "\n".join([
        "# 会場追加レビュー反映結果",
        "",
        f"- apply: {result['apply']}",
        f"- created: {result['created_count']}",
        f"- existing: {result['existing_count']}",
        f"- merged: {result['merged_count']}",
        f"- rejected: {result['rejected_count']}",
        f"- held: {result['held_count']}",
        f"- skipped: {result['skipped_count']}",
        "",
        "## 作成",
        "",
        table(result["created"]),
        "",
        "## 既存",
        "",
        table(result["existing"]),
        "",
        "## 統合",
        "",
        table(result["merged"]),
        "",
        "## スキップ",
        "",
        table(result["skipped"]),
        "",
    ]) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--decisions", type=Path, default=DECISIONS)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    if not TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    try:
        require_confirmation(
            args.apply,
            args.confirm,
            LEGACY_NOTION_REPAIR_CONFIRMATION,
            "legacy missing venue review Notion apply",
        )
    except ValueError as exc:
        parser.error(str(exc))

    created, existing, merged, rejected, held, skipped = apply_decisions(
        source_rows(args.source),
        decision_rows(args.decisions),
        apply=args.apply,
    )
    result = {
        "apply": args.apply,
        "source": str(args.source),
        "decisions": str(args.decisions),
        "created_count": len(created),
        "existing_count": len(existing),
        "merged_count": len(merged),
        "rejected_count": len(rejected),
        "held_count": len(held),
        "skipped_count": len(skipped),
        "created": created,
        "existing": existing,
        "merged": merged,
        "rejected": rejected,
        "held": held,
        "skipped": skipped,
    }
    write_json(args.out, result)
    args.out_md.write_text(render_markdown(result), encoding="utf-8")
    print(
        "done: apply={apply} created={created_count} existing={existing_count} "
        "merged={merged_count} rejected={rejected_count} held={held_count} skipped={skipped_count}".format(**result)
    )


if __name__ == "__main__":
    main()
