"""Append Bonsuke manga generation workflow rules to the content-current Notion page."""

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from notion_config import load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")
TWO_TRACKS_JSON = Path("data/bonsuke_two_tracks_notion.json")


def rich_text(text):
    return [{"type": "text", "text": {"content": str(text or "")[:2000]}}]


def heading(level, text):
    key = f"heading_{level}"
    return {"object": "block", "type": key, key: {"rich_text": rich_text(text)}}


def paragraph(text):
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text(text)}}


def bullet(text):
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": rich_text(text)},
    }


def notion_request(method, path, payload=None):
    data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        NOTION_API + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def note_blocks():
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return [
        heading(2, "盆助漫画: 写真寄せ・省コスト生成ルール"),
        paragraph(f"追記: {now} / 署名: おと（Codex）。内田さん確認: 第1話の写真寄せ版v2の絵柄を今後の基準にする。"),
        heading(3, "基準絵"),
        bullet("主基準: /Users/ryotauchida/bonsuke-manga/characters/likeness-checks/2026-06-29/momo-chen-photo-likeness-check-v1.png"),
        bullet("成功例: /Users/ryotauchida/bonsuke-manga/drafts/2026-06-29-episode-01-noticeboard-chase-photo-v2/assets/"),
        bullet("第一話v2 PNG: /Users/ryotauchida/bonsuke-manga/drafts/2026-06-29-episode-01-noticeboard-chase-photo-v2/episode-01-noticeboard-chase-photo-v2.png"),
        heading(3, "運用ルール"),
        bullet("毎回すべての写真を参照しない。まず基準絵1枚を主参照にし、場面だけ差し替えて1コマずつ生成する。"),
        bullet("似なくなった時だけ、モモ写真・陳さん写真を1枚ずつ追加参照する。写真の大量投入は避ける。"),
        bullet("画像生成では文字、吹き出し、UI内の読める文字を入れない。セリフはHTML/CSSで後入れする。"),
        bullet("同じ話の中では服装を固定する。第1話v2ではモモ=青い浴衣/祭り服、陳さん=赤系浴衣を基準にする。"),
        bullet("モモは、広い額、側頭部の短い髪、丸い顔、柔らかい頬、しっかりした体格を固定する。眼鏡は常用しない。"),
        bullet("陳さんは、大人の女性、丸い頬、自然な顔幅、小さめの目、中央分けに近い暗いロングヘアを固定する。少女化・細すぎ・V字顎を避ける。"),
        heading(3, "ローカルテンプレート"),
        bullet("1コマ生成プロンプト: /Users/ryotauchida/bonsuke-manga/templates/photo-likeness-panel-prompt.md"),
        bullet("場面差し替え集: /Users/ryotauchida/bonsuke-manga/templates/scene-snippets.md"),
        bullet("写真寄せ基準メモ: /Users/ryotauchida/bonsuke-manga/characters/likeness-checks/README.md"),
        heading(3, "制作方針"),
        bullet("完成ページを一発生成しない。1コマ絵を生成し、採用コマだけ保存し、最後にHTMLで組む。"),
        bullet("これにより、API/生成コスト、確認工数、セリフ修正コストを下げながら、いろいろなシーンを漫画として展開しやすくする。"),
    ]


def append_blocks(page_id, blocks):
    for idx in range(0, len(blocks), 90):
        notion_request("PATCH", f"/blocks/{page_id}/children", {"children": blocks[idx:idx + 90]})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--two-tracks-json", default=str(TWO_TRACKS_JSON))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    two_tracks = json.loads(Path(args.two_tracks_json).read_text(encoding="utf-8"))
    content = two_tracks["content"]
    page_id = content["page_id"]
    if args.dry_run:
        print(f"Would append manga generation rule note to Notion page: {content['title']} {content['url']}")
        return

    append_blocks(page_id, note_blocks())
    print(f"Notionに漫画生成ルールを追記しました: {content['url']}")


if __name__ == "__main__":
    main()
