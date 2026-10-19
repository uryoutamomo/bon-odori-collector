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
from zoneinfo import ZoneInfo


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
JST = ZoneInfo("Asia/Tokyo")
WORKSHOP_RE = re.compile(r"講習|練習|稽古|レッスン|ワークショップ|workshop|lesson|practice", re.I)
FESTIVAL_RE = re.compile(r"盆踊|盆おど|祭|まつり|フェス|納涼|おどり|踊り|bon\s*(?:dance|odori)", re.I)


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


def calendar_day(value: Any) -> date | None:
    """Date-only and naive timestamps use JST; aware timestamps convert to JST."""
    try:
        if isinstance(value, datetime):
            timestamp = value
        elif isinstance(value, date):
            return value
        else:
            text = str(value or "").strip()
            if len(text) == 10:
                return date.fromisoformat(text)
            timestamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return (timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=JST)).astimezone(JST).date()
    except (TypeError, ValueError):
        return None


def iso_dates(start: Any, end: Any, *, max_days: int = 366) -> set[str]:
    first, last = calendar_day(start), calendar_day(end or start)
    if not first or not last or last < first or (last - first).days >= max_days:
        return set()
    return {(first + timedelta(days=offset)).isoformat() for offset in range((last - first).days + 1)}


def row_dates(row: dict[str, Any], source: str) -> set[str]:
    if "_dates" in row:
        return set(row["_dates"])
    if source == "odottar":
        return iso_dates(row.get("start"), row.get("end"))
    return iso_dates(row.get("date"), row.get("date_end"))


def match_score(odottar: dict[str, Any], bonsuke: dict[str, Any]) -> float | None:
    odo_area = normalize_area(odottar.get("area"))
    bon_area = normalize_area(bonsuke.get("area"))
    if odo_area and bon_area and odo_area != bon_area:
        return None
    if odottar.get("_kind") != bonsuke.get("_kind"):
        return None
    if not normalize_text(odottar.get("venue")) or not normalize_text(bonsuke.get("venue")):
        return None
    name_score = similarity(odottar.get("name"), bonsuke.get("name"))
    venue_score = similarity(odottar.get("venue"), bonsuke.get("venue"))
    same_name = bool(normalize_text(odottar.get("name"))) and normalize_text(odottar.get("name")) == normalize_text(bonsuke.get("name"))
    same_venue = normalize_text(odottar.get("venue")) == normalize_text(bonsuke.get("venue"))
    date_overlap = bool(row_dates(odottar, "odottar") & row_dates(bonsuke, "bonsuke"))
    accepted = (
        date_overlap
        and (same_venue or venue_score >= 0.60)
        and (same_name or name_score >= 0.45)
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
                "odottar_eid": str(odo.get("_stable_key") or odo.get("eid") or ""),
                "bonsuke_key": str(bon.get("_stable_key") or "|".join(str(bon.get(key) or "") for key in ("name", "venue", "date"))),
                "score": score,
                "area": normalize_area(odo.get("area")),
                "overlap_days": len(row_dates(odo, "odottar") & row_dates(bon, "bonsuke")),
            }
        )
    return matches


def unmatched_sample(rows: Iterable[dict[str, Any]], matched_ids: set[str], source: str, limit: int = 30) -> list[dict[str, Any]]:
    sample = []
    for row in rows:
        row_id = row.get("_stable_key") or (str(row.get("eid") or "") if source == "odottar" else "|".join(
            str(row.get(key) or "") for key in ("name", "venue", "date")
        ))
        if row_id in matched_ids:
            continue
        sample.append(
            {
                "stable_key": row_id,
                "name": str(row.get("name") or ""),
                "venue": str(row.get("venue") or ""),
                "area": normalize_area(row.get("area")),
                "date": min(row_dates(row, source)) if row_dates(row, source) else "",
                "dates_in_window": sorted(row_dates(row, source)),
            }
        )
        if len(sample) >= limit:
            break
    return sample


def schedule(row: dict[str, Any], source: str) -> tuple[set[str], str, str | None]:
    if source == "odottar":
        # Only start/end are documented by the existing adapter. No confirmation
        # or category schema is available in the saved raw input evidence.
        return row_dates(row, source), "listed", None
    state = row.get("current_event_state")
    if state in {"ended", "cancelled"} or row.get("public_category") in {"ended", "cancelled"} or row.get("status") in {"ended", "cancelled"}:
        return set(), "confirmed", "excluded_status_rows"
    tier = row.get("date_certainty_tier")
    predicted = row.get("date_prediction") or {}
    if not isinstance(predicted, dict):
        predicted = {}
    if state in {"predicted", "announced"} or tier in {"rule_predicted", "historical_slide", "historical_reference", "season_hint"} or row.get("public_category") in {"recurring_last_year", "date_unknown"}:
        start = row.get("predicted_date") or predicted.get("date")
        end = row.get("predicted_date_end") or predicted.get("date_end")
        if start:
            return iso_dates(start, end), "predicted", None
        # Never slide historical dates or infer future dates from month/day hints.
        return set(), "predicted", "historical_without_forward_date_rows"
    certainty = "confirmed" if tier == "confirmed" or state == "confirmed" or row.get("status") == "confirmed" else "listed"
    return row_dates(row, source), certainty, None


def event_kind(row: dict[str, Any]) -> str:
    name = unicodedata.normalize("NFKC", str(row.get("name") or ""))
    if WORKSHOP_RE.search(name):
        return "workshop"
    return "festival" if FESTIVAL_RE.search(name) else "unclassified"


def prepare_events(rows: list[dict[str, Any]], source: str, start: date, end: date) -> tuple[list[dict[str, Any]], dict[str, int]]:
    quality = dict.fromkeys(("input_rows", "outside_tokyo23_rows", "excluded_status_rows", "historical_without_forward_date_rows",
                            "missing_or_invalid_date_rows", "outside_window_rows", "coalesced_listing_rows",
                            "identity_conflict_groups", "fallback_identity_groups", "mixed_certainty_groups"), 0)
    quality["input_rows"] = len(rows)
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        area = normalize_area(row.get("area"))
        if area not in TOKYO_WARDS:
            quality["outside_tokyo23_rows"] += 1
            continue
        dates, certainty, reason = schedule(row, source)
        if reason:
            quality[reason] += 1
            continue
        if not dates:
            quality["missing_or_invalid_date_rows"] += 1
            continue
        clipped = {day for day in dates if start.isoformat() <= day < end.isoformat()}
        if not clipped:
            quality["outside_window_rows"] += 1
            continue
        identifier = row.get("eid") if source == "odottar" else row.get("occurrence_id")
        if identifier is not None and str(identifier).strip():
            key = f"{source}:id:{identifier}"
        else:
            # Exact-record fallback, not title-based physical-event merging.
            digest = hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            key = f"{source}:record:{digest}"
        groups.setdefault(key, []).append({**row, "area": area, "_dates": sorted(clipped), "_certainty": certainty,
                                           "_kind": event_kind(row), "_stable_key": key})
    events = []
    for key, listings in sorted(groups.items()):
        locations = {(row["area"], normalize_text(row.get("venue"))) for row in listings}
        kinds = {row["_kind"] for row in listings}
        if len(locations) != 1 or len(kinds) != 1:
            quality["identity_conflict_groups"] += 1
            continue
        row = dict(min(listings, key=lambda listing: json.dumps(listing, ensure_ascii=False, sort_keys=True)))
        row["_dates"] = sorted({day for listing in listings for day in listing["_dates"]})
        certainties = {listing["_certainty"] for listing in listings}
        if len(certainties) > 1:
            quality["mixed_certainty_groups"] += 1
            row["_certainty"] = "predicted" if "predicted" in certainties else "listed"
        quality["coalesced_listing_rows"] += len(listings) - 1
        quality["fallback_identity_groups"] += int(":record:" in key)
        events.append(row)
    return events, quality


def freshness(snapshot_at: str | None, as_of: date) -> dict[str, Any]:
    day = calendar_day(snapshot_at)
    age = (as_of - day).days if day else None
    status = "unknown" if age is None else "after_as_of" if age < 0 else "stale" if age > 7 else "recently_fetched"
    return {"snapshot_at": snapshot_at, "age_days_at_as_of": age, "status": status,
            "stale_after_days": 7, "upstream_updated_at": None}


def coverage_metrics(odo: list[dict], bon: list[dict], matches: list[dict], *, day_unit: str = "dance_days") -> dict[str, int]:
    odo_days = sum(len(row["_dates"]) for row in odo)
    bon_days = sum(len(row["_dates"]) for row in bon)
    matched_days = sum(row["overlap_days"] for row in matches)
    return {"odottar_tokyo23": len(odo), "bonsuke_tokyo23": len(bon), "estimated_matched": len(matches),
            "odottar_only": len(odo) - len(matches), "bonsuke_only": len(bon) - len(matches),
            f"odottar_{day_unit}": odo_days, f"bonsuke_{day_unit}": bon_days, f"estimated_matched_{day_unit}": matched_days}


def build_report(raw: bytes, odottar_rows: Any, bonsuke_rows: Any, *, fetched_at: str | None, source_url: str,
                 as_of: date | datetime | str | None = None, days: int = 30,
                 bonsuke_snapshot_at: str | None = None, bonsuke_raw: bytes | None = None) -> dict[str, Any]:
    if not isinstance(odottar_rows, list) or not all(isinstance(row, dict) for row in odottar_rows):
        raise ValueError("odottar snapshot must be an array of objects")
    if not isinstance(bonsuke_rows, list) or not all(isinstance(row, dict) for row in bonsuke_rows):
        raise ValueError("Bonsuke public events must be an array of objects")
    start = calendar_day(as_of) if as_of is not None else datetime.now(JST).date()
    if start is None or not isinstance(days, int) or isinstance(days, bool) or not 1 <= days <= 366:
        raise ValueError("as_of must be an ISO date; days must be between 1 and 366")
    end = start + timedelta(days=days)
    odo_events, odo_quality = prepare_events(odottar_rows, "odottar", start, end)
    bon_events, bon_quality = prepare_events(bonsuke_rows, "bonsuke", start, end)
    def select(events, kind, *, uncertain=False):
        return [row for row in events if row["_kind"] == kind and (row["_certainty"] == "predicted") == uncertain]
    odo_23, bon_23 = select(odo_events, "festival"), select(bon_events, "festival")
    matches = greedy_matches(odo_23, bon_23)
    matched_odo = {row["odottar_eid"] for row in matches}
    matched_bon = {row["bonsuke_key"] for row in matches}
    wards = []
    for ward in TOKYO_WARDS:
        odo_count = sum(normalize_area(row.get("area")) == ward for row in odo_23)
        bon_count = sum(normalize_area(row.get("area")) == ward for row in bon_23)
        ward_odo = [row for row in odo_23 if row["area"] == ward]
        ward_bon = [row for row in bon_23 if row["area"] == ward]
        ward_matches = [match for match in matches if match["area"] == ward]
        matched_count = len(ward_matches)
        wards.append(
            {
                "ward": ward,
                "priority": ward in PRIORITY_WARDS,
                "odottar": odo_count,
                "bonsuke": bon_count,
                "estimated_matched": matched_count,
                "odottar_only": odo_count - matched_count,
                "bonsuke_only": bon_count - matched_count,
                "odottar_dance_days": sum(len(row["_dates"]) for row in ward_odo),
                "bonsuke_dance_days": sum(len(row["_dates"]) for row in ward_bon),
                "estimated_matched_dance_days": sum(match["overlap_days"] for match in ward_matches),
            }
        )
    return {
        "schema_version": 2,
        "generated_by": "build_odottar_coverage_benchmark.py",
        "fetched_at": fetched_at,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {"as_of": start.isoformat(), "start_inclusive": start.isoformat(), "end_exclusive": end.isoformat(),
                   "last_inclusive": (end - timedelta(days=1)).isoformat(), "days": days, "timezone": "Asia/Tokyo"},
        "source": {"url": source_url, "raw_sha256": hashlib.sha256(raw).hexdigest(), "row_count": len(odottar_rows)},
        "freshness": {"odottar": freshness(fetched_at, start), "bonsuke": freshness(bonsuke_snapshot_at, start)},
        "bonsuke_source": {"raw_sha256": hashlib.sha256(bonsuke_raw).hexdigest() if bonsuke_raw is not None else None,
                           "row_count": len(bonsuke_rows)},
        "method": {"event_identity": "source eid/occurrence_id, otherwise exact-record SHA-256; distinct IDs stay distinct",
                   "dance_day": "one unique event and JST calendar date; inclusive input date ranges; duplicate dates count once",
                   "classification": "name keywords; workshops take precedence; unclassified names are separate",
                   "certainty": "Bonsuke forecasts separate; odottar start/end are listed dates with confirmation unknown",
                   "range_limit": "invalid/reversed or over-366-day ranges are excluded, never collapsed to one day"},
        "safety_boundary": SAFETY_BOUNDARY,
        "canonical_write_count": 0,
        "review_inbox_candidate_count": 0,
        "summary": coverage_metrics(odo_23, bon_23, matches),
        "separate_counts": {kind: {
            "scheduled_or_listed": coverage_metrics(select(odo_events, kind), select(bon_events, kind),
                                                     greedy_matches(select(odo_events, kind), select(bon_events, kind)), day_unit="event_days"),
            "uncertain": {"odottar_events": len(select(odo_events, kind, uncertain=True)),
                          "bonsuke_events": len(select(bon_events, kind, uncertain=True)),
                          "odottar_projected_days": sum(len(row["_dates"]) for row in select(odo_events, kind, uncertain=True)),
                          "bonsuke_projected_days": sum(len(row["_dates"]) for row in select(bon_events, kind, uncertain=True))},
        } for kind in ("festival", "workshop", "unclassified")},
        "headline_certainty": {source: {certainty: sum(row["_certainty"] == certainty for row in events)
                                         for certainty in ("confirmed", "listed")} for source, events in (("odottar", odo_23), ("bonsuke", bon_23))},
        "input_quality": {"odottar": odo_quality, "bonsuke": bon_quality},
        "wards": wards,
        "samples": {
            "odottar_only": unmatched_sample(odo_23, matched_odo, "odottar"),
            "bonsuke_only": unmatched_sample(bon_23, matched_bon, "bonsuke"),
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    summary = report["summary"]
    window = report["window"]
    separate = report["separate_counts"]
    workshops = separate["workshop"]["scheduled_or_listed"]
    uncertain = separate["festival"]["uncertain"]
    lines = [
        "# odottar coverage benchmark",
        "",
        f"- source: おどったー（{report['source']['url']}）",
        f"- 集計生成: {report['generated_at']}",
        f"- 期間: {window['start_inclusive']}以上、{window['end_exclusive']}未満（JSTの{window['days']}暦日、基準日を含む）",
        f"- raw_sha256: `{report['source']['raw_sha256']}`",
        f"- safety: {report['safety_boundary']}",
        f"- 23区・盆踊り祭事の掲載イベント数（予測・講習会等は別枠）: odottar {summary['odottar_tokyo23']} / 盆助 {summary['bonsuke_tokyo23']}",
        f"- 開催日数（イベント×JST日付）: odottar {summary['odottar_dance_days']} / 盆助 {summary['bonsuke_dance_days']}",
        f"- 推定一致 {summary['estimated_matched']} / odottarのみ {summary['odottar_only']} / 盆助のみ {summary['bonsuke_only']}",
    ]
    for source, label in (("odottar", "odottar"), ("bonsuke", "盆助")):
        info = report["freshness"][source]
        age = f"{info['age_days_at_as_of']}日" if info["age_days_at_as_of"] is not None else "不明"
        lines.append(f"- {label}入力snapshot/取得時刻: {info['snapshot_at'] or '不明'} / 鮮度 {info['status']} / 基準日との差 {age}")
    if any(info["status"] != "recently_fetched" for info in report["freshness"].values()):
        lines.append("- 入力鮮度に制約があります。この集計を現在の網羅性と断定できません。staleは基準日より8日以上前、after_as_ofは基準日より後の入力です。")
    lines.extend([
        "- 取得時刻は掲載内容の更新時刻ではありません。両サイトの掲載更新時刻は不明です。",
        "- odottarの確認状態は不明で、日付付き掲載として計数。盆助の予測日は下記の別枠です。",
        f"- 主表の盆助: 日付確認済み {report['headline_certainty']['bonsuke']['confirmed']}件 / 確認状態不明の掲載 {report['headline_certainty']['bonsuke']['listed']}件。",
        "- 入力のstart/end・date/date_endは両端を含む連続日程として解釈。非連続日は同じIDの別行で表す場合だけ合算します。",
        "", "## 区別（イベント数 / 開催日数）", "",
        "| 区 | 優先 | odottar件 | odottar日 | 盆助件 | 盆助日 | 推定一致件 | odottarのみ | 盆助のみ |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in report["wards"]:
        lines.append(
            f"| {row['ward']} | {'yes' if row['priority'] else ''} | {row['odottar']} | {row['odottar_dance_days']} | {row['bonsuke']} | {row['bonsuke_dance_days']} | "
            f"{row['estimated_matched']} | {row['odottar_only']} | {row['bonsuke_only']} |"
        )
    lines.extend([
        "", "## 別枠", "",
        f"- 講習会・練習会等: odottar {workshops['odottar_tokyo23']}件 / {workshops['odottar_event_days']}日、盆助 {workshops['bonsuke_tokyo23']}件 / {workshops['bonsuke_event_days']}日。祭事件数には含めません。",
        f"- 盆踊り祭事の予測日: odottar {uncertain['odottar_events']}件 / {uncertain['odottar_projected_days']}予測日、盆助 {uncertain['bonsuke_events']}件 / {uncertain['bonsuke_projected_days']}予測日。確定開催日とは合算しません。",
        f"- 名称だけでは種別不明: odottar {separate['unclassified']['scheduled_or_listed']['odottar_tokyo23']}件、盆助 {separate['unclassified']['scheduled_or_listed']['bonsuke_tokyo23']}件。",
        "- 種別は名称キーワードによる暫定分類です。名称に講習・練習等を含む行を優先して別枠にし、祭事との併催を自動で推定しません。",
        "", "## 入力の除外・重複診断", "",
    ])
    for source, quality in report["input_quality"].items():
        lines.append(f"- {source}: {json.dumps(quality, ensure_ascii=False, sort_keys=True)}")
    lines.extend(["", "同じsource IDの重複日付は1回だけ数えます。IDがない場合は完全同一行だけを重複排除し、名称だけでは結合しません。",
                  "一致件数は会場と日付の重なりも必要とするcoverage推定であり、canonical同一性判断ではありません。", ""])
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
        history = {"schema_version": 2, "snapshots": []}
    history["schema_version"] = 2
    snapshots = history.setdefault("snapshots", [])
    entry = {"fetched_at": report["fetched_at"], "raw_sha256": report["source"]["raw_sha256"],
             "bonsuke_raw_sha256": report["bonsuke_source"]["raw_sha256"],
             "benchmark_schema_version": report["schema_version"], "window": report["window"], **report["summary"]}
    def identity(row):
        window = row.get("window") or {}
        return (row.get("fetched_at"), row.get("raw_sha256"), row.get("bonsuke_raw_sha256"),
                window.get("start_inclusive"), window.get("end_exclusive"), row.get("benchmark_schema_version"))
    snapshots[:] = [row for row in snapshots if identity(row) != identity(entry)]
    snapshots.append(entry)
    snapshots.sort(key=lambda row: (row.get("fetched_at") or "", (row.get("window") or {}).get("start_inclusive") or ""))
    write_json(path, history)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--odottar-json", type=Path, required=True)
    parser.add_argument("--bonsuke-json", type=Path, default=Path("data/public/events_public.json"))
    parser.add_argument("--out-json", type=Path, default=Path("data/odottar_coverage_latest.json"))
    parser.add_argument("--out-md", type=Path, default=Path("data/odottar_coverage_latest.md"))
    parser.add_argument("--history", type=Path, default=Path("data/odottar_coverage_history.json"))
    parser.add_argument("--fetched-at", help="Actual odottar retrieval timestamp; omitted means unknown, never now")
    parser.add_argument("--bonsuke-snapshot-at", help="Known Bonsuke snapshot timestamp; omitted means unknown")
    parser.add_argument("--as-of", type=date.fromisoformat, help="First included JST calendar date (default: today in JST)")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--source-url", default="https://odottar.com/events.json")
    args = parser.parse_args(argv)
    raw, odottar_rows = read_json_bytes(args.odottar_json)
    bonsuke_raw, bonsuke_rows = read_json_bytes(args.bonsuke_json)
    report = build_report(raw, odottar_rows, bonsuke_rows, fetched_at=args.fetched_at, source_url=args.source_url,
                          as_of=args.as_of, days=args.days, bonsuke_snapshot_at=args.bonsuke_snapshot_at, bonsuke_raw=bonsuke_raw)
    write_json(args.out_json, report)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.write_text(render_markdown(report), encoding="utf-8")
    append_history(args.history, report)
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
