"""Append yearly event inheritance and DB operation policy to Notion."""

import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone

from notion_support.notion_config import load_local_env


load_local_env()

NOTION_API = "https://api.notion.com/v1"
NOTION_TOKEN = os.environ.get("NOTION_API_TOKEN")

CURRENT_WORK_PAGE_ID = "37f8be04-e762-815c-9f62-d76866ca9e83"
CURRENT_WORK_PLAN_BLOCK_ID = "37f8be04-e762-814a-9463-dabca26c86e0"
CURRENT_WORK_PAGE_URL = "https://app.notion.com/p/37f8be04e762815c9f62d76866ca9e83"


def rich_text(text):
    return [{"type": "text", "text": {"content": str(text or "")[:2000]}}]


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


def heading(text):
    return {"object": "block", "type": "heading_2", "heading_2": {"rich_text": rich_text(text)}}


def subheading(text):
    return {"object": "block", "type": "heading_3", "heading_3": {"rich_text": rich_text(text)}}


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


def update_bullet(block_id, text):
    return notion_request("PATCH", f"/blocks/{block_id}", {"bulleted_list_item": {"rich_text": rich_text(text)}})


def policy_blocks():
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return [
        heading("年次イベント継承・DB運用方針"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "個別イベント一覧ではなく、2025年実績から2026年開催回へ何をどう継承するか、"
            "および2027年以降の毎年運用を定める上位方針。"
        ),
        subheading("基本モデル"),
        bullet("イベントDBの1行は、原則として年ごとの開催回を表す。2025年と2026年の同名イベントは、同じ系列でも別開催回として扱う。"),
        bullet("2026年専用テーブルや年別カラムを増やさない。必要なら event_year、series_key、inherited_from_year、根拠情報で年次関係を表す。"),
        bullet("将来的に必要になったら、恒久情報を持つ event_series と、年次開催回を持つ events に分ける。"),
        subheading("継承の原則"),
        bullet("2025年から2026年への継承は、前年情報を2026年の確定情報としてコピーすることではない。根拠付きの推定・参考情報として参照する。"),
        bullet("継承情報には source_year、source_event_id、source_url、basis、basis_label、confidence を残す。例: 2025年実測、前年実績、past_evidence、inherited。"),
        bullet("継承された情報は、2026年公式情報・今年告知・今年実測が出たら上書きまたは昇格する。"),
        subheading("情報種別ごとの扱い"),
        bullet("開催日: 前年日付を翌年へ直接コピーしない。前年実績は例年時期、開催可能性、探索優先度のヒントに留める。"),
        bullet("開催日: 2026年の公式HP、自治体/主催発表、信頼できるX投稿などで確認できたものだけを2026開催日として昇格する。"),
        bullet("曲目: 前年実績を2026年の曲目予測に使ってよい。ただし2026公式曲目表、2026事前告知、2026実測を優先する。"),
        bullet("雰囲気・規模感・曲の傾向: 系列情報として継承してよい。ただし根拠年、根拠URL、観測元、確からしさを残す。"),
        bullet("開催可能性: 前年開催実績は今年もある可能性の根拠になるが、開催確定ではない。単独の弱い投稿や前年実績だけで確認済みにしない。"),
        subheading("情報源ごとの時間的役割"),
        bullet("YouTube: 基本的に過去イベントの実績証拠。曲目、雰囲気、規模感、実際の開催有無に強いが、未来イベントの開催確定には使わない。"),
        bullet("公式HP・自治体/主催情報: 未来または今年のイベント情報の最優先証拠。開催日、場所、主催、公式曲目、開催確定ではYouTubeより優先する。"),
        bullet("X: 未来告知、参加予定、現地兆候、当日/事後の実測情報として扱う。主催・自治体・会場・信頼済みアカウントを強い根拠にする。"),
        subheading("2026年初年度の特別運用"),
        bullet("2026年は初年度なので、通常の冬ロールオーバーではなく、2026年6月中に一度だけ2025年から2026年への継承バッチを行う。"),
        todo("2025年イベントを event_name + venue を基本に系列化し、series_key を付ける。"),
        todo("既に2026年開催回があるものは、その2026イベントに同じ series_key を付ける。"),
        todo("2026年開催回がないが継承対象にするものは、2026年の未確認/継承候補として作成する。"),
        todo("開催日はコピーせず、例年時期・月・旬のヒントだけを継承する。"),
        todo("曲目、雰囲気、規模感、曲の傾向は、根拠年と確からしさ付きで継承する。"),
        todo("2026年公式情報や信頼できるX情報が見つかったものから、未確認/継承候補を確認済みへ昇格する。"),
        todo("YouTube由来の2025年情報は、2026年の確定情報ではなく、前年実績による予測根拠として扱う。"),
        subheading("2027年以降の通常運用"),
        bullet("10月-11月: 当年の実績、曲目、雰囲気、証拠を整理する。"),
        bullet("12月-1月: 当年実績から翌年開催回候補を生成する。"),
        bullet("2月-5月: 公式HP、自治体情報、主催SNS、Xで裏取りする。"),
        bullet("6月-9月: 今年情報で開催日、曲目、ステータス、証拠を更新する。"),
        bullet("シーズン後: 今年のYouTubeやXを実績証拠として整理し、翌年継承の材料にする。"),
        subheading("ステータス運用"),
        bullet("継承候補: 前年実績から翌年候補として作った段階。"),
        bullet("未確認: 今年開催の可能性はあるが、今年の直接証拠が弱い段階。"),
        bullet("確認済み: 公式HP、自治体/主催発表、信頼できる今年情報で開催日または開催が確認できた段階。"),
        bullet("終了: 当年開催が終了し、実績として扱う段階。"),
        bullet("保留: 盆踊り本DB対象か、年、会場、公式確認などに不確実性が残る段階。"),
        bullet("対象外: 周辺イベント、全国候補、盆踊りでないイベントなど、本DB登録対象外の段階。"),
        subheading("実装方針"),
        bullet("まずは既存 events を年次開催回テーブルとして明確に使う。必要に応じて event_year、series_key、inherited_from_year を追加する。"),
        bullet("継承結果は直接Notionへ大量反映せず、まずdry-run JSON/MDに出す。作成候補、既存2026イベントへの紐付け候補、保留、対象外を分ける。"),
        bullet("RDBでは証拠ごとに evidence_year と evidence_role を持つ方針にする。role例: past_result、future_announcement、current_hint、current_result。"),
        subheading("判断優先順位"),
        bullet("開催日: 公式HP/自治体/主催発表 > 主催/会場/信頼済みXの今年告知 > 複数の独立した今年情報 > 前年実績による例年時期ヒント。"),
        bullet("曲目: 今年の公式曲目表 > 今年の事前告知 > 今年のYouTube/投稿実測 > 前年YouTube/投稿による実績予測。"),
        bullet("雰囲気: 今年の投稿/動画 > 前年の投稿/動画 > 会場・系列の一般情報。"),
        subheading("注意"),
        bullet("継承情報を確定情報に見せない。YouTubeに動画があることを、今年開催確定の根拠にしない。"),
        bullet("開催日を前年から機械変換しない。年ごとのカラムを増やしてスキーマを固定年に依存させない。"),
        bullet("Notion正本を壊さないため、継承バッチは必ずdry-runを挟む。"),
        bullet("詳細版ローカル文書: docs/yearly-event-inheritance-policy.md"),
        bullet(f"入口: {CURRENT_WORK_PAGE_URL}"),
    ]


def append_policy_note():
    return notion_request("PATCH", f"/blocks/{CURRENT_WORK_PAGE_ID}/children", {"children": policy_blocks()})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    current_text = (
        "DB運用方針: 2025年実績から2026年開催回への継承は、確定情報のコピーではなく根拠付き推定として扱う。"
        "2026年6月中に初年度継承バッチ、以後は毎年冬に翌年候補を生成する。"
    )

    if args.dry_run:
        print(f"Would update current work block: {CURRENT_WORK_PLAN_BLOCK_ID} -> {current_text}")
        print(f"Would append yearly event inheritance policy note to current work page: {CURRENT_WORK_PAGE_ID}")
        return

    update_bullet(CURRENT_WORK_PLAN_BLOCK_ID, current_text)
    append_policy_note()
    print("Notionへ年次イベント継承・DB運用方針を追記しました")


if __name__ == "__main__":
    main()
