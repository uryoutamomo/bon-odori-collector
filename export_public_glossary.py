#!/usr/bin/env python3
"""Export glossary v2 terms for the public Yoimatsuri site.

The public JSON intentionally omits operational review notes and raw evidence.
It keeps enough structure for the site UI to group, search, and filter terms.
"""

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from notion_config import (
    GLOSSARY_V2_DATABASE_ID,
    NOTION_API_BASE,
    SONG_MASTER_DATABASE_ID,
    load_local_env,
)


load_local_env()

NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")
DB_ID = os.environ.get("GLOSSARY_V2_DB_ID") or GLOSSARY_V2_DATABASE_ID
SONG_DB_ID = os.environ.get("SONG_MASTER_DB_ID") or SONG_MASTER_DATABASE_ID
DEFAULT_OUT = Path.home() / "bon-odori-site" / "data" / "glossary_public.json"
SUPPLEMENTS = Path("data/public_glossary_supplements.json")
SONG_CONTENT_NOTES = Path("data/public_song_content_notes.json")
SONG_MASTER_REGISTRATION = Path("data/song_master_initial_registration.json")
YOUTUBE_SONG_MASTER = Path("data/youtube_song_master.json")
NOTION_VERSION = "2022-06-28"

PUBLIC_STATES = {"候補", "有効", "保留"}
EXCLUDED_KINDS = {"除外語", "イベント別名"}
EXCLUDED_CONFIDENCES = {"除外確定"}
GENERIC_SONG_DESCRIPTIONS = {
    "盆踊り会場の曲目として確認されている曲です。",
    "曲データベースに登録されている盆踊り曲です。会場カードや曲目データから参照されます。",
}

KIND_LABELS = {
    "会場別名": "会場の呼び名",
    "イベント別名": "イベントの呼び名",
    "曲名": "曲名・踊り名",
    "行動語": "参加・行動",
    "地域語": "地域語",
    "団体語": "呼び名・略語",
}

KIND_ORDER = {
    "行動語": 0,
    "団体語": 1,
    "地域語": 2,
    "会場別名": 3,
    "イベント別名": 4,
    "曲名": 5,
}


def notion_request(method, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{NOTION_API_BASE}{path}", data=data, method=method)
    req.add_header("Authorization", f"Bearer {NOTION_TOKEN}")
    req.add_header("Notion-Version", NOTION_VERSION)
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read())


def query_all_pages(db_id):
    rows = []
    cursor = None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        data = notion_request("POST", f"/databases/{db_id}/query", payload)
        rows.extend(data.get("results", []))
        if not data.get("has_more"):
            return rows
        cursor = data.get("next_cursor")


def plain_text(prop):
    if not prop:
        return ""
    prop_type = prop.get("type")
    if prop_type == "title":
        return "".join(part.get("plain_text", "") for part in prop.get("title", [])).strip()
    if prop_type == "rich_text":
        return "".join(part.get("plain_text", "") for part in prop.get("rich_text", [])).strip()
    if prop_type == "select":
        return (prop.get("select") or {}).get("name", "")
    if prop_type == "url":
        return prop.get("url") or ""
    if prop_type == "number":
        value = prop.get("number")
        return "" if value is None else str(value)
    if prop_type == "date":
        return (prop.get("date") or {}).get("start", "")
    if prop_type == "checkbox":
        return "true" if prop.get("checkbox") else "false"
    return ""


def multi_select(prop):
    if not prop or prop.get("type") != "multi_select":
        return []
    return [item.get("name", "") for item in prop.get("multi_select", []) if item.get("name")]


def number_value(prop):
    if not prop or prop.get("type") != "number":
        return 0
    return prop.get("number") or 0


def first_existing_text(props, names):
    for name in names:
        value = plain_text(props.get(name, {}))
        if value:
            return value
    return ""


def public_tags(kind, roles):
    tags = []
    if kind:
        tags.append(KIND_LABELS.get(kind, kind))
    for role in roles:
        if role and role not in tags and role != "除外語":
            tags.append(role)
    return tags


def should_include(props):
    state = plain_text(props.get("状態", {})) or "候補"
    kind = plain_text(props.get("種別", {}))
    confidence = plain_text(props.get("確度", {}))
    roles = set(multi_select(props.get("シグナル役割", {})))
    if state not in PUBLIC_STATES:
        return False
    if kind in EXCLUDED_KINDS:
        return False
    if confidence in EXCLUDED_CONFIDENCES:
        return False
    if "除外語" in roles:
        return False
    return True


def row_to_public_item(row):
    props = row.get("properties", {})
    term = plain_text(props.get("使用語", {}))
    kind = plain_text(props.get("種別", {}))
    roles = multi_select(props.get("シグナル役割", {}))
    description = first_existing_text(props, ("公開説明", "説明", "解釈", "正規語/表示名")) or term
    example = first_existing_text(props, ("公開使用例", "使用例", "例文", "用例"))
    reading = first_existing_text(props, ("読み", "よみ", "フリガナ", "ふりがな"))
    confidence = plain_text(props.get("確度", {}))
    state = plain_text(props.get("状態", {})) or "候補"

    item = {
        "term": term,
        "reading": reading,
        "description": description,
        "tags": public_tags(kind, roles),
        "category": kind,
        "category_label": KIND_LABELS.get(kind, kind or "その他"),
        "roles": roles,
        "status": state,
        "confidence": confidence,
        "source_count": number_value(props.get("証拠数", {})),
    }
    if example:
        item["example"] = example
    return item


def build_public_glossary():
    items = []
    skipped = 0
    for row in query_all_pages(DB_ID):
        props = row.get("properties", {})
        term = plain_text(props.get("使用語", {}))
        if not term:
            skipped += 1
            continue
        if not should_include(props):
            skipped += 1
            continue
        items.append(row_to_public_item(row))

    items.sort(key=lambda item: (
        KIND_ORDER.get(item["category"], 99),
        item["reading"] or item["term"],
        item["term"],
    ))
    return {
        "generated_by": "export_public_glossary.py",
        "glossary_v2_db_id": DB_ID,
        "count": len(items),
        "skipped_count": skipped,
        "items": items,
    }


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_public_supplements(path=SUPPLEMENTS):
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("items") or []


def load_song_content_notes(path=SONG_CONTENT_NOTES):
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        item.get("term"): item
        for item in payload.get("items", [])
        if item.get("term")
    }


def merge_supplements(items, supplements):
    by_key = {(item.get("term"), item.get("category")) for item in items}
    merged = list(items)
    for item in supplements:
        key = (item.get("term"), item.get("category"))
        if key not in by_key:
            merged.append(item)
            by_key.add(key)
    return merged


def youtube_song_master_rows(path=YOUTUBE_SONG_MASTER):
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for row in payload.get("songs", []):
        if not row.get("public_ready"):
            continue
        name = row.get("song_name")
        if not name:
            continue
        rows.append({
            "song_name": name,
            "classification": "YouTube曲目",
            "source_count": row.get("good_evidence_count") or row.get("evidence_count") or 1,
            "description": row.get("description") or "",
            "youtube_urls": row.get("youtube_urls") or [],
            "aliases": row.get("aliases") or [],
            "bon_usage_rank": row.get("bon_usage_rank") or "",
            "bon_usage_score": row.get("bon_usage_score") or 0,
            "song_genre": row.get("song_genre") or "",
            "song_genre_key": row.get("song_genre_key") or "",
            "genre_confidence": row.get("genre_confidence") or "",
            "genre_basis": row.get("genre_basis") or "",
            "genre_review_status": row.get("genre_review_status") or "",
        })
    return rows


def song_master_rows(path=SONG_MASTER_REGISTRATION):
    youtube_rows = youtube_song_master_rows()
    if youtube_rows:
        return youtube_rows
    if NOTION_TOKEN and SONG_DB_ID:
        rows = []
        for row in query_all_pages(SONG_DB_ID):
            props = row.get("properties", {})
            name = plain_text(props.get("曲名", {}))
            state = plain_text(props.get("状態", {})) or "候補"
            classification = plain_text(props.get("分類", {}))
            if not name or state == "無効" or classification == "ジャンル総称":
                continue
            rows.append({
                "song_name": name,
                "classification": classification,
                "source_count": number_value(props.get("証拠数", {})) or 1,
            })
        return rows
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("created", [])


def song_public_description(name, row):
    description = (row.get("description") or "").strip()
    if description and description not in GENERIC_SONG_DESCRIPTIONS:
        return description

    rank = row.get("bon_usage_rank") or ""
    genre = row.get("song_genre") or ""
    basis = row.get("genre_basis") or ""
    source_count = int(row.get("source_count") or 0)

    if rank == "定番":
        lead = "多くの盆踊り会場で確認されている定番曲です。"
    elif rank == "よく使われる":
        lead = "複数の盆踊り会場でよく使われる曲として確認されています。"
    elif rank == "ときどき使われる":
        lead = "会場によって曲目に入ることがある曲です。"
    elif rank == "地域・会場固有":
        lead = "特定の地域や会場で使われることが多い曲として扱っています。"
    elif rank == "要確認":
        lead = "盆踊り曲目として確認されていますが、利用頻度はまだ確認中です。"
    else:
        lead = "盆踊り会場の曲目として確認されている曲です。"

    details = []
    if genre and genre != "要調査":
        details.append(f"このサイトでは「{genre}」系として仮分類しています。")
    elif genre == "要調査":
        details.append("曲のジャンルはまだ要調査です。")
    if basis and basis != "曲名だけでは判定不能":
        details.append(f"分類メモ: {basis}。")
    if source_count:
        details.append(f"確認根拠は {source_count} 件あります。")
    return " ".join([lead, *details])


def load_song_master_items(path=SONG_MASTER_REGISTRATION):
    rows = song_master_rows(path)
    song_names = sorted({row.get("song_name") for row in rows if row.get("song_name")})
    by_name = {row.get("song_name"): row for row in rows if row.get("song_name")}
    content_notes = load_song_content_notes()
    items = []
    for name in song_names:
        note = content_notes.get(name, {})
        item = {
            "term": name,
            "reading": "",
            "description": song_public_description(name, by_name.get(name, {})),
            "tags": ["曲名・踊り名"],
            "category": "曲名",
            "category_label": "曲名・踊り名",
            "roles": [],
            "status": "有効",
            "confidence": by_name.get(name, {}).get("classification") or "曲DB",
            "source_count": by_name.get(name, {}).get("source_count") or 1,
            "youtube_urls": by_name.get(name, {}).get("youtube_urls") or [],
            "aliases": by_name.get(name, {}).get("aliases") or [],
            "bon_usage_rank": by_name.get(name, {}).get("bon_usage_rank") or "",
            "bon_usage_score": by_name.get(name, {}).get("bon_usage_score") or 0,
            "song_genre": by_name.get(name, {}).get("song_genre") or "",
            "song_genre_key": by_name.get(name, {}).get("song_genre_key") or "",
            "genre_confidence": by_name.get(name, {}).get("genre_confidence") or "",
            "genre_basis": by_name.get(name, {}).get("genre_basis") or "",
            "genre_review_status": by_name.get(name, {}).get("genre_review_status") or "",
        }
        if note.get("content_note"):
            item["content_note"] = note["content_note"]
        if note.get("content_note_status"):
            item["content_note_status"] = note["content_note_status"]
        items.append(item)
    return items


def replace_song_glossary_items(items, song_items):
    if not song_items:
        return items
    readings_by_term = {
        item.get("term"): item.get("reading")
        for item in items
        if item.get("term") and item.get("reading")
    }
    merged_song_items = []
    for item in song_items:
        merged = dict(item)
        merged["reading"] = merged.get("reading") or readings_by_term.get(merged.get("term"), "")
        merged_song_items.append(merged)
    return [
        item
        for item in items
        if item.get("category") != "曲名" and item.get("category_label") != "曲名・踊り名"
    ] + merged_song_items


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output JSON path")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    out_path = Path(args.out).expanduser()
    try:
        payload = build_public_glossary()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"用語集公開JSON export失敗 (HTTP {exc.code}): {body}") from exc

    supplements = load_public_supplements()
    if supplements:
        payload["items"] = merge_supplements(payload["items"], supplements)
    song_items = load_song_master_items()
    if song_items:
        payload["items"] = replace_song_glossary_items(payload["items"], song_items)
        payload["song_master_count"] = len(song_items)
    if supplements or song_items:
        payload["items"].sort(key=lambda item: (
            KIND_ORDER.get(item["category"], 99),
            item["reading"] or item["term"],
            item["term"],
        ))
        payload["count"] = len(payload["items"])
        if supplements:
            payload["supplement_count"] = len(supplements)
    write_json(out_path, payload)
    print(
        f"用語集公開JSON export完了: {payload['count']} 件 "
        f"(skipped={payload['skipped_count']}) -> {out_path}"
    )


if __name__ == "__main__":
    main()
