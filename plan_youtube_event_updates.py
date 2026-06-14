"""Plan review actions for YouTube-discovered event/song candidates."""

import argparse
import json
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path


DATA = Path("data")
YOUTUBE_EVENT_SONGS = DATA / "youtube_event_song_candidates.json"
PUBLIC_EVENTS = DATA / "public" / "events_public.json"
OUT = DATA / "youtube_event_update_plan.json"
MARKDOWN_OUT = DATA / "youtube_event_update_plan.md"

TOKYO_23_AREAS = {
    "千代田区", "中央区", "港区", "新宿区", "文京区", "台東区", "墨田区", "江東区",
    "品川区", "目黒区", "大田区", "世田谷区", "渋谷区", "中野区", "杉並区", "豊島区",
    "北区", "荒川区", "板橋区", "練馬区", "足立区", "葛飾区", "江戸川区",
}
OUT_OF_SCOPE_RE = re.compile(r"(博多|福岡|ラゾーナ川崎|川崎|横浜|鶴見|總持寺|総持寺)")
GENERIC_EVENT_NAMES = {"盆踊り大会", "盆踊り", "納涼盆踊り", "夏祭り"}


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


def norm(value):
    value = str(value or "").casefold()
    value = re.sub(r"20\d{2}年?|第\d+回|[0-9０-９]+日目|[0-9０-９]+部|[0-9０-９]+曲", "", value)
    return re.sub(r"[^0-9a-z一-龥ぁ-んァ-ヶー]+", "", value)


def text_blob(row):
    return "\n".join([
        row.get("event_name") or "",
        row.get("venue") or "",
        row.get("source_video_title") or "",
        row.get("description_excerpt") or "",
        row.get("source_channel_title") or "",
    ])


def is_out_of_scope(row):
    blob = text_blob(row)
    return bool(OUT_OF_SCOPE_RE.search(blob))


def public_event_rows(payload):
    return payload if isinstance(payload, list) else []


def match_public_event(row, public_events):
    blob = norm(text_blob(row))
    best = None
    for event in public_events:
        score = 0
        reasons = []
        raw_event_name = event.get("name") or ""
        event_name = norm(event.get("name"))
        venue = norm(event.get("venue"))
        if raw_event_name in GENERIC_EVENT_NAMES:
            if venue and venue in blob:
                score += 35
                reasons.append("generic_event_venue_only")
        elif event_name and event_name in blob:
            score += 70
            reasons.append("event_name_in_youtube")
        elif event_name and len(event_name) >= 6 and any(part and part in blob for part in split_event_parts(event.get("name"))):
            score += 35
            reasons.append("event_name_part")
        if venue and venue in blob:
            score += 35
            reasons.append("venue_in_youtube")
        if event.get("area") in TOKYO_23_AREAS:
            score += 5
        if score <= 0:
            continue
        candidate = {
            "name": event.get("name") or "",
            "venue": event.get("venue") or "",
            "date": event.get("date") or "",
            "date_end": event.get("date_end") or "",
            "area": event.get("area") or "",
            "score": score,
            "reasons": reasons,
        }
        if (
            best is None
            or candidate["score"] > best["score"]
            or (
                candidate["score"] == best["score"]
                and len(candidate["name"]) > len(best.get("name") or "")
            )
        ):
            best = candidate
    return best if best and best["score"] >= 70 else None


def split_event_parts(value):
    parts = []
    for part in re.split(r"(?:・|/|／| |　|「|」|『|』|【|】|\\(|\\)|（|）)", str(value or "")):
        part = norm(part)
        if len(part) >= 4:
            parts.append(part)
    return parts


def clean_song_title(value):
    value = str(value or "").strip()
    value = re.sub(r"\s*/\s*.*$", "", value)
    value = re.sub(r"^.{1,24}\s+-\s+", "", value)
    value = value.replace("盆踊り", "").strip(" -:：、。")
    return value


def planned_songs(row):
    songs = []
    seen = set()
    for song in row.get("songs") or []:
        title = clean_song_title(song.get("title") or "")
        key = norm(title)
        if not key or key in seen:
            continue
        seen.add(key)
        songs.append({
            "title": title,
            "number": song.get("number") or "",
            "url": song.get("url") or row.get("source_video_url") or "",
            "evidence_type": song.get("evidence_type") or "",
        })
    return songs


def plan_row(row, public_events):
    match = match_public_event(row, public_events)
    songs = planned_songs(row)
    if match:
        action = "append_evidence_to_existing_event"
        review_status = "既存候補"
        priority = "高" if len(songs) >= 3 else "通常"
    elif is_out_of_scope(row):
        action = "hold_out_of_public_scope"
        review_status = "対象外候補"
        priority = "低"
    elif row.get("event_date") and len(songs) >= 2:
        action = "review_new_event_candidate"
        review_status = "新規候補"
        priority = "高"
    else:
        action = "needs_research"
        review_status = "要調査"
        priority = "通常"
    return {
        "candidate_key": row.get("event_key") or "",
        "action": action,
        "review_status": review_status,
        "priority": priority,
        "youtube_event_name": row.get("event_name") or "",
        "youtube_venue": row.get("venue") or "",
        "youtube_event_date": row.get("event_date") or "",
        "source_video_url": row.get("source_video_url") or "",
        "source_video_title": row.get("source_video_title") or "",
        "source_channel_id": row.get("source_channel_id") or "",
        "source_channel_title": row.get("source_channel_title") or "",
        "thumbnail_url": row.get("thumbnail_url") or "",
        "description_excerpt": row.get("description_excerpt") or "",
        "matched_public_event": match,
        "song_count": len(songs),
        "songs": songs,
    }


def build_plan(youtube_payload, public_payload):
    events = youtube_payload.get("events") if isinstance(youtube_payload, dict) else []
    public_events = public_event_rows(public_payload)
    rows = [plan_row(row, public_events) for row in events]
    rows.sort(key=lambda row: (row["action"], -row["song_count"], row["youtube_event_date"]), reverse=False)
    counts = {}
    for row in rows:
        counts[row["action"]] = counts.get(row["action"], 0) + 1
    return {
        "generated_by": "plan_youtube_event_updates.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(YOUTUBE_EVENT_SONGS),
        "public_event_source": str(PUBLIC_EVENTS),
        "candidate_count": len(rows),
        "counts": counts,
        "rows": rows,
    }


def md_escape(value):
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def md_truncate(value, limit=90):
    value = md_escape(value)
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def render_markdown(plan):
    lines = [
        "# YouTubeイベント更新プラン",
        "",
        f"- 候補: {plan['candidate_count']}件",
    ]
    for action, count in sorted(plan["counts"].items()):
        lines.append(f"- {action}: {count}件")
    lines.extend([
        "",
        "| action | 優先 | 日付 | 曲数 | YouTube候補 | 既存一致 | URL |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ])
    for row in plan["rows"]:
        match = row.get("matched_public_event") or {}
        lines.append(
            "| "
            f"{md_escape(row['action'])} | "
            f"{md_escape(row['priority'])} | "
            f"{md_escape(row['youtube_event_date'])} | "
            f"{row['song_count']} | "
            f"{md_truncate(row['youtube_event_name'])} | "
            f"{md_truncate(match.get('name') or '')} | "
            f"{md_escape(row['source_video_url'])} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--youtube-events", default=str(YOUTUBE_EVENT_SONGS))
    parser.add_argument("--public-events", default=str(PUBLIC_EVENTS))
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--md-out", default=str(MARKDOWN_OUT))
    args = parser.parse_args()

    plan = build_plan(load_json(args.youtube_events, {}), load_json(args.public_events, []))
    plan["source"] = args.youtube_events
    plan["public_event_source"] = args.public_events
    atomic_write_json(args.out, plan)
    atomic_write_text(args.md_out, render_markdown(plan))
    print(
        "[youtube-event-plan] "
        f"candidates={plan['candidate_count']} "
        f"counts={plan['counts']} -> {args.out}, {args.md_out}"
    )


if __name__ == "__main__":
    main()
