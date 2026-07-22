#!/usr/bin/env python3
"""Dry-run retrospective harvest candidates into generalized occurrences."""

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from collection_support.event_evidence import dancer_key, normalize_event_name
from song_processing.song_occurrences import occurrence_id
from collection_support.suppression_rules import is_event_sentence_fragment


DATA = Path("data")
RETROSPECTIVE = DATA / "retrospective_harvest_candidates.json"
PUBLIC_EVENTS = DATA / "public" / "events_public.json"
VENUE_MASTER = DATA / "venue_master.json"
X_ACCOUNT_SCORES = DATA / "x_account_scores.json"
OUT = DATA / "retrospective_occurrence_dry_run.json"
OUT_REPORT = DATA / "retrospective_occurrence_dry_run.md"


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data, encoding="utf-8")


def norm(value):
    value = str(value or "")
    value = re.sub(r"[\s　\"'“”‘’「」『』【】\[\]（）()・、。!！?？:：/／\\|｜~〜\-‐‑–—_]+", "", value)
    return value.casefold()


def parse_month(value):
    if value in (None, ""):
        return ""
    try:
        month = int(value)
        return f"{month:02d}" if 1 <= month <= 12 else ""
    except (TypeError, ValueError):
        match = re.search(r"(\d{1,2})", str(value))
        if not match:
            return ""
        month = int(match.group(1))
        return f"{month:02d}" if 1 <= month <= 12 else ""


def event_year(candidate, default_year):
    try:
        return int(candidate.get("year") or default_year)
    except (TypeError, ValueError):
        return default_year


def event_date(candidate, default_year):
    year = event_year(candidate, default_year)
    value = str(candidate.get("estimated_date") or "")
    match = re.search(r"(20\d{2})[/-](\d{1,2})[/-](\d{1,2})", value)
    if match:
        parsed_year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{parsed_year:04d}-{month:02d}-{day:02d}"
    match = re.search(r"(\d{1,2})月(\d{1,2})日", value)
    if not match:
        match = re.search(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?!\d)", value)
    if match:
        month = int(match.group(1))
        day = int(match.group(2))
        if 1 <= month <= 12 and 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
    month = parse_month(candidate.get("month"))
    return f"{year:04d}-{month}-01" if month else ""


def evidence_digest(ev):
    raw = "\0".join(str(ev.get(key) or "") for key in ("identity", "tweet_id", "url", "text"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def evidence_row(ev, target):
    key = ev.get("dancer_key") or dancer_key(ev.get("account"))
    return {
        "id": ev.get("identity") or "retrospective:" + evidence_digest(ev),
        "target": target,
        "tweet_id": str(ev.get("tweet_id") or ""),
        "url": ev.get("url") or "",
        "text": re.sub(r"\s+", " ", str(ev.get("text") or "")).strip()[:240],
        "account": ev.get("account") or "",
        "dancer_key": key,
        "observed_at": ev.get("observed_at") or ev.get("spoken_at") or "",
        "source": "retrospective_harvest",
        "score": ev.get("score") or ev.get("source_score") or 0,
    }


def observation_from_evidence(ev, targets, registered_dancers):
    key = ev.get("dancer_key") or dancer_key(ev.get("account"))
    text = str(ev.get("text") or "")
    if re.search(r"(?:開催|告知|お知らせ|予定|情報)", text):
        act = "announce"
    elif re.search(r"(?:行った|行ってきた|参加した|踊った|踊ってきた|参戦)", text):
        act = "attend"
    else:
        act = "observe"
    return {
        "dancer_key": key,
        "registered_dancer": key in registered_dancers,
        "act": act,
        "targets": sorted(set(targets)),
        "evidence_id": ev.get("identity") or "retrospective:" + evidence_digest(ev),
        "url": ev.get("url") or "",
        "observed_at": ev.get("observed_at") or ev.get("spoken_at") or "",
    }


class MatchIndex:
    def __init__(self, events, venues):
        self.events = events
        self.venues = venues
        self.events_by_event_venue = {}
        self.events_by_event = defaultdict(list)
        self.events_by_venue = defaultdict(list)
        self.venues_by_key = {}
        self._build()

    def _event_keys(self, event):
        event_name = event.get("name") or ""
        venue = event.get("venue") or ""
        event_keys = {norm(event_name), norm(normalize_event_name(event_name))}
        venue_key = norm(venue)
        return {key for key in event_keys if key}, venue_key

    def _build(self):
        for event in self.events:
            event_keys, venue_key = self._event_keys(event)
            for event_key in event_keys:
                self.events_by_event[event_key].append(event)
                if venue_key:
                    self.events_by_event_venue[(event_key, venue_key)] = event
            if venue_key:
                self.events_by_venue[venue_key].append(event)

        for venue in self.venues:
            venue_name = venue.get("venue") or ""
            key = norm(venue_name)
            if key:
                self.venues_by_key[key] = venue

    def match_venue(self, venue_name):
        key = norm(venue_name)
        if not key:
            return None
        if key in self.venues_by_key:
            return self.venues_by_key[key]
        if len(key) < 4:
            return None
        matches = [
            venue for venue_key, venue in self.venues_by_key.items()
            if key in venue_key or venue_key in key
        ]
        return matches[0] if len(matches) == 1 else None

    def match_event(self, candidate):
        candidate_event_keys = {
            norm(candidate.get("display_name")),
            norm(candidate.get("normalized_event")),
            norm(normalize_event_name(candidate.get("display_name"))),
        }
        candidate_event_keys = {key for key in candidate_event_keys if key}
        venue_key = norm(candidate.get("venue"))
        month = parse_month(candidate.get("month"))

        for event_key in candidate_event_keys:
            if venue_key and (event_key, venue_key) in self.events_by_event_venue:
                return self.events_by_event_venue[(event_key, venue_key)], "event_venue"

        for event_key in candidate_event_keys:
            matches = self.events_by_event.get(event_key) or []
            if len(matches) == 1:
                return matches[0], "event_name"

        if venue_key:
            matches = self.events_by_venue.get(venue_key) or []
            if month:
                month_matches = [
                    event for event in matches
                    if month in {parse_month(value) for value in (event.get("months") or [])}
                    or parse_month(event.get("date", "")[5:7] if event.get("date") else "") == month
                ]
                if len(month_matches) == 1:
                    return month_matches[0], "venue_month"
            if len(matches) == 1:
                return matches[0], "venue_only"

        return None, ""


def trusted_dancers(account_scores):
    accounts = account_scores.get("accounts") or {}
    return {
        dancer_key(row.get("handle") or handle)
        for handle, row in accounts.items()
        if row.get("status") == "trusted"
    }


def add_occurrence(occurrences, candidate, event, match_type, venue_match, registered_dancers, default_year):
    year = event_year(candidate, default_year)
    event_name = event.get("name") or candidate.get("display_name") or ""
    venue = event.get("venue") or candidate.get("venue") or ""
    occ_id = occurrence_id(event_name, venue, year)
    row = occurrences.setdefault(occ_id, {
        "occurrence_id": occ_id,
        "event_name": event_name,
        "venue": venue,
        "year": year,
        "source": "retrospective_harvest",
        "event_match": {
            "matched": bool(event),
            "match_type": match_type,
            "name": event.get("name") if event else "",
            "venue": event.get("venue") if event else "",
            "status": event.get("status") if event else "",
        },
        "venue_match": {
            "matched": bool(venue_match),
            "name": (venue_match or {}).get("venue", ""),
            "notion_url": (venue_match or {}).get("notion_url", ""),
        },
        "predictions": {
            "existence": {
                "status": "not_calculated",
                "source": "retrospective_harvest",
                "evidence": [],
            },
            "date": {
                "status": "not_calculated",
                "source": "retrospective_harvest",
                "evidence": [],
            },
        },
        "event_songs": {},
        "observations": [],
        "source_candidates": [],
    })

    candidate_ref = {
        "candidate_key": candidate.get("candidate_key"),
        "kind": candidate.get("kind"),
        "display_name": candidate.get("display_name"),
        "tier": candidate.get("tier"),
        "score": candidate.get("score"),
        "estimated_date": event_date(candidate, default_year),
        "month": candidate.get("month") or "",
    }
    if candidate_ref not in row["source_candidates"]:
        row["source_candidates"].append(candidate_ref)

    targets = ["existence"]
    if event_date(candidate, default_year):
        targets.append("date")
    if candidate.get("kind") == "song":
        targets.append("songs")

    for ev in candidate.get("evidence") or []:
        if "existence" in targets:
            row["predictions"]["existence"]["evidence"].append(evidence_row(ev, "existence"))
        if "date" in targets:
            date_ev = evidence_row(ev, "date")
            date_ev["estimated_date"] = event_date(candidate, default_year)
            row["predictions"]["date"]["evidence"].append(date_ev)
        if candidate.get("kind") == "song":
            song_name = candidate.get("display_name") or ev.get("song_name") or ""
            song = row["event_songs"].setdefault(song_name, {
                "song_name": song_name,
                "source": "retrospective_harvest",
                "evidence": [],
            })
            song["evidence"].append(evidence_row(ev, "songs"))
        row["observations"].append(observation_from_evidence(ev, targets, registered_dancers))


def finalize_occurrences(occurrences):
    rows = []
    for row in occurrences.values():
        for key in ("existence", "date"):
            evidence = row["predictions"][key]["evidence"]
            seen = set()
            unique = []
            for ev in evidence:
                ev_key = ev.get("id")
                if ev_key in seen:
                    continue
                seen.add(ev_key)
                unique.append(ev)
            row["predictions"][key]["evidence"] = unique
            row["predictions"][key]["evidence_count"] = len(unique)

        row["event_songs"] = sorted(
            (
                {
                    **song,
                    "evidence_count": len(song.get("evidence") or []),
                    "speaker_count": len({ev.get("dancer_key") or ev.get("account") for ev in song.get("evidence") or []}),
                }
                for song in row["event_songs"].values()
            ),
            key=lambda item: item["song_name"],
        )
        seen_obs = set()
        observations = []
        for obs in row["observations"]:
            obs_key = (obs.get("dancer_key"), obs.get("act"), obs.get("evidence_id"), tuple(obs.get("targets") or []))
            if obs_key in seen_obs:
                continue
            seen_obs.add(obs_key)
            observations.append(obs)
        row["observations"] = sorted(observations, key=lambda item: (item.get("dancer_key") or "", item.get("observed_at") or ""))
        rows.append(row)
    rows.sort(key=lambda item: (item["year"], item["venue"], item["event_name"]))
    return rows


def new_event_candidate(candidate, venue_match, default_year):
    flags = review_flags(candidate, venue_match)
    evidence = [evidence_row(ev, "existence") for ev in (candidate.get("evidence") or [])[:5]]
    return {
        "candidate_key": candidate.get("candidate_key"),
        "display_name": candidate.get("display_name"),
        "normalized_event": candidate.get("normalized_event") or "",
        "venue": candidate.get("venue") or "",
        "venue_matched": bool(venue_match),
        "venue_match_name": (venue_match or {}).get("venue", ""),
        "year": event_year(candidate, default_year),
        "estimated_date": event_date(candidate, default_year),
        "month": candidate.get("month") or "",
        "tier": candidate.get("tier"),
        "score": candidate.get("score"),
        "evidence_count": candidate.get("evidence_count") or len(candidate.get("evidence") or []),
        "speaker_count": candidate.get("speaker_count") or 0,
        "source": "retrospective_harvest",
        "apply_status": "dry_run_review_required",
        "review_priority": review_priority(candidate, venue_match, flags),
        "review_flags": flags,
        "evidence_urls": [ev.get("url") for ev in candidate.get("evidence") or [] if ev.get("url")][:5],
        "evidence": evidence,
    }


def review_flags(candidate, venue_match):
    name = candidate.get("display_name") or ""
    normalized = candidate.get("normalized_event") or normalize_event_name(name)
    flags = []
    if is_event_sentence_fragment(name, normalized=normalized, has_anchor=bool(candidate.get("venue") or venue_match)):
        flags.append("sentence_fragment")
    if re.match(r"^(?:[0-9０-９]+|と|との|は|で|に|ここから|たぶん|とある|すっかり|今年初)", name):
        flags.append("bad_prefix")
    if len(name) >= 18 and re.search(r"(?:は|が|を|と|で|に|へ|から|まで|した|する|して|踊る|踊り|開催)", name):
        flags.append("long_phrase")
    if not candidate.get("venue") and not venue_match:
        flags.append("no_venue")
    if candidate.get("score", 0) >= 40:
        flags.append("high_score")
    return sorted(set(flags))


def review_priority(candidate, venue_match, flags):
    if "sentence_fragment" in flags or "bad_prefix" in flags or "long_phrase" in flags:
        return "noise_check"
    if candidate.get("score", 0) >= 40 and (candidate.get("venue") or venue_match):
        return "high"
    if candidate.get("score", 0) >= 40:
        return "medium"
    return "low"


def build_dry_run(candidates_data, events, venues, account_scores, target_year=None, generated_at=None):
    target_year = target_year or datetime.now(timezone.utc).year
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    index = MatchIndex(events, venues)
    registered_dancers = trusted_dancers(account_scores)
    occurrences = {}
    new_events = []
    skipped = Counter()
    match_types = Counter()

    for candidate in candidates_data.get("candidates") or []:
        if candidate.get("tier") not in {"promote", "review"}:
            skipped["tier_hold"] += 1
            continue
        venue_match = index.match_venue(candidate.get("venue"))
        match_candidate = dict(candidate)
        if venue_match and venue_match.get("venue"):
            match_candidate["venue"] = venue_match["venue"]
        event, match_type = index.match_event(match_candidate)
        if event:
            match_types[match_type] += 1
            add_occurrence(occurrences, candidate, event, match_type, venue_match, registered_dancers, target_year)
        elif candidate.get("kind") == "event":
            new_events.append(new_event_candidate(candidate, venue_match, target_year))
        else:
            skipped[f"unmatched_{candidate.get('kind') or 'unknown'}"] += 1

    occurrence_rows = finalize_occurrences(occurrences)
    by_kind = Counter(candidate.get("kind") for candidate in candidates_data.get("candidates") or [])
    by_tier = Counter(candidate.get("tier") for candidate in candidates_data.get("candidates") or [])
    occurrence_candidate_count = sum(len(row.get("source_candidates") or []) for row in occurrence_rows)
    dancer_keys = {
        obs.get("dancer_key")
        for row in occurrence_rows
        for obs in row.get("observations") or []
        if obs.get("dancer_key")
    }
    for candidate in new_events:
        for ev in next(
            (item.get("evidence") or [] for item in candidates_data.get("candidates") or []
             if item.get("candidate_key") == candidate.get("candidate_key")),
            [],
        ):
            key = ev.get("dancer_key") or dancer_key(ev.get("account"))
            if key:
                dancer_keys.add(key)

    return {
        "generated_by": "build_retrospective_occurrences.py",
        "generated_at": generated_at,
        "source": str(RETROSPECTIVE),
        "mode": "dry_run",
        "apply_performed": False,
        "target_year": target_year,
        "input_candidate_count": candidates_data.get("candidate_count") or len(candidates_data.get("candidates") or []),
        "input_counts": {
            "by_kind": dict(sorted(by_kind.items())),
            "by_tier": dict(sorted(by_tier.items())),
        },
        "summary": {
            "processed_candidate_count": sum(1 for item in candidates_data.get("candidates") or [] if item.get("tier") in {"promote", "review"}),
            "matched_existing_occurrence_count": len(occurrence_rows),
            "matched_existing_candidate_count": occurrence_candidate_count,
            "new_event_candidate_count": len(new_events),
            "registered_dancer_source": "data/x_account_scores.json status=trusted",
            "registered_dancer_count": len(registered_dancers),
            "observed_dancer_count": len(dancer_keys),
            "observed_registered_dancer_count": len(dancer_keys & registered_dancers),
            "observed_unregistered_dancer_count": len(dancer_keys - registered_dancers),
            "match_types": dict(sorted(match_types.items())),
            "skipped": dict(sorted(skipped.items())),
        },
        "occurrences": occurrence_rows,
        "new_event_candidates": sorted(new_events, key=lambda item: (-int(item.get("score") or 0), item.get("display_name") or "")),
    }


def markdown_report(output):
    summary = output["summary"]
    lines = [
        "# Retrospective occurrence dry-run",
        "",
        f"- generated_at: {output['generated_at']}",
        f"- input_candidate_count: {output['input_candidate_count']}",
        f"- processed_candidate_count: {summary['processed_candidate_count']}",
        f"- matched_existing_candidate_count: {summary['matched_existing_candidate_count']}",
        f"- matched_existing_occurrence_count: {summary['matched_existing_occurrence_count']}",
        f"- new_event_candidate_count: {summary['new_event_candidate_count']}",
        f"- apply_performed: {output['apply_performed']}",
        "",
        "## Match Types",
        "",
    ]
    for key, value in summary.get("match_types", {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Skipped", ""])
    for key, value in summary.get("skipped", {}).items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Existing Occurrences", ""])
    lines.append("| event | venue | candidates | songs | match |")
    lines.append("|---|---|---:|---:|---|")
    for row in output.get("occurrences", [])[:50]:
        lines.append(
            "| {event} | {venue} | {candidates} | {songs} | {match} |".format(
                event=row.get("event_name", "").replace("|", " "),
                venue=row.get("venue", "").replace("|", " "),
                candidates=len(row.get("source_candidates") or []),
                songs=len(row.get("event_songs") or []),
                match=(row.get("event_match") or {}).get("match_type", ""),
            )
        )

    lines.extend(["", "## New Event Candidates", ""])
    lines.append("| priority | score | event | venue | date | flags | evidence |")
    lines.append("|---|---:|---|---|---|---|---:|")
    for row in output.get("new_event_candidates", [])[:120]:
        lines.append(
            "| {priority} | {score} | {event} | {venue} | {date} | {flags} | {evidence} |".format(
                priority=row.get("review_priority", ""),
                score=row.get("score", ""),
                event=row.get("display_name", "").replace("|", " "),
                venue=(row.get("venue_match_name") or row.get("venue") or "").replace("|", " "),
                date=row.get("estimated_date", ""),
                flags=", ".join(row.get("review_flags") or []),
                evidence=row.get("evidence_count", ""),
            )
        )
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, default=RETROSPECTIVE)
    parser.add_argument("--events", type=Path, default=PUBLIC_EVENTS)
    parser.add_argument("--venues", type=Path, default=VENUE_MASTER)
    parser.add_argument("--accounts", type=Path, default=X_ACCOUNT_SCORES)
    parser.add_argument("--target-year", type=int, default=None)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--report-out", type=Path, default=OUT_REPORT)
    args = parser.parse_args()

    output = build_dry_run(
        load_json(args.candidates, {}),
        load_json(args.events, []),
        load_json(args.venues, []),
        load_json(args.accounts, {}),
        target_year=args.target_year,
    )
    write_json(args.out, output)
    write_text(args.report_out, markdown_report(output))
    summary = output["summary"]
    print(
        "retrospective occurrence dry-run: "
        f"processed={summary['processed_candidate_count']} "
        f"matched_candidates={summary['matched_existing_candidate_count']} "
        f"matched_occurrences={summary['matched_existing_occurrence_count']} "
        f"new_events={summary['new_event_candidate_count']} -> {args.out}, {args.report_out}"
    )


if __name__ == "__main__":
    main()
