#!/usr/bin/env python3
"""Shared daily/monthly budget guard for paid X API scripts.

`collect.py` has always stopped itself at the configured daily/monthly cap, but
the discovery and candidate-review scripts only *estimated* their spend and
recorded it in their own output — they never checked the shared ledger and never
wrote to it. That is why those two were kept manual-only (2026-06-26 decision,
`docs/x-candidate-workflows-operations.md`): unlike the daily collector they were
unbounded.

This module gives them the same ledger and the same fail-safe, so they can run on
a schedule without being able to outspend the cap.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

BUDGET_FILE = Path("data") / "x_budget.json"
CONFIG_FILE = Path("x_queries.json")


def load_config(path=None):
    path = Path(path or CONFIG_FILE)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def load_state(path=None):
    path = Path(path or BUDGET_FILE)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def spent(state=None, now=None):
    """Return (daily_spent_usd, monthly_spent_usd)."""
    state = state if state is not None else load_state()
    now = now or datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    month = today[:7]
    daily = float(state.get(today, 0.0) or 0.0)
    monthly = sum(
        float(value or 0.0) for key, value in state.items() if str(key).startswith(month)
    )
    return daily, monthly


def check(cfg=None, state=None, now=None, headroom_usd=0.0):
    """Return (allowed, message). `headroom_usd` は今から使う見込み額。"""
    cfg = cfg if cfg is not None else load_config()
    budget = (cfg or {}).get("budget", {}) or {}
    daily_cap = budget.get("daily_usd", 3.0)
    monthly_cap = budget.get("monthly_usd", 25.0)
    daily, monthly = spent(state, now)
    if daily + headroom_usd >= daily_cap:
        return False, (
            f"日次予算に到達のためスキップ（本日 ${daily:.4f} / 上限 ${daily_cap:.2f}）"
        )
    if monthly + headroom_usd >= monthly_cap:
        return False, (
            f"月次予算に到達のためスキップ（今月 ${monthly:.4f} / 上限 ${monthly_cap:.2f}）"
        )
    return True, (
        f"予算内（本日 ${daily:.4f}/${daily_cap:.2f} 今月 ${monthly:.4f}/${monthly_cap:.2f}）"
    )


def record_spend(usd, path=None, now=None):
    """Add spend to the shared ledger so other scripts see it the same day."""
    usd = float(usd or 0.0)
    if usd <= 0:
        return
    path = Path(path or BUDGET_FILE)
    state = load_state(path)
    today = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    state[today] = round(float(state.get(today, 0.0) or 0.0) + usd, 8)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
