#!/usr/bin/env python3
"""Batch-save first-pass venue review decisions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import urllib.request


DEFAULT_BASE_URL = "http://127.0.0.1:8751"
REVIEWER = "おと（Codex）"
LEGACY_DECISIONS = Path("data/accepted_venue_song_missing_venue_decisions.json")


def get_json(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def load_legacy_decisions() -> dict[str, dict]:
    if not LEGACY_DECISIONS.exists():
        return {}
    payload = json.loads(LEGACY_DECISIONS.read_text(encoding="utf-8"))
    rows = payload.get("rows") if isinstance(payload, dict) else payload
    decisions = {}
    for row in rows or []:
        key = row.get("key") or ""
        term = row.get("term") or ""
        if key:
            decisions[key] = row
        if term and term not in decisions:
            decisions[term] = row
    return decisions


def legacy_key(item: dict) -> str:
    title = item.get("title") or ""
    first_url = (item.get("urls") or [""])[0]
    return f"{title}||{first_url}"


def decide(item: dict, legacy: dict[str, dict]) -> dict:
    source_id = item.get("source_id")
    title = item.get("title") or ""
    first_url = (item.get("urls") or [""])[0]

    if source_id == "accepted_venue_song_missing_venue":
        legacy_row = legacy.get(legacy_key(item)) or legacy.get(title) or {}
        apply_value = legacy_row.get("decision") or "保留"
        note_suffix = legacy_row.get("note") or ""
        if apply_value == "会場追加":
            decision = "accept"
        elif apply_value == "既存に統合":
            decision = "accept"
        elif apply_value == "不採用":
            decision = "reject"
        else:
            decision = "hold"
            apply_value = "保留"
        note = (
            f"おと一括レビュー。既存の会場追加判断ファイルに合わせて「{apply_value}」。"
            f"会場候補: {title}。URL: {first_url}"
        )
        if note_suffix:
            note += f" 補足: {note_suffix}"
        return {"decision": decision, "apply_value": apply_value, "note": note}

    if source_id == "missing_occurrence_venue":
        note = (
            "おと一括レビュー。会場名・住所・根拠URLの同一性が未確定のため、"
            "開催回へ直接 venue_id を入れず、会場レビュー作成/追加調査へ回す。"
            f"イベント: {title}。URL: {first_url}"
        )
        return {"decision": "needs_research", "apply_value": "create_venue_review", "note": note}

    return {
        "decision": "hold",
        "apply_value": "hold",
        "note": f"おと一括レビュー。未知の source_id={source_id} のため保留。",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    legacy = load_legacy_decisions()
    base_url = args.base_url.rstrip("/")
    payload = get_json(f"{base_url}/api/items?status=pending&action_group=venue&limit=1000")
    rows = []
    for item in payload.get("items", []):
        decision = decide(item, legacy)
        row = {
            "item_id": item["id"],
            "source_id": item.get("source_id"),
            "title": item.get("title", ""),
            **decision,
        }
        if not args.dry_run:
            response = post_json(
                f"{base_url}/api/decision",
                {
                    "item_id": item["id"],
                    "reviewer": REVIEWER,
                    **decision,
                },
            )
            row["ok"] = bool(response.get("ok"))
            row["error"] = response.get("error", "")
        rows.append(row)

    print(json.dumps({"dry_run": args.dry_run, "count": len(rows), "rows": rows}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
