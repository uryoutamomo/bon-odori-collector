#!/usr/bin/env python3
"""Build review rows for adopted data that is not aligned with public JSON."""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
SITE_ROOT = ROOT.parent / "bon-odori-site"
OUT_PATH = ROOT / "data" / "publication_gap_review.json"


def read_json(path: Path, default: Any) -> Any:
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def unique_texts(values: list[Any]) -> list[str]:
    return sorted({str(value).strip() for value in values if str(value).strip()})


def public_terms(public_glossary: dict[str, Any], *, category: str | None = None) -> list[str]:
    items = public_glossary.get("items")
    if not isinstance(items, list):
        return []
    terms: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if category and item.get("category") != category:
            continue
        term = str(item.get("term") or "").strip()
        if term:
            terms.append(term)
    return unique_texts(terms)


def song_map(master: dict[str, Any]) -> dict[str, dict[str, Any]]:
    songs = master.get("songs")
    if not isinstance(songs, list):
        return {}
    return {
        str(song.get("song_name") or "").strip(): song
        for song in songs
        if isinstance(song, dict) and str(song.get("song_name") or "").strip()
    }


def build_rows() -> dict[str, Any]:
    glossary_review = read_json(ROOT / "data" / "glossary_v2_oto123_review_result.json", {})
    weekly_terms = read_json(ROOT / "data" / "weekly_harvest_human13_apply_result.json", {})
    weekly_songs = read_json(ROOT / "data" / "weekly_song_review_apply_result.json", {})
    song_master = read_json(ROOT / "data" / "youtube_song_master.json", {})
    occurrences = read_json(ROOT / "data" / "public" / "event_song_occurrences_public.json", {})
    public_glossary = read_json(SITE_ROOT / "data" / "glossary_public.json", {})
    song_priors = read_json(SITE_ROOT / "data" / "song_priors.json", {})

    public_all_terms = public_terms(public_glossary)
    public_song_terms = public_terms(public_glossary, category="曲名")

    accepted_terms = unique_texts(
        [
            row.get("term")
            for row in glossary_review.get("accepted", [])
            if isinstance(row, dict)
        ]
    )
    weekly_applied_terms = unique_texts(
        [
            row.get("term")
            for row in weekly_terms.get("applied_terms", [])
            if isinstance(row, dict)
        ]
    )
    songs_by_name = song_map(song_master)
    master_names = unique_texts(list(songs_by_name))
    public_ready_song_names = unique_texts(
        [
            name
            for name, row in songs_by_name.items()
            if row.get("public_ready") is True
        ]
    )
    weekly_updated_song_names = unique_texts(
        [
            row.get("song_name")
            for row in weekly_songs.get("updated", [])
            if isinstance(row, dict)
        ]
    )

    occurrence_names: list[str] = []
    for occurrence in occurrences.get("occurrences", []):
        if not isinstance(occurrence, dict):
            continue
        for song in occurrence.get("songs", []):
            if isinstance(song, dict) and str(song.get("name") or "").strip():
                occurrence_names.append(str(song["name"]).strip())
    occurrence_counts = Counter(occurrence_names)
    occurrence_unique = unique_texts(occurrence_names)

    priors_songs = unique_texts(list((song_priors.get("songs") or {}).keys()))

    rows: list[dict[str, Any]] = []

    for term in sorted(set(accepted_terms) - set(public_all_terms)):
        rows.append(
            {
                "gap_id": f"glossary_v2_missing_public:{term}",
                "gap_type": "採用済み用語が公開辞書にない",
                "domain": "用語",
                "term": term,
                "recommended_action": "needs_research",
                "priority_label": "P1",
                "reason": "用語集v2で採用済みですが、公開サイト用 glossary_public.json に見当たりません。",
                "source_file": "data/glossary_v2_oto123_review_result.json",
                "public_file": "bon-odori-site/data/glossary_public.json",
            }
        )

    for term in sorted(set(weekly_applied_terms) - set(public_all_terms)):
        rows.append(
            {
                "gap_id": f"weekly_term_missing_public:{term}",
                "gap_type": "週次採用用語が公開辞書にない",
                "domain": "用語",
                "term": term,
                "recommended_action": "needs_research",
                "priority_label": "P1",
                "reason": "週次レビューで反映済みですが、公開サイト用 glossary_public.json に見当たりません。",
                "source_file": "data/weekly_harvest_human13_apply_result.json",
                "public_file": "bon-odori-site/data/glossary_public.json",
            }
        )

    for song_name in sorted(set(public_ready_song_names) - set(public_song_terms)):
        rows.append(
            {
                "gap_id": f"public_ready_song_missing_public:{song_name}",
                "gap_type": "公開可の曲が公開辞書にない",
                "domain": "曲",
                "term": song_name,
                "song_name": song_name,
                "recommended_action": "needs_research",
                "priority_label": "P0",
                "reason": "曲マスタでは public_ready=true ですが、公開サイト用 glossary_public.json の曲名カテゴリに見当たりません。",
                "source_file": "data/youtube_song_master.json",
                "public_file": "bon-odori-site/data/glossary_public.json",
            }
        )

    for song_name in sorted(set(weekly_updated_song_names) - set(public_song_terms)):
        master_row = songs_by_name.get(song_name, {})
        rows.append(
            {
                "gap_id": f"weekly_song_updated_unpublished:{song_name}",
                "gap_type": "週次採用曲が公開辞書にない",
                "domain": "曲",
                "term": song_name,
                "song_name": song_name,
                "recommended_action": "needs_research",
                "priority_label": "P1",
                "reason": "週次曲レビューで更新済みですが、公開サイト用 glossary_public.json の曲名カテゴリに見当たりません。public_ready 判定または公開生成条件の確認対象です。",
                "public_ready": master_row.get("public_ready"),
                "review_reason": master_row.get("review_reason", ""),
                "status": master_row.get("status", ""),
                "evidence_count": master_row.get("evidence_count", ""),
                "source_file": "data/weekly_song_review_apply_result.json",
                "public_file": "bon-odori-site/data/glossary_public.json",
            }
        )

    for song_name in sorted(set(occurrence_unique) - set(master_names)):
        rows.append(
            {
                "gap_id": f"public_occurrence_song_not_in_master:{song_name}",
                "gap_type": "公開曲実績の曲名が曲マスタにない",
                "domain": "曲実績",
                "term": song_name,
                "song_name": song_name,
                "recommended_action": "needs_research",
                "priority_label": "P2",
                "reason": "公開 event_song_occurrences_public.json に出ていますが、曲マスタ youtube_song_master.json に同名曲がありません。YouTubeタイトル断片や表記ゆれの掃除対象です。",
                "occurrence_count": occurrence_counts[song_name],
                "source_file": "data/public/event_song_occurrences_public.json",
                "master_file": "data/youtube_song_master.json",
            }
        )

    summary = {
        "accepted_glossary_v2_count": len(accepted_terms),
        "weekly_applied_term_count": len(weekly_applied_terms),
        "public_glossary_count": len(public_all_terms),
        "public_song_term_count": len(public_song_terms),
        "song_master_count": len(master_names),
        "public_ready_song_count": len(public_ready_song_names),
        "weekly_updated_song_count": len(weekly_updated_song_names),
        "public_occurrence_unique_song_count": len(occurrence_unique),
        "song_priors_count": len(priors_songs),
        "accepted_glossary_v2_missing_public": len(set(accepted_terms) - set(public_all_terms)),
        "weekly_applied_terms_missing_public": len(set(weekly_applied_terms) - set(public_all_terms)),
        "public_ready_songs_missing_public": len(set(public_ready_song_names) - set(public_song_terms)),
        "weekly_updated_songs_missing_public": len(set(weekly_updated_song_names) - set(public_song_terms)),
        "public_occurrence_songs_not_in_master": len(set(occurrence_unique) - set(master_names)),
        "song_priors_not_public_ready": len(set(priors_songs) - set(public_ready_song_names)),
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": "build_publication_gap_review.py",
        "summary": summary,
        "rows": rows,
    }


def main() -> None:
    payload = build_rows()
    write_json(OUT_PATH, payload)
    print(
        "publication gap review: "
        f"rows={len(payload['rows'])} "
        f"path={OUT_PATH.relative_to(ROOT)}"
    )


if __name__ == "__main__":
    main()
