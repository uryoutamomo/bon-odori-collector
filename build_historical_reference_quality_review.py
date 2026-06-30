"""Build a review queue for already-published historical references.

The queue catches historical-reference events that are still missing reviewable
value, especially concrete historical dates and song hints.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


DATA = Path("data")
PUBLIC_EVENTS = DATA / "public" / "events_public.json"
OUT_JSON = DATA / "historical_reference_quality_review.json"
OUT_MD = DATA / "historical_reference_quality_review.md"
WEEKDAYS = ["月", "火", "水", "木", "金", "土", "日"]


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def public_event_rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        rows = payload.get("events") or payload.get("items") or []
    else:
        rows = payload
    return [row for row in rows if isinstance(row, dict)]


def parse_iso_date(value: Any) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def historical_dates(event: dict[str, Any]) -> list[str]:
    values = event.get("historical_last_seen_dates") or event.get("last_seen_dates") or []
    if not isinstance(values, list):
        values = []
    if not values:
        values = [value for value in (event.get("date"), event.get("date_end")) if value]
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if not isinstance(value, str) or value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def date_with_weekday(value: str) -> str:
    parsed = parse_iso_date(value)
    if not parsed:
        return value
    return f"{parsed.isoformat()}（{WEEKDAYS[parsed.weekday()]}）"


def dates_label(values: list[str]) -> str:
    if not values:
        return ""
    if len(values) == 1:
        return date_with_weekday(values[0])
    return f"{date_with_weekday(values[0])}〜{date_with_weekday(values[-1])}"


def weekdays_label(values: list[str]) -> str:
    labels = []
    for value in values:
        parsed = parse_iso_date(value)
        if not parsed:
            continue
        label = WEEKDAYS[parsed.weekday()]
        if label not in labels:
            labels.append(label)
    return "〜".join(labels)


def is_historical_reference(event: dict[str, Any]) -> bool:
    return bool(
        event.get("historical_reference")
        or event.get("historical_display_tier")
        or event.get("public_category") == "recurring_last_year"
    )


def stable_review_id(event: dict[str, Any], dates: list[str]) -> str:
    raw = "|".join(
        str(value or "")
        for value in [
            event.get("id"),
            event.get("name"),
            event.get("venue"),
            event.get("historical_last_seen_year") or event.get("last_seen_year"),
            ",".join(dates),
        ]
    )
    return "hrq_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def quality_issues(event: dict[str, Any]) -> list[str]:
    dates = historical_dates(event)
    issues = []
    if not dates:
        issues.append("historical_date_missing")
    elif any(parse_iso_date(value) is None for value in dates):
        issues.append("historical_date_invalid")
    if not event.get("songs"):
        issues.append("historical_songs_missing")
    return issues


def priority_for(issues: list[str]) -> tuple[int, str, str]:
    if "historical_date_missing" in issues or "historical_date_invalid" in issues:
        return 10, "P0", "review_missing_historical_date"
    if "historical_songs_missing" in issues:
        return 6, "P1", "review_missing_historical_songs"
    return 1, "P2", "review_context_only"


def issue_summary(issues: list[str]) -> str:
    labels = {
        "historical_date_missing": "過去実績日なし",
        "historical_date_invalid": "過去実績日が不正",
        "historical_songs_missing": "曲なし",
    }
    return " / ".join(labels.get(issue, issue) for issue in issues)


def next_step(issues: list[str]) -> str:
    if "historical_date_missing" in issues or "historical_date_invalid" in issues:
        return "過去実績としての公開価値が低いため、日付・曜日の根拠を再確認する。"
    if "historical_songs_missing" in issues:
        return "過去実績の曲候補がないため、YouTube/曲実績側の収集対象に回す。"
    return "文脈確認のみ。"


def build_review(events: list[dict[str, Any]]) -> dict[str, Any]:
    review: list[dict[str, Any]] = []
    historical_count = 0
    issue_counts: Counter[str] = Counter()
    for event in events:
        if not is_historical_reference(event):
            continue
        historical_count += 1
        issues = quality_issues(event)
        if not issues:
            continue
        issue_counts.update(issues)
        dates = historical_dates(event)
        songs = event.get("songs") if isinstance(event.get("songs"), list) else []
        score, label, action = priority_for(issues)
        review.append(
            {
                "quality_review_id": stable_review_id(event, dates),
                "event_name": event.get("name") or "",
                "name": event.get("name") or "",
                "venue": event.get("venue") or "",
                "area": event.get("area") or "",
                "public_category": event.get("public_category") or "",
                "public_status": event.get("public_status") or "",
                "display_tier": event.get("display_tier") or event.get("historical_display_tier") or "",
                "historical_last_seen_year": event.get("historical_last_seen_year") or event.get("last_seen_year") or "",
                "historical_dates": dates,
                "historical_dates_label": dates_label(dates),
                "historical_weekdays_label": weekdays_label(dates),
                "song_count": len(songs),
                "songs_sample": [song.get("name") or song.get("title") or song for song in songs[:8]],
                "source_url": event.get("source_url") or "",
                "historical_reference_label": event.get("historical_reference_label") or "",
                "historical_reference_confidence": event.get("historical_reference_confidence") or "",
                "historical_reference_score": event.get("historical_reference_score") or "",
                "issue_codes": issues,
                "issue_summary": issue_summary(issues),
                "next_step": next_step(issues),
                "priority_score": score,
                "priority_label": label,
                "recommended_action": action,
            }
        )
    review.sort(key=lambda row: (row["priority_label"], -row["priority_score"], row["event_name"], row["venue"]))
    return {
        "generated_by": "build_historical_reference_quality_review.py",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(PUBLIC_EVENTS),
        "summary": {
            "historical_reference_count": historical_count,
            "review_count": len(review),
            "issue_counts": dict(issue_counts),
        },
        "review": review,
    }


def markdown_cell(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def render_markdown(payload: dict[str, Any]) -> str:
    summary = payload["summary"]
    lines = [
        "# 採用済み過去実績品質レビュー",
        "",
        f"- generated_at: {payload['generated_at']}",
        f"- historical_reference_count: {summary['historical_reference_count']}",
        f"- review_count: {summary['review_count']}",
        f"- issue_counts: {summary['issue_counts']}",
        "",
        "| priority | issue | event | venue | historical dates | songs | action |",
        "| --- | --- | --- | --- | --- | ---: | --- |",
    ]
    for row in payload["review"][:160]:
        lines.append(
            f"| {row['priority_label']} | {markdown_cell(row['issue_summary'])} | "
            f"{markdown_cell(row['event_name'])} | {markdown_cell(row['venue'])} | "
            f"{markdown_cell(row['historical_dates_label'])} | {row['song_count']} | "
            f"{row['recommended_action']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-events", default=str(PUBLIC_EVENTS))
    parser.add_argument("--out-json", default=str(OUT_JSON))
    parser.add_argument("--out-md", default=str(OUT_MD))
    args = parser.parse_args()

    events = public_event_rows(load_json(Path(args.public_events), []))
    payload = build_review(events)
    write_json(Path(args.out_json), payload)
    Path(args.out_md).write_text(render_markdown(payload), encoding="utf-8")
    print(
        "historical reference quality review: "
        f"historical={payload['summary']['historical_reference_count']} "
        f"review={payload['summary']['review_count']} "
        f"issues={payload['summary']['issue_counts']}"
    )


if __name__ == "__main__":
    main()
