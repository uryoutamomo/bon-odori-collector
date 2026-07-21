"""Shared noise suppression rules for retrospective X harvest."""

import json
import re
import unicodedata
from pathlib import Path


RULES_FILE = Path("data/noise_suppression.json")
DEFAULT_RULES = {
    "blocked_cultural_names": [
        "死霊の盆踊り",
        "見取り図",
        "見取り図盆踊り",
    ],
    "generic_song_names": [
        "踊り",
        "おどり",
        "ぼんおどり",
        "盆踊り",
        "盆おどり",
        "夜の踊り",
        "新しい盆踊り",
        "息の合った踊り",
        "またその行事内で行われる踊り",
    ],
}


def normalize_text(value):
    value = unicodedata.normalize("NFKC", str(value or ""))
    value = value.casefold()
    return re.sub(r"[\s　\"'“”‘’「」『』【】\[\]（）()・、。!！?？:：/／\\|｜~〜\-‐‑–—_]+", "", value)


def load_rules(path=RULES_FILE):
    if not path.exists():
        return DEFAULT_RULES
    with path.open(encoding="utf-8") as handle:
        loaded = json.load(handle)
    rules = {key: list(value) for key, value in DEFAULT_RULES.items()}
    for key, value in loaded.items():
        if isinstance(value, list):
            rules[key] = value
    return rules


def blocked_cultural_match(value, rules=None):
    normalized = normalize_text(value)
    if not normalized:
        return ""
    for name in (rules or load_rules()).get("blocked_cultural_names", []):
        blocked = normalize_text(name)
        if blocked and blocked in normalized:
            return name
    return ""


def is_generic_song_name(value, rules=None):
    normalized = normalize_text(value)
    if not normalized:
        return True
    generic = {
        normalize_text(name)
        for name in (rules or load_rules()).get("generic_song_names", [])
    }
    if normalized in generic:
        return True
    if re.fullmatch(r"(?:その|この|あの)?(?:行事内で行われる)?(?:踊り|おどり|ぼんおどり|盆踊り|盆おどり)", normalized):
        return True
    return False


def has_specific_event_anchor(value):
    value = str(value or "")
    if re.search(r"(?:神社|寺|本願寺|公園|広場|会館|商店街|学校|小学校|中学校|駅前|シティ|明神)", value):
        return True
    if re.search(r"[一-龥ぁ-んァ-ヶーA-Za-z0-9]{2,}(?:音頭|まつり|祭り|盆踊り大会|盆おどり大会|納涼盆踊り大会)", value):
        return True
    if re.search(r"(?:アニソン|西馬音内|郡上|阿波|よさこい|真證寺|サンシャイン)", value):
        return True
    return False


def is_event_sentence_fragment(value, normalized=None, has_anchor=False):
    raw = str(value or "").strip()
    normalized = normalized if normalized is not None else normalize_text(raw)
    if not raw:
        return True
    if has_anchor or has_specific_event_anchor(raw):
        return False
    if re.match(r"^(?:今日|今日は|昨日|昨日は|本日|今年|今年初|今年は|先日|やります|やる|覚えた)", raw):
        return True
    if re.search(r"(?:今日は|昨日|やります|覚えた|なんとなく|仲間と|各地の|という|っぽい)", raw):
        return True
    if len(raw) >= 12 and re.search(r"(?:は|が|を|と|で|に|へ|から|まで|した|する|して|行く|行き|やる|やり|覚えた)", raw):
        return True
    if normalized in {"昨日盆踊り", "今日盆踊り", "今日は盆踊り", "やります盆踊り"}:
        return True
    return False
