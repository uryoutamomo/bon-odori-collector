"""Score whether an X account is an official/organizer source."""

from __future__ import annotations

import json
import re
from pathlib import Path

from x_official_source_accounts import (
    load_official_source_accounts,
    norm_handle,
    official_account_for_url,
)


ROOT = Path(__file__).resolve().parent
DEFAULT_ACCOUNT_CANDIDATES = ROOT / "data/x_candidate_accounts.json"
DEFAULT_OFFICIAL_ACCOUNTS = ROOT / "data/x_official_source_accounts.json"

ORG_HINTS = (
    "町会",
    "自治会",
    "商店街",
    "商店会",
    "振興組合",
    "実行委員会",
    "保存会",
    "青年部",
    "婦人部",
    "子供会",
    "こども会",
    "連合会",
    "観光協会",
    "商工会",
    "神社",
    "寺",
    "寺院",
    "区役所",
    "市役所",
    "まちづくり",
)
OFFICIAL_HINTS = ("公式", "広報", "お知らせ", "担当", "運営", "主催", "事務局")
PERSONAL_HINTS = (
    "好き",
    "ファン",
    "個人",
    "趣味",
    "踊り子",
    "盆踊ラー",
    "行ってきた",
    "巡り",
)
SCHEDULE_HINT_RE = re.compile(
    r"(?:開催|予定|お知らせ|ご案内|日程|会場|場所|時間|雨天|順延|中止|"
    r"\d{1,2}月\d{1,2}日?|\d{1,2}/\d{1,2}|\d{1,2}:\d{2}|[午前午後]\d{1,2}時)"
)
BON_HINT_RE = re.compile(r"盆踊り|盆おどり|ぼんおどり|納涼|民踊|音頭|やぐら|櫓", re.I)


def load_account_profiles(path: Path | str = DEFAULT_ACCOUNT_CANDIDATES) -> dict[str, dict]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return {}
    rows = payload.get("candidates") if isinstance(payload, dict) else payload
    profiles = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        handle = norm_handle(row.get("handle"))
        if handle:
            profiles[handle] = row
    return profiles


def text_blob(*values) -> str:
    return " ".join(str(value or "") for value in values if str(value or "").strip())


def has_area_overlap(candidate: dict, profile: dict, post_text: str) -> bool:
    profile_text = text_blob(profile.get("name"), profile.get("description"), profile.get("location"))
    for key in ("possible_area", "possible_venue", "possible_event_name"):
        value = str(candidate.get(key) or "").strip()
        if value and (value in profile_text or value in post_text):
            return True
    return False


def source_urls(candidate: dict, voice: dict | None = None) -> list[str]:
    urls = []
    for key in ("source_urls", "internal_discovery_urls", "confirmed_source_urls"):
        for url in candidate.get(key) or []:
            if url:
                urls.append(str(url))
    if voice and voice.get("url"):
        urls.append(str(voice["url"]))
    deduped = []
    for url in urls:
        if url not in deduped:
            deduped.append(url)
    return deduped


def registered_official_account(candidate: dict, voice: dict | None = None) -> dict | None:
    for url in source_urls(candidate, voice):
        account = official_account_for_url(url)
        if account:
            return account
    return None


def assess_source_officiality(
    candidate: dict,
    voice: dict | None = None,
    account_profiles: dict[str, dict] | None = None,
) -> dict:
    account_profiles = account_profiles or {}
    registered = registered_official_account(candidate, voice)
    if registered:
        return {
            "classification": "registered_official_social",
            "score": 100,
            "handle": registered.get("handle") or "",
            "account_name": registered.get("name") or "",
            "source_type": registered.get("source_type") or "official_or_organizer_social",
            "trust_level": registered.get("trust_level") or "organizer_official",
            "reasons": ["registered_official_source_account"],
            "recommended_action": "use_as_confirmed_source_after_post_review",
        }

    handle = ""
    authors = candidate.get("source_authors") or []
    if authors:
        handle = norm_handle(authors[0])
    if not handle and voice:
        handle = norm_handle(voice.get("account") or voice.get("author"))
    profile = account_profiles.get(handle, {})
    post_text = text_blob(
        voice.get("title") if voice else "",
        voice.get("text") if voice else "",
        candidate.get("source_text_excerpt"),
        candidate.get("internal_source_excerpt"),
        candidate.get("oto_interpreted_summary"),
    )
    profile_text = text_blob(profile.get("name"), profile.get("description"), profile.get("location"))

    score = 0
    reasons = []
    org_hits = [hint for hint in ORG_HINTS if hint in profile_text]
    if org_hits:
        score += 3
        reasons.append("organization_profile:" + ",".join(org_hits[:4]))
    official_hits = [hint for hint in OFFICIAL_HINTS if hint in profile_text]
    if official_hits:
        score += 2
        reasons.append("official_profile:" + ",".join(official_hits[:4]))
    if BON_HINT_RE.search(post_text) and SCHEDULE_HINT_RE.search(post_text):
        score += 2
        reasons.append("schedule_post_with_bon_context")
    if has_area_overlap(candidate, profile, post_text):
        score += 1
        reasons.append("area_or_name_overlap")
    personal_hits = [hint for hint in PERSONAL_HINTS if hint in profile_text]
    if personal_hits and not org_hits:
        score -= 2
        reasons.append("personal_profile:" + ",".join(personal_hits[:3]))

    if score >= 6:
        classification = "candidate_official_social"
        action = "review_account_then_register_if_confirmed"
    elif score >= 3:
        classification = "community_source_candidate"
        action = "keep_as_review_hint"
    else:
        classification = "unknown_or_personal_social"
        action = "find_independent_confirmation"

    return {
        "classification": classification,
        "score": score,
        "handle": f"@{handle}" if handle else "",
        "account_name": profile.get("name") or (voice or {}).get("name") or "",
        "source_type": "official_or_organizer_social_candidate"
        if classification == "candidate_official_social"
        else "",
        "trust_level": "candidate",
        "reasons": reasons,
        "recommended_action": action,
    }


def official_source_account_rows() -> list[dict]:
    return load_official_source_accounts(DEFAULT_OFFICIAL_ACCOUNTS)
