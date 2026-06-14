#!/usr/bin/env python3
"""Apply accepted venue-song associations to Notion song master relations."""

import argparse
import json
import os
import re
import unicodedata
from pathlib import Path

from notion_config import SONG_MASTER_DATABASE_ID, VENUE_DATABASE_ID, load_local_env
from register_song_master_initial import classify_song
from triage_weekly_song_candidates import notion_request, rich_text, title_index


load_local_env()

TOKEN = os.environ.get("NOTION_API_TOKEN")
SONG_DB_ID = os.environ.get("SONG_MASTER_DB_ID") or SONG_MASTER_DATABASE_ID
SOURCE = Path("data/retrospective_venue_song_associations_accepted.json")
OUT = Path("data/accepted_venue_song_associations_apply_result.json")
OUT_MD = Path("data/accepted_venue_song_associations_apply_result.md")

VENUE_ALIAS_MAP = {
    "中央区立社会教育会館": "日本橋社会教育会館",
    "辻堂駅北口神台公園": "辻堂神台公園",
    "日枝神社": "山王パークタワー公開空地",
    "赤坂日枝神社": "山王パークタワー公開空地",
    "夏祭り向けに有馬小学校": "有馬小学校",
}


def load_json(path):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def norm_title(value):
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[\s　\"'“”‘’「」『』【】\[\]（）()・、。!！?？:：/／\\|｜~〜\-‐‑–—_]+", "", value)


def title_index_plus(db_id):
    raw = title_index(db_id)
    rows = list(raw.values())
    exact = {norm_title(row["name"]): row for row in rows if row.get("name")}
    return {"rows": rows, "exact": exact}


def match_title(value, index, min_fuzzy_len=4, alias_map=None):
    lookup_value = (alias_map or {}).get(value, value)
    key = norm_title(lookup_value)
    if not key:
        return None, "empty"
    if key in index["exact"]:
        return index["exact"][key], "exact"
    candidates = []
    for row in index["rows"]:
        row_key = norm_title(row.get("name"))
        if not row_key or len(row_key) < min_fuzzy_len:
            continue
        if key in row_key or row_key in key:
            candidates.append((abs(len(row_key) - len(key)), -len(row_key), row))
    if candidates:
        candidates.sort(key=lambda item: (item[0], item[1], item[2]["name"]))
        return candidates[0][2], "fuzzy"
    return None, "missing"


def relation_ids(prop):
    if not prop or prop.get("type") != "relation":
        return []
    return [item["id"] for item in prop.get("relation", [])]


def number_value(prop):
    return prop.get("number") if prop and prop.get("type") == "number" else None


def plain_text(prop):
    if not prop:
        return ""
    prop_type = prop.get("type")
    if prop_type in ("title", "rich_text"):
        return "".join(item.get("plain_text", "") for item in prop.get(prop_type, [])).strip()
    return ""


def source_url(row):
    return (row.get("source_urls") or [""])[0]


def evidence_note(row):
    first = (row.get("evidence") or [{}])[0]
    flags = ", ".join(row.get("flags") or [])
    return (
        "[venue-song-review] X過去投稿レビュー採用\n"
        f"会場: {row.get('venue', '')}\n"
        f"曲: {row.get('song_name', '')}\n"
        f"確率: {row.get('probability', '')} / 確信度: {row.get('confidence', '')}\n"
        f"証拠数: {row.get('evidence_count', '')} / 話者数: {row.get('speaker_count', '')}\n"
        f"フラグ: {flags}\n"
        f"証拠URL: {source_url(row)}\n"
        f"証拠抜粋: {(first.get('text') or '')[:800]}"
    )


def song_update_props(song_name, row, venue_id, existing_page):
    props = existing_page.get("properties", {}) if existing_page else {}
    current_venues = relation_ids(props.get("会場", {}))
    current_evidence = number_value(props.get("証拠数", {})) or 0
    evidence_count = max(int(current_evidence), int(row.get("evidence_count") or 1))
    existing_memo = plain_text(props.get("メモ", {}))
    note = evidence_note(row)
    memo = existing_memo if note in existing_memo else (existing_memo.rstrip() + "\n\n" + note).strip()
    out = {
        "分類": {"select": {"name": classify_song(song_name)}},
        "状態": {"select": {"name": "有効"}},
        "会場": {"relation": [{"id": page_id} for page_id in sorted(set(current_venues + [venue_id]))]},
        "証拠数": {"number": evidence_count},
        "メモ": {"rich_text": rich_text(memo)},
    }
    if source_url(row):
        out["出典・音源URL"] = {"url": source_url(row)}
    return out


def song_create_props(song_name, row, venue_id):
    props = song_update_props(song_name, row, venue_id, existing_page=None)
    props["曲名"] = {"title": rich_text(song_name[:200])}
    return props


def plan_rows(rows, songs, venues):
    planned = []
    for row in rows:
        song_name = row.get("song_name") or ""
        venue_name = row.get("venue") or ""
        song, song_match = match_title(song_name, songs)
        venue, venue_match = match_title(venue_name, venues, alias_map=VENUE_ALIAS_MAP)
        if not venue:
            action = "skip_missing_venue"
        elif song:
            current_venues = relation_ids(song["page"].get("properties", {}).get("会場", {}))
            action = "already_linked" if venue["id"] in current_venues else "update_song"
        else:
            action = "create_song"
        planned.append({
            "action": action,
            "song_name": song_name,
            "venue": venue_name,
            "song_match": song_match,
            "matched_song": (song or {}).get("name", ""),
            "song_page_id": (song or {}).get("id", ""),
            "venue_match": venue_match,
            "matched_venue": (venue or {}).get("name", ""),
            "venue_page_id": (venue or {}).get("id", ""),
            "probability": row.get("probability"),
            "confidence": row.get("confidence"),
            "evidence_count": row.get("evidence_count"),
            "source_url": source_url(row),
            "source": row,
        })
    return planned


def apply_plan(plan, apply=False):
    created = []
    updated = []
    already_linked = []
    skipped = []
    for item in plan:
        row = item["source"]
        if item["action"] == "skip_missing_venue":
            skipped.append(public_item(item))
            continue
        if item["action"] == "already_linked":
            already_linked.append(public_item(item))
            continue
        if not apply:
            target = created if item["action"] == "create_song" else updated
            target.append({**public_item(item), "dry_run": True})
            continue
        if item["action"] == "update_song":
            props = song_update_props(
                item["matched_song"],
                row,
                item["venue_page_id"],
                row_existing_page(item),
            )
            notion_request("PATCH", f"/pages/{item['song_page_id']}", {"properties": props})
            updated.append(public_item(item))
        elif item["action"] == "create_song":
            page = notion_request(
                "POST",
                "/pages",
                {
                    "parent": {"database_id": SONG_DB_ID},
                    "properties": song_create_props(item["song_name"], row, item["venue_page_id"]),
                },
            )
            created.append({**public_item(item), "song_page_id": page["id"]})
    return created, updated, already_linked, skipped


def public_item(item):
    return {
        key: value for key, value in item.items()
        if key != "source" and not key.startswith("_")
    }


def row_existing_page(item):
    return {"properties": item.get("_song_properties") or {}}


def attach_song_properties(plan, songs):
    by_id = {row["id"]: row["page"].get("properties", {}) for row in songs["rows"]}
    for item in plan:
        if item.get("song_page_id"):
            item["_song_properties"] = by_id.get(item["song_page_id"], {})


def counts(created, updated, already_linked, skipped):
    return {
        "created_count": len(created),
        "updated_count": len(updated),
        "already_linked_count": len(already_linked),
        "skipped_count": len(skipped),
    }


def render_rows(rows):
    if not rows:
        return "_なし_"
    lines = [
        "| action | 会場 | 曲 | 一致会場 | 一致曲 | 確率 | URL |",
        "|---|---|---|---|---|---:|---|",
    ]
    for row in rows:
        lines.append(
            f"| {row.get('action', '')} | {row.get('venue', '')} | {row.get('song_name', '')} | "
            f"{row.get('matched_venue', '')} ({row.get('venue_match', '')}) | "
            f"{row.get('matched_song', '')} ({row.get('song_match', '')}) | "
            f"{row.get('probability', '')} | {row.get('source_url', '')} |"
        )
    return "\n".join(lines)


def render_markdown(result):
    return "\n".join([
        "# 採用済み 会場×曲 Notion反映計画",
        "",
        f"- apply: {result['apply']}",
        f"- 入力: {result['source']}",
        f"- 採用候補: {result['accepted_count']}",
        f"- 新規曲作成: {result['created_count']}",
        f"- 既存曲更新: {result['updated_count']}",
        f"- 既に紐付け済み: {result['already_linked_count']}",
        f"- スキップ: {result['skipped_count']}",
        "",
        "## 新規曲作成",
        "",
        render_rows(result["created"]),
        "",
        "## 既存曲更新",
        "",
        render_rows(result["updated"]),
        "",
        "## 既に紐付け済み",
        "",
        render_rows(result["already_linked"]),
        "",
        "## スキップ",
        "",
        render_rows(result["skipped"]),
        "",
    ]) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    if not SONG_DB_ID:
        raise SystemExit("SONG_MASTER_DB_ID is not set")

    source = load_json(args.source)
    rows = source.get("associations", [])
    songs = title_index_plus(SONG_DB_ID)
    venues = title_index_plus(VENUE_DATABASE_ID)
    plan = plan_rows(rows, songs, venues)
    attach_song_properties(plan, songs)
    created, updated, already_linked, skipped = apply_plan(plan, apply=args.apply)
    result = {
        "apply": args.apply,
        "source": str(args.source),
        "accepted_count": len(rows),
        **counts(created, updated, already_linked, skipped),
        "created": created,
        "updated": updated,
        "already_linked": already_linked,
        "skipped": skipped,
    }
    write_json(args.out, result)
    args.out_md.write_text(render_markdown(result), encoding="utf-8")
    print(
        "done: apply={apply} accepted={accepted_count} create={created_count} "
        "update={updated_count} linked={already_linked_count} skipped={skipped_count}".format(**result)
    )


if __name__ == "__main__":
    main()
