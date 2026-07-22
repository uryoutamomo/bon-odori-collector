"""Append manga-format guidance to the Bonsuke Kindle strategy Notion page."""

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from notion_support.notion_config import load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")
STRATEGY_JSON = Path("data/notion_bonsuke_kindle_strategy.json")


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


def todo(text, checked=False):
    return {
        "object": "block",
        "type": "to_do",
        "to_do": {"rich_text": rich_text(text), "checked": checked},
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
        heading(2, "漫画を程よく入れる方針"),
        paragraph(f"追記: {now} / 署名: おと（Codex）。内田さんの追加方針: 漫画で入口を作り、本文で情報量を担保する。"),
        bullet("方針は「漫画だけの本」ではなく、「漫画でわかる」系の読みやすさを取り入れた実践本にする。"),
        bullet("漫画は読者の心理的ハードルを下げる役割。Codex、Claude Code、Notion、GitHub、APIなどの用語で離脱しそうな読者を、会話と場面で引き込む。"),
        bullet("情報の厚みは漫画の後の解説パートで担保する。各章は『漫画2〜4ページ + 解説4〜8ページ + チェックリスト』くらいがよい。"),
        bullet("漫画パートの主人公は、地域イベント情報をまとめたい人。AIエージェント役は相棒として登場し、魔法のように全部解決するのではなく、確認・失敗・修正を一緒に進める。"),
        bullet("盆踊りの参加者や主催者をネタ化しない。漫画で扱う笑いは、AIとの試行錯誤、情報の散らばり、作業の迷いに置く。"),
        heading(3, "章ごとの型"),
        bullet("導入漫画: 困りごとを1つ見せる。例: 盆踊りの日程がSNS、自治体ページ、チラシに分散している。"),
        bullet("実践解説: その章で使う考え方・ツール・判断基準を説明する。"),
        bullet("盆助ではこうした: 実際の盆助開発での判断、失敗、改善を短く示す。"),
        bullet("真似するなら: 読者が自分の地域・趣味・団体サイトで使えるチェックリストに落とす。"),
        heading(3, "差別化への効き方"),
        bullet("AI活用本の一般論から外れて、実例の物語として読める。"),
        bullet("技術に詳しくない読者にも入口ができる一方、解説パートで実務価値を残せる。"),
        bullet("表紙と試し読みで強い。最初の数ページに漫画を置くと、Kindleのサンプルで魅力が伝わりやすい。"),
        bullet("『盆助』という固有の題材と漫画のキャラクターが結びつくため、ただのAIノウハウ本より記憶に残りやすい。"),
        heading(3, "制作時の注意"),
        bullet("漫画の作画コストを上げすぎない。まずは各章1本の短い4コマ〜数ページ漫画で十分。"),
        bullet("漫画内の画面UIやサービス名は変わりやすいので、細かい操作画面の再現より、状況と判断を描く。"),
        bullet("『マンガでわかる』系の一般的な構成は参考にしてよいが、特定シリーズ名や装丁に寄せすぎない。"),
        bullet("KDPの70%ロイヤリティでは配信コストが効くため、漫画画像は圧縮し、重すぎるフルカラー画像を増やしすぎない。"),
        heading(3, "追加タスク"),
        todo("目次を『漫画導入 + 解説 + チェックリスト』の章構成に組み替える。"),
        todo("主人公、AI相棒、地域活動側の登場人物を決める。"),
        todo("第1章の漫画ネームを作る。テーマは『情報が散らばりすぎていて、盆踊りに行きたい人へ届かない』。"),
        todo("表紙案を、漫画キャラクター + 地域情報サイト制作が伝わる方向で考える。"),
    ]


def append_blocks(page_id, blocks):
    for idx in range(0, len(blocks), 90):
        notion_request("PATCH", f"/blocks/{page_id}/children", {"children": blocks[idx:idx + 90]})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy-json", default=str(STRATEGY_JSON))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")
    strategy = json.loads(Path(args.strategy_json).read_text(encoding="utf-8"))
    page_id = strategy["page_id"]
    if args.dry_run:
        print(f"Would append manga note to Notion page: {page_id}")
        return
    append_blocks(page_id, note_blocks())
    print(f"Notionに漫画方針を追記しました: {strategy['url']}")


if __name__ == "__main__":
    main()
