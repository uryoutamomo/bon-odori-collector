#!/usr/bin/env python3
"""Build a reviewable queue for public song content note research."""

import argparse
import json
from pathlib import Path


DATA = Path("data")
SONG_MASTER = DATA / "youtube_song_master.json"
CONTENT_NOTES = DATA / "public_song_content_notes.json"
OUT_JSON = DATA / "song_content_research_queue.json"
OUT_MD = DATA / "song_content_research_queue.md"


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def md_cell(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def note_index(payload):
    return {
        item.get("term"): item
        for item in payload.get("items", [])
        if item.get("term")
    }


def evidence_count(song):
    return int(song.get("good_evidence_count") or song.get("evidence_count") or 0)


def priority_group(song, note):
    if note and note.get("content_note_status") != "公開可":
        return "P0既存要確認"
    if not note:
        if evidence_count(song) >= 50:
            return "P1未整備50件以上"
        if evidence_count(song) >= 20:
            return "P2未整備20件以上"
        return "P3未整備低頻度"
    return "P9整備済み"


def row_for_song(song, note):
    group = priority_group(song, note)
    return {
        "term": song.get("song_name") or "",
        "priority": group,
        "existing_content_note_status": note.get("content_note_status") if note else "",
        "existing_content_note": note.get("content_note") if note else "",
        "evidence_count": evidence_count(song),
        "bon_usage_rank": song.get("bon_usage_rank") or "",
        "song_genre": song.get("song_genre") or "",
        "genre_review_status": song.get("genre_review_status") or "",
        "sample_events": song.get("sample_events") or [],
        "sample_venues": song.get("sample_venues") or [],
        "youtube_urls": song.get("youtube_urls") or [],
        "research_status": "未調査",
        "research_queries": build_queries(song.get("song_name") or ""),
        "content_note": "",
        "content_note_status": "",
        "source_urls": [],
        "research_memo": "",
    }


def build_queries(term):
    return [
        f"{term} 由来 盆踊り",
        f"{term} 歌 由来",
        f"{term} 民謡 音頭",
    ]


def build_queue(song_master, content_notes, limit=25, include_done=False):
    notes = note_index(content_notes)
    rows = []
    for song in song_master.get("songs", []):
        if not song.get("public_ready"):
            continue
        term = song.get("song_name")
        if not term:
            continue
        note = notes.get(term)
        group = priority_group(song, note)
        if group == "P9整備済み" and not include_done:
            continue
        rows.append(row_for_song(song, note or {}))

    rows.sort(key=lambda row: (row["priority"], -row["evidence_count"], row["term"]))
    if limit:
        rows = rows[:limit]
    return {
        "generated_by": "build_song_content_research_queue.py",
        "source": str(SONG_MASTER),
        "content_notes": str(CONTENT_NOTES),
        "limit": limit,
        "rows": rows,
        "instructions": [
            "Webで公式・自治体・観光協会・保存会・レコード会社・信頼できる解説を優先して確認する。",
            "歌詞の引用は避け、由来・地域・曲調・盆踊りでの使われ方を120字前後で書く。",
            "同名別曲や根拠不足がある場合はcontent_note_statusを要確認のままにする。",
            "公開へ反映できるものだけcontent_note_statusを公開可にする。",
        ],
    }


def render_markdown(queue):
    rows = queue.get("rows") or []
    lines = [
        "# 曲内容メモ Web調査キュー",
        "",
        f"- source: `{queue.get('source')}`",
        f"- content_notes: `{queue.get('content_notes')}`",
        f"- rows: {len(rows)}",
        "",
        "## 作業ルール",
        "",
    ]
    lines.extend(f"- {item}" for item in queue.get("instructions") or [])
    lines.extend([
        "",
        "## 対象曲",
        "",
        "| 優先 | 曲名 | 根拠数 | 利用度 | ジャンル | 既存状態 | 検索クエリ |",
        "| --- | --- | ---: | --- | --- | --- | --- |",
    ])
    for row in rows:
        queries = "<br>".join(row.get("research_queries") or [])
        lines.append(
            f"| {md_cell(row['priority'])} | {md_cell(row['term'])} | {row['evidence_count']} | "
            f"{md_cell(row['bon_usage_rank'])} | {md_cell(row['song_genre'])} | "
            f"{md_cell(row['existing_content_note_status'])} | {md_cell(queries)} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_queue(queue, out_json=OUT_JSON, out_md=OUT_MD):
    out_json = Path(out_json)
    out_md = Path(out_md)
    out_json.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    out_md.write_text(render_markdown(queue) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--song-master", default=str(SONG_MASTER))
    parser.add_argument("--content-notes", default=str(CONTENT_NOTES))
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--include-done", action="store_true")
    args = parser.parse_args()

    queue = build_queue(
        load_json(args.song_master, {}),
        load_json(args.content_notes, {}),
        limit=args.limit,
        include_done=args.include_done,
    )
    queue["source"] = args.song_master
    queue["content_notes"] = args.content_notes
    write_queue(queue, args.out_json, args.out_md)
    print(f"song content research queue: rows={len(queue['rows'])} -> {args.out_json}, {args.out_md}")


if __name__ == "__main__":
    main()
