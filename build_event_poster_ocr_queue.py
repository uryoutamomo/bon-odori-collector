#!/usr/bin/env python3
"""Build a high-priority OCR queue for X poster/flyer event evidence."""

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from collection_support.poster_gap_matching import annotate, load_date_gap_events
from collection_support.poster_ocr_ledger import processed_status


DATA = Path("data")
VOICES = DATA / "voices.json"
IMPORTANT_INFORMANTS = DATA / "x_important_informants.json"
OUT = DATA / "event_poster_ocr_queue.json"

X_SOURCES = {"x", "x_whitelist", "x_event_history", "x_proactive"}
BON_RE = re.compile(r"(?:盆踊り|盆おどり|ぼんおどり|盆踊|民踊|納涼|音頭|やぐら|櫓)", re.I)
SCHEDULE_RE = re.compile(
    r"(?:開催|日程|予定|お知らせ|ご案内|会場|場所|時間|雨天|順延|中止|"
    r"20\d{2}|令和\d+年|\d{1,2}月\d{1,2}日?|\d{1,2}/\d{1,2}|\d{1,2}:\d{2}|"
    r"[午前午後]\d{1,2}時)"
)
POSTER_RE = re.compile(r"(?:ポスター|チラシ|フライヤー|掲示|回覧|町会|自治会|お知らせ|告知|案内)")


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def norm_handle(value):
    return str(value or "").strip().lstrip("@").lower()


def important_informants(path=IMPORTANT_INFORMANTS):
    payload = load_json(path, {})
    rows = {}
    for row in payload.get("accounts") or []:
        if row.get("collection_enabled") is False:
            continue
        handle = norm_handle(row.get("handle"))
        if handle:
            rows[handle] = row
    return rows


def queue_id(row):
    raw = "\0".join([
        row.get("url") or "",
        row.get("tweet_id") or "",
        "|".join(row.get("media_urls") or []),
    ])
    return "xposter_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def priority_for(row, informants):
    handle = norm_handle(row.get("account") or row.get("author"))
    text = f"{row.get('title') or ''}\n{row.get('text') or ''}"
    trusted = handle in informants
    has_poster_hint = bool(POSTER_RE.search(text))
    has_schedule_hint = bool(SCHEDULE_RE.search(text))
    if trusted and (has_poster_hint or has_schedule_hint):
        return "critical"
    if trusted:
        return "high"
    if has_poster_hint and has_schedule_hint:
        return "high"
    return "medium"


def should_queue(row, informants):
    if row.get("source") not in X_SOURCES:
        return False
    if not row.get("media_urls"):
        return False
    text = f"{row.get('title') or ''}\n{row.get('text') or ''}"
    handle = norm_handle(row.get("account") or row.get("author"))
    if handle in informants and BON_RE.search(text):
        return True
    return bool(BON_RE.search(text) and (POSTER_RE.search(text) or SCHEDULE_RE.search(text)))


def evidence_type(row, informants):
    handle = norm_handle(row.get("account") or row.get("author"))
    if handle in informants:
        return "trusted_field_reporter_poster_image"
    return "poster_or_flyer_image"


def parse_date(value):
    value = str(value or "")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def is_recent_enough(row, now=None, max_age_days=None):
    if max_age_days is None:
        return True
    parsed = parse_date(row.get("date"))
    if parsed is None:
        return True
    now = now or datetime.now(timezone.utc)
    return parsed >= now - timedelta(days=max_age_days)


def build(
    rows,
    informants=None,
    max_age_days=None,
    now=None,
    processed=None,
    date_gap_events=None,
):
    """Build the queue of unread poster images.

    `processed` は {queue_id: status} の読み取り済み台帳
    (`collection_support.poster_ocr_ledger`)。既に読んだ投稿はキューから外す。
    渡さない場合は台帳を参照しない（テスト・単体利用のため）。

    `date_gap_events` は開催日が未確定のイベント一覧
    (`collection_support.poster_gap_matching.load_date_gap_events`)。触れている
    投稿を先頭に並べ替える。
    """
    informants = informants if informants is not None else important_informants()
    processed = processed or {}
    queued = []
    seen = set()
    skipped_processed = 0
    for row in rows:
        if not isinstance(row, dict) or not should_queue(row, informants):
            continue
        if not is_recent_enough(row, now=now, max_age_days=max_age_days):
            continue
        qid = queue_id(row)
        if qid in seen:
            continue
        seen.add(qid)
        if qid in processed:
            skipped_processed += 1
            continue
        handle = norm_handle(row.get("account") or row.get("author"))
        informant = informants.get(handle, {})
        queued.append({
            "id": qid,
            "status": "needs_ocr",
            "priority": priority_for(row, informants),
            "evidence_type": evidence_type(row, informants),
            "assumed_source_confidence": "high" if handle in informants else "medium",
            "account": row.get("account") or row.get("author") or "",
            "account_name": row.get("name") or informant.get("name") or "",
            "trusted_informant": bool(handle in informants),
            "trusted_informant_rank": informant.get("usefulness_rank") or "",
            "url": row.get("url") or "",
            "tweet_id": row.get("tweet_id") or "",
            "date": row.get("date") or "",
            "media_urls": row.get("media_urls") or [],
            "text": (row.get("text") or "")[:1000],
            "review_hint": (
                "ポスター/チラシ画像をOCRし、イベント名・開催日・時間・会場・主催者を読めたら"
                "高確度の開催候補として昇格する"
            ),
        })
    if date_gap_events:
        annotate(queued, date_gap_events)
    priority_order = {"critical": 0, "high": 1, "medium": 2}
    # 日付未確定イベントに触れている投稿を最優先で読む。公開サイトで地図に出せて
    # いないのはこの「開催日が分からない」イベントなので、読めば直接埋まる。
    queued.sort(
        key=lambda row: (
            0 if row.get("matched_date_gap_events") else 1,
            priority_order.get(row["priority"], 9),
            row["date"],
            row["url"],
        )
    )
    return {
        "generated_by": "build_event_poster_ocr_queue.py",
        "count": len(queued),
        "summary": {
            "critical": sum(1 for row in queued if row["priority"] == "critical"),
            "high": sum(1 for row in queued if row["priority"] == "high"),
            "trusted_informant": sum(1 for row in queued if row["trusted_informant"]),
            "already_read": skipped_processed,
            "date_gap_matched": sum(
                1 for row in queued if row.get("matched_date_gap_events")
            ),
        },
        "items": queued,
    }


def load_date_gaps(event_year):
    """Read date-unknown events from the master RDB. Missing DB is not an error."""
    try:
        from master_rdb.master_db import connect_existing
    except ImportError:
        return []
    try:
        with connect_existing() as conn:
            return load_date_gap_events(conn, event_year)
    except Exception as exc:  # RDB未取得・スキーマ差異でもキュー生成自体は止めない
        print(f"[poster-ocr] 日付未確定イベントの読込をスキップ: {exc}")
        return []


def main():
    event_year = int(os.environ.get("TARGET_YEAR") or datetime.now(timezone.utc).year)
    output = build(
        load_json(VOICES, []),
        max_age_days=90,
        processed=processed_status(),
        date_gap_events=load_date_gaps(event_year),
    )
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "イベントポスター画像OCRキュー生成: "
        f"未読 {output['count']}件 critical={output['summary']['critical']} "
        f"日付未確定イベントに一致 {output['summary']['date_gap_matched']}件 "
        f"読取済み {output['summary']['already_read']}件 -> {OUT}"
    )


if __name__ == "__main__":
    main()
