#!/usr/bin/env python3
"""Download X poster/flyer images from the OCR queue for Claude (こと) to read.

`build_event_poster_ocr_queue.py` collects candidate posts but nothing consumed
them, so the queue grew to ~1800 unread items. This script pulls the images down
so こと can read them with the Read tool and write an official-notice report
(`docs/official-notice-field-report-operations.md`), which then flows into the
master RDB through the existing apply pipeline.

Usage:
    python3 fetch_poster_images.py --limit 20 --priority critical,high
    python3 fetch_poster_images.py --since 2026-07-19 --limit 40
"""

import argparse
import json
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from collection_support.poster_ocr_ledger import load_ledger, processed_ids

DATA = Path("data")
QUEUE = DATA / "event_poster_ocr_queue.json"
DEFAULT_OUT_DIR = DATA / "poster_images"
MANIFEST_NAME = "manifest.json"

# pbs.twimg.com は実画像。t.co / pic.x.com は本文中のショートリンクで画像本体ではない。
IMAGE_HOST_RE = re.compile(r"^https://pbs\.twimg\.com/", re.I)
# 動画サムネイルはポスターではないことが多いが、告知動画の1枚目に日程が出る例もあるため残す。
VIDEO_THUMB_RE = re.compile(r"/(?:ext_tw_video_thumb|amplify_video_thumb)/", re.I)

USER_AGENT = "bon-odori-collector/1.0 (poster OCR fetch)"


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def image_urls(item, include_video_thumbs=True):
    """Return real image URLs, preferring the large rendition for OCR accuracy."""
    out = []
    for url in item.get("media_urls") or []:
        if not isinstance(url, str) or not IMAGE_HOST_RE.match(url):
            continue
        if not include_video_thumbs and VIDEO_THUMB_RE.search(url):
            continue
        # pbs.twimg.com は name=large で長辺2048pxまで取れる。小さいままだと札の文字が潰れる。
        base = url.split("?", 1)[0]
        if base not in [u.split("?", 1)[0] for u in out]:
            out.append(f"{base}?format=jpg&name=large")
    return out


def select_items(
    queue_items,
    priorities,
    since,
    limit,
    skip_ids,
    include_video_thumbs=True,
    gap_only=False,
):
    selected = []
    for item in queue_items:
        if item.get("id") in skip_ids:
            continue
        if gap_only and not item.get("matched_date_gap_events"):
            continue
        if priorities and item.get("priority") not in priorities:
            continue
        if since and (item.get("date") or "")[:10] < since:
            continue
        if not image_urls(item, include_video_thumbs=include_video_thumbs):
            continue
        selected.append(item)
        if limit and len(selected) >= limit:
            break
    return selected


def download(url, dest, timeout=30):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = response.read()
    dest.write_bytes(payload)
    return len(payload)


def fetch(items, out_dir, include_video_thumbs=True, timeout=30):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    errors = []
    for item in items:
        urls = image_urls(item, include_video_thumbs=include_video_thumbs)
        local_paths = []
        for index, url in enumerate(urls, start=1):
            dest = out_dir / f"{item['id']}_{index}.jpg"
            if dest.exists() and dest.stat().st_size > 0:
                local_paths.append(str(dest))
                continue
            try:
                download(url, dest, timeout=timeout)
                local_paths.append(str(dest))
            except (urllib.error.URLError, urllib.error.HTTPError, OSError) as exc:
                errors.append({"id": item["id"], "url": url, "error": str(exc)})
        if not local_paths:
            continue
        manifest.append({
            "id": item["id"],
            "priority": item.get("priority"),
            "matched_date_gap_events": item.get("matched_date_gap_events") or [],
            "account": item.get("account"),
            "account_name": item.get("account_name"),
            "trusted_informant": item.get("trusted_informant"),
            "date": item.get("date"),
            "url": item.get("url"),
            "text": item.get("text"),
            "local_paths": local_paths,
        })
    return manifest, errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", default=str(QUEUE))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument(
        "--priority",
        default="critical,high",
        help="対象の優先度をカンマ区切りで指定。'all' で全件",
    )
    parser.add_argument("--since", default="", help="この日付以降の投稿だけ (YYYY-MM-DD)")
    parser.add_argument(
        "--include-processed",
        action="store_true",
        help="処理済み台帳にある投稿も対象にする（再読み込み用）",
    )
    parser.add_argument(
        "--no-video-thumbs",
        action="store_true",
        help="動画サムネイルを除外する",
    )
    parser.add_argument(
        "--gap-only",
        action="store_true",
        help="開催日が未確定のイベントに一致した投稿だけを対象にする",
    )
    args = parser.parse_args()

    queue = load_json(args.queue, {})
    queue_items = queue.get("items") or []
    priorities = (
        None
        if args.priority.strip().lower() == "all"
        else {p.strip() for p in args.priority.split(",") if p.strip()}
    )
    skip_ids = set() if args.include_processed else processed_ids(load_ledger())

    items = select_items(
        queue_items,
        priorities,
        args.since,
        args.limit,
        skip_ids,
        include_video_thumbs=not args.no_video_thumbs,
        gap_only=args.gap_only,
    )
    manifest, errors = fetch(
        items, args.out_dir, include_video_thumbs=not args.no_video_thumbs
    )

    out_dir = Path(args.out_dir)
    manifest_path = out_dir / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(
            {
                "generated_by": "fetch_poster_images.py",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "queue_total": len(queue_items),
                "already_processed": len(skip_ids),
                "count": len(manifest),
                "errors": errors,
                "items": manifest,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    image_count = sum(len(row["local_paths"]) for row in manifest)
    print(
        f"ポスター画像取得: 投稿 {len(manifest)}件 / 画像 {image_count}枚 -> {out_dir}\n"
        f"  キュー全体 {len(queue_items)}件 / 処理済み {len(skip_ids)}件 / 失敗 {len(errors)}件\n"
        f"  マニフェスト: {manifest_path}"
    )


if __name__ == "__main__":
    main()
