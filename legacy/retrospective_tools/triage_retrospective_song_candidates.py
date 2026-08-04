#!/usr/bin/env python3
"""Triage retrospective X-derived song candidates into usable buckets."""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from triage_weekly_song_candidates import (
    CANONICAL_MAP,
    NOISE_EXACT,
    build_song_catalog,
    classify_candidate,
    is_song_like,
    norm,
)


SOURCE = Path("data/retrospective_harvest_candidates.json")
SONG_MASTER = Path("data/song_master_initial_registration.json")
OUT = Path("data/retrospective_song_triage.json")
OUT_MD = Path("data/retrospective_song_triage.md")
DEFAULT_MASTER_DB = Path("data/bon_odori_master.sqlite")


EXTRA_CANONICAL = {
    "炭鉱節": "炭坑節",
    "北海道ソーラン節": "ソーラン節",
    "先日の郡上おどり": "郡上おどり",
    "初めての野毛山節": "野毛山節",
    "今朝やっとらんまん踊り": "らんまん踊り",
    "勝鬨橋を渡れば築地音頭": "築地音頭",
    "今回は難解な炭坑節": "炭坑節",
    "今日は新たに炭鉱節": "炭坑節",
    "先生はやはり炭鉱節": "炭坑節",
}

REJECT_PATTERNS = (
    r"踊り$",
    r"季節$",
    r"会場$",
    r"様子$",
    r"みなさん一緒に踊り$",
    r"ご一緒に踊り$",
    r"一緒に踊り$",
    r"全員で楽しく踊り$",
    r"一日中踊り$",
    r"僕は踊り$",
    r"今日は踊り$",
    r"今週末の踊り$",
    r"先日の踊り$",
    r"ライダーの踊り$",
    r"リードの皆様の踊り$",
)

EVENT_LIKE_PATTERNS = (
    r"郡上おどり$",
    r"郡上踊り$",
    r"徳島市阿波おどり$",
    r"飛鳥山公園輪踊り$",
    r"かすがい郡上おどり$",
    r"かすがい郡上踊り$",
)


def load_json(path, default):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def existing_song_names(master):
    names = []
    for key in ("created", "skipped"):
        for row in master.get(key) or []:
            name = row.get("song_name") or row.get("name")
            if name:
                names.append(name)
    return sorted(set(names))


def clean_candidate_name(name):
    name = str(name or "").strip()
    return EXTRA_CANONICAL.get(name) or CANONICAL_MAP.get(name) or name


def evidence_text(candidate):
    return "\n".join(ev.get("text") or "" for ev in candidate.get("evidence") or [])


def is_reject_noise(name):
    if name in NOISE_EXACT:
        return True
    return any(re.search(pattern, name) for pattern in REJECT_PATTERNS)


def is_event_like_song_name(name):
    return any(re.fullmatch(pattern, name) for pattern in EVENT_LIKE_PATTERNS)


def classify_retrospective(candidate, existing_index, catalog):
    raw_name = candidate.get("display_name") or ""
    canonical = clean_candidate_name(raw_name)
    row = {"term": raw_name}
    decision, weekly_canonical, weekly_reason = classify_candidate(row, catalog)
    if weekly_canonical != raw_name:
        canonical = clean_candidate_name(weekly_canonical)

    if is_reject_noise(raw_name) and raw_name not in existing_index:
        return "reject_noise", canonical, "曲名ではなく文章断片/一般語"

    key = norm(canonical)
    if key in existing_index:
        if canonical != raw_name:
            return "existing_match", existing_index[key], f"既存曲へ正規化: {raw_name} -> {existing_index[key]}"
        return "existing_match", existing_index[key], "既存曲マスタに一致"

    score = int(candidate.get("score") or 0)
    evidence_count = int(candidate.get("evidence_count") or 0)
    speaker_count = int(candidate.get("speaker_count") or 0)
    text = evidence_text(candidate)

    if decision == "reject" or is_reject_noise(raw_name):
        return "reject_noise", canonical, weekly_reason

    if is_event_like_song_name(canonical):
        return "review", canonical, "曲名にもイベント/踊り種別にも見えるため要確認"

    if is_song_like(canonical):
        if score >= 50 and (evidence_count >= 2 or speaker_count >= 2):
            return "new_song_candidate", canonical, "複数証拠があり曲名形として強い"
        if score >= 45 and candidate.get("venue") and candidate.get("month"):
            return "review", canonical, "会場・月付きの単独曲候補"
        if re.search(r"(曲目|曲|演目|セットリスト|セトリ|踊った|練習)", text):
            return "review", canonical, "曲文脈はあるが証拠が単独"
        return "review", canonical, "曲名形だが証拠が弱い"

    return "reject_noise", canonical, "曲名としての形が弱い"


def triage(data, master, catalog):
    existing = existing_song_names(master)
    existing_index = {norm(name): name for name in existing}
    rows = []
    for candidate in data.get("candidates") or []:
        if candidate.get("kind") != "song":
            continue
        bucket, canonical, reason = classify_retrospective(candidate, existing_index, catalog)
        rows.append({
            "bucket": bucket,
            "raw_name": candidate.get("display_name") or "",
            "canonical_song_name": canonical,
            "reason": reason,
            "score": candidate.get("score", 0),
            "tier": candidate.get("tier") or "",
            "venue": candidate.get("venue") or "",
            "month": candidate.get("month") or "",
            "evidence_count": candidate.get("evidence_count") or 0,
            "speaker_count": candidate.get("speaker_count") or 0,
            "candidate_key": candidate.get("candidate_key") or "",
            "evidence_sample": evidence_text(candidate)[:500],
        })
    rows.sort(key=lambda row: (
        {"new_song_candidate": 0, "existing_match": 1, "review": 2, "reject_noise": 3}.get(row["bucket"], 9),
        -int(row.get("score") or 0),
        row["canonical_song_name"],
    ))
    counts = Counter(row["bucket"] for row in rows)
    return {
        "generated_by": "triage_retrospective_song_candidates.py",
        "source": str(SOURCE),
        "candidate_count": len(rows),
        "existing_song_count": len(existing),
        "counts": dict(sorted(counts.items())),
        "rows": rows,
    }


def markdown(result):
    lines = [
        "# Retrospective song triage",
        "",
        f"- candidate_count: {result['candidate_count']}",
        f"- existing_song_count: {result['existing_song_count']}",
        "",
        "## Counts",
        "",
    ]
    for key, value in result["counts"].items():
        lines.append(f"- {key}: {value}")
    lines.extend([
        "",
        "## New Song Candidates",
        "",
        "| song | score | evidence | venue | reason |",
        "|---|---:|---:|---|---|",
    ])
    for row in result["rows"]:
        if row["bucket"] != "new_song_candidate":
            continue
        lines.append(
            "| {song} | {score} | {evidence} | {venue} | {reason} |".format(
                song=row["canonical_song_name"].replace("|", " "),
                score=row["score"],
                evidence=row["evidence_count"],
                venue=row["venue"].replace("|", " "),
                reason=row["reason"].replace("|", " "),
            )
        )
    lines.extend([
        "",
        "## Review Candidates",
        "",
        "| song | score | evidence | venue | reason |",
        "|---|---:|---:|---|---|",
    ])
    for row in result["rows"]:
        if row["bucket"] != "review":
            continue
        lines.append(
            "| {song} | {score} | {evidence} | {venue} | {reason} |".format(
                song=row["canonical_song_name"].replace("|", " "),
                score=row["score"],
                evidence=row["evidence_count"],
                venue=row["venue"].replace("|", " "),
                reason=row["reason"].replace("|", " "),
            )
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--song-master", type=Path, default=SONG_MASTER)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--md-out", type=Path, default=OUT_MD)
    parser.add_argument("--db", type=Path, default=DEFAULT_MASTER_DB)
    args = parser.parse_args()

    # Opened once, read-only, and reused for every candidate below -- same
    # contract as song_processing.weekly_song_triage.build_song_catalog().
    catalog = build_song_catalog(args.db)
    result = triage(load_json(args.source, {}), load_json(args.song_master, {}), catalog)
    write_json(args.out, result)
    args.md_out.write_text(markdown(result), encoding="utf-8")
    print(
        "retrospective song triage: candidates={candidate_count} "
        "existing={existing_match} new={new_song_candidate} review={review} noise={reject_noise}".format(
            candidate_count=result["candidate_count"],
            existing_match=result["counts"].get("existing_match", 0),
            new_song_candidate=result["counts"].get("new_song_candidate", 0),
            review=result["counts"].get("review", 0),
            reject_noise=result["counts"].get("reject_noise", 0),
        )
    )
    print(f"wrote {args.out}, {args.md_out}")


if __name__ == "__main__":
    main()
