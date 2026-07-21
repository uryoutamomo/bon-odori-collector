#!/usr/bin/env python3
"""First-pass current-date review helper for the local review console."""

from __future__ import annotations

import argparse
import html
import http.client
import json
import re
import urllib.error
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


def fetch_title(url: str) -> str:
    if not url:
        return ""
    match = re.search(r"https?://\S+", url)
    if match:
        url = match.group(0)
    if not re.match(r"^https?://", url):
        return ""
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=12) as response:
            raw = response.read(250_000).decode("utf-8", errors="ignore")
    except (urllib.error.URLError, TimeoutError, ValueError, http.client.InvalidURL):
        return ""
    match = re.search(r"<title[^>]*>(.*?)</title>", raw, flags=re.I | re.S)
    if not match:
        return ""
    return html.unescape(re.sub(r"\s+", " ", match.group(1))).strip()


def title_date_text(title: str) -> str:
    match = re.search(r"(20\d{2})(\d{2})(\d{2})(?:-(\d{2}))?", title)
    if not match:
        return ""
    year, month, day, day_end = match.groups()
    if day_end:
        return f"{year}年{int(month)}月{int(day)}日-{int(day_end)}日"
    return f"{year}年{int(month)}月{int(day)}日"


def decide(item: dict) -> dict:
    urls = item.get("urls") or []
    first_url = urls[0] if urls else ""
    advice = item.get("research_advice_status") or ""
    title = fetch_title(first_url)
    date_text = title_date_text(title)
    item_title = item.get("title", "")

    if "drive.google.com" in first_url:
        title_part = f"Google Drive公開画像タイトル「{title}」" if title else "Google Drive公開画像"
        date_part = f"で{date_text}を確認。" if date_text else "を確認。"
        note = (
            f"おと一次調査。{title_part}{date_part}"
            f"{item_title}の過去根拠候補として有用。ただし2026年の公式/主催/自治体告知は未確認で、"
            "この行に2026日付は無い。調査アドバイスはOCR待ち。画像本文OCRでイベント名・主催・時刻を確認し、"
            f"別途2026公式探索が必要。URL: {first_url}"
        )
        return {"decision": "needs_research", "apply_value": "needs_research", "note": note, "title": title, "advice": advice}

    if "x.com/" in first_url or "twitter.com/" in first_url:
        note = (
            f"おと一次調査。既存根拠はX投稿URL。{item_title}の2026公式/自治体/主催告知はこの一次確認では未確認。"
            "X投稿単独では2026日程確定にしない。調査アドバイスは投稿確認待ち。投稿本文・投稿者の信頼性・公式裏取りを確認。"
            f"URL: {first_url}"
        )
        return {"decision": "needs_research", "apply_value": "needs_research", "note": note, "title": title, "advice": advice}

    title_part = f"ページタイトル「{title}」を確認。" if title else "既存根拠URLを確認したがタイトル取得不可。"
    if "2026" in title or "令和8" in title:
        note = (
            f"おと一次調査。{title_part}2026年情報の可能性あり。ただしレビュー行の現在年日付フィールドへ自動反映できるかは未確認。"
            "日付・会場・主催の本文確認と日付補完applyが必要。確定採用は保留。"
            f"URL: {first_url}"
        )
    else:
        note = (
            f"おと一次調査。{title_part}2026年の直接根拠はこの一次確認では未確認。"
            "過去年根拠または予測ルールだけなら2026確定にしない。公式/自治体/主催/会場ページの追加探索待ち。"
            f"URL: {first_url}"
        )
    return {"decision": "needs_research", "apply_value": "needs_research", "note": note, "title": title, "advice": advice}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    payload = get_json(f"{base_url}/api/items?status=pending&action_group=current_date&limit={args.limit}")
    results = []
    for item in payload.get("items", []):
        decision = decide(item)
        row = {
            "item_id": item["id"],
            "item_title": item.get("title", ""),
            "research_advice": decision["advice"],
            "source_title": decision["title"],
            "decision": decision["decision"],
            "apply_value": decision["apply_value"],
            "note": decision["note"],
        }
        if not args.dry_run:
            response = post_json(
                f"{base_url}/api/decision",
                {
                    "item_id": item["id"],
                    "decision": decision["decision"],
                    "apply_value": decision["apply_value"],
                    "note": decision["note"],
                    "reviewer": REVIEWER,
                },
            )
            row["ok"] = bool(response.get("ok"))
            row["error"] = response.get("error", "")
        results.append(row)
    print(json.dumps({"dry_run": args.dry_run, "count": len(results), "results": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
