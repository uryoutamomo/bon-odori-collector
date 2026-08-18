#!/usr/bin/env python3
"""Apply frozen song-identity decisions to the existing public projection only.

The Master RDB remains the canonical evidence store.  This bounded projection
step intentionally keeps the existing public occurrence inventory, so a song
cleanup cannot accidentally publish unrelated observed occurrences.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DEFAULT_SOURCE = DATA / "public" / "event_song_occurrences_public.json"
DEFAULT_EVENTS_PUBLIC = DATA / "public" / "events_public.json"
DEFAULT_DECISIONS = DATA / "publication_gap_song_identity_llm_decisions.json"
DEFAULT_SONG_MASTER = DATA / "youtube_song_master.json"
DEFAULT_OUT = DATA / "review_backlog_song_projection_preview.json"
DEFAULT_EVENTS_OUT = DATA / "review_backlog_events_public_preview.json"
DEFAULT_SONG_MASTER_OUT = DATA / "review_backlog_youtube_song_master_preview.json"
DEFAULT_REPORT = DATA / "review_backlog_song_projection_report.json"
CONFIRM_PHRASE = "APPLY REVIEW BACKLOG SONG PROJECTION"


def normalize_text(value: object) -> str:
    value = re.sub(r"\s+", "", str(value or ""))
    value = re.sub(r"[\W_]+", "", value)
    return value.casefold()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def merge_song_rows(current: dict, incoming: dict) -> dict:
    merged = dict(current)
    current_probability = current.get("probability")
    incoming_probability = incoming.get("probability")
    probabilities = [
        value for value in (current_probability, incoming_probability) if value is not None
    ]
    merged["probability"] = max(probabilities) if probabilities else None
    merged["evidence_count"] = int(current.get("evidence_count") or 0) + int(
        incoming.get("evidence_count") or 0
    )
    merged["speaker_count"] = max(
        int(current.get("speaker_count") or 0),
        int(incoming.get("speaker_count") or 0),
    )
    merged["setlist_complete"] = bool(
        current.get("setlist_complete") or incoming.get("setlist_complete")
    )
    merged["prediction_reliability"] = sorted(
        set(current.get("prediction_reliability") or [])
        | set(incoming.get("prediction_reliability") or [])
    )
    merged["evidence_urls"] = list(
        dict.fromkeys(
            (current.get("evidence_urls") or []) + (incoming.get("evidence_urls") or [])
        )
    )
    current_score = (
        current_probability if current_probability is not None else -1,
        int(current.get("evidence_count") or 0),
    )
    incoming_score = (
        incoming_probability if incoming_probability is not None else -1,
        int(incoming.get("evidence_count") or 0),
    )
    if incoming_score > current_score:
        merged["basis"] = incoming.get("basis")
        merged["basis_label"] = incoming.get("basis_label")
    return {key: value for key, value in merged.items() if value is not None}


def decision_index(payload: dict) -> dict[str, dict]:
    rows = payload.get("decisions") or []
    index = {row["raw_song_name"]: row for row in rows}
    if len(rows) != len(index) or len(index) != 147:
        raise ValueError(f"expected 147 unique song decisions, got {len(index)}")
    return index


def transform(public_payload: dict, decisions_payload: dict, *, generated_at: str):
    decisions = decision_index(decisions_payload)
    found = set()
    renamed_rows = 0
    removed_rows = 0
    collapsed_rows = 0
    changed_occurrences = 0
    output_occurrences = []

    for occurrence in public_payload.get("occurrences") or []:
        output = dict(occurrence)
        songs_by_name: dict[str, dict] = {}
        original_songs = occurrence.get("songs") or []
        for source_song in original_songs:
            song = dict(source_song)
            raw_name = str(song.get("name") or "")
            decision = decisions.get(raw_name)
            if decision:
                found.add(raw_name)
                if decision["decision"] == "曲名ノイズとして除外":
                    removed_rows += 1
                    continue
                target = decision.get("target_song_name") or raw_name
                if target != raw_name:
                    renamed_rows += 1
                song["name"] = target
            key = normalize_text(song.get("name"))
            existing = songs_by_name.get(key)
            if existing is None:
                songs_by_name[key] = song
            else:
                songs_by_name[key] = merge_song_rows(existing, song)
                collapsed_rows += 1
        output["songs"] = sorted(
            songs_by_name.values(),
            key=lambda row: (-(row.get("probability") or 0), row.get("name") or ""),
        )
        if output["songs"] != original_songs:
            changed_occurrences += 1
        output_occurrences.append(output)

    missing = sorted(set(decisions) - found)
    if missing:
        raise ValueError(
            f"public projection no longer contains {len(missing)} frozen decision titles: {missing[:10]}"
        )
    result = dict(public_payload)
    result["generated_by"] = "scripts/apply_review_backlog_song_projection.py"
    result["generated_at"] = generated_at
    result["occurrences"] = output_occurrences
    before_count = sum(
        len(row.get("songs") or []) for row in public_payload.get("occurrences") or []
    )
    after_count = sum(len(row.get("songs") or []) for row in output_occurrences)
    report = {
        "generated_by": "scripts/apply_review_backlog_song_projection.py",
        "generated_at": generated_at,
        "mode": "bounded_existing_public_projection",
        "summary": {
            "decision_count": len(decisions),
            "decision_titles_found": len(found),
            "occurrence_count_before": len(public_payload.get("occurrences") or []),
            "occurrence_count_after": len(output_occurrences),
            "song_relation_count_before": before_count,
            "song_relation_count_after": after_count,
            "changed_occurrence_count": changed_occurrences,
            "renamed_song_row_count": renamed_rows,
            "removed_noise_row_count": removed_rows,
            "collapsed_duplicate_row_count": collapsed_rows,
            "unrelated_occurrences_added": 0,
            "unrelated_occurrences_removed": 0,
        },
    }
    return result, report


def transform_event_cards(events: list[dict], decisions_payload: dict):
    decisions = decision_index(decisions_payload)
    changed_events = 0
    renamed_rows = 0
    removed_rows = 0
    collapsed_rows = 0
    output = []
    for event in events:
        updated = dict(event)
        original_songs = event.get("songs") or []
        songs_by_name = {}
        for source_song in original_songs:
            song = dict(source_song) if isinstance(source_song, dict) else {"name": source_song}
            raw_name = str(song.get("name") or "")
            decision = decisions.get(raw_name)
            if decision:
                if decision["decision"] == "曲名ノイズとして除外":
                    removed_rows += 1
                    continue
                target = decision.get("target_song_name") or raw_name
                if target != raw_name:
                    renamed_rows += 1
                song["name"] = target
            key = normalize_text(song.get("name"))
            existing = songs_by_name.get(key)
            if existing is None:
                songs_by_name[key] = song
            else:
                songs_by_name[key] = merge_song_rows(existing, song)
                collapsed_rows += 1
        updated["songs"] = sorted(
            songs_by_name.values(),
            key=lambda row: (-(row.get("probability") or 0), row.get("name") or ""),
        )
        if updated["songs"] != original_songs:
            changed_events += 1
        output.append(updated)
    return output, {
        "event_count_before": len(events),
        "event_count_after": len(output),
        "changed_event_count": changed_events,
        "renamed_song_row_count": renamed_rows,
        "removed_noise_row_count": removed_rows,
        "collapsed_duplicate_row_count": collapsed_rows,
        "non_song_fields_changed": 0,
    }


def reviewed_master_row(
    name: str,
    raw_name: str,
    public_projection: dict,
    *,
    status: str,
    review_reason: str,
):
    matching = []
    for occurrence in public_projection.get("occurrences") or []:
        for song in occurrence.get("songs") or []:
            if song.get("name") == name:
                matching.append((occurrence, song))
    urls = list(
        dict.fromkeys(
            url
            for _, song in matching
            for url in song.get("evidence_urls") or []
        )
    )
    aliases = [raw_name] if raw_name != name else []
    return {
        "song_name": name,
        "aliases": aliases,
        "evidence_count": sum(
            int(song.get("evidence_count") or 0) for _, song in matching
        ),
        "good_evidence_count": 0,
        "years": sorted(
            {
                int(occurrence["year"])
                for occurrence, _ in matching
                if occurrence.get("year")
            }
        ),
        "reliability_counts": {"llm_reviewed_public_occurrence": len(matching)},
        "source_counts": {"event_song_occurrences_public": len(matching)},
        "speaker_count": max(
            [int(song.get("speaker_count") or 0) for _, song in matching] or [0]
        ),
        "occurrence_count": len(
            {occurrence.get("occurrence_id") for occurrence, _ in matching}
        ),
        "evidence_url_count": len(urls),
        "status": status,
        "public_ready": False,
        "review_reason": review_reason,
        "source_label": "公開イベント曲目 / LLMレビュー",
        "description": "盆踊り曲目のレビュー済み候補です。",
        "bon_usage_rank": "要確認",
        "bon_usage_score": 0,
        "song_genre_key": "needs_research",
        "song_genre": "要調査",
        "genre_confidence": "低",
        "genre_basis": "レビュー済み候補のため要調査",
        "genre_review_status": "要調査",
        "sample_events": list(
            dict.fromkeys(
                occurrence.get("event_name")
                for occurrence, _ in matching
                if occurrence.get("event_name")
            )
        )[:5],
        "sample_venues": list(
            dict.fromkeys(
                occurrence.get("venue")
                for occurrence, _ in matching
                if occurrence.get("venue")
            )
        )[:5],
        "youtube_urls": urls[:5],
    }


def transform_song_master(
    master_payload: dict,
    decisions_payload: dict,
    public_projection: dict,
    *,
    generated_at: str,
):
    decisions = decisions_payload.get("decisions") or []
    rows = [dict(row) for row in master_payload.get("songs") or []]
    by_name = {row.get("song_name"): row for row in rows}
    alias_updates = 0
    candidate_additions = 0
    target_bridge_additions = 0

    for decision in decisions:
        if decision["decision"] != "既存曲へ統合":
            continue
        target = by_name.get(decision.get("target_song_name"))
        if target is None:
            catalog = decision.get("target_catalog_match") or {}
            status = "要確認" if catalog.get("status") in {"候補", "要確認"} else "有効"
            target = reviewed_master_row(
                decision["target_song_name"],
                decision["raw_song_name"],
                public_projection,
                status=status,
                review_reason="Master RDBの既存曲へ統合済み。公開昇格は別レビュー。",
            )
            rows.append(target)
            by_name[target["song_name"]] = target
            target_bridge_additions += 1
        alias = decision["raw_song_name"]
        aliases = list(target.get("aliases") or [])
        if alias != target["song_name"] and alias not in aliases:
            aliases.append(alias)
            target["aliases"] = sorted(aliases)
            alias_updates += 1

    for decision in decisions:
        if decision["decision"] != "新規曲候補として維持":
            continue
        name = decision["target_song_name"]
        if name in by_name:
            continue
        row = reviewed_master_row(
            name,
            decision["raw_song_name"],
            public_projection,
            status="要確認",
            review_reason="LLMレビュー済み新規曲候補。公開昇格は別レビュー。",
        )
        rows.append(row)
        by_name[name] = row
        candidate_additions += 1

    result = dict(master_payload)
    result["generated_by"] = "scripts/apply_review_backlog_song_projection.py"
    result["generated_at"] = generated_at
    result["songs"] = rows
    result["song_count"] = len(rows)
    result["public_ready_count"] = sum(bool(row.get("public_ready")) for row in rows)
    result["review_count"] = len(rows) - result["public_ready_count"]
    return result, {
        "alias_updates": alias_updates,
        "candidate_additions": candidate_additions,
        "target_bridge_additions": target_bridge_additions,
        "song_count_before": len(master_payload.get("songs") or []),
        "song_count_after": len(rows),
    }


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--events-public", type=Path, default=DEFAULT_EVENTS_PUBLIC)
    parser.add_argument("--decisions", type=Path, default=DEFAULT_DECISIONS)
    parser.add_argument("--song-master", type=Path, default=DEFAULT_SONG_MASTER)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--events-out", type=Path, default=DEFAULT_EVENTS_OUT)
    parser.add_argument("--song-master-out", type=Path, default=DEFAULT_SONG_MASTER_OUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    if args.apply and args.confirm != CONFIRM_PHRASE:
        parser.error(f"--apply requires --confirm '{CONFIRM_PHRASE}'")
    decisions_payload = load(args.decisions)
    result, report = transform(
        load(args.source), decisions_payload, generated_at=args.generated_at
    )
    events_public, events_summary = transform_event_cards(
        load(args.events_public), decisions_payload
    )
    song_master, song_master_summary = transform_song_master(
        load(args.song_master),
        decisions_payload,
        result,
        generated_at=args.generated_at,
    )
    report["song_master"] = song_master_summary
    report["events_public"] = events_summary
    if args.apply:
        backup = args.source.with_suffix(args.source.suffix + ".pre-llm-review.bak")
        song_master_backup = args.song_master.with_suffix(
            args.song_master.suffix + ".pre-llm-review.bak"
        )
        events_backup = args.events_public.with_suffix(
            args.events_public.suffix + ".pre-llm-review.bak"
        )
        shutil.copy2(args.source, backup)
        shutil.copy2(args.song_master, song_master_backup)
        shutil.copy2(args.events_public, events_backup)
        write_json(args.source, result)
        write_json(args.song_master, song_master)
        write_json(args.events_public, events_public)
        report["mode"] = "apply"
        report["source_written"] = str(args.source)
        report["backup"] = str(backup)
        report["song_master_written"] = str(args.song_master)
        report["song_master_backup"] = str(song_master_backup)
        report["events_public_written"] = str(args.events_public)
        report["events_public_backup"] = str(events_backup)
    else:
        write_json(args.out, result)
        write_json(args.song_master_out, song_master)
        write_json(args.events_out, events_public)
        report["preview"] = str(args.out)
        report["song_master_preview"] = str(args.song_master_out)
        report["events_public_preview"] = str(args.events_out)
    write_json(args.report, report)
    print(
        json.dumps(
            {
                "projection": report["summary"],
                "song_master": song_master_summary,
                "events_public": events_summary,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
