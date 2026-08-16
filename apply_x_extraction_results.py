#!/usr/bin/env python3
"""Validate untrusted X extraction answers and persist deterministic observations."""
from __future__ import annotations

import argparse
import json
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

from build_x_extraction_packets import normalized_text
from master_rdb.master_db import normalize_text, stable_id


SONG_ISSUE_TYPES = {"malformed_observation", "empty_song_name", "song_not_in_text"}
GLOSSARY_ISSUE_TYPES = {"malformed_glossary", "malformed_term", "empty_term", "term_not_in_text"}


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _issue(issues, kind, **extra):
    issues.append({"issue_type": kind, **extra})


def _add_url(detail: str, url: str) -> str:
    line = f"- 出典URL: {url}"
    return detail if line in detail else detail.rstrip() + "\n" + line


def _detail(note: str, packet: dict) -> str:
    if packet.get("officiality") == "registered_official_social":
        who = packet.get("account_name") or packet.get("account") or "公式アカウント"
        prefix = f"出典：{who}のX投稿。"
    else:
        prefix = "現地の告知投稿で開催を確認。"
    return _add_url((prefix + (note if note else "")).strip(), packet.get("url") or "")


def _material_text(value: str) -> str:
    """Normalize only the variants allowed by E0X-S v1.1.

    NFKC folds full-width ASCII. Middle dots, prolonged sound marks, URLs and
    whitespace are ignored. Hiragana and katakana intentionally stay distinct.
    """
    value = unicodedata.normalize("NFKC", str(value or ""))
    return normalized_text(value).replace("・", "").replace("ー", "")


def _appears_in_text(value: str, text: str) -> bool:
    needle = _material_text(value)
    return bool(needle) and needle in _material_text(text)


def _song_rows(ledger: dict) -> list[dict]:
    rows = ledger.get("observations")
    if not isinstance(rows, list):
        rows = []
        ledger["observations"] = rows
    return rows


def _glossary_rows(ledger: dict) -> list[dict]:
    rows = ledger.get("terms")
    if not isinstance(rows, list):
        rows = []
        ledger["terms"] = rows
    return rows


def _record_song_group(
    *,
    item: dict,
    no,
    event_name,
    songs,
    origin: str,
    score: int | None,
    batch_id,
    stamp: str,
    issues: list[dict],
    rows: list[dict],
    existing_ids: set[str],
) -> int:
    if event_name is not None and not isinstance(event_name, str):
        _issue(issues, "malformed_observation", no=no, origin=origin)
        return 0
    if not isinstance(songs, list):
        _issue(issues, "malformed_observation", no=no, origin=origin)
        return 0

    event_value = event_name.strip() if isinstance(event_name, str) else None
    text = str(item.get("text") or "")
    added = 0
    for song_index, raw_song in enumerate(songs):
        if not isinstance(raw_song, str) or not raw_song.strip():
            _issue(issues, "empty_song_name", no=no, origin=origin, song_index=song_index)
            continue
        song_name = raw_song.strip()
        if not _appears_in_text(song_name, text):
            _issue(issues, "song_not_in_text", no=no, origin=origin, song_name=song_name)
            continue
        observation_id = stable_id(
            "xsong",
            item.get("tweet_id") or "",
            _material_text(event_value or ""),
            _material_text(song_name),
        )
        if observation_id in existing_ids:
            continue
        rows.append({
            "observation_id": observation_id,
            "tweet_id": item.get("tweet_id") or "",
            "url": item.get("url") or "",
            "posted_at": item.get("posted_at") or "",
            "account": item.get("account") or "",
            "officiality": item.get("officiality") or "",
            "event_name": event_value,
            "song_name": song_name,
            "origin": origin,
            "batch_id": batch_id,
            "score": score,
            "text": text,
            "first_seen_at": stamp,
        })
        existing_ids.add(observation_id)
        added += 1
    return added


def _record_glossary(
    *,
    item: dict,
    no,
    glossary,
    stamp: str,
    issues: list[dict],
    rows: list[dict],
) -> set[str]:
    if not isinstance(glossary, list):
        _issue(issues, "malformed_glossary", no=no)
        return set()

    by_term = {
        row.get("term"): row
        for row in rows
        if isinstance(row, dict) and isinstance(row.get("term"), str)
    }
    accepted: set[str] = set()
    tweet_id = str(item.get("tweet_id") or "")
    text = str(item.get("text") or "")
    for term_index, raw_term in enumerate(glossary):
        if not isinstance(raw_term, str):
            _issue(issues, "malformed_term", no=no, term_index=term_index)
            continue
        term = raw_term.strip()
        if not term:
            _issue(issues, "empty_term", no=no, term_index=term_index)
            continue
        if not _appears_in_text(term, text):
            _issue(issues, "term_not_in_text", no=no, term=term)
            continue
        accepted.add(term)
        row = by_term.get(term)
        if row is None:
            row = {
                "term": term,
                "source_tweet_ids": [],
                "count": 0,
                "first_seen_at": stamp,
                "last_seen_at": stamp,
                "examples": [],
            }
            rows.append(row)
            by_term[term] = row

        source_ids = row.get("source_tweet_ids")
        if not isinstance(source_ids, list):
            source_ids = []
            row["source_tweet_ids"] = source_ids
        if tweet_id not in source_ids:
            source_ids.append(tweet_id)
            row["last_seen_at"] = stamp
            examples = row.get("examples")
            if not isinstance(examples, list):
                examples = []
                row["examples"] = examples
            if len(examples) < 5:
                examples.append({"tweet_id": tweet_id, "url": item.get("url") or "", "text": text})
        # count is deliberately derived; it must never drift from source_tweet_ids.
        row["count"] = len(source_ids)
    return accepted


def _record_materials(
    result: dict,
    item: dict,
    no,
    score: int | None,
    batch_id,
    stamp: str,
    issues: list[dict],
    song_ledger: dict,
    glossary_ledger: dict,
) -> tuple[int, set[str]]:
    song_rows = _song_rows(song_ledger)
    existing_ids = {
        row.get("observation_id")
        for row in song_rows
        if isinstance(row, dict) and row.get("observation_id")
    }
    new_songs = 0

    # Events go first so a duplicate from observations keeps the stronger origin.
    events = result.get("events")
    if score == 5 and isinstance(events, list):
        for event in events:
            if isinstance(event, dict) and "songs" in event:
                new_songs += _record_song_group(
                    item=item,
                    no=no,
                    event_name=event.get("event_name"),
                    songs=event.get("songs"),
                    origin="events",
                    score=score,
                    batch_id=batch_id,
                    stamp=stamp,
                    issues=issues,
                    rows=song_rows,
                    existing_ids=existing_ids,
                )

    if "observations" in result:
        observations = result.get("observations")
        if not isinstance(observations, list):
            _issue(issues, "malformed_observation", no=no, origin="observations")
        else:
            for observation in observations:
                if not isinstance(observation, dict):
                    _issue(issues, "malformed_observation", no=no, origin="observations")
                    continue
                new_songs += _record_song_group(
                    item=item,
                    no=no,
                    event_name=observation.get("event_name"),
                    songs=observation.get("songs"),
                    origin="observations",
                    score=score,
                    batch_id=batch_id,
                    stamp=stamp,
                    issues=issues,
                    rows=song_rows,
                    existing_ids=existing_ids,
                )

    accepted_terms: set[str] = set()
    if "glossary" in result:
        accepted_terms = _record_glossary(
            item=item,
            no=no,
            glossary=result.get("glossary"),
            stamp=stamp,
            issues=issues,
            rows=_glossary_rows(glossary_ledger),
        )
    return new_songs, accepted_terms


def apply(
    packet: dict,
    answer: dict,
    state: dict,
    reports_dir: Path,
    *,
    song_ledger: dict | None = None,
    glossary_ledger: dict | None = None,
    today: date | None = None,
    now: datetime | None = None,
) -> dict:
    now = now or datetime.now(timezone.utc)
    # Preserve the existing local-calendar cutoff for event dates. `now` is UTC
    # because it is only used for persisted timestamps.
    today = today or date.today()
    stamp = now.isoformat()
    issues: list[dict] = []
    reports: list[str] = []
    scores: list[dict] = []
    song_ledger = song_ledger if isinstance(song_ledger, dict) else {}
    glossary_ledger = glossary_ledger if isinstance(glossary_ledger, dict) else {}
    song_ledger.update({"generated_by": "apply_x_extraction_results.py", "updated_at": stamp})
    glossary_ledger.update({"generated_by": "apply_x_extraction_results.py", "updated_at": stamp})

    if "tweets" not in state:
        state["tweets"] = {key: value for key, value in state.items() if isinstance(value, dict)}
    state_rows = state["tweets"]
    by_no = {item["no"]: item for item in packet.get("packets", [])}
    answers = {}
    if answer.get("batch_id") != packet.get("batch_id"):
        _issue(issues, "batch_id_mismatch")
    for result in answer.get("results", []):
        if not isinstance(result, dict):
            _issue(issues, "malformed_result")
            continue
        no = result.get("no")
        if no not in by_no:
            _issue(issues, "unknown_packet", no=no)
            continue
        if no not in answers:
            answers[no] = result

    song_observation_count = 0
    accepted_glossary_terms: set[str] = set()
    reports_dir.mkdir(parents=True, exist_ok=True)
    for no, item in by_no.items():
        result = answers.get(no)
        outcome = "issue"
        if not isinstance(result, dict):
            # Missing answers stay issued so they can be reissued after 24 hours.
            _issue(issues, "missing_result", no=no)
            continue

        score = result.get("s")
        if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 5:
            _issue(issues, "invalid_score", no=no)
            score = None
        if score is not None:
            scores.append({
                "batch_id": packet.get("batch_id"),
                "no": no,
                "tweet_id": item["tweet_id"],
                "score": score,
                "note": result.get("n"),
            })

        added, accepted_terms = _record_materials(
            result,
            item,
            no,
            score,
            packet.get("batch_id"),
            stamp,
            issues,
            song_ledger,
            glossary_ledger,
        )
        song_observation_count += added
        accepted_glossary_terms.update(accepted_terms)

        if score is not None and score < 5:
            outcome = "scored_only"
        elif score == 5:
            events = result.get("events")
            if not isinstance(events, list) or not events:
                _issue(issues, "missing_events", no=no)
            else:
                for event in events:
                    if not isinstance(event, dict):
                        _issue(issues, "malformed_event", no=no)
                        continue
                    event_ok = True
                    past = False
                    quote = str(event.get("quote") or "")
                    venue = str(event.get("venue_name") or "")
                    dates = [event.get("date_start"), event.get("date_end") or event.get("date_start")]
                    if not quote or normalized_text(quote) not in normalized_text(item.get("text", "")):
                        _issue(issues, "quote_not_in_text", no=no)
                        event_ok = False
                    if not venue or normalized_text(venue) not in normalized_text(item.get("text", "")):
                        _issue(issues, "venue_not_in_text", no=no)
                        event_ok = False
                    if not item.get("url"):
                        _issue(issues, "missing_source_url", no=no)
                        event_ok = False
                    if any(value not in item.get("machine_extracted_dates", []) for value in dates):
                        _issue(issues, "date_not_in_text", no=no)
                        event_ok = False
                        continue
                    if dates[1] < dates[0]:
                        _issue(issues, "date_range_invalid", no=no)
                        event_ok = False
                        continue
                    if event_ok and date.fromisoformat(dates[1]) < today:
                        _issue(issues, "date_in_past", no=no)
                        past = True
                    if past:
                        continue
                    if event_ok:
                        outcome = "report"
                        report_id = "x_event_" + stable_id(
                            "xevent",
                            normalize_text(event.get("event_name") or ""),
                            event["date_start"],
                            normalize_text(event.get("venue_name") or ""),
                        )
                        path = reports_dir / f"{report_id}.json"
                        if path.exists():
                            report = load(path, {})
                            existing = report.get("events", [{}])[0]
                            existing["detail_addendum"] = _add_url(existing.get("detail_addendum", ""), item["url"])
                        else:
                            report = {
                                "report_type": "official_notice",
                                "reported_at": stamp,
                                "source": {
                                    "report_id": report_id,
                                    "title": f"{event.get('event_name')}（X投稿より）",
                                    "account_key": item.get("account") or "",
                                    "url": item.get("url"),
                                    "notice_kind": "x_post",
                                    "raw_text": item.get("text") or "",
                                },
                                "events": [{
                                    "action": "register_new",
                                    "event_name_hint": event.get("event_name"),
                                    "event_year": int(event["date_start"][:4]),
                                    "date_start": event["date_start"],
                                    "date_end": event.get("date_end") or event["date_start"],
                                    "venue": {"name": event.get("venue_name"), "area": event.get("ward") or ""},
                                    "detail_addendum": _detail(str(result.get("n") or "").strip(), item),
                                }],
                            }
                        _write(path, report)
                        reports.append(report_id)

        if outcome != "report" and result.get("s") == 5:
            outcome = (
                "scored_only"
                if any(row.get("issue_type") == "date_in_past" and row.get("no") == no for row in issues)
                else "issue"
            )
        state_rows[item["tweet_id"]] = {
            "issued_at": state_rows.get(item["tweet_id"], {}).get("issued_at"),
            "batch_id": packet.get("batch_id"),
            "applied_at": stamp,
            "outcome": outcome,
        }

    song_rows = _song_rows(song_ledger)
    glossary_rows = _glossary_rows(glossary_ledger)
    song_rows.sort(key=lambda row: str(row.get("observation_id") or ""))
    glossary_rows.sort(key=lambda row: str(row.get("term") or ""))
    song_issue_count = sum(row.get("issue_type") in SONG_ISSUE_TYPES for row in issues)
    glossary_issue_count = sum(row.get("issue_type") in GLOSSARY_ISSUE_TYPES for row in issues)
    return {
        "batch_id": packet.get("batch_id"),
        "score_count": len(scores),
        "report_count": len(set(reports)),
        "bundled_count": len(reports) - len(set(reports)),
        "song_observation_count": song_observation_count,
        "glossary_term_count": len(accepted_glossary_terms),
        "song_issue_count": song_issue_count,
        "glossary_issue_count": glossary_issue_count,
        "song_observations_total": len(song_rows),
        "glossary_terms_total": len(glossary_rows),
        "issues": issues,
        "scores": scores,
        "reports": sorted(set(reports)),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--state", type=Path, default=Path("data/x_extraction_state.json"))
    parser.add_argument("--reports-dir", type=Path, default=Path("data/x_post_reports"))
    parser.add_argument("--scores", type=Path, default=Path("data/x_post_scores.json"))
    parser.add_argument("--song-observations", type=Path, default=Path("data/x_song_observations.json"))
    parser.add_argument("--glossary-observations", type=Path, default=Path("data/x_glossary_observations.json"))
    parser.add_argument("--out", type=Path, default=Path("data/x_post_extraction_apply_report.json"))
    args = parser.parse_args()

    state = load(args.state, {"tweets": {}})
    song_ledger = load(args.song_observations, {"observations": []})
    glossary_ledger = load(args.glossary_observations, {"terms": []})
    result = apply(
        load(args.packet, {}),
        load(args.results, {}),
        state,
        args.reports_dir,
        song_ledger=song_ledger,
        glossary_ledger=glossary_ledger,
    )
    old_scores = load(args.scores, [])
    _write(args.scores, old_scores + result["scores"])
    _write(args.state, state)
    _write(args.song_observations, song_ledger)
    _write(args.glossary_observations, glossary_ledger)
    _write(args.out, result)
    print(json.dumps({
        "reports": result["report_count"],
        "song_observations": result["song_observation_count"],
        "glossary_terms": result["glossary_term_count"],
        "issues": len(result["issues"]),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
