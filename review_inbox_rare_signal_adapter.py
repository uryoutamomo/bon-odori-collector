#!/usr/bin/env python3
"""Adapt interpreted rare-signal backcheck rows without applying them.

The machine-generated X digest is intentionally not an inbox source.  This
adapter accepts only the smaller queue produced after Oto interpretation and
uses immutable discovery references for stable identity.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from review_inbox_source_adapter import load_adapted_source, write_adapted_snapshot


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "data" / "rare_signal_backcheck_queue.json"
DEFAULT_OUTPUT = ROOT / "data" / "review_inbox_adapted" / "rare_signal.json"
PROMOTION_TARGETS = {"event", "song", "venue", "existing_evidence"}
REFERENCE_TARGETS = {"song", "existing_evidence"}
ACTION_CONFIG = {
    "find_non_x_confirmation": "research_non_x_confirmation",
    "review_official_social_post": "review_registered_official_social",
    "review_source_account_then_find_confirmation": "review_source_account_and_confirmation",
}
X_HOSTS = {"x.com", "www.x.com", "twitter.com", "www.twitter.com"}
X_STATUS_RE = re.compile(r"/(?:[^/]+/)?status/(\d+)(?:/|$)")


class RareSignalAdapter:
    source_id = "rare_signal"

    def adapt(self, payload: Any) -> Iterable[Mapping[str, Any]]:
        if not isinstance(payload, dict) or not isinstance(payload.get("queue"), list):
            raise ValueError("rare signal payload requires queue list")
        return [self.adapt_row(row) for row in payload["queue"]]

    def adapt_row(self, row: Any) -> dict[str, Any]:
        if not isinstance(row, dict):
            raise TypeError("rare signal rows must be objects")
        title = str(
            row.get("primary_name")
            or row.get("possible_event_name")
            or row.get("possible_venue")
            or row.get("candidate_id")
            or ""
        ).strip()
        if not title:
            raise ValueError("rare signal row requires a review title")

        promotion_target = str(row.get("promotion_target") or "").strip()
        if promotion_target not in PROMOTION_TARGETS:
            raise ValueError(f"unsupported rare signal promotion target: {promotion_target}")
        next_action = str(row.get("next_action") or "").strip()
        if next_action not in ACTION_CONFIG:
            raise ValueError(f"unsupported rare signal action: {next_action}")

        source_urls = discovery_urls(row)
        source_key = immutable_source_key(row, source_urls=source_urls)
        source_officiality = row.get("source_officiality")
        officiality_class = (
            str(source_officiality.get("classification") or "")
            if isinstance(source_officiality, dict)
            else ""
        )
        return {
            "kind": "rare_signal",
            "domain": "X/RSS",
            "time_scope": "reference" if promotion_target in REFERENCE_TARGETS else "future",
            "priority_label": "P0" if officiality_class == "registered_official_social" else "P1",
            "priority_score": None,
            "title": title,
            "event_name": str(row.get("possible_event_name") or ""),
            "venue": str(row.get("possible_venue") or ""),
            "event_year": integer_or_none(row.get("event_year")),
            "source_key": source_key,
            "source_url": source_urls[0] if source_urls else "",
            "recommended_action": ACTION_CONFIG[next_action],
            "payload": row,
        }


def discovery_urls(row: Mapping[str, Any]) -> list[str]:
    values = row.get("internal_discovery_urls") or row.get("source_urls") or []
    if isinstance(values, str):
        values = [values]
    urls = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in urls:
            urls.append(text)
    return urls


def immutable_source_key(row: Mapping[str, Any], *, source_urls: list[str] | None = None) -> str:
    information_type = str(row.get("information_type") or "rare_signal").strip()
    promotion_target = str(row.get("promotion_target") or "").strip()
    references = sorted(
        {
            reference
            for reference in (
                immutable_source_reference(url) for url in (source_urls or discovery_urls(row))
            )
            if reference
        }
    )
    if not references:
        candidate_id = str(row.get("candidate_id") or "").strip()
        if not candidate_id:
            raise ValueError("rare signal row requires an immutable source URL or candidate_id")
        references = [f"candidate:{candidate_id}"]
    return "|".join((information_type, promotion_target, *references))


def immutable_source_reference(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlsplit(text)
    host = parsed.netloc.lower()
    if not parsed.scheme or not host:
        return ""
    if host in X_HOSTS:
        match = X_STATUS_RE.search(parsed.path)
        if match:
            return f"x-status:{match.group(1)}"
    query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
    canonical = urlunsplit(
        (parsed.scheme.lower(), host, parsed.path.rstrip("/") or "/", query, "")
    )
    return f"url:{canonical}"


def integer_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def build_snapshot(
    input_path: Path,
    *,
    canary_source_key: str | None = None,
) -> dict[str, Any]:
    snapshot = load_adapted_source(RareSignalAdapter(), input_path)
    if canary_source_key is not None:
        source_key = str(canary_source_key).strip()
        if not source_key:
            raise ValueError("rare signal canary source key must not be empty")
        selected = [
            item for item in snapshot["items"] if item.get("source_key") == source_key
        ]
        if len(selected) != 1:
            raise ValueError(
                f"rare signal canary source key must select exactly one item: {source_key}"
            )
        snapshot["items"] = selected
        snapshot["item_count"] = 1
        snapshot["selection"] = {
            "mode": "canary",
            "source_keys": [source_key],
        }
    else:
        snapshot["selection"] = {
            "mode": "all",
            "source_keys": [item["source_key"] for item in snapshot["items"]],
        }
    snapshot["write_mode"] = "snapshot_only_default_off"
    snapshot["upstream_boundary"] = "oto_interpreted_backcheck_candidates_only"
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    snapshot = build_snapshot(args.input)
    write_adapted_snapshot(snapshot, args.output)
    print(
        f"rare signal snapshot: items={snapshot['item_count']} "
        f"input_sha256={snapshot['input_sha256']} -> {args.output}"
    )


if __name__ == "__main__":
    main()
