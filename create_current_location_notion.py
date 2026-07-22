"""Turn the current-work Notion page into the shared current-location page."""

import argparse
import json
import os
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from operation_safety.manual_apply_guards import NOTION_WORKLOG_MAINTENANCE_CONFIRMATION, require_confirmation
from notion_config import load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")
DEFAULT_PARENT_PAGE_ID = "3708be04-e762-811d-bbb7-c984b14fe452"
CURRENT_WORK = Path("data/notion_current_work_index.json")
OUT = Path("data/notion_current_location.json")


def rich_text(text, href=None):
    text_obj = {"content": str(text or "")[:2000]}
    if href:
        text_obj["link"] = {"url": href}
    return [{"type": "text", "text": text_obj}]


def notion_request(method, path, payload=None):
    data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        NOTION_API + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def heading(level, text):
    key = f"heading_{level}"
    return {"object": "block", "type": key, key: {"rich_text": rich_text(text)}}


def paragraph(text, href=None):
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text(text, href)}}


def bullet(text, href=None):
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": rich_text(text, href)},
    }


def todo(text, checked=False):
    return {
        "object": "block",
        "type": "to_do",
        "to_do": {"rich_text": rich_text(text), "checked": checked},
    }


def load_json(path):
    with Path(path).open(encoding="utf-8") as handle:
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


def block_text(block):
    btype = block.get("type")
    if btype in {"paragraph", "heading_1", "heading_2", "heading_3", "bulleted_list_item"}:
        rich = (block.get(btype) or {}).get("rich_text") or []
        return "".join(part.get("plain_text", "") for part in rich)
    if btype == "child_page":
        return (block.get("child_page") or {}).get("title") or ""
    return ""


def block_href(block):
    btype = block.get("type")
    if btype not in {"paragraph", "bulleted_list_item"}:
        return ""
    rich = (block.get(btype) or {}).get("rich_text") or []
    for part in rich:
        text = part.get("text") or {}
        text_link = text.get("link") or {}
        link = part.get("href") or text_link.get("url")
        if link:
            return link
    return ""


def children(block_id):
    rows = []
    cursor = ""
    while True:
        query = "?page_size=100"
        if cursor:
            query += "&" + urllib.parse.urlencode({"start_cursor": cursor})
        data = notion_request("GET", f"/blocks/{block_id}/children{query}")
        rows.extend(data.get("results") or [])
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor") or ""
    return rows


def update_page_title(page_id, title):
    notion_request("PATCH", f"/pages/{page_id}", {"properties": {"title": {"title": rich_text(title)}}})


def update_bullet(block_id, text, href):
    notion_request(
        "PATCH",
        f"/blocks/{block_id}",
        {"bulleted_list_item": {"rich_text": rich_text(text, href)}},
    )


def append_after(parent_page_id, after_block_id, block):
    notion_request(
        "PATCH",
        f"/blocks/{parent_page_id}/children",
        {"after": after_block_id, "children": [block]},
    )


def append_blocks(page_id, blocks):
    for idx in range(0, len(blocks), 90):
        notion_request("PATCH", f"/blocks/{page_id}/children", {"children": blocks[idx:idx + 90]})


def ensure_first_look_link(parent_page_id, url):
    in_first_look = False
    last_in_section = None
    for block in children(parent_page_id):
        btype = block.get("type")
        text = block_text(block)
        if btype in {"heading_1", "heading_2", "heading_3"} and "まず見る" in text:
            in_first_look = True
            last_in_section = block
            continue
        if in_first_look and btype in {"heading_1", "heading_2", "heading_3"}:
            break
        if not in_first_look:
            continue
        href = block_href(block)
        if "現在地" in text or "今やっていること" in text or href == url:
            update_bullet(block["id"], "現在地", url)
            return {"action": "updated", "block_id": block["id"]}
        last_in_section = block
    if not last_in_section:
        raise RuntimeError("Notion page does not contain a visible 'まず見る' section")
    append_after(parent_page_id, last_in_section["id"], bullet("現在地", url))
    return {"action": "inserted", "block_id": last_in_section["id"]}


def current_location_blocks():
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return [
        heading(2, "現在地"),
        paragraph(f"更新: {now} / 署名: おと（Codex）。内田さん・こと・おとが同じ前提を見るための正本入口。"),
        heading(3, "正本ルール"),
        bullet("このページを、盆踊りプロジェクトの現在地ダッシュボードにする。内田さん・こと・おとが同じものを見る。"),
        bullet("oto_koto MCP と .agents/messages/oto-koto.md は連絡履歴。現在地の正本ではない。重要な決定はこのページへ要約する。"),
        bullet("AGENTS.md は常設ルール。日々の作業状態、未コミット、次アクションはこのページへ置く。"),
        bullet("おと専用・こと専用の見えない長期メモリは作らない。必要な認識合わせはNotionに残す。"),
        heading(3, "2026-06-17 夜の状態"),
        bullet("bon-odori-collector: GitHub側3コミットは取り込み済み。手元は origin/main より14コミット先行。作業ツリーはclean。"),
        bullet("collectorで完了: 公式ソース判定ワークフロー追加、公式候補55件判定、巡回チェック confirmed 10件、公開再開催/曲データ更新。"),
        bullet("bon-odori-site: ことの README/LICENSE 更新は amend 後の 650ae7b が正。app.js / style.css / data/events_public.json / data/song_priors.json に未コミット差分あり。"),
        bullet("site側未コミット差分は、次回おとが中身をレビューしてから扱う。特に『第N回+1』表示の妥当性を確認する。"),
        heading(3, "次に見る順番"),
        todo("bon-odori-site の未コミット差分をレビューし、表示ロジックとデータ同期の妥当性を確認する。"),
        todo("回数表示は edition_number をそのまま出すか、翌年推定として +1 するかを内田さん・ことと決める。"),
        todo("collector の安全用stashが不要になったら削除する。"),
        todo("collector の14コミットをpushする前に、site側との整合と公開スナップショット再生成方針を確認する。"),
        heading(3, "入口"),
        bullet("Notion親ページの『まず見る』には、このページを『現在地』として置く。"),
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--parent-page-id", default=DEFAULT_PARENT_PAGE_ID)
    parser.add_argument("--current-work-json", default=str(CURRENT_WORK))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    try:
        require_confirmation(
            True,
            args.confirm,
            NOTION_WORKLOG_MAINTENANCE_CONFIRMATION,
            "current location Notion page maintenance",
        )
    except ValueError as exc:
        parser.error(str(exc))

    current_work = load_json(args.current_work_json)
    page_id = current_work["page_id"]
    url = current_work["url"]
    update_page_title(page_id, "現在地")
    first_look = ensure_first_look_link(args.parent_page_id, url)
    append_blocks(page_id, current_location_blocks())

    output = {
        "generated_by": "create_current_location_notion.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "title": "現在地",
        "page_id": page_id,
        "url": url,
        "parent_page_id": args.parent_page_id,
        "first_look": first_look,
    }
    atomic_write_json(args.out, output)
    current_work["title"] = "現在地"
    atomic_write_json(args.current_work_json, current_work)
    print(f"Notionの現在地ページを作成/更新しました: {url}")


if __name__ == "__main__":
    main()
