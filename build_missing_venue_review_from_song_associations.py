#!/usr/bin/env python3
"""Build review rows for venues missing from accepted venue-song associations."""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path


SOURCE = Path("data/accepted_venue_song_associations_apply_result.json")
ACCEPTED = Path("data/retrospective_venue_song_associations_accepted.json")
OUT = Path("data/accepted_venue_song_missing_venue_review.json")
OUT_MD = Path("data/accepted_venue_song_missing_venue_review.md")

VENUE_CLEANUPS = {
    "夏祭り向けに有馬小学校": "有馬小学校",
    "東大阪市布施駅前": "布施駅前",
}


def load_json(path):
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def clean_venue(value):
    value = VENUE_CLEANUPS.get(value, value)
    value = re.sub(r"^(?:夏祭り向けに|今年は|去年は|本日は|今日は)", "", value or "")
    return value.strip()


def association_by_key(accepted):
    return {
        (row.get("venue"), row.get("song_name")): row
        for row in accepted.get("associations", [])
    }


def build_rows(result, accepted):
    accepted_index = association_by_key(accepted)
    grouped = defaultdict(lambda: {
        "category": "会場追加候補",
        "type": "missing_venue",
        "term": "",
        "suggested_venue": "",
        "raw_venues": set(),
        "songs": [],
        "song_count": 0,
        "evidence_count": 0,
        "source_urls": set(),
        "reason": "採用済み会場×曲候補だが、Notion会場DBに会場が見つからなかった。",
        "evidence": [],
    })
    for row in result.get("skipped", []):
        raw_venue = row.get("venue") or ""
        song = row.get("song_name") or ""
        suggested = clean_venue(raw_venue)
        key = (suggested, row.get("source_url") or "")
        group = grouped[key]
        group["term"] = suggested
        group["suggested_venue"] = suggested
        group["raw_venues"].add(raw_venue)
        if song and song not in group["songs"]:
            group["songs"].append(song)
        source = accepted_index.get((raw_venue, song), {})
        group["evidence_count"] += int(source.get("evidence_count") or 1)
        if row.get("source_url"):
            group["source_urls"].add(row["source_url"])
        for ev in source.get("evidence") or []:
            group["evidence"].append({
                "url": ev.get("url") or row.get("source_url") or "",
                "date": ev.get("observed_at") or "",
                "account": ev.get("account") or "",
                "text": ev.get("text") or "",
            })

    rows = []
    for group in grouped.values():
        group["raw_venues"] = sorted(group["raw_venues"])
        group["songs"] = sorted(group["songs"])
        group["song_count"] = len(group["songs"])
        group["source_urls"] = sorted(group["source_urls"])
        group["evidence"] = group["evidence"][:5]
        group["evidence_text"] = "\n---\n".join(ev.get("text", "") for ev in group["evidence"][:3])
        group["evidence_url"] = group["source_urls"][0] if group["source_urls"] else ""
        group["songs_text"] = "、".join(group["songs"])
        rows.append(group)
    rows.sort(key=lambda row: (-row["song_count"], row["suggested_venue"]))
    return rows


def render_markdown(payload):
    lines = [
        "# 採用済み会場×曲からの会場追加レビュー",
        "",
        f"- 候補会場: {payload['count']}",
        "",
        "| 会場候補 | 曲 | 証拠URL | 元抽出名 |",
        "|---|---|---|---|",
    ]
    for row in payload["rows"]:
        lines.append(
            f"| {row['suggested_venue']} | {row['songs_text']} | "
            f"{row['evidence_url']} | {', '.join(row['raw_venues'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--accepted", type=Path, default=ACCEPTED)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    args = parser.parse_args()

    rows = build_rows(load_json(args.source), load_json(args.accepted))
    payload = {
        "generated_by": "build_missing_venue_review_from_song_associations.py",
        "source": str(args.source),
        "accepted": str(args.accepted),
        "count": len(rows),
        "rows": rows,
    }
    write_json(args.out, payload)
    args.out_md.write_text(render_markdown(payload), encoding="utf-8")
    print(f"missing venue review: {len(rows)} rows -> {args.out}")


if __name__ == "__main__":
    main()
