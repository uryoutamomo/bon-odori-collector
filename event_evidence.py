import hashlib
import re
from datetime import datetime, timedelta, timezone


PATTERN_KEYWORDS = {
    "A": ("行く", "行きます", "行こう", "参加予定", "参加します", "参戦", "踊りに行", "ハシゴ", "はしご"),
    "B": ("いつ", "どこ", "何時", "教えて", "知ってる", "ありますか", "やりますか", "開催ですか", "問い合わせ"),
    "C": ("おすすめ", "オススメ", "ぜひ", "行ってみて", "共有", "情報です", "開催情報", "お知らせ", "告知"),
    "D": ("一緒に", "誰か", "行かない", "行きませんか", "集合", "待ち合わせ", "誘って", "連れて"),
    "E": ("行った", "行ってきた", "踊った", "踊ってきた", "参加した", "楽しかった", "最高だった", "去年", "一昨年", "昨年"),
}

BON_CONTEXT = ("盆踊り", "盆おどり", "盆踊", "音頭", "やぐら", "櫓", "輪踊り", "納涼踊り", "民踊", "踊り大会")
SCHEDULE_WORDS = ("開催", "予定", "日程", "会場", "場所", "告知", "お知らせ", "チラシ", "ポスター", "中止", "延期", "順延")
YEAR_SIGNALS = ("去年", "昨年", "一昨年", "来年", "今年も")
REGION_RE = re.compile(r"([一-龥ぁ-んァ-ヶー]{2,12}(?:都|道|府|県|市|区|町|村|駅|丁目))")
DATE_RE = re.compile(r"((?:20\d{2}年)?\d{1,2}月\d{1,2}日|(?:20\d{2}[/-])?\d{1,2}[/-]\d{1,2}|今週末|来週|週末|明日|今日|本日)")
MONTH_RE = re.compile(r"(?:(?:20\d{2}年)?(\d{1,2})月|(?:20\d{2}[/-])?(\d{1,2})[/-]\d{1,2})")
HASHTAG_RE = re.compile(r"#([A-Za-z0-9_一-龥ぁ-んァ-ヶー・ー]+)")
VENUE_RE = re.compile(r"([一-龥ぁ-んァ-ヶーA-Za-z0-9]{2,18}(?:神社|寺|本願寺|公園|広場|会館|商店街|学校|小学校|中学校|駅前))")
EVENT_RE = re.compile(r"([一-龥ぁ-んァ-ヶーA-Za-z0-9・ー]{2,30}(?:盆踊り大会|盆おどり大会|盆踊り|盆おどり|納涼大会|夏祭り|まつり|祭り))")
GROUP_RE = re.compile(r"([一-龥ぁ-んァ-ヶーA-Za-z0-9・ー]{2,24}(?:保存会|舞踊会|民踊会|婦人会|青年会|町会|自治会|実行委員会))")
SONG_RE = re.compile(r"(?:曲|音頭)[「『]?([一-龥ぁ-んァ-ヶーA-Za-z0-9・ー]{2,24})[」』]?")


def tweet_id_from_voice(voice):
    tweet_id = str(voice.get("tweet_id") or "").strip()
    if tweet_id:
        return tweet_id
    match = re.search(r"/status/(\d+)", voice.get("url") or "")
    return match.group(1) if match else ""


def evidence_identity(voice):
    tweet_id = tweet_id_from_voice(voice)
    if tweet_id:
        return f"evidence:{tweet_id}"
    raw = "\0".join(str(voice.get(key) or "") for key in ("url", "account", "date", "text"))
    return "evidence:sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _unique_matches(regex, text, limit=5):
    values = []
    for match in regex.finditer(text):
        value = (match.group(1) or "").strip(" 、。!！?？「」『』")
        if value and value not in values:
            values.append(value)
        if len(values) >= limit:
            break
    return values


def _clean_venue_hint(value):
    value = re.sub(
        r"^.*(?:都|道|府|県|市|区|町|村|駅|丁目)の",
        "",
        value,
    )
    value = re.sub(r"^(?:今年も|去年の|昨年の|来年の)", "", value)
    return value


def _clean_event_hint(value):
    value = re.sub(r"^(?:今年も|去年の|昨年の|来年の|先日の)", "", value or "")
    return value.strip()


def _related_key(hints):
    parts = []
    for key in ("dates", "regions", "venues", "songs", "groups", "events"):
        values = hints.get(key) or []
        if values:
            parts.append(re.sub(r"\s+", "", values[0]).casefold())
    return "|".join(parts)[:500]


def _norm_key_part(value):
    return re.sub(r"\s+", "", str(value or "").strip()).casefold()


def _first(values):
    return next((value for value in values or [] if value), "")


def _month_from_hints(time_hints):
    for hint in time_hints or []:
        match = MONTH_RE.search(str(hint))
        if match:
            value = match.group(1) or match.group(2)
            try:
                return f"{int(value):02d}"
            except (TypeError, ValueError):
                return ""
    return ""


def _hashtags_from_text(text):
    values = []
    for value in HASHTAG_RE.findall(text or ""):
        if value not in values:
            values.append(value)
    return values[:5]


def build_event_candidate_match_key(evidence):
    event_name = _norm_key_part(evidence.get("estimated_event"))
    venue = _norm_key_part(evidence.get("estimated_venue") or _first(evidence.get("venue_hints")))
    month = _month_from_hints(evidence.get("time_hints"))
    hashtags = [_norm_key_part(value) for value in _hashtags_from_text(evidence.get("text"))]
    parts = []
    if event_name:
        parts.append(f"event:{event_name}")
    if venue:
        parts.append(f"venue:{venue}")
    if month:
        parts.append(f"month:{month}")
    if hashtags:
        parts.append("tag:" + ",".join(sorted(hashtags)[:3]))
    if not parts:
        parts.append(_norm_key_part(evidence.get("identity")))
    return "|".join(parts)[:500]


def build_event_candidate_key(match_key):
    digest = hashlib.sha256(str(match_key or "").encode("utf-8")).hexdigest()
    return f"event:{digest}"


def score_event_candidate_v2(candidate, known_venues=None):
    known_venues = known_venues or {}
    evidence_items = candidate.get("evidence") or []
    speakers = {
        _norm_key_part(item.get("account"))
        for item in evidence_items
        if item.get("account")
    }
    speaker_count = len(speakers)
    score = 0
    breakdown = []

    if speaker_count:
        speaker_score = 10
        if speaker_count >= 2:
            speaker_score += 15
        if speaker_count >= 3:
            speaker_score += min((speaker_count - 2) * 10, 10)
        speaker_score = min(speaker_score, 35)
        score += speaker_score
        breakdown.append({"reason": "speakers", "points": speaker_score})

    venue = candidate.get("estimated_venue") or ""
    if venue and venue in known_venues:
        score += 15
        breakdown.append({"reason": "known_venue", "points": 15})

    has_anchor = bool(candidate.get("estimated_event") or venue)
    if has_anchor and candidate.get("estimated_date"):
        score += 15
        breakdown.append({"reason": "date_with_anchor", "points": 15})
    elif has_anchor and candidate.get("estimated_month"):
        score += 10
        breakdown.append({"reason": "month_with_anchor", "points": 10})

    event_names = [
        item.get("estimated_event")
        for item in evidence_items
        if item.get("estimated_event")
    ]
    if candidate.get("estimated_event"):
        event_score = 15 if len(set(event_names)) == 1 and len(event_names) >= 2 else 8
        score += event_score
        breakdown.append({"reason": "event_name", "points": event_score})

    if any(item.get("year_signals") for item in evidence_items):
        score += 10
        breakdown.append({"reason": "year_continuity", "points": 10})

    if candidate.get("official_source"):
        score += 25
        breakdown.append({"reason": "official_source", "points": 25})

    if any("weak_bon_context:-3" in (item.get("score_reasons") or []) for item in evidence_items):
        score -= 20
        breakdown.append({"reason": "weak_bon_context", "points": -20})

    score = max(0, min(100, score))
    return score, breakdown


def aggregate_event_candidates(evidence_list, known_venues=None):
    grouped = {}
    for evidence in evidence_list or []:
        if evidence.get("type") != "イベント":
            continue
        match_key = build_event_candidate_match_key(evidence)
        candidate_key = build_event_candidate_key(match_key)
        group = grouped.setdefault(candidate_key, {
            "candidate_key": candidate_key,
            "match_key": match_key,
            "match_key_parts": match_key.split("|"),
            "type": "イベント",
            "source": "x_event_evidence",
            "status": "未確認",
            "priority": "通常",
            "estimated_event": "",
            "estimated_venue": "",
            "estimated_month": "",
            "estimated_date": "",
            "hashtags": [],
            "evidence": [],
        })
        if evidence.get("estimated_event") and not group["estimated_event"]:
            group["estimated_event"] = evidence["estimated_event"]
        if evidence.get("estimated_venue") and not group["estimated_venue"]:
            group["estimated_venue"] = evidence["estimated_venue"]
        if evidence.get("time_hints"):
            group["estimated_date"] = group["estimated_date"] or _first(evidence.get("time_hints"))
            group["estimated_month"] = group["estimated_month"] or _month_from_hints(evidence.get("time_hints"))
        for hashtag in _hashtags_from_text(evidence.get("text")):
            if hashtag not in group["hashtags"]:
                group["hashtags"].append(hashtag)
        group["evidence"].append({
            "identity": evidence.get("identity"),
            "tweet_id": evidence.get("tweet_id"),
            "url": evidence.get("url"),
            "text": (evidence.get("text") or "")[:500],
            "account": evidence.get("account"),
            "spoken_at": evidence.get("spoken_at"),
            "patterns": evidence.get("patterns") or [],
            "source_score": evidence.get("score", 0),
            "score_reasons": evidence.get("score_reasons") or [],
            "estimated_event": evidence.get("estimated_event"),
            "estimated_venue": evidence.get("estimated_venue"),
            "time_hints": evidence.get("time_hints") or [],
            "year_signals": evidence.get("year_signals") or [],
        })

    candidates = []
    for group in grouped.values():
        title = group["estimated_event"]
        if not title and group["estimated_venue"]:
            title = f"{group['estimated_venue']}の盆踊り（名称未確定）"
        if not title:
            title = "[断片] イベント候補（名称未確定）"
        speakers = sorted({
            item.get("account") for item in group["evidence"] if item.get("account")
        })
        score, breakdown = score_event_candidate_v2(group, known_venues)
        group.update({
            "venue": title,
            "title": title,
            "identity": group["candidate_key"],
            "priority": "高" if score >= 50 else "通常",
            "confidence_score": score,
            "score_breakdown": breakdown,
            "evidence_count": len(group["evidence"]),
            "speaker_count": len(speakers),
            "speakers": speakers,
            "text": "\n\n".join(
                item.get("text") or "" for item in group["evidence"][:3]
            )[:1900],
            "url": _first([item.get("url") for item in group["evidence"]]),
            "account": _first(speakers),
            "spoken_at": _first([item.get("spoken_at") for item in group["evidence"]]),
            "time_hints": [group["estimated_date"]] if group["estimated_date"] else [],
            "venue_hints": [group["estimated_venue"]] if group["estimated_venue"] else [],
            "score": score,
            "score_reasons": [
                f"{item['reason']}:{item['points']:+d}"
                for item in breakdown
            ],
        })
        candidates.append(group)
    return sorted(candidates, key=lambda item: (-item["confidence_score"], item["title"]))


def classify_event_evidence(voice, config=None):
    config = config or {}
    text = voice.get("text") or ""
    low = text.casefold()
    exclude = [keyword for keyword in config.get("exclude_keywords", []) if keyword.casefold() in low]
    patterns = [
        code for code, keywords in PATTERN_KEYWORDS.items()
        if any(keyword.casefold() in low for keyword in keywords)
    ]
    if not patterns:
        return None

    bon_hits = [word for word in BON_CONTEXT if word in text]
    schedule_hits = [word for word in SCHEDULE_WORDS if word in text]
    hints = {
        "dates": _unique_matches(DATE_RE, text),
        "regions": _unique_matches(REGION_RE, text),
        "venues": [
            _clean_venue_hint(value)
            for value in _unique_matches(VENUE_RE, text)
        ],
        "events": [
            _clean_event_hint(value)
            for value in _unique_matches(EVENT_RE, text)
        ],
        "groups": _unique_matches(GROUP_RE, text),
        "songs": _unique_matches(SONG_RE, text),
        "year_signals": [word for word in YEAR_SIGNALS if word in text],
    }

    score = 0
    reasons = []
    additions = [
        (bool(hints["dates"]), 3, "date_or_time:+3"),
        (bool(hints["venues"] or hints["regions"]), 3, "place_or_venue:+3"),
        (bool(hints["events"]), 4, "event_name:+4"),
        (bool(hints["songs"] or hints["groups"]), 2, "song_or_group:+2"),
        ("A" in patterns or bool(schedule_hits), 3, "plan_or_announcement:+3"),
        (any(code in patterns for code in ("B", "C", "D")), 2, "question_recommend_invite:+2"),
        ("E" in patterns, 2, "past_participation:+2"),
        (bool(hints["year_signals"]), 3, "year_continuity:+3"),
    ]
    for matched, points, reason in additions:
        if matched:
            score += points
            reasons.append(reason)
    if not bon_hits:
        score -= 3
        reasons.append("weak_bon_context:-3")
    if exclude:
        score -= 5
        reasons.append("excluded_context:-5")

    account = voice.get("account") or ""
    date = voice.get("date") or ""
    display_name = hints["events"][0] if hints["events"] else f"[断片] {account or '発言者不明'} {date[:10] or '日付不明'}"
    return {
        "venue": display_name,
        "identity": evidence_identity(voice),
        "type": "イベント",
        "source": "x_event_evidence",
        "priority": "高" if score >= 8 else "通常",
        "status": "未確認",
        "text": text,
        "url": voice.get("url") or "",
        "account": account,
        "spoken_at": date,
        "tweet_id": tweet_id_from_voice(voice),
        "patterns": patterns,
        "score": score,
        "score_reasons": reasons,
        "time_hints": hints["dates"],
        "place_hints": hints["regions"],
        "venue_hints": hints["venues"],
        "song_hints": hints["songs"],
        "group_hints": hints["groups"],
        "year_signals": hints["year_signals"],
        "estimated_event": hints["events"][0] if hints["events"] else "",
        "estimated_venue": hints["venues"][0] if hints["venues"] else "",
        "related_key": _related_key(hints),
    }


def build_initial_window(now=None, days=14):
    now = now or datetime.now(timezone.utc)
    try:
        start = now.replace(year=now.year - 1, hour=0, minute=0, second=0, microsecond=0)
    except ValueError:
        start = now.replace(year=now.year - 1, month=2, day=28, hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=days)


def build_history_query(handles, start, end):
    froms = " OR ".join(f"from:{handle.lstrip('@')}" for handle in handles)
    since = start.astimezone(timezone.utc).strftime("%Y-%m-%d_%H:%M:%S_UTC")
    until = end.astimezone(timezone.utc).strftime("%Y-%m-%d_%H:%M:%S_UTC")
    return f"({froms}) -filter:retweets since:{since} until:{until}"
