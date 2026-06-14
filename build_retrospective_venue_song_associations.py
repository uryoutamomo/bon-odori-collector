#!/usr/bin/env python3
"""Build probabilistic venue-song associations from retrospective X voices."""

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from bon_odori_songs import extract_song_candidates
from event_evidence import VENUE_RE, _clean_venue_hint, classify_event_evidence, dancer_key


DATA = Path("data")
VOICES = DATA / "voices.json"
OUT_JSON = DATA / "retrospective_venue_song_associations.json"
OUT_MD = DATA / "retrospective_venue_song_associations.md"

PRACTICE_RE = re.compile(r"(?:練習会|練習|予習|レクチャー|講習)")
OBSERVED_RE = re.compile(r"(?:行った|行ってきた|参加した|踊った|踊ってきた|楽しかった|お邪魔しました)")
ANNOUNCED_RE = re.compile(r"(?:曲目|曲順|セットリスト|セトリ|演目|プログラム|告知|開催|予定)")
GUEST_OR_REFERENCE_RE = re.compile(r"(?:ゲスト|お馴染み|でお馴染み|登場|さんが登場)")
FALSE_SONG_RE = re.compile(
    r"(?:一緒に踊り|ご一緒に踊り|踊りましょう|踊ってくれた姿|踊り子|"
    r"これからの季節|会場全体|客席|皆様|お客様|参加いただ|疎開先|"
    r"昨日|本日|今年|去年|来年|先日|いつも|嬉しそう|先生の|テーマ曲|"
    r"ゲスト|お馴染み|大会が|地域の|私の|ゆりの中|夜通し踊り|"
    r"ジャンボリーミッキーを踊り|私は踊り|会場で|現地で|念仏踊り|流し踊り|を踊り$)"
)
DIRTY_VENUE_PREFIX_RE = re.compile(
    r"^(?:駅近の|去年は|昨年は|今年は|今日は|昨日の|本日は|レコードを|第[0-9０-９]+回)"
)
ASSOCIATION_SONG_RE = re.compile(
    r"([一-龥ぁ-んァ-ヶA-Za-z0-9・ー]{2,18}(?:音頭|おどり|踊り|小唄|甚句|節|ソーラン|八木節|ヒーロー))"
)
ASSOCIATION_CONTEXT_RE = re.compile(r"(?:盆踊り|盆おどり|曲目|曲順|踊|予習|練習|セトリ|セットリスト)")


def load_json(path, default):
    if not Path(path).exists():
        return default
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, payload):
    with Path(path).open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    value = str(value or "").strip().casefold()
    return re.sub(r"\s+", "", value)


def digest(*parts, length=20):
    raw = "\0".join(str(part or "") for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:length]


def is_x_voice(voice):
    source = str(voice.get("source") or "").casefold()
    url = str(voice.get("url") or "")
    return source == "x" or "x.com/" in url or "twitter.com/" in url or bool(voice.get("tweet_id"))


def clean_venue_name(value):
    venue = _clean_venue_hint(value or "")
    venue = venue.strip(" 「」『』（）()[]【】、。")
    venue = re.sub(r"^.*としても人気の", "", venue)
    venue = DIRTY_VENUE_PREFIX_RE.sub("", venue).strip()
    venue = re.sub(r"^(?:の|は|で|に|と)", "", venue).strip()
    return venue


def venue_is_probable_false_positive(venue):
    if not venue:
        return True
    if venue in {"公園", "広場", "学校", "小学校", "会館"}:
        return True
    if re.search(r"^(?:夏は|現地の|あと私の|大阪の小学生|私の地域)", venue):
        return True
    return False


def venue_hints_from_text(text):
    values = []
    for match in VENUE_RE.finditer(text or ""):
        venue = clean_venue_name(match.group(1))
        if venue and venue not in values:
            values.append(venue)
    return values[:5]


def song_is_probable_false_positive(song):
    if not song:
        return True
    if song.startswith(("・", "を", "で", "に", "の", "が")):
        return True
    if FALSE_SONG_RE.search(song):
        return True
    if re.fullmatch(r"[一-龥ぁ-んァ-ヶー]{2,10}の踊り", song):
        return True
    if len(song) >= 12 and re.search(r"[がをにへでからのとや]", song):
        return True
    return False


def clean_association_song(value):
    song = str(value or "").strip(" 「」『』（）()[]【】、。")
    song = re.sub(r"^.*(?:盆踊り|盆おどり)(?:で|に|の)?", "", song)
    song = re.sub(r"^第[0-9０-９]+回", "", song)
    song = re.sub(r"^(?:・|で|に|の|は|も|曲目は|曲は|演目は|ここで|なぜか|ご当地の)", "", song)
    suffix = r"(音頭|おどり|踊り|小唄|甚句|節|ソーラン|八木節|ヒーロー)"
    compound = "と" in song and len(re.findall(suffix, song)) >= 2
    match = re.search(suffix, song)
    if match and match.end() < len(song) and not compound:
        song = song[:match.end()]
    return song.strip(" 「」『』（）()[]【】、。")


def split_song_name(song):
    song = clean_association_song(song)
    if song_is_probable_false_positive(song):
        return []
    if "と" in song:
        parts = [part.strip() for part in song.split("と") if part.strip()]
        if len(parts) >= 2 and all(re.search(r"(?:音頭|おどり|踊り|小唄|甚句|節|ソーラン|八木節|ヒーロー)$", part) for part in parts):
            return [part for part in parts if not song_is_probable_false_positive(part)]
    return [song]


def extract_association_song_names(text):
    names = []
    for candidate in extract_song_candidates(text):
        for song in split_song_name(candidate.get("name")):
            if song and song not in names:
                names.append(song)
    if ASSOCIATION_CONTEXT_RE.search(text or ""):
        for match in ASSOCIATION_SONG_RE.finditer(text or ""):
            for song in split_song_name(match.group(1)):
                if song and not song_is_probable_false_positive(song) and song not in names:
                    names.append(song)
    return names


def select_venue(voice, evidence):
    text = voice.get("text") or ""
    hints = []
    if evidence and evidence.get("estimated_venue"):
        hints.append(evidence["estimated_venue"])
    if evidence:
        hints.extend(evidence.get("venue_hints") or [])
    hints.extend(venue_hints_from_text(text))
    for hint in hints:
        venue = clean_venue_name(hint)
        if venue and not venue_is_probable_false_positive(venue):
            return venue, [clean_venue_name(value) for value in hints if clean_venue_name(value)]
    return "", []


def context_flags(text, venue, venue_hints):
    flags = []
    if PRACTICE_RE.search(text):
        flags.append("practice_or_preview")
    if GUEST_OR_REFERENCE_RE.search(text):
        flags.append("guest_or_reference")
    if OBSERVED_RE.search(text):
        flags.append("observed")
    if ANNOUNCED_RE.search(text):
        flags.append("announced_or_setlist")
    if DIRTY_VENUE_PREFIX_RE.search(str(venue or "")):
        flags.append("dirty_venue")
    if len(set(venue_hints or [])) >= 2:
        flags.append("multiple_venue_hints")
    return sorted(set(flags))


def evidence_row(voice, evidence, song, venue, venue_hints):
    text = clean_text(voice.get("text"))
    flags = context_flags(text, venue, venue_hints)
    return {
        "tweet_id": str(voice.get("tweet_id") or ""),
        "url": voice.get("url") or "",
        "account": voice.get("account") or "",
        "dancer_key": dancer_key(voice.get("account") or ""),
        "observed_at": voice.get("date") or "",
        "song_name": song,
        "venue": venue,
        "venue_hints": venue_hints,
        "event_hint": (evidence or {}).get("estimated_event") or "",
        "month": (evidence or {}).get("estimated_month") or "",
        "year": (evidence or {}).get("year") or "",
        "bon_context_hits": (evidence or {}).get("bon_context_hits") or [],
        "flags": flags,
        "text": text[:500],
    }


def add_evidence(group, row):
    key = row.get("tweet_id") or row.get("url") or row.get("text")
    seen = {item.get("tweet_id") or item.get("url") or item.get("text") for item in group["evidence"]}
    if key and key in seen:
        return
    group["evidence"].append(row)


def probability_for_group(group):
    evidence = group["evidence"]
    speakers = {item.get("dancer_key") or item.get("account") for item in evidence if item.get("dancer_key") or item.get("account")}
    all_flags = {flag for item in evidence for flag in item.get("flags", [])}
    bon_hits = {hit for item in evidence for hit in item.get("bon_context_hits", [])}
    months = {item.get("month") for item in evidence if item.get("month")}

    probability = 0.36
    probability += min((len(evidence) - 1) * 0.08, 0.18)
    probability += min((len(speakers) - 1) * 0.10, 0.20)
    if "announced_or_setlist" in all_flags:
        probability += 0.10
    if "observed" in all_flags:
        probability += 0.08
    if bon_hits:
        probability += 0.05
    if months:
        probability += 0.04
    if "practice_or_preview" in all_flags:
        probability -= 0.12
    if "guest_or_reference" in all_flags:
        probability -= 0.20
    if "multiple_venue_hints" in all_flags:
        probability -= 0.05

    probability = max(0.12, min(0.92, probability))
    return round(probability * 100)


def confidence_label(probability):
    if probability >= 75:
        return "high"
    if probability >= 55:
        return "medium"
    if probability >= 35:
        return "low"
    return "weak"


def finalize_group(group):
    evidence = group["evidence"]
    speakers = sorted({item.get("dancer_key") or item.get("account") for item in evidence if item.get("dancer_key") or item.get("account")})
    flags = sorted({flag for item in evidence for flag in item.get("flags", [])})
    event_hints = sorted({item.get("event_hint") for item in evidence if item.get("event_hint")})
    months = sorted({item.get("month") for item in evidence if item.get("month")})
    years = sorted({str(item.get("year")) for item in evidence if item.get("year")})
    probability = probability_for_group(group)
    group.update({
        "probability": probability,
        "confidence": confidence_label(probability),
        "evidence_count": len(evidence),
        "speaker_count": len(speakers),
        "speakers": speakers,
        "flags": flags,
        "event_hints": event_hints,
        "months": months,
        "years": years,
        "source_urls": sorted({item.get("url") for item in evidence if item.get("url")})[:10],
    })
    return group


def build_from_voices(voices, generated_at=None, x_only=True):
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    groups = {}
    scanned = 0
    with_song = 0
    skipped_false_song = 0
    skipped_no_venue = 0

    for voice in voices:
        if not isinstance(voice, dict):
            continue
        if x_only and not is_x_voice(voice):
            continue
        scanned += 1
        text = voice.get("text") or ""
        songs = extract_association_song_names(text)
        if not songs:
            continue
        with_song += 1
        evidence = classify_event_evidence(voice) or {}
        venue, venue_hints = select_venue(voice, evidence)
        if not venue:
            skipped_no_venue += len(songs)
            continue
        for song in songs:
            if song_is_probable_false_positive(song):
                skipped_false_song += 1
                continue
            key = (norm(venue), norm(song))
            group = groups.setdefault(key, {
                "association_id": "venue_song:" + digest("venue-song", venue, song),
                "venue": venue,
                "venue_key": digest("venue", norm(venue)),
                "song_name": song,
                "song_key": digest("song", norm(song)),
                "evidence": [],
            })
            add_evidence(group, evidence_row(voice, evidence, song, venue, venue_hints))

    associations = [finalize_group(group) for group in groups.values()]
    associations.sort(key=lambda item: (-item["probability"], -item["evidence_count"], item["venue"], item["song_name"]))
    by_confidence = Counter(item["confidence"] for item in associations)
    by_flag = Counter(flag for item in associations for flag in item.get("flags", []))
    return {
        "generated_by": "build_retrospective_venue_song_associations.py",
        "generated_at": generated_at,
        "source": str(VOICES),
        "source_scope": "x_only" if x_only else "all_sources",
        "scanned_voice_count": scanned,
        "voice_with_song_candidate_count": with_song,
        "association_count": len(associations),
        "counts": {
            "by_confidence": dict(sorted(by_confidence.items())),
            "by_flag": dict(sorted(by_flag.items())),
            "skipped_false_song_count": skipped_false_song,
            "skipped_no_venue_song_count": skipped_no_venue,
        },
        "associations": associations,
    }


def render_markdown(payload, limit=None):
    rows = payload["associations"][:limit] if limit else payload["associations"]
    lines = [
        "# X過去投稿からの会場×曲 推定紐付け",
        "",
        f"- 生成: {payload['generated_at']}",
        f"- 対象: {payload['source_scope']}",
        f"- 調査投稿数: {payload['scanned_voice_count']}",
        f"- 曲候補を含む投稿数: {payload['voice_with_song_candidate_count']}",
        f"- 会場×曲候補: {payload['association_count']}",
        f"- 確信度別: {payload['counts']['by_confidence']}",
        "",
        "確率は実測値ではなく、X上の証拠数・独立話者・曲目/実参加/練習/ゲスト文脈などから作った優先度です。",
        "",
        "| 確率 | 確信度 | 会場 | 曲 | 証拠 | 話者 | フラグ | URL |",
        "|---:|---|---|---|---:|---:|---|---|",
    ]
    for item in rows:
        url = item["source_urls"][0] if item.get("source_urls") else ""
        flags = ", ".join(item.get("flags") or [])
        lines.append(
            f"| {item['probability']} | {item['confidence']} | {item['venue']} | {item['song_name']} | "
            f"{item['evidence_count']} | {item['speaker_count']} | {flags} | {url} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--voices", type=Path, default=VOICES)
    parser.add_argument("--out-json", type=Path, default=OUT_JSON)
    parser.add_argument("--out-md", type=Path, default=OUT_MD)
    parser.add_argument("--all-sources", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    payload = build_from_voices(load_json(args.voices, []), x_only=not args.all_sources)
    if not args.dry_run:
        write_json(args.out_json, payload)
        args.out_md.write_text(render_markdown(payload), encoding="utf-8")
    print(
        f"[venue-song] scanned={payload['scanned_voice_count']} "
        f"associations={payload['association_count']} confidence={payload['counts']['by_confidence']}"
    )


if __name__ == "__main__":
    main()
