#!/usr/bin/env python3
"""Promote reviewed dry-run change requests into applyable JSON.

This tool only writes a reviewed JSON file and a small report. It does not run
apply_change_requests.py and does not modify the Master RDB.
"""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_REVIEWER = "おと（Codex）"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def default_reviewed_path(path: Path) -> Path:
    if path.name.endswith("_reviewed.json"):
        return path
    return path.with_name(f"{path.stem}_reviewed{path.suffix or '.json'}")


def load_approved_ids(path: Path | None, explicit_ids: list[str]) -> list[str]:
    ids: list[str] = []
    if path:
        for line in path.read_text(encoding="utf-8").splitlines():
            value = line.strip()
            if not value or value.startswith("#"):
                continue
            ids.append(value)
    ids.extend(explicit_ids)
    return ids


def request_index(requests: list[dict]) -> dict[str, dict]:
    out = {}
    for request in requests:
        request_id = request.get("request_id")
        if not request_id:
            raise ValueError("all requests require request_id")
        if request_id in out:
            raise ValueError(f"duplicate request_id: {request_id}")
        out[request_id] = request
    return out


def promote_payload(
    payload: dict,
    approved_ids: list[str] | None = None,
    *,
    reviewed_by: str = DEFAULT_REVIEWER,
    reviewed_at: str | None = None,
    review_note: str = "",
) -> tuple[dict, dict]:
    if payload.get("request_type") != "rdb_change_requests":
        raise ValueError(f"invalid request_type: {payload.get('request_type')!r}")
    requests = payload.get("requests")
    if not isinstance(requests, list) or not requests:
        raise ValueError("requests must be a non-empty list")
    indexed = request_index(requests)
    selected_ids = approved_ids or list(indexed)
    unknown = [request_id for request_id in selected_ids if request_id not in indexed]
    if unknown:
        raise ValueError(f"approved request_id not found: {', '.join(unknown)}")
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("approved request_id list contains duplicates")

    reviewed_at = reviewed_at or datetime.now(timezone.utc).isoformat()
    promoted = []
    blocked = []
    for request_id in selected_ids:
        request = deepcopy(indexed[request_id])
        if request.get("dry_run_only") is not True:
            blocked.append(request_id)
            continue
        request.pop("dry_run_only", None)
        request["reviewed_by"] = reviewed_by
        request["reviewed_at"] = reviewed_at
        if review_note:
            request["review_note"] = review_note
        promoted.append(request)
    if blocked:
        raise ValueError(
            "selected requests are not dry_run_only; refusing to promote without a fresh review: "
            + ", ".join(blocked)
        )

    reviewed_payload = deepcopy(payload)
    reviewed_payload["generated_by"] = "scripts/promote_change_requests_for_review.py"
    reviewed_payload["source_generated_by"] = payload.get("generated_by")
    reviewed_payload["scope"] = f"{payload.get('scope') or 'change_requests'}_reviewed"
    reviewed_payload["reviewed_by"] = reviewed_by
    reviewed_payload["reviewed_at"] = reviewed_at
    reviewed_payload["review_note"] = review_note
    reviewed_payload["source_request_count"] = len(requests)
    reviewed_payload["approved_request_count"] = len(promoted)
    reviewed_payload["requests"] = promoted

    report = {
        "generated_by": "scripts/promote_change_requests_for_review.py",
        "reviewed_by": reviewed_by,
        "reviewed_at": reviewed_at,
        "source_request_count": len(requests),
        "approved_request_count": len(promoted),
        "skipped_request_count": len(requests) - len(promoted),
        "approved_request_ids": selected_ids,
        "change_type_counts": {},
    }
    for request in promoted:
        change_type = request.get("change_type") or ""
        report["change_type_counts"][change_type] = report["change_type_counts"].get(change_type, 0) + 1
    return reviewed_payload, report


def render_markdown(report: dict) -> str:
    lines = [
        "# Reviewed Change Requests Promotion",
        "",
        f"- generated_by: {report['generated_by']}",
        f"- reviewed_by: {report['reviewed_by']}",
        f"- reviewed_at: {report['reviewed_at']}",
        f"- source_request_count: {report['source_request_count']}",
        f"- approved_request_count: {report['approved_request_count']}",
        f"- skipped_request_count: {report['skipped_request_count']}",
        "",
        "## Change Types",
        "",
    ]
    for key, value in sorted(report["change_type_counts"].items()):
        lines.append(f"- {key}: {value}")
    lines.extend(
        [
            "",
            "## Guard",
            "",
            "- `dry_run_only` was removed only from approved requests.",
            "- `request_id` values are preserved for apply-side idempotency.",
            "- This script does not apply to the Master RDB.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Promote reviewed dry-run change requests into applyable JSON.")
    parser.add_argument("--requests", required=True, type=Path)
    parser.add_argument("--approved-ids", type=Path, help="optional text file with one approved request_id per line")
    parser.add_argument("--request-id", action="append", default=[], help="approved request_id; repeatable")
    parser.add_argument("--reviewed-by", default=DEFAULT_REVIEWER)
    parser.add_argument("--review-note", default="")
    parser.add_argument("--out-json", type=Path)
    parser.add_argument("--out-md", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = load_json(args.requests)
    approved_ids = load_approved_ids(args.approved_ids, args.request_id)
    reviewed_payload, report = promote_payload(
        payload,
        approved_ids or None,
        reviewed_by=args.reviewed_by,
        review_note=args.review_note,
    )
    out_json = args.out_json or default_reviewed_path(args.requests)
    out_md = args.out_md or out_json.with_suffix(".md")
    write_json(out_json, reviewed_payload)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(render_markdown(report), encoding="utf-8")
    print(
        "promoted change requests for review: "
        f"approved={report['approved_request_count']} "
        f"out={out_json}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
