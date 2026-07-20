#!/usr/bin/env python3
"""Adapt pending active-video reviews into the unified review inbox.

The adapter itself is a pure transformer.  The snapshot entry point loads the
same song vocabulary used by the legacy console so parent-event song clips
that are already auto-resolved stay out of the human queue.
"""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qs, urlsplit

from review_console.data import load_known_song_terms
from review_inbox_source_adapter import load_adapted_source, write_adapted_snapshot


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "data" / "youtube_active_video_review.json"
DEFAULT_OUTPUT = ROOT / "data" / "review_inbox_adapted" / "youtube_active_video.json"
SONG_VOCABULARY_PATHS = (
    Path("data/bon_odori_master.sqlite"),
    Path("data/youtube_song_master.json"),
)
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
PENDING_ACTIONS = {
    "needs_official_confirmation": "needs_research",
    "review_video_evidence": "add_song_evidence",
    "bon_component_of_parent_event": "add_song_evidence",
}
CLOSED_ACTIONS = {"append_existing_event", "ignore", "out_of_scope"}
GENERIC_SONG_TERMS = {
    "盆踊り", "bon dance", "bon odori", "音頭", "民踊", "おどり", "踊り",
    "まつり", "祭り", "さくら", "春", "夏", "秋", "冬", "東京", "浅草", "青山",
}


class YouTubeActiveVideoAdapter:
    """Pure active-video adapter with an injected immutable song vocabulary."""

    source_id = "youtube_evidence"

    def __init__(self, known_song_terms: Mapping[str, str] | None = None):
        self.known_song_terms = dict(known_song_terms or {})

    def adapt(self, payload: Any) -> Iterable[Mapping[str, Any]]:
        if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
            raise ValueError("YouTube active video payload requires rows list")
        items = []
        for row in payload["rows"]:
            if self.is_pending(row):
                items.append(self.adapt_row(row))
        return items

    def is_pending(self, row: Any) -> bool:
        if not isinstance(row, dict):
            raise TypeError("YouTube active video rows must be objects")
        action = str(row.get("action") or "").strip()
        if action in CLOSED_ACTIONS:
            return False
        if action not in PENDING_ACTIONS:
            raise ValueError(f"unsupported YouTube active video action: {action or 'missing'}")
        if action == "bon_component_of_parent_event" and has_known_song_evidence(
            row, self.known_song_terms
        ):
            return False
        return True

    def adapt_row(self, row: Mapping[str, Any]) -> dict[str, Any]:
        action = str(row.get("action") or "").strip()
        if action not in PENDING_ACTIONS:
            raise ValueError(f"unsupported pending YouTube active video action: {action}")
        video_id = canonical_video_id(row)
        year = target_year(row)
        matched = row.get("matched_public_event")
        matched = matched if isinstance(matched, dict) else {}
        component = row.get("parent_event_component")
        component = component if isinstance(component, dict) else {}
        event_name = str(
            matched.get("name")
            or component.get("component_label")
            or component.get("parent_event_name")
            or row.get("title_event_name_candidate")
            or ""
        ).strip()
        title = str(row.get("title") or event_name or video_id).strip()
        if not title:
            raise ValueError("YouTube active video row requires a review title")
        priority = str(row.get("priority") or "normal").strip().casefold()
        return {
            "kind": "youtube_evidence",
            "domain": "YouTube",
            "time_scope": "historical",
            "priority_label": "P1" if priority == "high" else "P2",
            "priority_score": None,
            "title": title,
            "event_name": event_name,
            "venue": str(matched.get("venue") or "").strip(),
            "event_year": year,
            "source_key": stable_source_key(video_id, row, year),
            "source_url": f"https://www.youtube.com/watch?v={video_id}",
            "recommended_action": PENDING_ACTIONS[action],
            "payload": dict(row),
        }


def normalize_song_text(value: Any) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"[\s　]+", "", text)
    text = re.sub(r"[「」『』【】\[\]()（）・･|｜/／,，、.。:：#＃\"'“”]", "", text)
    return re.sub(r"[\-ー–—!！?？]", "", text)


def has_known_song_evidence(row: Mapping[str, Any], known_song_terms: Mapping[str, str]) -> bool:
    if has_structured_song_evidence(row):
        return True
    values = [str(row.get("title") or "")]
    title_candidates = row.get("title_song_candidates")
    if isinstance(title_candidates, list):
        values.extend(str(value or "") for value in title_candidates)
    haystack = normalize_song_text(" ".join(values))
    if not haystack:
        return False
    for norm, canonical in sorted(known_song_terms.items(), key=lambda item: len(item[0]), reverse=True):
        if str(canonical).casefold() in GENERIC_SONG_TERMS:
            continue
        if norm and norm in haystack:
            return True
    return False


def has_structured_song_evidence(row: Mapping[str, Any]) -> bool:
    songs = row.get("songs")
    if isinstance(songs, list):
        for song in songs:
            value = (
                song.get("name") or song.get("song_name") or song.get("title")
                if isinstance(song, dict)
                else song
            )
            if str(value or "").strip():
                return True
    occurrences = row.get("setlist_occurrences")
    if isinstance(occurrences, list):
        for occurrence in occurrences:
            if not isinstance(occurrence, dict):
                continue
            setlist = occurrence.get("setlist")
            if not isinstance(setlist, list):
                continue
            for song in setlist:
                value = (
                    song.get("song_name") or song.get("name") or song.get("title")
                    if isinstance(song, dict)
                    else song
                )
                if str(value or "").strip():
                    return True
    return False


def video_id_from_url(value: Any) -> str:
    parsed = urlsplit(str(value or "").strip())
    host = (parsed.hostname or "").casefold()
    if host not in YOUTUBE_HOSTS:
        return ""
    if host == "youtu.be":
        return parsed.path.strip("/").split("/", 1)[0]
    if parsed.path.startswith("/shorts/"):
        return parsed.path.split("/shorts/", 1)[1].split("/", 1)[0]
    return (parse_qs(parsed.query).get("v") or [""])[0]


def canonical_video_id(row: Mapping[str, Any]) -> str:
    explicit = str(row.get("video_id") or "").strip()
    url_ids = {
        found
        for found in (
            video_id_from_url(row.get("video_url")),
            video_id_from_url(row.get("source_url")),
        )
        if found
    }
    if explicit and url_ids and url_ids != {explicit}:
        raise ValueError(f"YouTube video_id does not match source URL: {explicit}")
    video_id = explicit or (next(iter(url_ids)) if len(url_ids) == 1 else "")
    if not video_id:
        raise ValueError("YouTube active video row requires an immutable video_id")
    return video_id


def integer_year(value: Any) -> int | None:
    match = re.match(r"^(20\d{2})", str(value or "").strip())
    return int(match.group(1)) if match else None


def target_year(row: Mapping[str, Any]) -> int | None:
    matched = row.get("matched_public_event")
    matched = matched if isinstance(matched, dict) else {}
    return (
        integer_year(row.get("detected_event_date"))
        or integer_year(matched.get("date"))
        or integer_year(row.get("published_at"))
    )


def target_occurrence_id(row: Mapping[str, Any]) -> str:
    matched = row.get("matched_public_event")
    if isinstance(matched, dict) and matched.get("id"):
        return str(matched["id"]).strip()
    return ""


def stable_source_key(video_id: str, row: Mapping[str, Any], year: int | None) -> str:
    occurrence_id = target_occurrence_id(row)
    target = f"occurrence:{occurrence_id}" if occurrence_id else f"year:{year or 'unknown'}"
    return f"video:{video_id}|{target}"


def file_lineage(path: Path, root: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    return {
        "path": str(path.relative_to(root)),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
    }


def build_snapshot(
    input_path: Path,
    *,
    root: Path = ROOT,
    known_song_terms: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    root = Path(root)
    injected_terms = known_song_terms is not None
    terms = dict(known_song_terms) if injected_terms else load_known_song_terms(root)
    snapshot = load_adapted_source(YouTubeActiveVideoAdapter(terms), input_path)
    snapshot["write_mode"] = "snapshot_only_default_off"
    snapshot["upstream_boundary"] = "pending_active_video_reviews_only"
    snapshot["selection"] = {
        "mode": "all",
        "source_keys": [item["source_key"] for item in snapshot["items"]],
    }
    snapshot["supporting_input_lineage"] = (
        [{"mode": "injected_test_vocabulary", "term_count": len(terms)}]
        if injected_terms
        else [
            file_lineage(root / relative, root)
            for relative in SONG_VOCABULARY_PATHS
            if (root / relative).exists()
        ]
    )
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    snapshot = build_snapshot(args.input)
    write_adapted_snapshot(snapshot, args.output)
    print(
        f"YouTube active video snapshot: items={snapshot['item_count']} "
        f"input_sha256={snapshot['input_sha256']} -> {args.output}"
    )


if __name__ == "__main__":
    main()
