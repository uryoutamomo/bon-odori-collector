#!/usr/bin/env python3
"""Append historical-reference review flow diagrams to the Notion operations manual."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from append_review_console_flow_to_notion import DEFAULT_PAGE_ID
from append_review_console_operations_manual_to_notion import (
    DEFAULT_QUERY,
    bullet,
    choose_manual_page,
    heading_2,
    heading_3,
    notion_request,
    paragraph,
    rich_text,
)


ADOPTION_FLOW = """flowchart TD
  A["登録済みイベント調査カード"] --> B{"反映ルートを選ぶ"}

  B -->|過去実績として採用| C{"過去実績日がある?"}
  C -->|ない| D["保存不可\\n保留または要調査へ"]
  C -->|ある| E["過去年の開催実績として採用\\n例: 2025-07-20（日）"]

  E --> F["2026年日程は未確認のまま残る"]
  E --> G["曲は確定登録しない\\n候補があっても別工程扱い"]
  E --> H["採用済み過去実績品質レビューへ再点検対象として残る"]

  B -->|2026年日程確認済みにする| I{"2026年の直接日付根拠がある?"}
  I -->|ない| J["保存不可\\n過去実績・保留・要調査へ"]
  I -->|ある| K["2026年開催日として確認済みに進める"]

  B -->|要調査| L["公式確認・同一性確認・日付/曲確認へ"]
  B -->|保留| M["文脈だけ残して今回は進めない"]
  B -->|不採用| N["候補として使わない"]
"""


QUALITY_CYCLE_FLOW = """flowchart TD
  A["採用済み過去実績"] --> B["品質レビュー生成\\nbuild_historical_reference_quality_review.py"]
  B --> C{"日付・曜日・曲は足りている?"}

  C -->|日付なし / 日付不正| D["P0: 日付・曜日を再調査"]
  D --> E["根拠URLや過去資料を確認"]
  E --> F{"日付を確認できた?"}
  F -->|できた| G["過去実績日を補完\\n曜日は日付から算出"]
  F -->|できない| H["保留または過去実績から外す判断"]

  C -->|曲なし| I["P1: 曲候補を再調査"]
  I --> J["YouTube / song_occurrences / 曲実績側で収集"]
  J --> K{"曲候補が見つかった?"}
  K -->|見つかった| L["曲候補を追加\\n公開export時に曲ヒントとして利用"]
  K -->|見つからない| M["曲なしとして維持または保留"]

  C -->|足りている| N["過去実績として維持"]

  G --> B
  L --> B
  M --> B
  H --> B
  N --> B
"""


def code_block(text: str, language: str = "mermaid") -> dict:
    return {
        "object": "block",
        "type": "code",
        "code": {"rich_text": rich_text(text), "language": language},
    }


def flow_blocks(language: str = "mermaid") -> list[dict]:
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return [
        {"object": "block", "type": "divider", "divider": {}},
        heading_2("過去実績採用と再点検フロー"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "レビューコンソールで「過去実績として採用」を押した後、"
            "日付・曜日・曲候補の確認機会がどこに残るかを整理したフロー。"
        ),
        heading_3("前提"),
        bullet("過去実績として採用しても、2026年開催確定にはしない。"),
        bullet("2026年日程確認済みにするには、2026年の直接根拠が必要。"),
        bullet("過去実績採用だけでは、曲データを確定登録しない。"),
        bullet("採用済み過去実績は、後続の品質レビューで日付・曜日・曲候補を再点検する。"),
        heading_3("登録済みイベント調査からの流れ"),
        code_block(ADOPTION_FLOW, language),
        heading_3("採用後の再点検サイクル"),
        code_block(QUALITY_CYCLE_FLOW, language),
        heading_3("現在のローカル状態"),
        bullet("過去実績系: 93件。"),
        bullet("日付なし: 0件。"),
        bullet("曲なし: 65件。"),
        bullet("現在の「採用済み過去実績品質レビュー」は、主に曲候補を再調査するためのキュー。"),
        heading_3("判断の目安"),
        bullet("過去実績日があり、曜日を算出できるものは、過去年の根拠として採用可能。"),
        bullet("過去実績日がない、同一イベント性が怪しい、根拠URLが弱い場合は、保留または要調査を優先する。"),
        bullet("採用済みだが曲データがないものは、曲候補を再調査に回す。"),
        paragraph("ローカル詳細版: docs/historical-reference-review-flow.md"),
    ]


def append_flow(page_id: str, language: str = "mermaid") -> None:
    notion_request("PATCH", f"/blocks/{page_id}/children", {"children": flow_blocks(language)})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--page-id", default=DEFAULT_PAGE_ID)
    parser.add_argument("--language", default="mermaid")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    target, candidates = choose_manual_page(args.query, args.page_id)
    if not target:
        raise SystemExit(f"No Notion page found for query: {args.query}")

    if args.dry_run:
        print(f"Target: {target['title']} / {target['id']} / {target.get('url', '')}")
        if candidates:
            print("Candidates:")
            for row in candidates[:10]:
                print(f"- {row['title']} / {row['id']} / {row.get('last_edited_time', '')}")
        print(f"Blocks: {len(flow_blocks(args.language))}")
        print(f"Language: {args.language}")
        return

    try:
        append_flow(target["id"], args.language)
    except Exception:
        if args.language == "mermaid":
            append_flow(target["id"], "plain text")
            print(
                "Mermaid code language was rejected by Notion API; appended diagrams as plain text instead."
            )
        else:
            raise
    print(f"Notion運用マニュアルへ過去実績採用と再点検フローを追記しました: {target['title']} / {target['id']}")
    if target.get("url"):
        print(target["url"])


if __name__ == "__main__":
    main()
