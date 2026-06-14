#!/usr/bin/env python3
"""Evaluate song prediction snapshots against result evidence.

This is intentionally small for the first prospective rehearsal. It reads the
generated occurrence evidence and frozen prediction snapshots, then scores only
occurrences that have complete result evidence.
"""

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def result_sets(occurrences):
    by_occurrence = {}
    for occurrence in occurrences.get("occurrences", []):
        occurrence_id = occurrence.get("occurrence_id")
        complete_reliabilities = []
        present_songs = set()
        for song in occurrence.get("songs", []):
            for evidence in song.get("evidence", []):
                if evidence.get("role") == "result" and evidence.get("setlist_complete"):
                    complete_reliabilities.append(float(evidence.get("reliability") or 1.0))
                    present_songs.add(song.get("song_name"))
        if complete_reliabilities:
            by_occurrence[occurrence_id] = {
                "present_songs": present_songs,
                "result_reliability": max(complete_reliabilities),
            }
    return by_occurrence


def prediction_evidence_index(occurrences):
    index = {}
    for occurrence in occurrences.get("occurrences", []):
        occurrence_id = occurrence.get("occurrence_id")
        for song in occurrence.get("songs", []):
            keys = []
            reliabilities = []
            for evidence in song.get("evidence", []):
                if evidence.get("role") == "prediction":
                    key = evidence.get("reliability_key") or "unknown"
                    if key not in keys:
                        keys.append(key)
                    if evidence.get("reliability") is not None:
                        reliabilities.append(float(evidence.get("reliability")))
            index[(occurrence_id, song.get("song_name"))] = {
                "reliability_keys": keys,
                "prediction_reliability": reliabilities,
            }
    return index


def summarize(rows):
    if not rows:
        return {}
    by_event = defaultdict(list)
    by_key = defaultdict(list)
    for row in rows:
        by_event[(row["event_name"], row["venue"])].append(row)
        for key in row.get("reliability_keys") or ["unknown"]:
            by_key[key].append(row)

    event_summary = []
    for (event_name, venue), items in sorted(by_event.items()):
        mean_brier = sum(item["brier"] for item in items) / len(items)
        event_summary.append({
            "event_name": event_name,
            "venue": venue,
            "scored_count": len(items),
            "actual_present_count": sum(1 for item in items if item["actual_present"]),
            "mean_probability": round(sum(item["probability"] for item in items) / len(items), 4),
            "mean_soft_label": round(sum(item["soft_label"] for item in items) / len(items), 4),
            "mean_brier": round(mean_brier, 6),
        })

    reliability_summary = []
    for key, items in sorted(by_key.items()):
        mean_soft_label = sum(item["soft_label"] for item in items) / len(items)
        mean_probability = sum(item["probability"] for item in items) / len(items)
        mean_brier = sum(item["brier"] for item in items) / len(items)
        reliability_summary.append({
            "reliability_key": key,
            "scored_count": len(items),
            "actual_present_count": sum(1 for item in items if item["actual_present"]),
            "mean_probability": round(mean_probability, 4),
            "mean_soft_label": round(mean_soft_label, 4),
            "mean_brier": round(mean_brier, 6),
            "suggested_reliability": round(mean_soft_label, 4),
            "suggested_delta": round(mean_soft_label - mean_probability, 4),
        })
    return {
        "by_event": event_summary,
        "by_reliability_key": reliability_summary,
    }


def evaluate(snapshot, occurrences):
    results = result_sets(occurrences)
    evidence_index = prediction_evidence_index(occurrences)
    rows = []
    by_occurrence = defaultdict(list)
    for item in snapshot.get("snapshots", []):
        by_occurrence[item.get("occurrence_id")].append(item)

    for occurrence_id, result in results.items():
        for item in by_occurrence.get(occurrence_id, []):
            probability = float(item.get("probability") or 0) / 100.0
            reliability = result["result_reliability"]
            actual = item.get("song_name") in result["present_songs"]
            soft_label = reliability if actual else 1.0 - reliability
            brier = (probability - soft_label) ** 2
            rows.append({
                "snapshot_id": item.get("snapshot_id"),
                "occurrence_id": occurrence_id,
                "event_name": item.get("event_name"),
                "venue": item.get("venue"),
                "song_name": item.get("song_name"),
                "probability": round(probability, 4),
                "soft_label": round(soft_label, 4),
                "actual_present": actual,
                "brier": round(brier, 6),
                **evidence_index.get((occurrence_id, item.get("song_name")), {}),
            })
    mean_brier = sum(row["brier"] for row in rows) / len(rows) if rows else None
    basis_counts = Counter(row.get("event_name") for row in rows)
    return {
        "snapshot_count": snapshot.get("snapshot_count", 0),
        "scored_count": len(rows),
        "mean_brier": None if mean_brier is None else round(mean_brier, 6),
        "scored_event_count": len(basis_counts),
        "summary": summarize(rows),
        "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, default=Path("data/song_prediction_snapshots.json"))
    parser.add_argument("--occurrences", type=Path, default=Path("data/song_occurrences.json"))
    parser.add_argument("--out", type=Path, default=Path("data/song_prediction_calibration.json"))
    args = parser.parse_args()

    result = evaluate(
        load_json(args.snapshot, {}),
        load_json(args.occurrences, {}),
    )
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "曲予測較正: "
        f"scored={result['scored_count']} "
        f"mean_brier={result['mean_brier']} -> {args.out}"
    )


if __name__ == "__main__":
    main()
