"""Build a hold list for YouTube videos outside the current Tokyo scope."""

import argparse
import json
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


DATA = Path("data")
REVIEW = DATA / "youtube_active_video_review.json"
OUT = DATA / "youtube_nationwide_hold_candidates.json"
MARKDOWN_OUT = DATA / "youtube_nationwide_hold_candidates.md"


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


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


def atomic_write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=".tmp-", suffix=".md", delete=False
    ) as handle:
        handle.write(text)
        tmp_name = handle.name
    Path(tmp_name).replace(path)


def event_key(row):
    title = row.get("title") or ""
    if "横浜開港祭" in title:
        return ("横浜開港祭 BON ODORI", "パシフィコ横浜プラザ広場", row.get("detected_event_date") or "")
    for occurrence in row.get("setlist_occurrences") or []:
        name = occurrence.get("event_name") or ""
        venue = occurrence.get("venue") or ""
        date = occurrence.get("event_date") or row.get("detected_event_date") or ""
        if name:
            return (name, venue, date)
    return (title, "", row.get("detected_event_date") or "")


def normalize_label(value):
    return " ".join(str(value or "").split())


def compact_video(row):
    return {
        "video_id": row.get("video_id") or "",
        "video_url": row.get("video_url") or "",
        "title": row.get("title") or "",
        "channel": row.get("channel_title") or "",
        "published_at": row.get("published_at") or "",
        "detected_event_date": row.get("detected_event_date") or "",
    }


def build_hold(review):
    groups = defaultdict(list)
    for row in review.get("rows") or []:
        if row.get("action") != "out_of_scope":
            continue
        groups[event_key(row)].append(row)

    candidates = []
    for (event_name, venue, event_date), rows in sorted(groups.items()):
        official_urls = []
        songs = []
        for row in rows:
            for url in row.get("official_urls") or []:
                if url not in official_urls:
                    official_urls.append(url)
            for occurrence in row.get("setlist_occurrences") or []:
                label = occurrence.get("event_name") or ""
                count = occurrence.get("song_count") or 0
                if label and count and f"{label}({count})" not in songs:
                    songs.append(f"{label}({count})")
        candidates.append(
            {
                "event_name": event_name,
                "venue": venue,
                "event_date": event_date,
                "scope_status": "hold_for_nationwide_expansion",
                "reason": "現行の東京23区公開DB範囲外のため本DBには登録しない",
                "video_count": len(rows),
                "channels": sorted({normalize_label(row.get("channel_title")) for row in rows if row.get("channel_title")}),
                "official_urls": official_urls,
                "setlist_summaries": songs,
                "videos": [compact_video(row) for row in rows],
            }
        )
    return {
        "generated_by": "build_youtube_nationwide_hold.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(REVIEW),
        "candidate_count": len(candidates),
        "video_count": sum(candidate["video_count"] for candidate in candidates),
        "candidates": candidates,
    }


def md_escape(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(hold):
    lines = [
        "# YouTube全国展開候補 hold",
        "",
        f"- 生成: {hold['generated_at']}",
        f"- 候補数: {hold['candidate_count']}",
        f"- 動画数: {hold['video_count']}",
        "- 方針: 現行の東京23区公開DBには入れず、全国展開時の候補として保持する。",
        "",
        "| event | date | venue | videos | channels | representative_video |",
        "| --- | --- | --- | ---: | --- | --- |",
    ]
    for candidate in hold["candidates"]:
        first_video = (candidate.get("videos") or [{}])[0]
        video_url = first_video.get("video_url") or ""
        title = md_escape(first_video.get("title") or "")
        representative = f"[{title}]({video_url})" if video_url else title
        lines.append(
            "| "
            f"{md_escape(candidate['event_name'])} | "
            f"{md_escape(candidate['event_date'])} | "
            f"{md_escape(candidate['venue'])} | "
            f"{candidate['video_count']} | "
            f"{md_escape(', '.join(candidate['channels']))} | "
            f"{representative} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--review", default=str(REVIEW))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--markdown-out", default=str(MARKDOWN_OUT))
    args = parser.parse_args()

    hold = build_hold(load_json(args.review, {}))
    atomic_write_json(args.out, hold)
    atomic_write_text(args.markdown_out, render_markdown(hold))
    print(
        f"wrote {args.out} "
        f"({hold['candidate_count']} candidates, {hold['video_count']} videos)"
    )


if __name__ == "__main__":
    main()
