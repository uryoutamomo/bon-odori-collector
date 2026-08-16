"""Append-only, route-level X API cost and outcome ledger.

``x_budget.json`` remains the intentionally simple shared budget guard.  This
ledger supplements it with the route and outcome detail needed to judge whether
a collection change saved money without silently reducing useful intake.
"""

import json
from datetime import datetime, timezone
from pathlib import Path


COST_LEDGER_FILE = Path("data") / "x_cost_ledger.json"
SCHEMA_VERSION = 1
ROUTES = {
    "search",
    "whitelist",
    "cohort_evidence",
    "candidate_probe",
    "social_graph",
    "proactive",
    "unattributed",
}


def load_ledger(path=None):
    path = Path(path or COST_LEDGER_FILE)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        payload = {}
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read X cost ledger: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"X cost ledger is not an object: {path}")
    entries = payload.get("entries")
    if entries is None:
        entries = []
    if not isinstance(entries, list):
        raise ValueError(f"X cost ledger entries is not a list: {path}")
    return {
        "schema_version": SCHEMA_VERSION,
        "entries": entries,
    }


def record_run(
    route,
    *,
    cost_usd,
    requests=0,
    tweets_fetched=0,
    new_urls=0,
    voices_accepted=0,
    evidence_detected=0,
    candidates_found=0,
    candidates_promoted=0,
    query_id=None,
    source="collector",
    note=None,
    path=None,
    now=None,
):
    """Append one immutable run summary, including zero-cost useful outcomes.

    ``route`` is deliberately finite so weekly analysis cannot accidentally
    introduce spelling variants.  Callers may use ``query_id`` to split the
    normal search route into q-base, q-report, and so on.
    """
    if route not in ROUTES:
        raise ValueError(f"unknown X cost route: {route}")
    now = now or datetime.now(timezone.utc)
    entry = {
        "recorded_at": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "route": route,
        "query_id": query_id,
        "cost_usd": round(float(cost_usd or 0.0), 8),
        "requests": int(requests or 0),
        "tweets_fetched": int(tweets_fetched or 0),
        "new_urls": int(new_urls or 0),
        "voices_accepted": int(voices_accepted or 0),
        "evidence_detected": int(evidence_detected or 0),
        "candidates_found": int(candidates_found or 0),
        "candidates_promoted": int(candidates_promoted or 0),
        "source": str(source or "collector"),
        "note": note,
    }
    ledger_path = Path(path or COST_LEDGER_FILE)
    try:
        ledger = load_ledger(ledger_path)
    except ValueError as exc:
        print(f"[x-cost-ledger] 読込エラー（収集は継続）: {exc}")
        return None
    ledger["entries"].append(entry)
    try:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ledger_path.write_text(
            json.dumps(ledger, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        # Observability must never turn a successful X collection into a failure.
        print(f"[x-cost-ledger] 保存エラー（収集は継続）: {exc}")
        return None
    return entry
