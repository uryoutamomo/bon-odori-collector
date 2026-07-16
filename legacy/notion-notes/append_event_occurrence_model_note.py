"""Append the event occurrence data model plan to the current-location Notion page."""

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
CURRENT_LOCATION = Path("data/notion_current_location.json")


def rich_text(text):
    return [{"type": "text", "text": {"content": str(text or "")[:2000]}}]


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


def note_blocks():
    now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return [
        heading(2, "年次開催回モデル・過去年収集方針"),
        paragraph(f"更新: {now} / 署名: おと（Codex）。内田さんとの設計合意メモ。"),
        bullet("年次データは会場ではなく、イベント系列に紐づく年次開催回に持たせる。会場は場所マスタ、イベント系列は毎年続くもの、年次開催回はその年にいつどこで開かれたか。"),
        bullet("基本構造: venues / event_series / event_occurrences / occurrence_songs。event_series は通常会場、event_occurrences はその年の実会場を持つ。"),
        bullet("2026年予測のため、2025年だけでは弱い。最低3年分として2023・2024・2025を集め、重要イベントは5年分を目指す。"),
        bullet("2024年・2023年も最終的には2025年と同程度の粒度で集める。2020〜2021は欠測/例外年扱いを想定。"),
        bullet("曲目は盆踊りの重要要素として年次開催回に紐づける。まずは直近2年分を優先し、2年連続曲を定番候補、片年曲を年替わり候補として扱う。"),
        bullet("詳細方針は docs/yearly-event-inheritance-policy.md に追記済み。"),
        heading(3, "次にやること"),
        todo("既存YouTube実績から event_occurrence_observations の初期JSONを作る。"),
        todo("公式URLなし・継続性高・公開価値高のイベントを優先して、2024/2023 YouTube検索キューを作る。"),
        todo("3年分以上ある系列から date_rule と predicted_2026 をdry-runで出す。"),
        todo("曲目はまず2024/2025の2年分を occurrence_songs として整理する。"),
    ]


def append_blocks(page_id, blocks):
    for idx in range(0, len(blocks), 90):
        notion_request("PATCH", f"/blocks/{page_id}/children", {"children": blocks[idx:idx + 90]})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--current-location-json", default=str(CURRENT_LOCATION))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not NOTION_TOKEN:
        raise SystemExit("NOTION_API_TOKEN is not set")

    current = json.loads(Path(args.current_location_json).read_text(encoding="utf-8"))
    if args.dry_run:
        print(f"Would append event occurrence model note to: {current['page_id']}")
        return
    append_blocks(current["page_id"], note_blocks())
    print(f"Notion現在地に年次開催回モデル方針を追記しました: {current['url']}")


if __name__ == "__main__":
    main()
