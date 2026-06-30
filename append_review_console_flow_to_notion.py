#!/usr/bin/env python3
"""Append review console flow diagrams to the Notion operations manual."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from append_review_console_operations_manual_to_notion import (
    DEFAULT_QUERY,
    choose_manual_page,
    heading_2,
    heading_3,
    notion_request,
    paragraph,
    bullet,
    rich_text,
)


DEFAULT_PAGE_ID = "3778be04-e762-81ee-8b68-d3706cfaf31b"


REVIEW_FLOW_MERMAID = """flowchart TD
    A["レビュー候補JSON<br/>data/*review / data/*queue"] --> B["レビューコンソール<br/>http://127.0.0.1:8751/"]
    B --> C{"内田さんの判断"}
    C -->|1 採用| D["decisions.json<br/>decision=accept"]
    C -->|2 却下| E["decisions.json<br/>decision=reject"]
    C -->|3 保留| F["decisions.json<br/>decision=hold"]
    C -->|4 要調査| G["decisions.json<br/>decision=needs_research"]
    D --> H["エクスポート e<br/>exported_decisions.json / .md"]
    E --> H
    F --> H
    G --> H
    H --> I["ステージ適用 g<br/>staged/*_decisions.json"]
    I --> J["おと、または個別applyが確認"]
    J --> K{"本番反映する?"}
    K -->|はい| L["個別applyスクリプト<br/>dry-run後に明示実行"]
    K -->|いいえ| M["ローカルに保持"]
    L --> N["Master RDB / 公開JSON / Notion等"]
"""


BUTTON_FLOW_MERMAID = """flowchart LR
    R["更新 r"] --> R1["読み直しのみ<br/>書き込みなし"]
    T["棚卸し保存 t"] --> T1["source_inventory.json / .md<br/>件数スナップショット"]
    S["保存 s"] --> S1["decisions.json<br/>1件の判断を保存"]
    C["解除 c"] --> C1["decisions.json<br/>1件の判断を削除"]
    E["エクスポート e"] --> E1["exported_decisions.json / .md<br/>判断を束ねる"]
    G["ステージ適用 g"] --> G1["staged/*_decisions.json<br/>apply用パケット"]
    G1 -. 直接変更しない .-> P["Master RDB / Notion / 公開JSON / S3等"]
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
        heading_2("レビューコンソール フロー図"),
        paragraph(
            f"更新: {now} / 署名: おと（Codex）。"
            "レビューコンソールで判断してから、どのローカルファイルに保存され、どこから先が別applyになるかを図にしたもの。"
        ),
        heading_3("全体フロー"),
        code_block(REVIEW_FLOW_MERMAID, language),
        bullet("採用・却下・保留・要調査はいずれも、まず data/review_console/decisions.json に保存される。"),
        bullet("エクスポートは保存済み判断をまとめるだけで、元データや本番データは変更しない。"),
        bullet("ステージ適用は apply 用パケットを作るだけ。Master RDB、Notion、公開JSON、S3/CloudFront には直接反映しない。"),
        heading_3("ボタン別の到達点"),
        code_block(BUTTON_FLOW_MERMAID, language),
        bullet("日常操作で頻繁に使うのは、更新 r、判断 1/2/3/4、保存 s。"),
        bullet("まとまったレビューができた時だけ、エクスポート e とステージ適用 g を使う。"),
        bullet("実データへ反映する場合は、このページのフロー図の外側で、個別applyスクリプトを dry-run してから明示実行する。"),
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
    print(f"Notion運用マニュアルへレビューコンソールのフロー図を追記しました: {target['title']} / {target['id']}")
    if target.get("url"):
        print(target["url"])


if __name__ == "__main__":
    main()
