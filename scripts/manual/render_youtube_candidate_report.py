"""Render YouTube discovery candidates as a small Markdown review report."""

import argparse
import json
from pathlib import Path


SOURCE = Path("data/youtube_channel_candidates.json")
OUT = Path("data/youtube_channel_candidates.md")


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def one_line(value, limit=120):
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def table_row(values):
    return "| " + " | ".join(str(value).replace("|", "\\|") for value in values) + " |"


def render(payload):
    lines = [
        "# YouTubeチャンネル・イベント候補",
        "",
        f"- 動画候補: {payload.get('video_count', 0)}件",
        f"- チャンネル候補: {payload.get('channel_candidate_count', 0)}件",
        f"- イベント候補: {payload.get('event_candidate_count', 0)}件",
        f"- 検索語: {', '.join(payload.get('queries') or [])}",
        "",
        "## 優先チャンネル候補",
        "",
        table_row(["score", "状態", "既存", "チャンネル", "動画", "曲目候補", "日付", "URL"]),
        table_row(["---", "---", "---", "---", "---", "---", "---", "---"]),
    ]
    for row in (payload.get("channels") or [])[:15]:
        lines.append(table_row([
            row.get("candidate_score", 0),
            row.get("review_status", ""),
            "yes" if row.get("already_known") else "no",
            row.get("channel_title", ""),
            row.get("found_video_count", 0),
            row.get("setlist_candidate_count", 0),
            row.get("event_date_candidate_count", 0),
            row.get("channel_url", ""),
        ]))

    lines.extend([
        "",
        "## 曲目つきイベント候補",
        "",
        table_row(["日付", "曲目数", "チャンネル", "タイトル", "URL"]),
        table_row(["---", "---", "---", "---", "---"]),
    ])
    setlist_events = [
        row for row in (payload.get("event_candidates") or [])
        if (row.get("setlist_count") or 0) >= 2
    ]
    for row in setlist_events[:30]:
        lines.append(table_row([
            row.get("event_date") or "",
            row.get("setlist_count") or 0,
            row.get("channel_title") or "",
            one_line(row.get("title") or "", 90),
            row.get("url") or "",
        ]))

    lines.extend([
        "",
        "## 日付つきイベント候補",
        "",
        table_row(["日付", "チャンネル", "タイトル", "URL"]),
        table_row(["---", "---", "---", "---"]),
    ])
    dated = [row for row in (payload.get("event_candidates") or []) if row.get("event_date")]
    for row in dated[:30]:
        lines.append(table_row([
            row.get("event_date") or "",
            row.get("channel_title") or "",
            one_line(row.get("title") or "", 100),
            row.get("url") or "",
        ]))
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(SOURCE))
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    payload = load_json(args.source, {})
    text = render(payload)
    Path(args.out).write_text(text, encoding="utf-8")
    print(f"[youtube-report] wrote {args.out}")


if __name__ == "__main__":
    main()
