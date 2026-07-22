"""Create separated Notion track pages for Bonsuke development and content."""

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
KINDLE_STRATEGY = Path("data/bonsuke_kindle_strategy_notion.json")
OUT = Path("data/bonsuke_two_tracks_notion.json")


PROJECT_ROOT = Path("/Users/ryotauchida/bon-odori-collector")
SITE_ROOT = Path("/Users/ryotauchida/bon-odori-site")
MANGA_ROOT = Path("/Users/ryotauchida/bonsuke-manga")
CHARACTER_ROOT = MANGA_ROOT / "characters"
REFERENCE_ROOT = MANGA_ROOT / "assets/references/from-bon-odori-collector"
CHARACTER_BIBLE = CHARACTER_ROOT / "canon/character-bible.md"
MASCOT_IMAGE = REFERENCE_ROOT / "originals/bonsuke-mascot-lantern-original.png"


def rich_text(text, href=None):
    text_obj = {"content": str(text or "")[:2000]}
    if href:
        text_obj["link"] = {"url": href}
    return [{"type": "text", "text": text_obj}]


def paragraph(text, href=None):
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": rich_text(text, href)},
    }


def heading(level, text):
    key = f"heading_{level}"
    return {"object": "block", "type": key, key: {"rich_text": rich_text(text)}}


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


def load_json(path, default):
    if not Path(path).exists():
        return default
    return json.loads(Path(path).read_text(encoding="utf-8"))


def atomic_write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=".tmp-",
        suffix=".json",
        delete=False,
    ) as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        tmp_name = handle.name
    Path(tmp_name).replace(path)


def common_intro(track_name):
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return [
        paragraph(f"作成: {now} / 署名: おと（Codex）"),
        paragraph(f"このページは盆助プロジェクトのうち「{track_name}」だけを見る入口。別トラックの判断基準を混ぜない。"),
    ]


def development_blocks():
    return [
        *common_intro("盆助 開発本体"),
        heading(2, "目的"),
        bullet("正確で使える盆踊り情報サービスを作る。"),
        bullet("イベント、会場、曲、YouTube証拠、公開サイト、運用手順を扱う。"),
        bullet("判断基準は、正確性、根拠、今年/過去年の分離、公開して問題ないか。"),
        heading(2, "このトラックで扱うもの"),
        bullet("Notionのイベント・会場・曲・用語DB"),
        bullet("イベント情報の収集、照合、昇格、公開可否判断"),
        bullet("YouTube過去実績、曲目、動画証拠の扱い"),
        bullet("公開サイト、S3/CloudFrontまたはGitHub Actionsの公開運用"),
        bullet("RDB、JSON、エクスポート、テスト、データ品質監査"),
        heading(2, "このトラックで扱わないもの"),
        bullet("Kindle本の構成、表紙、キャラクター、漫画ネーム、販促文"),
        bullet("キャラクター画像素材の管理"),
        bullet("開発過程のストーリー化や収益化アイデア"),
        heading(2, "ローカルの主な場所"),
        bullet(str(PROJECT_ROOT)),
        bullet(str(SITE_ROOT)),
        bullet(str(PROJECT_ROOT / "data")),
        bullet(str(PROJECT_ROOT / "docs")),
        heading(2, "作業開始時の合図"),
        bullet("『今日は盆助 開発本体』"),
        bullet("『イベントDBを見たい』"),
        bullet("『公開データを直したい』"),
        bullet("『YouTube証拠を整理したい』"),
        heading(2, "次に整えること"),
        todo("既存の現在地ページから、開発本体の進行中タスクだけをこのページへ集約する。"),
        todo("公開データ、YouTube、RDB、Notion DBの入口リンクを整理する。"),
        todo("コンテンツ化トラックに置くべきメモが混ざっていたら移す。"),
    ]


def content_blocks(kindle_url):
    blocks = [
        *common_intro("盆助 開発過程コンテンツ"),
        heading(2, "目的"),
        bullet("盆助の作り方、考え方、試行錯誤をコンテンツにする。"),
        bullet("Kindle、漫画、キャラクター、開発日記、ノウハウ、収益化方針を扱う。"),
        bullet("判断基準は、面白さ、わかりやすさ、盆踊りへの敬意、手法として売れるか。"),
        heading(2, "このトラックで扱うもの"),
        bullet("Kindle本の構成、タイトル、価格、販売ページ文"),
        bullet("モモ、陳さん、おとのキャラクター設定"),
        bullet("漫画ネーム、導入マンガ、章ごとの会話パート"),
        bullet("表紙、ロゴ、キャラクター画像、販促画像"),
        bullet("開発過程のストーリー化、noteやXでの発信"),
        bullet("有料にする知見と無料で公開する情報の線引き"),
        heading(2, "このトラックで扱わないもの"),
        bullet("公開イベント情報の正本更新"),
        bullet("開催日や会場の確定判断"),
        bullet("本番公開データのデプロイ"),
        heading(2, "画像・キャラクター素材の置き場所"),
        bullet(str(MANGA_ROOT)),
        bullet(str(CHARACTER_ROOT / "canon")),
        bullet(str(CHARACTER_ROOT / "reference-sheets")),
        bullet(str(REFERENCE_ROOT)),
        bullet(str(MANGA_ROOT / "publish")),
        heading(3, "主要素材"),
        bullet(f"主役マスコット: {MASCOT_IMAGE}"),
        bullet(f"キャラクター設定書: {CHARACTER_BIBLE}"),
        bullet(f"説明マンガ: {REFERENCE_ROOT / 'originals/bonsuke-explainer-manga-5panel.png'}"),
        bullet(f"モモ素材: {REFERENCE_ROOT / 'originals/bonsuke-guide-man-yukata-original.png'}"),
        bullet(f"設定画・ポーズ集: {CHARACTER_ROOT / 'reference-sheets'}"),
        heading(2, "現在のキャラクター設定"),
        bullet("モモ: はげのおっさん。名前の由来は不明。マニアックでこだわりがある。非エンジニアだがITに詳しい。盆踊り2年生の新入り。"),
        bullet("陳さん: ITは疎いが営業職らしく行動的。天然ボケ。盆踊り2年目だが、盆踊り情報の収集能力は半端ない。"),
        bullet("おと: 頼れるAI。無茶振りにも耐え続ける。優しく、とても賢い。モモと陳さんの混沌を整理する。"),
        heading(2, "関連Notion"),
    ]
    if kindle_url:
        blocks.append(bullet("盆助 Kindle 250円出版戦略メモ", kindle_url))
    else:
        blocks.append(bullet("盆助 Kindle 250円出版戦略メモ: data/bonsuke_kindle_strategy_notion.json を参照"))
    blocks.extend(
        [
            heading(2, "作業開始時の合図"),
            bullet("『今日は盆助 コンテンツ化』"),
            bullet("『Kindle本を進めたい』"),
            bullet("『盆助キャラ素材を使って』"),
            bullet("『モモと陳さんとおとの漫画にして』"),
            heading(2, "次に整えること"),
            todo("Kindle本の章立てを、モモ・陳さん・おとの会話構成へ置き換える。"),
            todo("表紙案をcoversフォルダに作る。"),
            todo("キャラクター設定書を漫画ネーム用にさらに濃くする。"),
            todo("無料で公開する開発日記と、Kindleに入れる内容を分ける。"),
        ]
    )
    return blocks


def current_location_append_blocks(dev_url, content_url):
    return [
        heading(2, "盆助 2トラック運用"),
        paragraph("盆助プロジェクトを、開発本体と開発過程コンテンツの2トラックに分ける。作業開始時にどちらのトラックかを明示する。"),
        bullet("盆助 開発本体 現在地", dev_url),
        bullet("盆助 開発過程コンテンツ 現在地", content_url),
        bullet("画像素材、キャラクター設定、Kindle本、漫画、販促は開発過程コンテンツ側に置く。"),
        bullet("イベントDB、会場、曲、YouTube証拠、公開サイト、デプロイは開発本体側に置く。"),
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--current-location-json", default=str(CURRENT_LOCATION))
    parser.add_argument("--kindle-strategy-json", default=str(KINDLE_STRATEGY))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    current = load_json(args.current_location_json, {})
    kindle = load_json(args.kindle_strategy_json, {})
    parent_page_id = current.get("page_id")
    if not parent_page_id:
        raise SystemExit("current location page_id is missing")

    if args.dry_run:
        print(f"Would create two track pages under {parent_page_id}")
        return

    dev_page = create_page(parent_page_id, "盆助 開発本体 現在地")
    append_blocks(dev_page["id"], development_blocks())

    content_page = create_page(parent_page_id, "盆助 開発過程コンテンツ 現在地")
    append_blocks(content_page["id"], content_blocks(kindle.get("url") or ""))

    append_blocks(
        parent_page_id,
        current_location_append_blocks(dev_page.get("url") or "", content_page.get("url") or ""),
    )

    output = {
        "generated_by": Path(__file__).name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "parent_page_id": parent_page_id,
        "parent_url": current.get("url") or "",
        "development": {
            "title": "盆助 開発本体 現在地",
            "page_id": dev_page["id"],
            "url": dev_page.get("url") or "",
        },
        "content": {
            "title": "盆助 開発過程コンテンツ 現在地",
            "page_id": content_page["id"],
            "url": content_page.get("url") or "",
        },
        "kindle_strategy_url": kindle.get("url") or "",
        "manga_root": str(MANGA_ROOT),
        "character_root": str(CHARACTER_ROOT),
        "reference_root": str(REFERENCE_ROOT),
        "character_bible": str(CHARACTER_BIBLE),
        "mascot_image": str(MASCOT_IMAGE),
    }
    atomic_write_json(Path(args.out), output)
    print(f"開発本体: {output['development']['url']}")
    print(f"開発過程コンテンツ: {output['content']['url']}")


if __name__ == "__main__":
    main()
