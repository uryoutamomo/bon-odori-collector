"""Append opening hook guidance to the Bonsuke Kindle strategy Notion page."""

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
        heading(2, "最初のつかみ"),
        paragraph(f"追記: {now} / 署名: おと（Codex）。内田さんの追加方針: AIをフル活用して、非エンジニアが自分にもみんなにも役立つ情報サイトを作った話として始める。"),
        heading(3, "冒頭コンセプト"),
        paragraph(
            "これは、プログラミングの専門家ではない個人が、AIとの対話を何度も何度も繰り返し、"
            "ノートを育てるように情報と仕組みを育て、自分にも地域の人にも役立つ情報サイトを少しずつ作り上げた記録である。"
        ),
        paragraph(
            "最初から完成形が見えていたわけではない。AIに一度頼んで終わりでもない。"
            "問いかけ、出てきた案を読み、違和感を伝え、調べ直し、ノートに残し、また頼む。"
            "その往復の積み重ねが、盆助という情報サイトになっていった。"
        ),
        heading(3, "読者への約束"),
        bullet("この本は、AIで一発でアプリを作る魔法の話ではない。"),
        bullet("非エンジニアでも、AIとの対話、記録、確認、修正を重ねれば、役に立つ情報サイトを育てられることを示す。"),
        bullet("完成品の作り方だけでなく、迷い、失敗、確認、人間が判断すべきところまで見せる。"),
        bullet("読者が自分の地域、自分の趣味、自分の仕事の情報サイトに応用できる形にする。"),
        heading(3, "本の冒頭案"),
        paragraph(
            "盆踊りに行きたいと思っても、情報はあちこちに散らばっている。自治体のページ、町会のチラシ、Xの投稿、YouTubeの過去動画。"
            "どれが今年の情報で、どれが去年の情報なのかも分かりにくい。"
        ),
        paragraph(
            "私はプログラミングの専門家としてこの問題に取り組んだのではない。"
            "AIに相談し、CodexやClaude Codeと対話し、Notionにメモを積み上げ、少しずつ盆助を育てていった。"
            "この本は、その過程をできるだけ具体的に残すための本である。"
        ),
        heading(3, "キャッチコピー候補"),
        bullet("AIと何度も対話し、ノートを育て、地域情報サイトを作る。"),
        bullet("非エンジニアでも、AIと一緒なら情報サイトは少しずつ育てられる。"),
        bullet("一発生成ではなく、対話と記録で作る新しい時代の開発手法。"),
        bullet("盆助は、AIと人間が一緒に育てた地域情報サイトです。"),
        heading(3, "漫画での見せ方"),
        bullet("主人公が『自分にもみんなにも役立つ情報サイトを作りたいが、何から始めればよいか分からない』ところから始める。"),
        bullet("AI相棒は万能ではなく、質問、提案、整理、実装補助をする存在として描く。"),
        bullet("ノートが少しずつ増え、散らばった情報が整理され、最後にサイトとして形になる流れを視覚化する。"),
        bullet("『完成品』よりも『育っていく過程』を漫画で見せる。"),
        heading(3, "タイトルへの反映案"),
        bullet("盆助のつくり方: AIとノートを育てて地域情報サイトを作る"),
        bullet("AIと育てる情報サイト: 非エンジニアが盆助を作るまで"),
        bullet("ノートを育ててサイトを作る: CodexとClaude Codeで始める地域情報開発"),
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
        print(f"Would append opening hook note to Notion page: {page_id}")
        return
    append_blocks(page_id, note_blocks())
    print(f"Notionに最初のつかみ案を追記しました: {strategy['url']}")


if __name__ == "__main__":
    main()
