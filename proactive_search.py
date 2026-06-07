import html
import json
import os
import re
import urllib.request
from datetime import datetime, timezone


DEFAULT_CONFIG = "data/evergreen_events.json"
BON_KEYWORDS = ("盆踊り", "盆おどり", "民踊大会", "音頭と民踊")
CONFIRM_KEYWORDS = (
    "開催", "開催決定", "開催予定", "日程", "プログラム",
    "奉祝行事", "民踊大会", "盆踊り", "盆おどり",
)


def parse_months(value):
    if value is None:
        return []
    if isinstance(value, list):
        values = []
        for item in value:
            values.extend(re.findall(r"\d{1,2}", str(item)))
    else:
        values = re.findall(r"\d{1,2}", str(value))
    months = []
    for raw in values:
        try:
            month = int(raw)
        except (TypeError, ValueError):
            continue
        if 1 <= month <= 12 and month not in months:
            months.append(month)
    return months


def load_targets(venue_master, config_path=DEFAULT_CONFIG):
    config = {}
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except (OSError, ValueError):
        pass

    by_name = {}
    for venue in venue_master or []:
        name = (venue.get("venue") or "").strip()
        months = parse_months(venue.get("month"))
        if not name or not months:
            continue
        by_name[name] = {
            "venue": name,
            "event_name": name,
            "months": months,
            "aliases": [],
            "official_sources": [],
            "region": venue.get("region") or "",
        }

    for event in config.get("events", []):
        name = (event.get("venue") or "").strip()
        if not name:
            continue
        current = by_name.get(name, {})
        merged = dict(current)
        merged.update(event)
        merged["venue"] = name
        merged["event_name"] = (
            event.get("event_name") or current.get("event_name") or name
        )
        merged["months"] = parse_months(
            event.get("months") or current.get("months")
        )
        merged["aliases"] = _unique(
            [name, merged["event_name"]]
            + list(current.get("aliases") or [])
            + list(event.get("aliases") or [])
        )
        merged["official_sources"] = _unique(
            list(current.get("official_sources") or [])
            + list(event.get("official_sources") or [])
        )
        if merged["months"]:
            by_name[name] = merged

    return list(by_name.values()), config


def select_due_targets(targets, now=None, lead_months=1):
    now = now or datetime.now(timezone.utc)
    active = {((now.month - 1 + offset) % 12) + 1 for offset in range(lead_months + 1)}
    return [
        target for target in targets
        if active.intersection(parse_months(target.get("months")))
    ]


def build_queries(target, year):
    names = _unique(
        [target.get("venue"), target.get("event_name")]
        + list(target.get("aliases") or [])
    )
    quoted = " OR ".join(f'"{name}"' for name in names if name)
    return {
        "news": f"({quoted}) {year} (盆踊り OR 民踊大会 OR 山王祭)",
        "x": (
            f"({quoted}) ({year} OR 令和{year - 2018}年) "
            "(盆踊り OR 盆おどり OR 民踊大会) lang:ja -filter:retweets"
        ),
    }


def check_official_sources(target, year, timeout=20):
    evidence = []
    terms = _unique(
        [target.get("venue"), target.get("event_name")]
        + list(target.get("aliases") or [])
    )
    for url in target.get("official_sources") or []:
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "bon-odori-collector/1.0"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                content_type = response.headers.get("Content-Type", "")
                if "text/html" not in content_type:
                    continue
                raw = response.read(1_500_000).decode("utf-8", errors="ignore")
            text = _html_to_text(raw)
            if _is_confirmation(text, terms, year):
                evidence.append({
                    "source": "official",
                    "title": f"{target['event_name']} 公式情報",
                    "text": _snippet(text, terms, year),
                    "url": url,
                })
        except Exception as exc:
            print(f"[proactive] 公式URL確認失敗（{url}）: {exc}")
    return evidence


def build_report(targets, collected_items, year):
    report = []
    for target in targets:
        terms = _unique(
            [target.get("venue"), target.get("event_name")]
            + list(target.get("aliases") or [])
        )
        matches = []
        for item in collected_items:
            text = " ".join(
                str(item.get(key) or "")
                for key in ("title", "text", "date", "pubDate", "url")
            )
            if not any(term in text for term in terms):
                continue
            if not _is_confirmation(text, terms, year):
                continue
            matches.append({
                "source": item.get("source") or "collected",
                "title": item.get("title") or item.get("text", "")[:80],
                "text": item.get("text") or item.get("title") or "",
                "url": item.get("url") or "",
            })
        report.append({
            "venue": target["venue"],
            "event_name": target.get("event_name") or target["venue"],
            "months": target.get("months") or [],
            "status": "confirmed" if matches else "unconfirmed",
            "evidence": matches[:3],
        })
    return report


def _is_confirmation(text, terms, year):
    compact = re.sub(r"\s+", " ", html.unescape(text or ""))
    has_name = any(term and term in compact for term in terms)
    has_context = any(keyword in compact for keyword in CONFIRM_KEYWORDS)
    has_year = str(year) in compact or f"令和{year - 2018}年" in compact
    return has_name and has_context and has_year


def _html_to_text(raw):
    raw = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw)
    raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return re.sub(r"\s+", " ", html.unescape(raw)).strip()


def _snippet(text, terms, year, width=220):
    positions = [text.find(term) for term in terms if term and term in text]
    year_pos = text.find(str(year))
    if year_pos >= 0:
        positions.append(year_pos)
    start = max(0, min(positions or [0]) - 60)
    return text[start:start + width]


def _unique(values):
    return list(dict.fromkeys(value for value in values if value))
