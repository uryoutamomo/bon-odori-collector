#!/usr/bin/env python3
"""Build initial glossary v2 seed candidates from collected X voices."""

import hashlib
import json
import re
from collections import defaultdict
from pathlib import Path

from bon_odori_songs import extract_song_candidates


DATA = Path("data")
OUT = DATA / "glossary_v2_seed_candidates.json"

TERM_RE = re.compile(
    r"([一-龥ぁ-んァ-ヶA-Za-z0-9・ー'’-]{2,24}"
    r"(?:盆|ボン|BON|音頭|おどり|踊り|民踊|輪踊り|ハシゴ|はしご))"
)
BEHAVIOR_TERMS = {
    "ハシゴ": ("行動語", ["参加予告", "参加報告"]),
    "はしご": ("行動語", ["参加予告", "参加報告"]),
}
NOISE_TERMS = {
    "盆踊り",
    "盆おどり",
    "盆踊",
    "盆踊り大会",
    "盆おどり大会",
    "音頭",
    "踊り",
}
NOISE_TERM_PARTS = (
    "伝統的な",
    "一体となって",
    "楽しさ",
    "様子",
    "イベント",
    "コンテンツ",
)


def load_json(path, default):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def norm(value):
    return re.sub(r"\s+", "", str(value or "")).casefold()


def candidate_id(term, kind, interpretation):
    raw = "\0".join([term, kind, interpretation])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def reference_terms():
    refs = []
    for event in load_json(DATA / "public/events_public.json", []):
        name = event.get("name") or ""
        venue = event.get("venue") or ""
        if name:
            refs.append({"kind": "event", "name": name, "venue": venue, "area": event.get("area") or ""})
        if venue:
            refs.append({"kind": "venue", "name": venue, "venue": venue, "area": event.get("area") or ""})
    for venue in load_json(DATA / "venue_master.json", []):
        name = venue.get("venue") or ""
        if name:
            refs.append({"kind": "venue", "name": name, "venue": name, "area": venue.get("region") or ""})
    deduped = {}
    for ref in refs:
        deduped[(ref["kind"], ref["name"])] = ref
    return list(deduped.values())


def infer_reference(text, refs):
    text_norm = norm(text)
    best = None
    best_score = 0
    for ref in refs:
        name_norm = norm(ref["name"])
        if not name_norm or name_norm not in text_norm:
            continue
        score = len(name_norm) + (4 if ref["kind"] == "event" else 0)
        if score > best_score:
            best = ref
            best_score = score
    return best


def add_candidate(grouped, term, kind, roles, interpretation, ref, voice, reason):
    if not term or term in NOISE_TERMS:
        return
    if term.startswith(("の", "な", "で", "と")) or any(part in term for part in NOISE_TERM_PARTS):
        return
    if kind == "曲名":
        interpretation = term
    key = (term, kind, interpretation)
    item = grouped.setdefault(key, {
        "id": candidate_id(term, kind, interpretation),
        "term": term,
        "interpretation": interpretation or term,
        "kind": kind,
        "roles": sorted(set(roles)),
        "confidence": "推察",
        "state": "候補",
        "auto_apply": False,
        "inferred_target": ref or {},
        "reasons": set(),
        "evidence": [],
    })
    item["reasons"].add(reason)
    url = voice.get("url") or ""
    if url and all(ev["url"] != url for ev in item["evidence"]):
        item["evidence"].append({
            "url": url,
            "account": voice.get("account") or "",
            "date": voice.get("date") or "",
            "text": (voice.get("text") or "")[:420],
        })


def build():
    voices = load_json(DATA / "voices.json", [])
    refs = reference_terms()
    grouped = {}
    for voice in voices:
        text = voice.get("text") or ""
        if not text:
            continue
        ref = infer_reference(text, refs)

        for behavior, (kind, roles) in BEHAVIOR_TERMS.items():
            if behavior in text:
                add_candidate(grouped, behavior, kind, roles, behavior, ref, voice, "behavior_term")

        for song in extract_song_candidates(text):
            add_candidate(
                grouped,
                song["name"],
                "曲名",
                ["曲目ヒント"],
                song["name"],
                ref,
                voice,
                "song_candidate",
            )

        for match in TERM_RE.finditer(text):
            term = match.group(1).strip("、。!！?？「」『』（）()[]【】")
            if len(term) < 3 or term in NOISE_TERMS:
                continue
            kind = "イベント別名" if "盆" in term else "曲名"
            roles = ["会場ヒント"] if kind == "イベント別名" else ["曲目ヒント"]
            interpretation = ref["name"] if ref and kind == "イベント別名" else term
            add_candidate(grouped, term, kind, roles, interpretation, ref, voice, "term_pattern")

    rows = []
    for item in grouped.values():
        item["reasons"] = sorted(item["reasons"])
        item["evidence_count"] = len(item["evidence"])
        rows.append(item)
    rows.sort(key=lambda row: (-row["evidence_count"], row["kind"], row["term"]))
    selected = rows[:120]
    return {
        "generated_by": "build_glossary_v2_seed_candidates.py",
        "count": len(selected),
        "total_count": len(rows),
        "candidates": selected,
    }


def main():
    output = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"用語集v2初期シード候補生成完了: {output['count']}件 -> {OUT}")


if __name__ == "__main__":
    main()
