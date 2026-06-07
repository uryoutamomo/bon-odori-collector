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


def _related_key(hints):
    parts = []
    for key in ("dates", "regions", "venues", "songs", "groups", "events"):
        values = hints.get(key) or []
        if values:
            parts.append(re.sub(r"\s+", "", values[0]).casefold())
    return "|".join(parts)[:500]


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
        "events": _unique_matches(EVENT_RE, text),
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
