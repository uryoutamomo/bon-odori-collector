#!/usr/bin/env python3
"""Compare adapted legacy review sources with the consolidated inbox projection."""

from __future__ import annotations

import argparse
import json
import string
from pathlib import Path
from typing import Any

from review_inbox import payload_hash
from review_inbox_adapters.source_adapter import input_sha256


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DEFAULT_INBOX = DATA / "review_inbox.json"
DEFAULT_JSON = DATA / "review_inbox_parity.json"
DEFAULT_MD = DATA / "review_inbox_parity.md"

PARITY_FIELDS = (
    "kind",
    "time_scope",
    "event_name",
    "venue",
    "event_year",
    "source_url",
    "recommended_action",
)


def read_json(path: Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def item_payload_hash(item: dict[str, Any]) -> str:
    if item.get("source_payload_hash"):
        return str(item["source_payload_hash"])
    payload = item.get("payload")
    payload_json = json.dumps({} if payload is None else payload, ensure_ascii=False, sort_keys=True)
    return payload_hash(payload_json)


def comparable_value(item: dict[str, Any], field: str) -> Any:
    value = item.get(field)
    return "" if value is None else value


def index_items(items: list[dict[str, Any]], *, label: str) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    duplicates = []
    for item in items:
        inbox_id = str(item.get("inbox_id") or "")
        if not inbox_id:
            raise ValueError(f"{label} item is missing inbox_id")
        if inbox_id in indexed:
            duplicates.append(inbox_id)
        indexed[inbox_id] = item
    if duplicates:
        raise ValueError(f"{label} contains duplicate inbox ids: {', '.join(sorted(set(duplicates)))}")
    return indexed


def compare_source(
    adapted_snapshot: dict[str, Any],
    inbox_items: list[dict[str, Any]],
) -> dict[str, Any]:
    source_id = str(adapted_snapshot.get("source_id") or "")
    if not source_id:
        raise ValueError("adapted source snapshot is missing source_id")
    source_input_sha = str(adapted_snapshot.get("input_sha256") or "")
    if len(source_input_sha) != 64 or any(char not in string.hexdigits for char in source_input_sha):
        raise ValueError(f"adapted source snapshot has invalid input_sha256: {source_id}")
    expected_items = list(adapted_snapshot.get("items") or [])
    actual_items = [item for item in inbox_items if item.get("source_id") == source_id]
    expected = index_items(expected_items, label=f"{source_id} expected")
    actual = index_items(actual_items, label=f"{source_id} inbox")

    missing = sorted(set(expected) - set(actual))
    extra = sorted(set(actual) - set(expected))
    mismatches = []
    for inbox_id in sorted(set(expected).intersection(actual)):
        fields: dict[str, dict[str, Any]] = {}
        for field in PARITY_FIELDS:
            expected_value = comparable_value(expected[inbox_id], field)
            actual_value = comparable_value(actual[inbox_id], field)
            if expected_value != actual_value:
                fields[field] = {"expected": expected_value, "actual": actual_value}
        expected_hash = item_payload_hash(expected[inbox_id])
        actual_hash = item_payload_hash(actual[inbox_id])
        if expected_hash != actual_hash:
            fields["source_payload_hash"] = {
                "expected": expected_hash,
                "actual": actual_hash,
            }
        if fields:
            mismatches.append({"inbox_id": inbox_id, "fields": fields})

    parity = not missing and not extra and not mismatches
    return {
        "source_id": source_id,
        "input": {
            "path": adapted_snapshot.get("input_path") or "",
            "sha256": source_input_sha.lower(),
            "size_bytes": adapted_snapshot.get("input_size_bytes"),
            "adapter_snapshot_path": adapted_snapshot.get("adapter_snapshot_path") or "",
            "adapter_snapshot_sha256": adapted_snapshot.get("adapter_snapshot_sha256") or "",
        },
        "summary": {
            "expected_count": len(expected),
            "inbox_count": len(actual),
            "missing_count": len(missing),
            "extra_count": len(extra),
            "content_mismatch_count": len(mismatches),
            "parity": parity,
        },
        "missing_in_inbox": missing,
        "extra_in_inbox": extra,
        "content_mismatches": mismatches,
    }


def build_parity_report(
    adapted_snapshots: list[dict[str, Any]],
    inbox_payload: dict[str, Any],
) -> dict[str, Any]:
    source_ids = [str(snapshot.get("source_id") or "") for snapshot in adapted_snapshots]
    duplicates = sorted({source_id for source_id in source_ids if source_ids.count(source_id) > 1})
    if duplicates:
        raise ValueError("duplicate adapted source snapshots: " + ", ".join(duplicates))
    inbox_items = list(inbox_payload.get("items") or [])
    sources = [compare_source(snapshot, inbox_items) for snapshot in adapted_snapshots]
    return {
        "generated_by": "review_inbox_parity.py",
        "inbox_source": inbox_payload.get("source") or "",
        "summary": {
            "source_count": len(sources),
            "expected_count": sum(source["summary"]["expected_count"] for source in sources),
            "inbox_count": sum(source["summary"]["inbox_count"] for source in sources),
            "missing_count": sum(source["summary"]["missing_count"] for source in sources),
            "extra_count": sum(source["summary"]["extra_count"] for source in sources),
            "content_mismatch_count": sum(
                source["summary"]["content_mismatch_count"] for source in sources
            ),
            "parity": all(source["summary"]["parity"] for source in sources),
        },
        "sources": sources,
    }


def markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        "# Review Inbox Parity Report",
        "",
        f"- parity: `{str(summary['parity']).lower()}`",
        f"- sources: {summary['source_count']}",
        f"- expected / inbox: {summary['expected_count']} / {summary['inbox_count']}",
        f"- missing / extra / mismatch: {summary['missing_count']} / {summary['extra_count']} / {summary['content_mismatch_count']}",
        "",
        "| source | input sha256 | expected | inbox | missing | extra | mismatch | parity |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for source in report["sources"]:
        source_summary = source["summary"]
        lines.append(
            f"| {source['source_id']} | `{source['input']['sha256']}` | "
            f"{source_summary['expected_count']} | {source_summary['inbox_count']} | "
            f"{source_summary['missing_count']} | {source_summary['extra_count']} | "
            f"{source_summary['content_mismatch_count']} | "
            f"{str(source_summary['parity']).lower()} |"
        )
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], out_json: Path, out_md: Path) -> None:
    Path(out_json).parent.mkdir(parents=True, exist_ok=True)
    Path(out_json).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    Path(out_md).parent.mkdir(parents=True, exist_ok=True)
    Path(out_md).write_text(markdown_report(report), encoding="utf-8")


def load_adapted_snapshot(path: Path) -> dict[str, Any]:
    path = Path(path)
    raw = path.read_bytes()
    snapshot = json.loads(raw)
    snapshot["adapter_snapshot_path"] = str(path)
    snapshot["adapter_snapshot_sha256"] = input_sha256(raw)
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--adapted-snapshot", type=Path, action="append", required=True)
    parser.add_argument("--inbox", type=Path, default=DEFAULT_INBOX)
    parser.add_argument("--out-json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--out-md", type=Path, default=DEFAULT_MD)
    parser.add_argument("--require-parity", action="store_true")
    args = parser.parse_args()

    snapshots = [load_adapted_snapshot(path) for path in args.adapted_snapshot]
    report = build_parity_report(snapshots, read_json(args.inbox))
    write_report(report, args.out_json, args.out_md)
    print(
        f"review inbox parity: parity={report['summary']['parity']} "
        f"sources={report['summary']['source_count']} -> {args.out_json}"
    )
    if args.require_parity and not report["summary"]["parity"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
