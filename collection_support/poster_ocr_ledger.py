#!/usr/bin/env python3
"""Ledger of poster/flyer images that have already been read (OCR'd).

`data/event_poster_ocr_queue.json` is rebuilt from scratch on every collect run,
so "already read this one" cannot live in the queue file itself. This ledger is
the durable record: it survives rebuilds and lets the queue mark items as done
instead of showing them as `needs_ocr` forever.

Statuses:
- `ocr_done`         読み取り、イベント情報を抽出した（`report_id` に反映先レポート）
- `ocr_no_event`     読んだが公開に使えるイベント情報が無かった（提灯の写真など）
- `ocr_unreadable`   画像が不鮮明・関係ない画像で読み取れなかった
"""

import json
from datetime import datetime, timezone
from pathlib import Path

LEDGER_PATH = Path("data") / "poster_ocr_processed.json"

DONE_STATUSES = ("ocr_done", "ocr_no_event", "ocr_unreadable")


def load_ledger(path=None):
    path = Path(path or LEDGER_PATH)
    if not path.exists():
        return {"updated_at": "", "processed": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"updated_at": "", "processed": {}}
    if not isinstance(payload, dict):
        return {"updated_at": "", "processed": {}}
    payload.setdefault("processed", {})
    return payload


def processed_ids(ledger=None):
    ledger = ledger if ledger is not None else load_ledger()
    return {
        queue_id
        for queue_id, row in (ledger.get("processed") or {}).items()
        if isinstance(row, dict) and row.get("status") in DONE_STATUSES
    }


def processed_status(ledger=None):
    """Return {queue_id: status} for every recorded item."""
    ledger = ledger if ledger is not None else load_ledger()
    return {
        queue_id: row.get("status")
        for queue_id, row in (ledger.get("processed") or {}).items()
        if isinstance(row, dict) and row.get("status")
    }


def record(queue_id, status, report_id="", note="", ledger=None, path=None, save=True):
    """Mark one queue item as read. Returns the updated ledger."""
    if status not in DONE_STATUSES:
        raise ValueError(f"未知のstatus: {status} (許可: {', '.join(DONE_STATUSES)})")
    ledger = ledger if ledger is not None else load_ledger(path)
    ledger.setdefault("processed", {})[queue_id] = {
        "status": status,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "report_id": report_id,
        "note": note,
    }
    ledger["updated_at"] = datetime.now(timezone.utc).isoformat()
    if save:
        save_ledger(ledger, path)
    return ledger


def save_ledger(ledger, path=None):
    path = Path(path or LEDGER_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path
