"""Append free web serial + Kindle compilation guidance to the Bonsuke strategy page."""

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
        heading(2, "無料Web連載 + Kindleまとめ案"),
        paragraph(f"追記: {now} / 署名: おと（Codex）。Kindle単発よりも、無料で広げてから250円の編集版にする案。"),
        heading(3, "基本方針"),
        bullet("まずWebで盆助の考え方・制作記録・AIエージェント活用を無料連載する。"),
        bullet("後から、読まれた記事を整理・加筆・漫画化・図解化して、250円のKindle版にまとめる。"),
        bullet("有料化するのは情報の囲い込みではなく、編集、体系化、漫画、チェックリスト、保存性に対する対価。"),
        bullet("盆踊り情報そのものは無料で届ける。Kindleは『地域情報サイトを作る方法』の教材にする。"),
        heading(3, "なぜ相性が良いか"),
        bullet("公共性の高い盆踊り情報を閉じずに済む。無料公開と低価格Kindleの組み合わせは倫理的に説明しやすい。"),
        bullet("Web連載で反応を見られる。読まれるテーマ、わかりにくい箇所、刺さる表現を確認してから本にできる。"),
        bullet("Kindle版の価値を『限定情報』ではなく『読みやすく編集された保存版』にできる。"),
        bullet("漫画入りKindleとの相性が良い。Webでは文章中心、本では漫画導入と図解を足すことで別価値を作れる。"),
        bullet("出版後もWeb記事が販売導線になる。検索、SNS、盆助サイトからKindleへ自然に送れる。"),
        heading(3, "無料版とKindle版の差"),
        bullet("無料Web版: 開発日記、考え方の断片、途中経過、失敗談、個別テーマ記事。"),
        bullet("Kindle版: 章立てを整理した保存版、漫画導入、図解、実践チェックリスト、プロンプト例、自分の地域で真似する手順。"),
        bullet("無料Web版は『現場から出てきた記録』、Kindle版は『読者が最短で全体像を掴むための編集版』と位置づける。"),
        heading(3, "販売時の説明文案"),
        bullet("この本は、盆踊り情報そのものを売る本ではありません。"),
        bullet("無料で公開している盆助の制作記録をもとに、AIエージェントで地域情報サイトを作る方法を、漫画・図解・チェックリストつきで読みやすく再編集した保存版です。"),
        bullet("Codex、Claude Code、Notion、GitHub、公開サイト運用を、架空のサンプルではなく実例で知りたい人向けです。"),
        heading(3, "連載候補"),
        bullet("01: なぜ盆助を作ろうと思ったか。盆踊り情報が散らばる問題。"),
        bullet("02: 盆踊り情報を売り物にしない理由。無料公開と有料ノウハウの線引き。"),
        bullet("03: AIエージェントで地域情報サイトを作るとは何か。"),
        bullet("04: CodexとClaude Codeをどう使い分けたか。"),
        bullet("05: Notionを情報管理の中心にした理由。"),
        bullet("06: イベント情報の確定と推定を分ける。"),
        bullet("07: AIに任せてはいけない確認作業。"),
        bullet("08: 公開サイトにするまでの流れ。JSON、GitHub、静的サイト。"),
        bullet("09: 失敗したこと、やり直したこと。"),
        bullet("10: ほかの地域・趣味サイトに応用する方法。"),
        heading(3, "媒体候補"),
        bullet("盆助サイト内の開発記録: 盆助との一体感が強く、検索導線も育てられる。"),
        bullet("note: 非エンジニア読者に届きやすく、SNS拡散もしやすい。"),
        bullet("Zenn: Codex / Claude Code / Notion / GitHub など技術寄りの記事に向く。"),
        bullet("個人ブログ: 長期的な資産になりやすい。Kindle出版後の導線も自由に作れる。"),
        bullet("おすすめは、最初はnoteまたは盆助サイトで3〜5本公開し、技術寄りの回だけZennにも展開する形。"),
        heading(3, "実行手順"),
        todo("最初の3本の連載テーマを決める。"),
        todo("各記事の最後に、将来のKindle版へつながる一文を入れる。例: この記事群は後日、漫画とチェックリストを加えてKindle版にまとめる予定です。"),
        todo("3〜5本公開して、読まれたテーマ・反応・質問を集める。"),
        todo("Kindle用に章順を組み替え、漫画導入、図解、チェックリストを足す。"),
        todo("Kindle出版後、各無料記事の末尾にKindle版への導線を追加する。"),
        heading(3, "注意点"),
        bullet("Web記事をそのまま束ねるだけだと有料版の価値が弱い。Kindle版では編集、漫画、図解、チェックリストを必ず足す。"),
        bullet("Webで出しすぎることを恐れすぎない。今回の価値は秘密情報ではなく、実例を読みやすくまとめる編集価値。"),
        bullet("外部サービスの画面や仕様は変わるため、Web連載では更新しやすい情報、Kindleでは考え方と判断プロセスを中心にする。"),
        bullet("KDP Selectを使う場合、他媒体で同じ内容を公開できるかなど独占条件の確認が必要。無料連載を続けるなら、出版前に条件確認する。"),
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
        print(f"Would append web serial note to Notion page: {page_id}")
        return
    append_blocks(page_id, note_blocks())
    print(f"Notionに無料Web連載 + Kindleまとめ案を追記しました: {strategy['url']}")


if __name__ == "__main__":
    main()
