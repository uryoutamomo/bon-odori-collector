#!/usr/bin/env python3
"""Apply reviewed YouTube rows that need official confirmation."""

import argparse
import json
import os
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from manual_apply_guards import LEGACY_YOUTUBE_NOTION_CONFIRMATION, require_confirmation
from notion_support.notion_api import NotionApi, plain_text
from notion_config import EVENT_DATA_SOURCE_ID, load_local_env


REVIEW = Path("data/youtube_active_video_review.json")
OUT = Path("data/youtube_official_confirmation_apply_result.json")
OUT_MD = Path("data/youtube_official_confirmation_apply_result.md")

MARUNOUCHI_URL = "https://www.marunouchi.com/pickup/event/6763/"
MARUNOUCHI_EVENT_NAME = "丸の内de盆踊り"


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=".tmp-", suffix=".json", delete=False
    ) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        tmp_name = handle.name
    Path(tmp_name).replace(path)


def atomic_write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=".tmp-", suffix=".md", delete=False
    ) as handle:
        handle.write(text)
        tmp_name = handle.name
    Path(tmp_name).replace(path)


def rich_text_prop(text):
    if not text:
        return {"rich_text": []}
    chunks = [text[i:i + 1900] for i in range(0, len(text), 1900)]
    return {"rich_text": [{"text": {"content": chunk}} for chunk in chunks[:100]]}


def query_event(api, name):
    rows = api.query_data_source(
        EVENT_DATA_SOURCE_ID,
        {"filter": {"property": "イベント名", "title": {"equals": name}}, "page_size": 5},
    )
    return rows[0] if rows else None


def current_detail(page):
    return plain_text((page.get("properties") or {}).get("開催パターン詳細"))


def needs_rows(review):
    return [row for row in review.get("rows") or [] if row.get("action") == "needs_official_confirmation"]


def first_official(row):
    for url in row.get("official_urls") or []:
        if "instagram.com" in url or "ebay.com" in url or "goo.gl/maps" in url or "maps.app.goo.gl" in url:
            continue
        return url
    return (row.get("official_urls") or [""])[0] if row.get("official_urls") else ""


def classify_row(row):
    title = row.get("title") or ""
    urls = row.get("official_urls") or []
    if MARUNOUCHI_URL in urls:
        return {
            "decision": "append_existing_event",
            "target_event_name": MARUNOUCHI_EVENT_NAME,
            "reason": "Marunouchi.com公式ページで丸の内夏祭り2025内の丸の内de盆踊りを確認済み",
        }
    if "shibuyadogenzaka.com" in " ".join(urls):
        return {
            "decision": "hold",
            "target_event_name": "渋谷盆踊り2025",
            "reason": "公式URL候補はあるが本文取得不可。YouTube単独登録はしない",
        }
    if "おはら祭" in title:
        return {
            "decision": "hold",
            "target_event_name": "渋谷・鹿児島おはら祭",
            "reason": "音頭を含む踊りイベントだが、盆踊り本DBの定番盆踊りイベントとしては要確認",
        }
    if "Pokémon GO Fest" in title or "ピカチュウ音頭" in title:
        return {
            "decision": "hold",
            "target_event_name": "Pokémon GO Fest TOKYO 2026",
            "reason": "ブランドイベント内のステージ/キャラクター音頭。盆踊り本DB登録対象としては要確認",
        }
    return {
        "decision": "hold",
        "target_event_name": "",
        "reason": "未分類",
    }


def grouped_ready(rows):
    grouped = defaultdict(list)
    held = []
    for row in rows:
        classification = classify_row(row)
        item = {
            "video_url": row.get("video_url") or "",
            "title": row.get("title") or "",
            "channel_title": row.get("channel_title") or "",
            "published_at": row.get("published_at") or "",
            "detected_event_date": row.get("detected_event_date") or "",
            "official_url": first_official(row),
            **classification,
        }
        if item["decision"] == "append_existing_event":
            grouped[item["target_event_name"]].append(item)
        else:
            held.append(item)
    return grouped, held


def evidence_note(event_name, rows):
    dates = sorted({row.get("detected_event_date") for row in rows if row.get("detected_event_date")})
    channels = []
    for row in rows:
        if row.get("channel_title") and row["channel_title"] not in channels:
            channels.append(row["channel_title"])
    lines = [
        "[youtube_evidence] YouTube公式確認済み追加証拠",
        f"- 対象イベント: {event_name}",
        f"- 検出日付: {', '.join(dates) if dates else '未抽出'}",
        f"- 動画数: {len(rows)}",
    ]
    if channels:
        lines.append(f"- チャンネル: {', '.join(channels)}")
    for row in rows[:6]:
        lines.append(f"- 動画: {row['video_url']} / {row['channel_title']} / {row['title']}")
    lines.append(f"- 公式確認URL: {MARUNOUCHI_URL}")
    return "\n".join(lines)


def merged_detail(existing, note):
    if not note:
        return existing or ""
    if note in (existing or ""):
        return existing or ""
    if existing:
        return existing.rstrip() + "\n\n" + note
    return note


def build_updates(api, review):
    grouped, held = grouped_ready(needs_rows(review))
    updates = []
    for event_name, rows in sorted(grouped.items()):
        page = query_event(api, event_name)
        result = {
            "target_event_name": event_name,
            "row_count": len(rows),
            "video_count": len(rows),
            "apply_status": "blocked" if not page else "ready",
            "reason": "" if page else "target event not found",
            "videos": rows,
        }
        if not page:
            updates.append(result)
            continue
        old_detail = current_detail(page)
        urls = [row["video_url"] for row in rows if row.get("video_url")]
        duplicate_urls = [url for url in urls if url in old_detail]
        note = evidence_note(event_name, rows)
        all_urls_duplicate = bool(urls) and len(duplicate_urls) == len(urls)
        new_detail = old_detail if all_urls_duplicate else merged_detail(old_detail, note)
        result.update({
            "target_page_id": page.get("id") or "",
            "target_page_url": page.get("url") or "",
            "duplicate_url_count": len(duplicate_urls),
            "changed": new_detail != old_detail,
            "note": note,
            "properties": {"開催パターン詳細": rich_text_prop(new_detail)},
        })
        updates.append(result)
    return updates, held


def render_markdown(output):
    lines = [
        "# YouTube official confirmation apply結果",
        "",
        f"- 生成: {output['generated_at']}",
        f"- mode: {output['mode']}",
        f"- ready: {output['ready_count']}",
        f"- changed: {output['changed_count']}",
        f"- applied: {output['applied_count']}",
        f"- held: {output['held_count']}",
        "",
        "| status | event | videos | changed | duplicate_urls |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in output["updates"]:
        lines.append(
            f"| {row.get('apply_status')} | {row.get('target_event_name')} | {row.get('video_count')} | "
            f"{row.get('changed', False)} | {row.get('duplicate_url_count', 0)} |"
        )
    if output["held"]:
        lines.extend(["", "## held", ""])
        for row in output["held"]:
            lines.append(f"- {row['target_event_name'] or row['title']}: {row['reason']} ({row['video_url']})")
    for row in output["updates"]:
        if row.get("note"):
            lines.extend(["", f"## {row['target_event_name']}", "", "```text", row["note"], "```"])
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", type=Path, default=REVIEW)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--markdown-out", type=Path, default=OUT_MD)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        require_confirmation(
            args.apply,
            args.confirm,
            LEGACY_YOUTUBE_NOTION_CONFIRMATION,
            "legacy YouTube official-confirmation Notion update",
        )
    except ValueError as exc:
        parser.error(str(exc))

    load_local_env()
    api = NotionApi(os.environ.get("NOTION_API_TOKEN"))
    review = load_json(args.review, {})
    updates, held = build_updates(api, review)
    applied = []
    if args.apply:
        for row in updates:
            if row.get("apply_status") == "ready" and row.get("changed"):
                api.update_page(row["target_page_id"], row["properties"])
                applied.append(row["target_page_id"])
    output = {
        "generated_by": "apply_youtube_official_confirmation.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if args.apply else "dry_run",
        "apply_performed": bool(args.apply),
        "ready_count": sum(1 for row in updates if row.get("apply_status") == "ready"),
        "changed_count": sum(1 for row in updates if row.get("changed")),
        "applied_count": len(applied),
        "held_count": len(held),
        "updates": updates,
        "held": held,
    }
    atomic_write_json(args.out, output)
    atomic_write_text(args.markdown_out, render_markdown(output))
    print(
        "youtube official confirmation: "
        f"mode={output['mode']} ready={output['ready_count']} changed={output['changed_count']} "
        f"applied={output['applied_count']} held={output['held_count']} -> {args.out}"
    )


if __name__ == "__main__":
    main()
