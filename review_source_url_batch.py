#!/usr/bin/env python3
"""Batch-save first-pass source URL review decisions."""

from __future__ import annotations

import argparse
import json
import urllib.request


DEFAULT_BASE_URL = "http://127.0.0.1:8751"
REVIEWER = "おと（Codex）"


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


def decide(item: dict) -> dict:
    source_id = item.get("source_id")
    title = item.get("title") or ""
    subtitle = item.get("subtitle") or ""
    urls = item.get("urls") or []
    first_url = urls[0] if urls else ""

    if source_id == "official_source":
        apply_value = item.get("source_decision") or "hold"
        if apply_value in {"official", "hp", "post"}:
            decision = "accept"
            note = (
                f"おと一括レビュー。候補生成時の判定 {apply_value} を採用。"
                f"イベント/候補: {title} / {subtitle}。URL: {first_url}"
            )
        elif apply_value == "reject":
            decision = "reject"
            note = (
                "おと一括レビュー。候補生成時点で不採用判定のため反映対象外。"
                f"イベント/候補: {title} / {subtitle}。URL: {first_url}"
            )
        else:
            decision = "hold"
            apply_value = "hold"
            note = (
                "おと一括レビュー。候補生成時点で保留判定。"
                "Drive画像、汎用ページ、イベント同一性などの追加確認が必要。"
                f"イベント/候補: {title} / {subtitle}。URL: {first_url}"
            )
        return {"decision": decision, "apply_value": apply_value, "note": note}

    if source_id == "missing_source_url":
        action = item.get("action") or ""
        if action == "ready_source_url_candidate" and first_url:
            note = (
                "おと一括レビュー。既存ローカル根拠から候補URLあり。"
                "開催日・会場の別レビューは残し、今回は occurrence.source_url 補完だけを採用。"
                f"イベント: {title}。URL: {first_url}"
            )
            return {"decision": "accept", "apply_value": "fill_source_url", "note": note}
        note = (
            "おと一括レビュー。公開判断に使える公式/自治体/主催/会場URLが未確定。"
            "個人投稿だけなら弱い根拠として扱い、公式系URLの追加探索待ち。"
            f"イベント: {title}。"
        )
        return {"decision": "needs_research", "apply_value": "source_research_required", "note": note}

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

    base_url = args.base_url.rstrip("/")
    payload = get_json(f"{base_url}/api/items?status=pending&action_group=source_url&limit=1000")
    rows = []
    for item in payload.get("items", []):
        decision = decide(item)
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
