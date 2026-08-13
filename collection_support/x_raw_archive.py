"""Immutable, private S3 preservation for newly fetched X posts.

This module deliberately stores acquisition facts only. It must never add a
meaning judgement: the separate X reading-disposition ledger owns that work.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

from collection_support.x_author_profile import author_profile_description


SCHEMA_VERSION = "x_raw_post/v1"
DEFAULT_PREFIX = "x-raw"
MAX_PUT_ATTEMPTS = 3


class RawXArchiveError(RuntimeError):
    """Raised when a fetched X post cannot be durably preserved."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_prefix(prefix: str | None) -> str:
    return str(prefix or DEFAULT_PREFIX).strip("/") or DEFAULT_PREFIX


def _safe_key_part(value: str | None, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.=-]+", "-", str(value or "").strip())
    return cleaned.strip("-") or fallback


def _tweet_text(tweet: dict[str, Any]) -> str:
    """Return provider text unchanged; do not inherit voices.json limits."""
    if tweet.get("text") is not None:
        return str(tweet["text"])
    if tweet.get("full_text") is not None:
        return str(tweet["full_text"])
    return ""


def _media_urls(tweet: dict[str, Any]) -> list[str]:
    urls: list[str] = []

    def add(value: Any) -> None:
        if isinstance(value, str) and value and value not in urls:
            urls.append(value)

    containers = [
        tweet.get("media"), tweet.get("medias"), tweet.get("photos"),
        (tweet.get("entities") or {}).get("media"),
        (tweet.get("extendedEntities") or {}).get("media"),
        (tweet.get("extended_entities") or {}).get("media"),
    ]
    for container in containers:
        if isinstance(container, dict):
            container = [container]
        if not isinstance(container, list):
            continue
        for item in container:
            if not isinstance(item, dict):
                continue
            add(item.get("media_url_https"))
            add(item.get("media_url"))
            add(item.get("url"))
            add(item.get("display_url"))
            add(item.get("preview_image_url"))
    return urls


def _canonical_url(tweet: dict[str, Any], handle: str, tweet_id: str) -> str:
    return str(tweet.get("url") or (f"https://x.com/{handle}/status/{tweet_id}" if handle and tweet_id else ""))


def _payload_fingerprint(tweet: dict[str, Any]) -> str:
    encoded = json.dumps(tweet, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _logical_post_key(tweet_id: str, url: str) -> str:
    if tweet_id:
        return f"tweet:{tweet_id}"
    if url:
        return "url:" + hashlib.sha256(url.encode("utf-8")).hexdigest()
    raise RawXArchiveError("raw X post has neither tweet_id nor URL")


def _record(tweet: dict[str, Any], context: dict[str, Any], captured_at: str) -> dict[str, Any]:
    author = tweet.get("author") or tweet.get("user") or {}
    handle = str(author.get("userName") or author.get("screen_name") or "").lstrip("@")
    tweet_id = str(tweet.get("id") or tweet.get("id_str") or "")
    url = _canonical_url(tweet, handle, tweet_id)
    post_key = _logical_post_key(tweet_id, url)
    raw_created_at = str(tweet.get("createdAt") or tweet.get("created_at") or "")
    return {
        "schema_version": SCHEMA_VERSION,
        "capture_id": hashlib.sha256(f"{post_key}\0{captured_at}".encode("utf-8")).hexdigest(),
        "post_key": post_key,
        "tweet_id": tweet_id,
        "url": url,
        "account": f"@{handle}" if handle else "",
        "account_name": str(author.get("name") or ""),
        # Preserved without the shared probe: the archive re-reads the same
        # authors the mapper already counted, so probing here would double it.
        "profile_description": author_profile_description(author, probe=None),
        "created_at_raw": raw_created_at,
        "captured_at": captured_at,
        "text": _tweet_text(tweet),
        "media_urls": _media_urls(tweet),
        "acquisition": {
            "route": str(context.get("route") or ""),
            "query_id": str(context.get("query_id") or ""),
            "batch_id": str(context.get("batch_id") or ""),
            "run_id": str(context.get("run_id") or ""),
            "estimated_cost_usd": float(context.get("estimated_cost_usd") or 0),
        },
        "api_payload_sha256": _payload_fingerprint(tweet),
    }


def _s3_client():
    try:
        import boto3
    except ImportError as exc:  # pragma: no cover - dependency is declared in requirements.txt
        raise RawXArchiveError("boto3 is required for raw X post preservation") from exc
    return boto3.client("s3", region_name=os.environ.get("AWS_REGION") or None)


def capture_raw_x_posts(
    tweets: list[dict[str, Any]], context: dict[str, Any], *, client: Any | None = None,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Persist one newly-fetched batch before a caller advances its seen set.

    Records are deduplicated by tweet ID (falling back to URL) within a batch.
    A caller advances ``voices_seen.json`` only after this function returns;
    a retry can therefore preserve the same post again without losing it.
    """
    if not tweets:
        return {"count": 0, "object_key": "", "manifest_key": ""}

    bucket = os.environ.get("X_RAW_POSTS_S3_BUCKET", "").strip()
    if not bucket:
        raise RawXArchiveError("X_RAW_POSTS_S3_BUCKET is required before fetching new X posts")

    capture_time = captured_at or _now_iso()
    records: list[dict[str, Any]] = []
    seen_post_keys: set[str] = set()
    for tweet in tweets:
        record = _record(tweet, context, capture_time)
        if record["post_key"] in seen_post_keys:
            continue
        seen_post_keys.add(record["post_key"])
        records.append(record)
    if not records:
        return {"count": 0, "object_key": "", "manifest_key": ""}

    jsonl = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        for record in records
    ).encode("utf-8")
    content_sha256 = hashlib.sha256(jsonl).hexdigest()
    captured_date = capture_time[:10]
    prefix = _clean_prefix(os.environ.get("X_RAW_POSTS_S3_PREFIX"))
    run_id = _safe_key_part(context.get("run_id") or os.environ.get("GITHUB_RUN_ID"), "manual")
    route = _safe_key_part(context.get("route"), "unknown")
    batch_id = _safe_key_part(context.get("batch_id"), "batch")
    key_base = f"{prefix}/v1/captured_date={captured_date}/run={run_id}/route={route}/{batch_id}-{content_sha256[:16]}"
    object_key = f"{key_base}.jsonl.gz"
    manifest_key = f"{key_base}.manifest.json"
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "captured_at": capture_time,
        "count": len(records),
        "content_sha256": content_sha256,
        "object_key": object_key,
        "post_keys": [record["post_key"] for record in records],
        "acquisition": records[0]["acquisition"],
    }

    client = client or _s3_client()
    last_error = None
    for attempt in range(1, MAX_PUT_ATTEMPTS + 1):
        try:
            client.put_object(
                Bucket=bucket, Key=object_key, Body=gzip.compress(jsonl, mtime=0),
                ContentType="application/x-ndjson", ContentEncoding="gzip",
                ServerSideEncryption="AES256",
            )
            client.put_object(
                Bucket=bucket, Key=manifest_key,
                Body=(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"),
                ContentType="application/json", ServerSideEncryption="AES256",
            )
            return {"count": len(records), "object_key": object_key, "manifest_key": manifest_key}
        except Exception as exc:
            last_error = exc
            if attempt < MAX_PUT_ATTEMPTS:
                time.sleep(0.25 * attempt)
    raise RawXArchiveError(
        f"failed to preserve raw X posts after {MAX_PUT_ATTEMPTS} attempts: {last_error}"
    ) from last_error
