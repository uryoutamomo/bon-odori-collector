#!/usr/bin/env python3
"""Measure odottar coverage against Bonsuke without creating event candidates.

The odottar snapshot is a third-party benchmark input only.  This command writes
aggregate reports and a hash history; it never imports rows into canonical data,
review inboxes, or source URLs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


TOKYO_WARDS = (
    "千代田区", "中央区", "港区", "新宿区", "文京区", "台東区", "墨田区", "江東区",
    "品川区", "目黒区", "大田区", "世田谷区", "渋谷区", "中野区", "杉並区", "豊島区",
    "北区", "荒川区", "板橋区", "練馬区", "足立区", "葛飾区", "江戸川区",
)
PRIORITY_WARDS = ("江戸川区", "足立区", "板橋区", "葛飾区", "大田区", "豊島区", "荒川区", "練馬区")
SAFETY_BOUNDARY = (
    "coverage_benchmark_only: no canonical import, no review-inbox candidate, "
    "and no odottar URL projection into event source_urls"
)
PUNCTUATION_RE = re.compile(r"[\s\u3000・･,，.。:：;；/／\\|｜()（）\[\]［］【】「」『』'\"`~〜～!！?？_-]+")
EDITION_RE = re.compile(r"(?:第\s*)?\d+\s*回|(?:20\d{2}|令和\d+)年")


def read_json_bytes(path: Path) -> tuple[bytes, Any]:
    raw = path.read_bytes()
    return raw, json.loads(raw.decode("utf-8"))


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = EDITION_RE.sub("", text)
    return PUNCTUATION_RE.sub("", text)


def normalize_area(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    return text.removeprefix("東京都")


def ngrams(value: Any, width: int = 3) -> set[str]:
    text = normalize_text(value)
    if not text:
        return set()
    if len(text) <= width:
        return {text}
    return {text[index : index + width] for index in range(len(text) - width + 1)}


def similarity(left: Any, right: Any) -> float:
    a, b = ngrams(left), ngrams(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def iso_dates(start: Any, end: Any, *, max_days: int = 14) -> set[str]:
    try:
        first = date.fromisoformat(str(start or "")[:10])
    except ValueError:
        return set()
    try:
        last = date.fromisoformat(str(end or start or "")[:10])
    except ValueError:
        last = first
    if last < first or (last - first).days > max_days:
        last = first
    return {(first + timedelta(days=offset)).isoformat() for offset in range((last - first).days + 1)}


def row_dates(row: dict[str, Any], source: str) -> set[str]:
    if source == "odottar":
        return iso_dates(row.get("start"), row.get("end"))
    return iso_dates(row.get("date"), row.get("date_end"))


def match_score(odottar: dict[str, Any], bonsuke: dict[str, Any]) -> float | None:
    odo_area = normalize_area(odottar.get("area"))
    bon_area = normalize_area(bonsuke.get("area"))
    if odo_area and bon_area and odo_area != bon_area:
        return None
    name_score = similarity(odottar.get("name"), bonsuke.get("name"))
    venue_score = similarity(odottar.get("venue"), bonsuke.get("venue"))
    same_name = normalize_text(odottar.get("name")) == normalize_text(bonsuke.get("name"))
    same_venue = normalize_text(odottar.get("venue")) == normalize_text(bonsuke.get("venue"))
    date_overlap = bool(row_dates(odottar, "odottar") & row_dates(bonsuke, "bonsuke"))
    accepted = (
        (same_name and same_venue)
        or (date_overlap and (same_name or same_venue))
        or (date_overlap and max(name_score, venue_score) >= 0.60)
        or (date_overlap and name_score >= 0.45 and venue_score >= 0.45)
    )
    if not accepted:
        return None
    return round(name_score * 0.55 + venue_score * 0.35 + (0.10 if date_overlap else 0.0), 6)


def greedy_matches(odottar_rows: list[dict[str, Any]], bonsuke_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges = []
    for odo_index, odo in enumerate(odottar_rows):
        for bon_index, bon in enumerate(bonsuke_rows):
            score = match_score(odo, bon)
            if score is not None:
                edges.append((score, odo_index, bon_index))
    used_odo, used_bon, matches = set(), set(), []
    for score, odo_index, bon_index in sorted(edges, reverse=True):
        if odo_index in used_odo or bon_index in used_bon:
            continue
        used_odo.add(odo_index)
        used_bon.add(bon_index)
        odo, bon = odottar_rows[odo_index], bonsuke_rows[bon_index]
        matches.append(
            {
                "odottar_eid": str(odo.get("eid") or ""),
                "bonsuke_key": "|".join(str(bon.get(key) or "") for key in ("name", "venue", "date")),
                "score": score,
            }
        )
    return matches


def unmatched_sample(rows: Iterable[dict[str, Any]], matched_ids: set[str], source: str, limit: int = 30) -> list[dict[str, Any]]:
    sample = []
    for row in rows:
        row_id = str(row.get("eid") or "") if source == "odottar" else "|".join(
            str(row.get(key) or "") for key in ("name", "venue", "date")
        )
        if row_id in matched_ids:
            continue
        sample.append(
            {
                "stable_key": row_id,
                "name": str(row.get("name") or ""),
                "venue": str(row.get("venue") or ""),
                "area": normalize_area(row.get("area")),
                "date": str(row.get("start") or "") if source == "odottar" else str(row.get("date") or ""),
            }
        )
        if len(sample) >= limit:
            break
    return sample


def build_report(raw: bytes, odottar_rows: Any, bonsuke_rows: Any, *, fetched_at: str, source_url: str) -> dict[str, Any]:
    if not isinstance(odottar_rows, list) or not all(isinstance(row, dict) for row in odottar_rows):
        raise ValueError("odottar snapshot must be an array of objects")
    if not isinstance(bonsuke_rows, list) or not all(isinstance(row, dict) for row in bonsuke_rows):
        raise ValueError("Bonsuke public events must be an array of objects")
    odo_23 = [row for row in odottar_rows if normalize_area(row.get("area")) in TOKYO_WARDS]
    bon_23 = [row for row in bonsuke_rows if normalize_area(row.get("area")) in TOKYO_WARDS]
    matches = greedy_matches(odo_23, bon_23)
    matched_odo = {row["odottar_eid"] for row in matches}
    matched_bon = {row["bonsuke_key"] for row in matches}
    wards = []
    for ward in TOKYO_WARDS:
        odo_count = sum(normalize_area(row.get("area")) == ward for row in odo_23)
        bon_count = sum(normalize_area(row.get("area")) == ward for row in bon_23)
        matched_count = sum(
            any(str(odo.get("eid") or "") == match["odottar_eid"] and normalize_area(odo.get("area")) == ward for odo in odo_23)
            for match in matches
        )
        wards.append(
            {
                "ward": ward,
                "priority": ward in PRIORITY_WARDS,
                "odottar": odo_count,
                "bonsuke": bon_count,
                "estimated_matched": matched_count,
                "odottar_only": odo_count - matched_count,
                "bonsuke_only": bon_count - matched_count,
            }
        )
    return {
        "schema_version": 1,
        "generated_by": "build_odottar_coverage_benchmark.py",
        "fetched_at": fetched_at,
        "source": {"url": source_url, "raw_sha256": hashlib.sha256(raw).hexdigest(), "row_count": len(odottar_rows)},
        "safety_boundary": SAFETY_BOUNDARY,
        "canonical_write_count": 0,
        "review_inbox_candidate_count": 0,
        "summary": {
            "odottar_tokyo23": len(odo_23),
            "bonsuke_tokyo23": len(bon_23),
            "estimated_matched": len(matches),
            "odottar_only": len(odo_23) - len(matches),
            "bonsuke_only": len(bon_23) - len(matches),
        },
        "wards": wards,
        "samples": {
            "odottar_only": unmatched_sample(odo_23, matched_odo, "odottar"),
            "bonsuke_only": unmatched_sample(bon_23, matched_bon, "bonsuke"),
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# odottar coverage benchmark",
        "",
        f"- source: おどったー（{report['source']['url']}）",
        f"- fetched_at: {report['fetched_at']}",
        f"- raw_sha256: `{report['source']['raw_sha256']}`",
        f"- safety: {report['safety_boundary']}",
        f"- 23区: odottar {summary['odottar_tokyo23']} / 盆助 {summary['bonsuke_tokyo23']}",
        f"- 推定一致 {summary['estimated_matched']} / odottarのみ {summary['odottar_only']} / 盆助のみ {summary['bonsuke_only']}",
        "",
        "## 区別",
        "",
        "| 区 | 優先 | odottar | 盆助 | 推定一致 | odottarのみ | 盆助のみ |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report["wards"]:
        lines.append(
            f"| {row['ward']} | {'yes' if row['priority'] else ''} | {row['odottar']} | {row['bonsuke']} | "
            f"{row['estimated_matched']} | {row['odottar_only']} | {row['bonsuke_only']} |"
        )
    lines.extend(["", "一致件数は名称・会場の3-gram類似と日付一致によるcoverage推定であり、canonical同一性判断ではない。", ""])
    return "\n".join(lines)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def append_history(path: Path, report: dict[str, Any]) -> None:
    if path.exists():
        history = json.loads(path.read_text(encoding="utf-8"))
    else:
        history = {"schema_version": 1, "snapshots": []}
    snapshots = history.setdefault("snapshots", [])
    entry = {"fetched_at": report["fetched_at"], "raw_sha256": report["source"]["raw_sha256"], **report["summary"]}
    snapshots[:] = [row for row in snapshots if row.get("fetched_at") != entry["fetched_at"]]
    snapshots.append(entry)
    snapshots.sort(key=lambda row: row.get("fetched_at") or "")
    write_json(path, history)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--odottar-json", type=Path, required=True)
    parser.add_argument("--bonsuke-json", type=Path, default=Path("data/public/events_public.json"))
    parser.add_argument("--out-json", type=Path, default=Path("data/odottar_coverage_latest.json"))
    parser.add_argument("--out-md", type=Path, default=Path("data/odottar_coverage_latest.md"))
    parser.add_argument("--history", type=Path, default=Path("data/odottar_coverage_history.json"))
    parser.add_argument("--fetched-at", default=datetime.now(timezone.utc).isoformat())
    parser.add_argument("--source-url", default="https://odottar.com/events.json")
    args = parser.parse_args()
    raw, odottar_rows = read_json_bytes(args.odottar_json)
    _, bonsuke_rows = read_json_bytes(args.bonsuke_json)
    report = build_report(raw, odottar_rows, bonsuke_rows, fetched_at=args.fetched_at, source_url=args.source_url)
    write_json(args.out_json, report)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(render_markdown(report), encoding="utf-8")
    append_history(args.history, report)
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
