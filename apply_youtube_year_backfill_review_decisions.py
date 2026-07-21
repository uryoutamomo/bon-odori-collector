#!/usr/bin/env python3
"""Apply Koto-reviewed yearly YouTube backfill decisions to local evidence files."""

import argparse
import json
import re
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from youtube_channels.backfill_youtube_descriptions import load_env_value
from youtube_channels.discover_youtube_channels import (
    enrich_video_candidate,
    extract_chapter_setlist,
    filter_numbered_setlist,
    fetch_video_snippets,
    merge_setlist_candidates,
)
from event_series_normalization import series_event_name
from youtube_channels.extract_youtube_setlists import extract_setlist, parse_youtube_event_date
from manual_apply_guards import LOCAL_EVIDENCE_ONE_OFF_CONFIRMATION, require_confirmation


DATA = Path("data")
DECISIONS = DATA / "youtube_year_backfill_review_decisions_koto_2026-06-20.json"
CANDIDATES = DATA / "youtube_year_backfill_candidates.json"
MANUAL_EVIDENCE = DATA / "song_evidence_manual.json"
OUT = DATA / "youtube_year_backfill_review_apply_result.json"
OUT_MD = DATA / "youtube_year_backfill_review_apply_result.md"
SOURCE = "youtube_year_backfill_review"
ACCEPT_SONG_DECISIONS = {"accept_with_songs", "accept_with_songs_existing_occurrence"}


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


def video_id_from_url(url):
    match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{6,})", str(url or ""))
    return match.group(1) if match else ""


def normalize_song_title(value):
    value = re.sub(r"\s+", " ", str(value or "")).strip()
    value = value.strip("\"'“”「」『』【】")
    return value


def stable_song_key(value):
    return re.sub(r"\W+", "", normalize_song_title(value)).casefold()


def candidate_by_video(candidates):
    rows = {}
    for row in candidates.get("candidates") or []:
        video_id = row.get("video_id") or video_id_from_url(row.get("video_url"))
        if video_id:
            rows[video_id] = row
    return rows


def decision_video_ids(decisions):
    ids = []
    for decision in decisions.get("decisions") or []:
        for video in decision.get("videos_detail") or []:
            video_id = video_id_from_url(video.get("url"))
            if video_id and video_id not in ids:
                ids.append(video_id)
    return ids


def fetch_enriched_videos(video_ids, api_key, candidate_map):
    snippets = fetch_video_snippets(video_ids, api_key)
    rows = {}
    for video_id in video_ids:
        snippet = snippets.get(video_id) or {}
        candidate = candidate_map.get(video_id) or {}
        video = {
            "video_id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "title": snippet.get("title") or candidate.get("title") or "",
            "description": snippet.get("description") or "",
            "channel_id": snippet.get("channelId") or candidate.get("channel_id") or "",
            "channel_title": snippet.get("channelTitle") or candidate.get("channel_title") or "",
            "published_at": snippet.get("publishedAt") or candidate.get("published_at") or "",
            "thumbnail_url": candidate.get("thumbnail_url") or "",
        }
        if snippet:
            row = enrich_video_candidate(video)
            numbered = filter_numbered_setlist(extract_setlist(video.get("description") or ""))
            chapters = extract_chapter_setlist(video.get("description") or "")
            row["setlist"] = merge_setlist_candidates(numbered, chapters)
            row["setlist_count"] = len(row["setlist"])
        else:
            row = {
                **video,
                "setlist_count": candidate.get("setlist_count") or 0,
                "setlist_sample": candidate.get("setlist_sample") or [],
                "setlist": candidate.get("setlist_sample") or [],
                "event_date": candidate.get("detected_event_date") or "",
                "description_excerpt": candidate.get("description_excerpt") or "",
            }
        rows[video_id] = row
    return rows, snippets


def fallback_event_date(decision, enriched_videos):
    if decision.get("matched_event_date"):
        return decision["matched_event_date"]
    if decision.get("event_date"):
        return decision["event_date"]
    texts = []
    for video in enriched_videos:
        texts.extend([video.get("description") or "", video.get("title") or ""])
    event_date = parse_youtube_event_date(*texts)
    if event_date:
        return event_date
    return f"{int(decision['target_year']):04d}-01-01"


def songs_for_video(video):
    songs = []
    seen = set()
    for item in video.get("setlist") or video.get("setlist_sample") or []:
        title = normalize_song_title(item.get("title") or "")
        key = stable_song_key(title)
        if not title or not key or key in seen:
            continue
        seen.add(key)
        songs.append(title)
    return songs


def source_urls_for_songs(video):
    urls = {}
    for item in video.get("setlist") or video.get("setlist_sample") or []:
        title = normalize_song_title(item.get("title") or "")
        if title and item.get("url"):
            urls.setdefault(title, item["url"])
    return urls


def build_accept_evidence(decision, enriched_videos, decisions_path):
    event_date = fallback_event_date(decision, enriched_videos)
    items = []
    for video in enriched_videos:
        songs = songs_for_video(video)
        if not songs:
            continue
        title = video.get("title") or ""
        video_url = video.get("url") or ""
        source_urls = source_urls_for_songs(video)
        text = (
            f"Koto review accepted YouTube year backfill. "
            f"{decision.get('reason') or ''} / source video: {title}"
        )
        items.append({
            "event_name": series_event_name(decision.get("matched_to") or decision.get("event_name") or ""),
            "venue": decision.get("venue") or "",
            "event_date": event_date,
            "event_start": event_date,
            "observed_at": (video.get("published_at") or event_date)[:10],
            "kind": "observed",
            "role": "result",
            "reliability": 0.9,
            "reliability_key": "complete_numbered_video" if len(songs) >= 3 else "partial_impression",
            "setlist_complete": len(songs) >= 3,
            "speaker": video.get("channel_title") or "youtube",
            "source": SOURCE,
            "url": video_url,
            "text": text[:240],
            "decision_file": str(decisions_path),
            "decision": decision.get("decision"),
            "source_video_title": title,
            "source_song_urls": source_urls,
            "songs": songs,
        })
    return items


def source_marker(item, decisions_path):
    return item.get("source") == SOURCE and item.get("decision_file") == str(decisions_path)


def apply_manual_evidence(manual, evidence_items, apply, decisions_path):
    evidence = list(manual.get("evidence") or [])
    before = len(evidence)
    kept = [item for item in evidence if not source_marker(item, decisions_path)]
    removed = before - len(kept)
    if apply:
        manual["evidence"] = kept + evidence_items
        manual.setdefault(
            "description",
            "Manual song evidence that should feed song_occurrences before public exports.",
        )
        manual.setdefault("version", 1)
    return removed


def build_result(decisions, candidates, decisions_path, fetch, apply, env):
    candidate_map = candidate_by_video(candidates)
    video_ids = decision_video_ids(decisions)
    enriched = {}
    fetched_count = 0
    if fetch:
        api_key = load_env_value("YOUTUBE_DATA_API_KEY", env)
        if not api_key:
            raise SystemExit("YOUTUBE_DATA_API_KEY is not set")
        enriched, snippets = fetch_enriched_videos(video_ids, api_key, candidate_map)
        fetched_count = len(snippets)
    else:
        for video_id in video_ids:
            row = candidate_map.get(video_id) or {}
            enriched[video_id] = {
                "video_id": video_id,
                "url": row.get("video_url") or f"https://www.youtube.com/watch?v={video_id}",
                "title": row.get("title") or "",
                "channel_title": row.get("channel_title") or "",
                "published_at": row.get("published_at") or "",
                "setlist_count": row.get("setlist_count") or 0,
                "setlist_sample": row.get("setlist_sample") or [],
                "setlist": row.get("setlist_sample") or [],
                "event_date": row.get("detected_event_date") or "",
                "description_excerpt": row.get("description_excerpt") or "",
            }

    evidence_items = []
    applied_groups = []
    occurrence_only = []
    skipped = []
    needs_review = []
    for decision in decisions.get("decisions") or []:
        videos = []
        for source_video in decision.get("videos_detail") or []:
            video_id = video_id_from_url(source_video.get("url"))
            if video_id and video_id in enriched:
                videos.append(enriched[video_id])
        row = {
            "event_name": decision.get("matched_to") or decision.get("event_name") or "",
            "venue": decision.get("venue") or "",
            "target_year": decision.get("target_year"),
            "decision": decision.get("decision"),
            "video_count": len(decision.get("videos_detail") or []),
            "reason": decision.get("reason") or "",
            "videos": [
                {
                    "url": video.get("url") or "",
                    "title": video.get("title") or "",
                    "setlist_count": video.get("setlist_count") or 0,
                    "song_count_applied": len(songs_for_video(video)),
                }
                for video in videos
            ],
        }
        if "要確認" in row["reason"] or "不一致" in row["reason"] or "年ズレ" in row["reason"]:
            needs_review.append(row)
        if decision.get("decision") in ACCEPT_SONG_DECISIONS:
            items = build_accept_evidence(decision, videos, decisions_path)
            evidence_items.extend(items)
            row["evidence_items"] = len(items)
            row["song_mentions_applied"] = sum(len(item.get("songs") or []) for item in items)
            row["unique_songs_applied"] = len({
                stable_song_key(song)
                for item in items
                for song in item.get("songs") or []
                if stable_song_key(song)
            })
            applied_groups.append(row)
        elif decision.get("decision") == "merge_to_existing":
            occurrence_only.append(row)
        else:
            skipped.append(row)

    manual = load_json(MANUAL_EVIDENCE, {"version": 1, "evidence": []})
    removed_existing = apply_manual_evidence(manual, evidence_items, apply, decisions_path)
    if apply:
        atomic_write_json(MANUAL_EVIDENCE, manual)

    counts = Counter(row.get("decision") for row in decisions.get("decisions") or [])
    return {
        "generated_by": "apply_youtube_year_backfill_review_decisions.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "apply" if apply else "dry_run",
        "fetched_descriptions": bool(fetch),
        "fetched_video_count": fetched_count,
        "decisions": str(decisions_path),
        "decision_counts": dict(sorted(counts.items())),
        "manual_evidence": str(MANUAL_EVIDENCE),
        "removed_existing_source_items": removed_existing,
        "new_evidence_items": len(evidence_items),
        "new_song_mentions": sum(len(item.get("songs") or []) for item in evidence_items),
        "accept_groups": applied_groups,
        "occurrence_only_groups": occurrence_only,
        "skipped_groups": skipped,
        "needs_review": needs_review,
    }


def render_markdown(result):
    lines = [
        "# YouTube年バックフィル review 適用結果",
        "",
        f"- 生成: {result['generated_at']}",
        f"- mode: {result['mode']}",
        f"- fetched_descriptions: {result['fetched_descriptions']} ({result['fetched_video_count']} videos)",
        f"- 判定内訳: {result['decision_counts']}",
        f"- manual evidence 追加: {result['new_evidence_items']} items / {result['new_song_mentions']} song mentions",
        f"- source再実行削除: {result['removed_existing_source_items']} items",
        "",
        "## accept_with_songs",
        "",
        "| event | year | videos | evidence_items | song_mentions | unique_songs |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in result["accept_groups"]:
        lines.append(
            f"| {row['event_name']} | {row['target_year']} | {row['video_count']} | "
            f"{row['evidence_items']} | {row['song_mentions_applied']} | {row['unique_songs_applied']} |"
        )
    lines.extend(["", "## occurrence only / hold", ""])
    for row in result["occurrence_only_groups"]:
        lines.append(f"- {row['event_name']} ({row['target_year']}): {row['video_count']} videos / {row['reason']}")
    lines.extend(["", "## skipped", ""])
    for row in result["skipped_groups"]:
        lines.append(f"- [{row['decision']}] {row['event_name']} ({row['target_year']}): {row['reason']}")
    if result["needs_review"]:
        lines.extend(["", "## needs_review", ""])
        for row in result["needs_review"]:
            lines.append(f"- {row['event_name']} ({row['target_year']}): {row['reason']}")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--decisions", type=Path, default=DECISIONS)
    parser.add_argument("--candidates", type=Path, default=CANDIDATES)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--markdown-out", type=Path, default=OUT_MD)
    parser.add_argument("--env", default=".env")
    parser.add_argument("--fetch-descriptions", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()
    try:
        require_confirmation(
            args.apply,
            args.confirm,
            LOCAL_EVIDENCE_ONE_OFF_CONFIRMATION,
            "YouTube year backfill manual evidence update",
        )
    except ValueError as exc:
        parser.error(str(exc))

    result = build_result(
        load_json(args.decisions, {}),
        load_json(args.candidates, {}),
        decisions_path=args.decisions,
        fetch=args.fetch_descriptions,
        apply=args.apply,
        env=args.env,
    )
    atomic_write_json(args.out, result)
    atomic_write_text(args.markdown_out, render_markdown(result))
    print(
        "youtube year backfill review decisions: "
        f"mode={result['mode']} fetched={result['fetched_video_count']} "
        f"evidence_items={result['new_evidence_items']} "
        f"song_mentions={result['new_song_mentions']} -> {args.out}"
    )


if __name__ == "__main__":
    main()
