#!/usr/bin/env python3
"""Make LLM-readable, non-semantic extraction packets from X voices."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from collection_support.x_source_officiality import assess_source_officiality
from master_rdb.master_db import stable_id

X_SOURCES = {"x", "x_whitelist", "x_proactive", "x_event_history"}
URL_RE = re.compile(r"https?://\S+")
CALENDAR_DATE_RE = re.compile(r"(?:(20\d{2})[年/-])?(\d{1,2})月(\d{1,2})日?|(?:(20\d{2})[/-])?(\d{1,2})/(\d{1,2})(?!\d)")
ELIDED_DAY_RE = re.compile(
    r"(?:(20\d{2})[年/-])?(\d{1,2})[月/-](\d{1,2})日?"
    r"(?:\s*[（(][^）)]*[）)])?\s*(?:[・･、,，.．〜～~\-ー–—]|と|＆|&)\s*"
    r"(\d{1,2})日?(?!\d|\s*[:：時])"
)
ADJACENT_WEEKDAY_DAY_RE = re.compile(
    r"(?:(20\d{2})[年/-])?(\d{1,2})[月/-](\d{1,2})日?"
    r"\s*[（(][月火水木金土日](?:曜(?:日)?)?[）)]\s*"
    r"(\d{1,2})日?\s*[（(][月火水木金土日](?:曜(?:日)?)?[）)]"
)
REIWA_DATE_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:R|令和)\s*(\d{1,2})(?:年|[./])\s*"
    r"(\d{1,2})(?:月|[./])\s*(\d{1,2})日?(?!\d)",
    re.IGNORECASE,
)
COMPACT_DATE_RE = re.compile(
    r"(?<!\d)([23]\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])"
    r"\s*[（(][月火水木金土日](?:曜(?:日)?)?[）)]"
)
RELATIVE_DAY_RE = re.compile(r"(?:明日|翌日)\s*[（(]\s*(\d{1,2})日\s*[）)]")


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def normalized_text(value: str) -> str:
    return re.sub(r"\s+", "", URL_RE.sub("", str(value or "")))


def _posted_at(voice: dict) -> str:
    return str(voice.get("posted_at") or voice.get("date") or voice.get("created_at") or "")


def _posted_date(value: str, fallback: date) -> date:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return fallback


def _resolved_date(explicit_year: str | None, month: int, day: int, posted: date) -> date | None:
    year = int(explicit_year) if explicit_year else posted.year
    if not explicit_year and month < posted.month - 2:
        year += 1
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _overlaps(span: tuple[int, int], occupied: list[tuple[int, int]]) -> bool:
    return any(span[0] < end and start < span[1] for start, end in occupied)


def machine_dates(text: str, posted_at: str, *, today: date | None = None) -> list[str]:
    """Extract text-grounded calendar dates; clock times never match."""
    today = today or date.today()
    posted = _posted_date(posted_at, today)
    found: set[date] = set()
    anchors: list[tuple[int, date]] = []
    occupied: list[tuple[int, int]] = []

    # Era and compact forms carry their own year.  Mark their spans so the
    # ordinary month/day pass cannot also infer a conflicting posted-at year.
    for match in REIWA_DATE_RE.finditer(text):
        era_year = int(match.group(1))
        value = (
            _resolved_date(str(2018 + era_year), int(match.group(2)), int(match.group(3)), posted)
            if era_year else None
        )
        if value:
            found.add(value)
            anchors.append((match.end(), value))
        occupied.append(match.span())
    for match in COMPACT_DATE_RE.finditer(text):
        value = _resolved_date(str(2000 + int(match.group(1))), int(match.group(2)), int(match.group(3)), posted)
        if value:
            found.add(value)
            anchors.append((match.end(), value))
        occupied.append(match.span())

    for match in CALENDAR_DATE_RE.finditer(text):
        if _overlaps(match.span(), occupied):
            continue
        groups = match.groups()
        explicit = groups[0] or groups[3]
        month, day = int(groups[1] or groups[4]), int(groups[2] or groups[5])
        value = _resolved_date(explicit, month, day, posted)
        if value:
            found.add(value)
            anchors.append((match.end(), value))

    # A range/list may omit the second month (8/21-23, 8月22・23日).  Only
    # reuse the explicitly grounded start month, and reject backwards values
    # rather than guessing a month rollover.
    for match in (*ELIDED_DAY_RE.finditer(text), *ADJACENT_WEEKDAY_DAY_RE.finditer(text)):
        if _overlaps(match.span(), occupied):
            continue
        start = _resolved_date(match.group(1), int(match.group(2)), int(match.group(3)), posted)
        if not start:
            continue
        try:
            end = date(start.year, start.month, int(match.group(4)))
        except ValueError:
            continue
        if end < start:
            continue
        found.update((start, end))
        anchors.append((match.end(), end))

    # A day-only relative expression is accepted only when a prior explicit
    # date in the same post proves the exact next day.  "本日"/"今週末" and a
    # bare "明日" remain unexpanded because they would depend on posted_at.
    anchors.sort(key=lambda row: row[0])
    for match in RELATIVE_DAY_RE.finditer(text):
        prior = [value for end, value in anchors if end <= match.start()]
        if not prior:
            continue
        expected = prior[-1] + timedelta(days=1)
        if expected.day == int(match.group(1)):
            found.add(expected)
    return [value.isoformat() for value in sorted(found)]


def _state_rows(state: dict) -> dict:
    return state.get("tweets", state) if isinstance(state, dict) else {}


def build(voices: list[dict], state: dict, *, batch_size: int = 150, now: datetime | None = None,
          reissue: bool = False, since: date | None = None, max_batches: int = 10) -> list[dict]:
    """voices からパケットを組む。

    `voices.json` は日次の差分ではなく**累積**（2026-08-16 時点で X 系 32,476件）なので、
    投稿日の下限を置かないと state が空の初回実行で102バッチ＝30,557件が対象になる。
    実測では1日分が約780件（3バッチ）なので、既定は「前日以降」にしてある。
    過去へ遡りたいときだけ `since` を明示する。
    """
    now = now or datetime.now(timezone.utc)
    since = since or (now.date() - timedelta(days=1))
    rows = _state_rows(state)
    selected, text_seen = [], set()
    for voice in voices:
        if not isinstance(voice, dict) or voice.get("source") not in X_SOURCES:
            continue
        # 投稿日が読めないものは落とさず通す（読ませない側へ倒さない）。
        if _posted_date(_posted_at(voice), now.date()) < since:
            continue
        text = str(voice.get("text") or voice.get("title") or "")
        dedupe = normalized_text(text)
        if not dedupe or dedupe in text_seen:
            continue
        # Deduplicate before state filtering: a repost of a just-issued text
        # must not sneak into another packet under a different tweet id.
        text_seen.add(dedupe)
        tweet_id = str(voice.get("tweet_id") or voice.get("id") or "")
        if not tweet_id:
            continue
        record = rows.get(tweet_id) or {}
        issued = str(record.get("issued_at") or "")
        if record.get("applied_at"):
            continue
        if issued and not reissue:
            try:
                if now - datetime.fromisoformat(issued.replace("Z", "+00:00")) < timedelta(hours=24):
                    continue
            except ValueError:
                pass
        officiality = assess_source_officiality({}, voice=voice)
        posted_at = _posted_at(voice)
        selected.append({"tweet_id": tweet_id, "url": str(voice.get("url") or ""),
            "account": str(voice.get("account") or voice.get("author") or ""),
            "account_name": str(voice.get("account_name") or voice.get("name") or officiality.get("account_name") or ""),
            "posted_at": posted_at, "officiality": officiality.get("classification") or "unknown_or_personal_social",
            "text": text, "has_media": bool(voice.get("has_media") or voice.get("media")),
            "machine_extracted_dates": machine_dates(text, posted_at, today=now.date())})
    packets=[]
    # 上限を超えた分は捨てず、state へ issued を書かないので次回そのまま出てくる。
    for offset in range(0, min(len(selected), batch_size * max_batches), batch_size):
        number = offset // batch_size + 1
        batch_id = f"x_extraction_{now:%Y%m%d}_{number:02d}"
        items=[]
        for no, value in enumerate(selected[offset:offset + batch_size], 1):
            text_hash = hashlib.sha256(value["text"].encode()).hexdigest()
            items.append({"packet_version": 1, "packet_id": stable_id("xpacket", value["tweet_id"], text_hash), "no": no, **value})
        packets.append({"batch_id": batch_id, "generated_at": now.isoformat(), "packets": items})
    return packets


def write_packets(packets: list[dict], state: dict, out_dir: Path, state_path: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = _state_rows(state)
    if "tweets" not in state: state = {"tweets": rows}
    stamp = datetime.now(timezone.utc).isoformat()
    for packet in packets:
        base = out_dir / f"batch_{packet['batch_id'].removeprefix('x_extraction_')}.json"
        base.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        lines = [f"# {packet['batch_id']}", "", "```json", json.dumps(packet, ensure_ascii=False, indent=2), "```", ""]
        base.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")
        for item in packet["packets"]:
            rows[item["tweet_id"]] = {"issued_at": stamp, "batch_id": packet["batch_id"], "applied_at": None, "outcome": None}
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--voices", type=Path, default=Path("data/voices.json")); p.add_argument("--state", type=Path, default=Path("data/x_extraction_state.json"))
    p.add_argument("--out-dir", type=Path, default=Path("data/x_extraction_packets")); p.add_argument("--batch-size", type=int, default=150); p.add_argument("--reissue", action="store_true")
    p.add_argument("--since", type=date.fromisoformat, help="この日以降に投稿されたものだけを対象にする（既定は前日以降）")
    p.add_argument("--max-batches", type=int, default=10, help="1回に出すバッチ数の上限。超えた分は次回へ残す")
    a = p.parse_args()
    if a.batch_size < 1: p.error("--batch-size must be positive")
    if a.max_batches < 1: p.error("--max-batches must be positive")
    state = load_json(a.state, {"tweets": {}})
    packets = build(load_json(a.voices, []), state, batch_size=a.batch_size, reissue=a.reissue,
                    since=a.since, max_batches=a.max_batches)
    write_packets(packets, state, a.out_dir, a.state)
    print(f"x extraction packets: {len(packets)} batches / {sum(len(p['packets']) for p in packets)} posts")


if __name__ == "__main__": main()
