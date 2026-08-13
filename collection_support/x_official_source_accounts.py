"""Local registry for official or organizer X accounts."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REGISTRY = ROOT / "data/x_official_source_accounts.json"
SOCIAL_HOSTS = {"x.com", "twitter.com", "www.x.com", "www.twitter.com"}


def norm_handle(handle: str | None) -> str:
    return (handle or "").strip().lstrip("@").lower()


def load_official_source_accounts(path: Path | str = DEFAULT_REGISTRY) -> list[dict]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return []

    rows = payload.get("accounts") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return []

    accounts = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        handle_key = norm_handle(row.get("handle"))
        if not handle_key or handle_key in seen:
            continue
        seen.add(handle_key)
        account = dict(row)
        account["handle"] = f"@{handle_key}"
        # A rejected row is a record of a decision, not a source.  It is
        # dropped rather than returned as 休止 because this list is assembled
        # ahead of the bonodorer roster and shadows it by handle: returning a
        # muted row here would quietly stop reading an account that the person
        # only ruled out as an *official* source.
        if account.get("tier") == "rejected":
            continue
        # v2 registry rows are retained even while dormant.  Only active rows
        # are daily readers; legacy rows without a tier retain their old,
        # explicit-priority behaviour.
        if "tier" in account:
            # Import lazily: the registry matcher also imports norm_handle.
            from collection_support.x_source_registry import tier_for_account
            account["tier"] = tier_for_account(account)
            account["manual_status"] = "優先" if account["tier"] == "active" else "休止"
        elif "manual_status" not in account:
            account["manual_status"] = "優先" if account.get("tier", "active") == "active" else "休止"
        account.setdefault("source_type", "official_or_organizer_social")
        account.setdefault("trust_level", "organizer_official")
        account.setdefault("page_id", "")
        account.setdefault("source_registry", str(path))
        accounts.append(account)
    return accounts


def handle_from_social_url(url: str) -> str:
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    if parsed.netloc.lower() not in SOCIAL_HOSTS:
        return ""
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return ""
    first = parts[0]
    if first in {"i", "intent", "share", "search", "hashtag"}:
        return ""
    return norm_handle(first)


def official_account_for_url(
    url: str,
    path: Path | str = DEFAULT_REGISTRY,
) -> dict | None:
    handle = handle_from_social_url(url)
    if not handle:
        return None
    for account in load_official_source_accounts(path):
        if norm_handle(account.get("handle")) == handle:
            return account
    return None


def is_official_social_url(url: str, path: Path | str = DEFAULT_REGISTRY) -> bool:
    return official_account_for_url(url, path) is not None
