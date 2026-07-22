"""Create a Notion planning note for illustrated ward SEO pages."""

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
OUT = Path("data/notion_regional_seo_illustrated_list_plan.json")
APPLY_CONFIRMATION = "CREATE REGIONAL SEO ILLUSTRATED PLAN"


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
        paragraph(f"作成: {now} / 署名: おと（Codex）。地域別SEOページの企画骨子。"),
        heading(2, "結論"),
        bullet("中央区・墨田区・台東区・品川区の4区から始める。イベント一覧だけでなく、区ごとの土地柄をイラスト付きの短い読み物にして、検索入口と回遊入口を兼ねる。"),
        bullet("ページの主役は実用情報。イラストと面白紹介は冒頭の3〜5割に抑え、下部は日程、会場、駅、確認状況、曲傾向、公式リンクへすぐ進める構成にする。"),
        bullet("トーンは『地域をいじる』ではなく『その区らしさを少し大げさに案内する』。町会・神社・商店街への敬意を崩さない。"),
        heading(2, "ページの型"),
        bullet("URL案: /area/chuo/bon-odori/、/area/sumida/bon-odori/、/area/taito/bon-odori/、/area/shinagawa/bon-odori/。"),
        bullet("H1案: 中央区の盆踊り、墨田区の盆踊り、台東区の盆踊り、品川区の盆踊り。検索語は素直に入れる。"),
        bullet("冒頭: 区キャッチコピー、イラスト、短い導入、今年の確認済み/未確認/昨年開催の件数。"),
        bullet("中段: 地図、日程順カード、駅・エリア・開催状況フィルタ。"),
        bullet("下段: 区の楽しみ方、初心者向け注意、代表曲/雰囲気、近隣区への導線。"),
        bullet("末尾: 更新日、情報の見方、公式・主催リンクの優先方針。"),
        heading(2, "ビジュアル共通ルール"),
        bullet("各区1枚のメインイラストを置く。横長カードで、スマホでは上部に1枚だけ表示。"),
        bullet("人物キャラは使ってよいが、実在の自治体キャラ・商標・施設ロゴには寄せない。"),
        bullet("背景に区の記号を入れる。中央区=銀座/築地/浜町、墨田区=隅田川/タワー/職人、台東区=上野/浅草/縁日、品川区=旧東海道/運河/商店街。"),
        bullet("絵柄は軽い漫画調。観光ポスター風より、盆助らしい『便利だけど少し笑える案内板』にする。"),
        heading(2, "中央区"),
        bullet("キャッチコピー案: 老舗と高層ビルが、同じ輪で踊る区。"),
        bullet("編集キャラ: 銀座では背筋が伸び、築地では急にお腹が鳴り、浜町ではやぐらを見て安心する“江戸前の案内人”。"),
        bullet("見せ方: 築地本願寺、浜町公園、銀座、日本橋、人形町を『大人の都心盆踊り回遊』として扱う。高級感だけでなく、下町・市場・水辺の顔を出す。"),
        bullet("イラスト案: 扇子を持った案内人が、片手に寿司折、背後に銀座の灯りと築地本願寺風のシルエット、遠くに浜町の櫓。"),
        bullet("SEO切り口: 中央区 盆踊り、築地本願寺 盆踊り、浜町公園 盆踊り、銀座 盆踊り、日本橋 盆踊り。"),
        bullet("注意: 銀座・築地・日本橋の商業イメージだけに寄せすぎず、町会/公園/寺の地域行事として紹介する。"),
        heading(2, "墨田区"),
        bullet("キャッチコピー案: タワーの足元で、町会の太鼓が本気を出す区。"),
        bullet("編集キャラ: 北斎、相撲、職人、川風を全部背負っているが、最後は町会掲示板を見に行く“すみだ現場派”。"),
        bullet("見せ方: 牛嶋神社系の奉納踊り、錦糸町河内音頭、隅田公園、押上/向島/本所の小さな会場を、密度の高い下町盆踊り圏として見せる。"),
        bullet("イラスト案: スカイツリーを遠景に、法被姿の職人風キャラが団扇を構え、足元に川風、提灯、ちゃんこ鍋っぽい湯気を少しだけ。"),
        bullet("SEO切り口: 墨田区 盆踊り、錦糸町 河内音頭、牛嶋神社 奉納踊り、押上 盆踊り、向島 盆踊り。"),
        bullet("注意: スカイツリーだけの観光ページにしない。町会単位の奉納踊りが強み。"),
        heading(2, "台東区"),
        bullet("キャッチコピー案: 上野も浅草も、気づいたら全員ステージ側。"),
        bullet("編集キャラ: 浅草のにぎわい、上野公園のイベント感、御徒町の駅前感を渡り歩く“下町劇場の呼び込み係”。"),
        bullet("見せ方: 上野公園の大型/企画型、浅草・奥浅草・東本願寺・浅草橋の下町型を分け、観光客でも入りやすい区として出す。"),
        bullet("イラスト案: パンダ柄の団扇を持つ呼び込み係。背景は上野の緑、浅草の提灯、屋台の明かり。浅草寺そのものの細密再現は避ける。"),
        bullet("SEO切り口: 台東区 盆踊り、上野 盆踊り、浅草 盆踊り、奥浅草 盆踊り、御徒町 盆踊り。"),
        bullet("注意: 観光客向けの軽さだけでなく、寺・町会・公園イベントの違いを説明する。"),
        heading(2, "品川区"),
        bullet("キャッチコピー案: 宿場町、運河、商店街。踊り場が多すぎて区民まつりが迷路。"),
        bullet("編集キャラ: 旧東海道の旅人なのに、運河沿いで寄り道し、戸越銀座で買い食いし、大井町で太鼓に吸い寄せられる“品川回遊人”。"),
        bullet("見せ方: 区民まつり系、戸越/荏原/旗の台/大井町/東品川の地域分散を強みにする。ひとつの中心ではなく、生活圏ごとに踊る区として紹介。"),
        bullet("イラスト案: 旅装束風のキャラがスニーカーで歩き、背後に旧東海道の札、運河、商店街のアーケード、学校校庭の提灯。"),
        bullet("SEO切り口: 品川区 盆踊り、戸越 盆踊り、大井町 盆踊り、旗の台 盆踊り、品川区民まつり 盆踊り。"),
        bullet("注意: 品川駅周辺だけの印象に寄せない。実際のデータでは荏原・戸越・大井・八潮・東品川など広い。"),
        heading(2, "MVPで作る内容"),
        todo("4区の静的ページを作る。最初はイベントカード、区紹介、イラスト枠、内部リンクまで。", False),
        todo("各区のイベント件数、今後開催、日程未確認、昨年開催を自動集計して表示する。", False),
        todo("各区1枚のイラストを生成または制作し、altテキストも区名+盆踊り文脈で入れる。", False),
        todo("地図/フィルタは既存UIがあれば流用。なければ日程順カードを先に公開する。", False),
        todo("Search Consoleで『区名 盆踊り』『会場名 盆踊り』の表示回数とCTRを見る。", False),
        heading(2, "記事本文のサンプル文体"),
        paragraph("中央区の盆踊りは、銀座で背筋を伸ばした直後に、築地でお腹が鳴り、浜町でやぐらを見てほっとするタイプです。都心の顔をしているのに、夜になると急に町の行事の顔を見せます。"),
        paragraph("墨田区の盆踊りは、観光名所の影で町会が本気を出してくるタイプです。スカイツリーを見上げていたはずが、気づくと牛嶋神社の奉納踊りや錦糸町の河内音頭を調べています。"),
        paragraph("台東区の盆踊りは、浅草のにぎわいと上野の公園イベントが同じ区に入っている、だいぶ情報量の多い夏です。初めてでも入りやすい会場が多い一方、地域の行事としての顔も濃いです。"),
        paragraph("品川区の盆踊りは、一か所に集まるというより、生活圏ごとにぽこぽこ踊り場が立ち上がる感じです。旧東海道、商店街、学校、公園、運河沿い。歩くほど別の品川が出てきます。"),
        heading(2, "実装メモ"),
        bullet("公開JSONの address から4区を抽出できる。将来は ward フィールドを正規化した方が安定する。"),
        bullet("地域ページは重複ページ扱いを避けるため、区紹介・エリア分解・曲傾向・初心者メモを区ごとに変える。"),
        bullet("イベント詳細ページがある場合は、地域ページから詳細へ内部リンクを張る。詳細ページがない場合はカード内に公式URLを明示する。"),
        bullet("構造化データはイベント詳細側を優先。地域一覧ページはBreadcrumbとItemList程度に留めるのが無難。"),
        heading(2, "参照した観光/公式系ページ"),
        bullet("すみだ観光サイト: 墨田区は隅田川、両国、錦糸町、スカイツリー周辺、伝統工芸などの観光軸が見える。", "https://visit-sumida.jp/"),
        bullet("TAITOおでかけナビ: 台東区は上野・浅草・谷中・浅草橋などを公式観光情報として扱っている。", "https://t-navi.city.taito.lg.jp/"),
        bullet("しながわ観光協会: 品川区は品川宿、商店街、運河などのまち歩き文脈が強い。", "https://shinagawa-kanko.or.jp/"),
        bullet("中央区は銀座・日本橋・築地・月島・浜町などを主要文脈として扱う。ただし本文公開前に中央区/中央区観光協会の公式ページで表現確認する。"),
        paragraph("次アクション: 4区のページワイヤーを1枚作り、イラスト生成プロンプトと公開JSONの抽出仕様を固める。"),
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--current-location-json", default=str(CURRENT_LOCATION))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--confirm",
        default="",
        help=f"Required with --apply: {APPLY_CONFIRMATION}",
    )
    parser.add_argument("--dry-run", action="store_true", help="Accepted for compatibility; default behavior is dry-run")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    current = json.loads(Path(args.current_location_json).read_text(encoding="utf-8"))
    parent_page_id = current["page_id"]
    title = "盆助SEO 地域別イラスト付き一覧ページ企画"
    if not args.apply or args.dry_run:
        print(f"Would create Notion page under {parent_page_id}: {title}")
        return
    if args.confirm != APPLY_CONFIRMATION:
        raise SystemExit(f'--apply requires --confirm "{APPLY_CONFIRMATION}"')

    page = create_page(parent_page_id, title)
    append_blocks(page["id"], page_blocks())
    output = {
        "generated_by": "create_regional_seo_illustrated_list_plan_notion.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "title": title,
        "page_id": page["id"],
        "url": page.get("url") or "",
        "parent_page_id": parent_page_id,
        "parent_url": current.get("url") or "",
    }
    atomic_write_json(args.out, output)
    print(f"Notionに地域別SEO企画メモを作成しました: {page.get('url') or page['id']}")


if __name__ == "__main__":
    main()
