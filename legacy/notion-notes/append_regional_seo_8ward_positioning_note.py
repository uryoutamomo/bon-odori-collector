"""Append 8-ward SEO positioning to the regional SEO Notion plan."""

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
PLAN_JSON = Path("data/notion_regional_seo_illustrated_list_plan.json")
OUT = Path("data/notion_regional_seo_8ward_positioning_append.json")


def rich_text(text, href=None):
    text_obj = {"content": str(text or "")[:2000]}
    if href:
        text_obj["link"] = {"url": href}
    return [{"type": "text", "text": text_obj}]


def block(block_type, key, text, href=None):
    return {
        "object": "block",
        "type": block_type,
        block_type: {key: rich_text(text, href)},
    }


def paragraph(text, href=None):
    return block("paragraph", "rich_text", text, href)


def heading(level, text):
    key = f"heading_{level}"
    return block(key, "rich_text", text)


def bullet(text, href=None):
    return block("bulleted_list_item", "rich_text", text, href)


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


def append_blocks(page_id, blocks):
    for idx in range(0, len(blocks), 90):
        notion_request(
            "PATCH",
            f"/blocks/{page_id}/children",
            {"children": blocks[idx:idx + 90]},
        )


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


def page_blocks():
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return [
        heading(2, "8区展開のSEOポジショニング"),
        paragraph(f"追記: {now} / 署名: おと（Codex）。内田さん提示の8区整理を、制作優先度とページ設計へ反映。"),
        bullet("方針: 中央区・墨田区・台東区・品川区を第1波、渋谷区・新宿区・豊島区・千代田区を第2波にする。第1波でページ型とイラスト型を固め、第2波で横展開する。"),
        bullet("中央区: SEO上の役割=都心・日本橋・築地・月島系 / 切り口=老舗と町会の盆踊り。都心の有名地名で入口を作り、浜町・築地・日本橋など地域行事へつなぐ。"),
        bullet("墨田区: SEO上の役割=下町・スカイツリー・錦糸町 / 切り口=下町らしい盆踊り。観光地名だけでなく、奉納踊り・町会・河内音頭の濃さを前面に出す。"),
        bullet("台東区: SEO上の役割=浅草・上野・祭り文化 / 切り口=観光客も入りやすい盆踊り。上野公園や浅草の検索需要を受けつつ、寺・町会・下町行事へ案内する。"),
        bullet("品川区: SEO上の役割=住宅地・商店街・湾岸 / 切り口=地元密着の盆踊り。区民まつり、学校、商店街、神社、運河沿いを生活圏ごとに見せる。"),
        bullet("渋谷区: SEO上の役割=若者・観光・代々木・恵比寿 / 切り口=初めてでも行きやすい都心の盆踊り。盆踊り未経験者向けの安心導線を強める。"),
        bullet("新宿区: SEO上の役割=繁華街・神楽坂・四谷・落合 / 切り口=都心と住宅地が混ざる盆踊り。新宿の派手な印象と、地域の町会行事のギャップを見せる。"),
        bullet("豊島区: SEO上の役割=池袋・大塚・巣鴨・雑司が谷 / 切り口=駅近・商店街・地域色のある盆踊り。アクセスの良さと商店街感を出す。"),
        bullet("千代田区: SEO上の役割=皇居・神田・麹町・飯田橋 / 切り口=都心ど真ん中の意外な盆踊り。検索者の『千代田区にも盆踊りあるの？』に答えるページにする。"),
        heading(3, "優先順位"),
        bullet("第1優先: 中央区、台東区。築地本願寺・上野・浅草など検索入口が強く、観光客にも説明しやすい。"),
        bullet("第2優先: 墨田区、品川区。イベントの地域色が強く、盆助らしい独自性を出しやすい。"),
        bullet("第3優先: 渋谷区、新宿区、豊島区、千代田区。第1波の型が固まった後、都心SEOの面を広げる。"),
        heading(3, "ページ量産時の注意"),
        bullet("8区すべてを同じテンプレ文にしない。区ごとに『誰に向けるか』を変える。中央区=都心回遊、墨田区=下町濃度、台東区=観光客導入、品川区=地元密着。"),
        bullet("ページ上部は楽しく、イベントカードは正確に。開催日、公式リンク、未確認表示は既存の公開ステータスを優先する。"),
        bullet("イラストは区の印象を補助するためのもの。実在キャラクター、自治体ロゴ、施設ロゴ、商標に寄せない。"),
        bullet("第2波に入る前に、Search Consoleで第1波の表示回数、クリック率、クエリを見て、見出しと内部リンクを調整する。"),
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan-json", default=str(PLAN_JSON))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    plan = json.loads(Path(args.plan_json).read_text(encoding="utf-8"))
    page_id = plan["page_id"]
    if args.dry_run:
        print(f"Would append 8-ward positioning to Notion page: {plan.get('url') or page_id}")
        return

    append_blocks(page_id, page_blocks())
    output = {
        "generated_by": "append_regional_seo_8ward_positioning_note.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "page_id": page_id,
        "url": plan.get("url") or "",
    }
    atomic_write_json(args.out, output)
    print(f"Notionに8区SEOポジショニングを追記しました: {plan.get('url') or page_id}")


if __name__ == "__main__":
    main()
