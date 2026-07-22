"""Create a Notion strategy note for the Bonsuke Kindle book idea."""

import argparse
import json
import os
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from notion_support.notion_config import load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")
CURRENT_LOCATION = Path("data/notion_current_location.json")
OUT = Path("data/notion_bonsuke_kindle_strategy.json")


def rich_text(text, href=None):
    text_obj = {"content": str(text or "")[:2000]}
    if href:
        text_obj["link"] = {"url": href}
    return [{"type": "text", "text": text_obj}]


def block(block_type, key, text, href=None):
    return {"object": "block", "type": block_type, block_type: {key: rich_text(text, href)}}


def paragraph(text, href=None):
    return block("paragraph", "rich_text", text, href)


def heading(level, text):
    key = f"heading_{level}"
    return block(key, "rich_text", text)


def bullet(text, href=None):
    return block("bulleted_list_item", "rich_text", text, href)


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


def create_page(parent_page_id, title):
    return notion_request(
        "POST",
        "/pages",
        {
            "parent": {"page_id": parent_page_id},
            "properties": {
                "title": {
                    "title": [{"type": "text", "text": {"content": title}}],
                }
            },
        },
    )


def append_blocks(page_id, blocks):
    for idx in range(0, len(blocks), 90):
        notion_request("PATCH", f"/blocks/{page_id}/children", {"children": blocks[idx:idx + 90]})


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


def page_blocks():
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return [
        paragraph(f"作成: {now} / 署名: おと（Codex）。内田さん外出中の検討メモ。"),
        heading(2, "結論"),
        bullet("250円Kindleで進める。100円よりも、Amazon.co.jpの70%ロイヤリティ条件に乗せやすく、価格も支援・実践メモとして自然。"),
        bullet("ただし本の主題は「盆踊りの収益化」ではない。主題は、AIエージェントを使って地域情報サイトを具体的に作った実例。"),
        bullet("イベント情報そのものは公共性の高い無料資産として扱い、有料化するのは調査手法・設計思想・AI運用・制作記録に限定する。"),
        heading(2, "一番の価値"),
        bullet("CodexやClaude Codeを使い、非エンジニア寄りの個人が、実用的な地域情報サイトを作っていく過程を具体的に示せること。"),
        bullet("AI活用本は多いが、実サービスを題材に、情報収集、データ設計、Notion連携、公開サイト、レビュー運用まで見せる本は差別化しやすい。"),
        bullet("盆助は題材として強い。地域文化、公共性、情報の散らばり、AIの得意不得意、人間レビューの必要性が一つの実例にまとまっている。"),
        heading(2, "想定読者"),
        bullet("地域イベント、商店街、文化活動、同人活動、趣味コミュニティなどの情報サイトを作りたい人。"),
        bullet("AIで何か作りたいが、架空のサンプルではなく、実際の運用例を見たい人。"),
        bullet("Notion、GitHub、Codex、Claude Code、MCP、APIなどの名前は知っているが、組み合わせ方が見えていない人。"),
        bullet("プログラミング専業ではないが、AIエージェントと一緒なら小さなWebサービスを作れるか知りたい人。"),
        heading(2, "競合に埋もれないか"),
        bullet("盆踊り本として見ると、歴史・民俗・踊り方・写真集が競合になる。ただし本書はそこでは勝負しない。"),
        bullet("AI活用本として見ると、ChatGPT入門、Notion活用、ノーコード本が競合になる。ただし多くは一般論やツール紹介で、実サービス運用の泥臭さが薄い。"),
        bullet("本書の独自性は「盆助という実例」「地域文化情報」「AIエージェントとの協働ログ」「公開サイトまで作る具体性」の4点。"),
        bullet("検索で埋もれないため、タイトルに『盆助』だけでなく『AIエージェント』『地域情報サイト』『Codex / Claude Code』の語を入れる。"),
        heading(2, "タイトル案"),
        bullet("第1候補: 盆助のつくり方: CodexとClaude Codeで地域情報サイトを作る"),
        bullet("第2候補: AIエージェントで地域情報サイトを作る: 盆助開発記録"),
        bullet("第3候補: 250円で読む盆助開発記: 盆踊り情報サイトをAIと作る方法"),
        heading(2, "価格と販売方針"),
        bullet("基本価格は250円。支援しやすく、安すぎて価値が伝わらない問題も避けられる。"),
        bullet("Amazon.co.jpのKDP価格条件では、35%ロイヤリティは99円から、70%ロイヤリティは250円から1250円まで。"),
        bullet("70%ロイヤリティでは、税と配信コストを差し引いた上で計算される。画像を重くしすぎると配信コストが増えるので、本文中心・軽量画像がよい。"),
        bullet("Kindle Unlimited/KDP Selectは検討余地あり。ただし独占条件や他媒体展開との相性を出版直前に確認する。"),
        heading(2, "他の方法"),
        bullet("Kindle単体: 信用と買いやすさが強い。最初の入口として第一候補。"),
        bullet("note有料記事: 更新しやすいが、Kindleほど本として残りにくい。補足・更新履歴向き。"),
        bullet("Zenn Book: 技術読者には届きやすいが、地域活動・非エンジニア読者には少し寄りすぎる。技術編の別冊に向く。"),
        bullet("BOOTH/PDF販売: テンプレートや付録ファイルを売りやすい。Kindle後の拡張に向く。"),
        bullet("無料Web連載 + Kindleまとめ: 最も倫理的に説明しやすい。無料で広げ、まとまった版を250円で売る。"),
        bullet("講座・相談・導入支援: 本が名刺になる。収益性は高いが、まず本で思想と実績を見せてからが自然。"),
        heading(2, "内容案"),
        bullet("0. はじめに: 盆踊りを売るのではなく、情報を届ける技術を共有する。"),
        bullet("1. なぜ盆踊り情報サイトを作ろうと思ったか。情報が散らばる、公式発表が遅い、地域ごとに形式が違う。"),
        bullet("2. 盆助の全体像。Notion、ローカルDB、公開JSON、静的サイト、GitHub、AIエージェントの役割分担。"),
        bullet("3. CodexとClaude Codeの使い分け。設計相談、実装、レビュー、調査、Notion連携、作業ログ。"),
        bullet("4. AIに任せてよい作業、任せてはいけない作業。日付確定、主催者名、権利・引用・公開判断は人間レビューを残す。"),
        bullet("5. 情報収集の実際。公式サイト、自治体ページ、X、YouTube、過去実績、信頼度の見方。"),
        bullet("6. データ設計。イベント、会場、開催年、曲目、根拠URL、推定と確定の分離。"),
        bullet("7. 公開サイト化。JSON出力、検索・地図・日程表示、誤情報を減らす表示文言。"),
        bullet("8. 運用の現実。毎日更新、作業ログ、失敗、デプロイをまとめる、外部サービス費用。"),
        bullet("9. ほかの地域・分野に応用する方法。祭り、朝市、ライブ、講座、地域掲示板。"),
        bullet("10. 付録。実際のプロンプト例、AGENTS.mdの考え方、Notion項目例、公開前チェックリスト。"),
        heading(2, "制作手順"),
        todo("本の約束を1文で決める: 「AIエージェントで地域情報サイトを作る実例を、盆助で具体的に見せる」。", True),
        todo("タイトルを1つに絞る。現時点の第一候補は「盆助のつくり方: CodexとClaude Codeで地域情報サイトを作る」。"),
        todo("章立てを10章程度に固定し、各章1000〜2000字の短い実践メモとして書く。"),
        todo("実際に使ったプロンプト、Notion項目、データ設計、公開サイトのスクリーンショット候補を集める。"),
        todo("外部サービス名・画面・価格は変わるため、本文では日付つきで書き、最新情報は更新ページに逃がす。"),
        todo("Kindle原稿をMarkdownまたはGoogle Docsで作り、Kindle Previewerで崩れを確認する。"),
        todo("表紙は『盆踊り感』よりも『地域情報サイト制作』が伝わるデザインにする。"),
        todo("KDPで電子書籍を作成し、価格250円、70%ロイヤリティを選べる条件を最終確認する。"),
        todo("出版後、盆助サイト・X・note・Notion公開メモから導線を張る。"),
        heading(2, "注意点"),
        bullet("イベント情報を囲い込まない。公開情報、公式リンク、地域への敬意を無料側に残す。"),
        bullet("主催者・踊り手・撮影者の権利や気持ちに配慮する。写真や動画の転載ではなく、原則リンク・引用範囲・説明に留める。"),
        bullet("AIで作った内容は、日付・会場・主催者・価格・開催可否などを必ず人間が確認する。"),
        bullet("Codex/Claude Codeの画面や機能は変わるため、操作マニュアルに寄せすぎず、考え方と判断プロセスを中心にする。"),
        heading(2, "参照"),
        bullet("KDP eBook List Price Requirements: Amazon.co.jpは70%ロイヤリティが250円〜1250円。", "https://kdp.amazon.com/en_US/help/topic/G200634560"),
        bullet("KDP Digital Book Pricing Page: 70%ロイヤリティは税・配信コスト差し引き後に計算。", "https://kdp.amazon.com/en_US/help/topic/G200634500"),
        bullet("OpenAI Codex manual: Codexはコード作成、理解、レビュー、デバッグ、自動化に使える coding agent。", "https://developers.openai.com/codex/codex-manual.md"),
        bullet("Claude Code docs: Claude Codeはコードベースを読み、ファイル編集・コマンド実行・開発ツール連携を行う agentic coding tool。", "https://code.claude.com/docs/en/overview"),
        paragraph("次に内田さんが戻ったら、タイトル決定、目次確定、最初の章の試し書きに進む。"),
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--current-location-json", default=str(CURRENT_LOCATION))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    current = json.loads(Path(args.current_location_json).read_text(encoding="utf-8"))
    parent_page_id = current["page_id"]
    title = "盆助Kindle本 250円戦略メモ"
    if args.dry_run:
        print(f"Would create Notion page under {parent_page_id}: {title}")
        return

    page = create_page(parent_page_id, title)
    append_blocks(page["id"], page_blocks())
    output = {
        "generated_by": "create_bonsuke_kindle_strategy_notion.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "title": title,
        "page_id": page["id"],
        "url": page.get("url") or "",
        "parent_page_id": parent_page_id,
        "parent_url": current.get("url") or "",
    }
    atomic_write_json(args.out, output)
    print(f"Notionに盆助Kindle戦略メモを作成しました: {page.get('url') or page['id']}")


if __name__ == "__main__":
    main()
