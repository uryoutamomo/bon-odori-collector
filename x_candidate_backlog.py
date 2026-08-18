#!/usr/bin/env python3
"""Persist X event candidates beyond the bounded daily review projection.

``build_x_gap_candidates.py`` deliberately limits the human-facing daily queue.
This module keeps both selected and overflow candidates in a durable ledger,
assigns an explicit lifecycle, and selects a small daily review cohort without
discarding the remainder.

The backlog is not a decision writer.  Scheduled Review Inbox publication may
move an item from ``unprocessed`` to ``in_progress`` only after the CAS write
succeeds.  Terminal ``registered``/``rejected`` transitions require an explicit
operator or agent command with a reason and evidence reference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
DEFAULT_INPUT = DATA / "x_gap_candidates.json"
DEFAULT_BACKLOG = DATA / "x_candidate_backlog.json"
DEFAULT_ALERT_JSON = DATA / "x_candidate_backlog_alerts.json"
DEFAULT_ALERT_MD = DATA / "x_candidate_backlog_alerts.md"

SCHEMA_VERSION = 1
STATUSES = {"unprocessed", "in_progress", "registered", "rejected"}
TERMINAL_STATUSES = {"registered", "rejected"}
STATUS_LABELS = {
    "unprocessed": "未処理",
    "in_progress": "処理中",
    "registered": "登録済み",
    "rejected": "却下",
}
ALLOWED_TRANSITIONS = {
    "unprocessed": {"in_progress", "registered", "rejected"},
    "in_progress": {"unprocessed", "registered", "rejected"},
    "registered": set(),
    "rejected": set(),
}
HIGH_CONFIDENCE_TIERS = {"high_existing_official", "high_new_official"}


class BacklogError(ValueError):
    """Raised when a backlog mutation would break its lifecycle contract."""


def load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temp_path = Path(handle.name)
    os.replace(temp_path, path)


def _atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(text)
        temp_path = Path(handle.name)
    os.replace(temp_path, path)


def write_backlog(path: Path, backlog: Mapping[str, Any]) -> None:
    """Atomically persist a validated backlog payload."""
    _validated_existing(backlog)
    _atomic_write(path, backlog)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _parse_datetime(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def candidate_sha256(candidate: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        candidate, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _candidate_rows(payload: Mapping[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    rows: list[tuple[str, dict[str, Any]]] = []
    for bucket, field in (
        ("daily_selected", "candidates"),
        ("daily_overflow", "archived_candidates"),
    ):
        values = payload.get(field) or []
        if not isinstance(values, list):
            raise BacklogError(f"x gap payload requires {field} list")
        for raw in values:
            if not isinstance(raw, dict):
                continue
            source_key = str(raw.get("source_key") or "").strip()
            if not source_key:
                raise BacklogError("x gap candidate requires source_key")
            rows.append((bucket, dict(raw)))
    return rows


def candidate_event_date(candidate: Mapping[str, Any]) -> date | None:
    values: list[str] = []
    values.extend(str(value) for value in candidate.get("observed_dates") or [])
    match = candidate.get("matched_occurrence") or {}
    if match.get("date_start"):
        values.append(str(match["date_start"]))
    for value in values:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            continue
    return None


def confidence_policy(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Classify the evidence without authorizing a production mutation."""
    official = (
        (candidate.get("source_officiality") or {}).get("classification")
        == "registered_official_social"
    )
    matched = bool(candidate.get("matched_occurrence"))
    kind = str(candidate.get("candidate_kind") or "")
    source_count = int(
        candidate.get("source_count")
        or candidate.get("corroboration_count")
        or 1
    )
    voice = candidate.get("voice") or {}
    has_poster = bool(
        candidate.get("source_media_urls")
        or voice.get("media_urls")
        or voice.get("media")
        or voice.get("has_media")
    )

    if kind in {"schedule_change", "date_range_conflict"}:
        tier = "collision_or_schedule_conflict"
        target = "needs_user_confirmation"
    elif matched and official:
        tier = "high_existing_official"
        target = "auto_update_existing"
    elif not matched and official:
        tier = "high_new_official"
        target = "auto_register_new_after_duplicate_check"
    elif not matched and has_poster and source_count >= 2:
        tier = "medium_corroborated_poster"
        target = "auto_register_candidate_after_duplicate_check"
    else:
        tier = "low_single_or_personal"
        target = "hold_for_more_evidence"

    return {
        "tier": tier,
        "target_action": target,
        "source_official": official,
        "matched_existing_occurrence": matched,
        "source_count": source_count,
        "has_poster": has_poster,
        # The first five-per-day rollout measures mistakes before any of the
        # target actions are allowed to mutate or publish canonical facts.
        "execution_mode": "daily_canary_review_only",
        "automatic_publication_enabled": False,
    }


def review_priority(candidate: Mapping[str, Any], *, today: date) -> dict[str, Any]:
    event_date = candidate_event_date(candidate)
    days_until = (event_date - today).days if event_date else None
    base = float(candidate.get("priority_score") or 0)
    policy = confidence_policy(candidate)
    score = base
    if policy["source_official"]:
        score += 40
    if days_until is not None:
        if 0 <= days_until <= 7:
            score += 140
        elif days_until <= 14 and days_until >= 0:
            score += 90
        elif days_until <= 30 and days_until >= 0:
            score += 40
        elif days_until < 0:
            score -= 120
    return {
        "score": round(score, 3),
        "base_score": base,
        "event_date": event_date.isoformat() if event_date else None,
        "days_until_event": days_until,
    }


def _validated_existing(existing: Mapping[str, Any] | None) -> dict[str, Any]:
    if not existing:
        return {"schema_version": SCHEMA_VERSION, "items": []}
    if existing.get("schema_version") != SCHEMA_VERSION:
        raise BacklogError("unsupported X candidate backlog schema")
    items = existing.get("items")
    if not isinstance(items, list) or any(not isinstance(row, dict) for row in items):
        raise BacklogError("X candidate backlog requires items list")
    keys = [str(row.get("source_key") or "") for row in items]
    if not all(keys) or len(keys) != len(set(keys)):
        raise BacklogError("X candidate backlog contains empty or duplicate source keys")
    for row in items:
        if row.get("status") not in STATUSES:
            raise BacklogError(f"unsupported X candidate status: {row.get('status')}")
    return dict(existing)


def build_backlog(
    payload: Mapping[str, Any],
    existing: Mapping[str, Any] | None,
    *,
    now: datetime,
    today: date,
) -> dict[str, Any]:
    previous = _validated_existing(existing)
    previous_by_key = {row["source_key"]: dict(row) for row in previous["items"]}
    stamp = _iso(now)
    seen_current: set[str] = set()

    for source_bucket, candidate in _candidate_rows(payload):
        source_key = str(candidate["source_key"])
        seen_current.add(source_key)
        old = previous_by_key.get(source_key) or {}
        status = old.get("status") or "unprocessed"
        first_seen = old.get("first_seen_at") or stamp
        row = {
            "source_key": source_key,
            "candidate_id": str(candidate.get("candidate_id") or ""),
            "status": status,
            "status_label": STATUS_LABELS[status],
            "status_updated_at": old.get("status_updated_at") or first_seen,
            "first_seen_at": first_seen,
            "last_seen_at": stamp,
            "present_in_latest": True,
            "latest_source_bucket": source_bucket,
            "candidate_sha256": candidate_sha256(candidate),
            "candidate": candidate,
            "confidence": confidence_policy(candidate),
            "priority": review_priority(candidate, today=today),
            "queued_at": old.get("queued_at"),
            "review_observation_id": old.get("review_observation_id"),
            "inbox_id": old.get("inbox_id"),
            "resolution": old.get("resolution"),
        }
        previous_by_key[source_key] = row

    for source_key, row in previous_by_key.items():
        if source_key in seen_current:
            continue
        row["present_in_latest"] = False
        row["status_label"] = STATUS_LABELS[row["status"]]
        # Carried candidates still age every day.  Recalculate urgency and
        # policy from their preserved evidence even when today's bounded gap
        # projection no longer contains them.
        row["priority"] = review_priority(row.get("candidate") or {}, today=today)
        row["confidence"] = confidence_policy(row.get("candidate") or {})

    items = sorted(
        previous_by_key.values(),
        key=lambda row: (
            row["status"] in TERMINAL_STATUSES,
            -float((row.get("priority") or {}).get("score") or 0),
            str(row.get("first_seen_at") or ""),
            row["source_key"],
        ),
    )
    status_counts = Counter(row["status"] for row in items)
    current_overflow = {
        candidate["source_key"]
        for bucket, candidate in _candidate_rows(payload)
        if bucket == "daily_overflow"
    }
    missing_overflow = sorted(current_overflow - {row["source_key"] for row in items})
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_by": "x_candidate_backlog.py",
        "updated_at": stamp,
        "source_generated_at": payload.get("generated_at"),
        "summary": {
            "total": len(items),
            "present_in_latest": len(seen_current),
            "carried_from_prior_runs": len(items) - len(seen_current),
            "status_counts": {status: status_counts.get(status, 0) for status in sorted(STATUSES)},
            "latest_selected_count": sum(
                row["latest_source_bucket"] == "daily_selected"
                for row in items
                if row.get("present_in_latest")
            ),
            "latest_overflow_count": len(current_overflow),
            "overflow_missing_after_merge": len(missing_overflow),
        },
        "carryover_check": {
            "passed": not missing_overflow,
            "missing_source_keys": missing_overflow,
        },
        "items": items,
    }


def select_daily_cohort(
    backlog: Mapping[str, Any], *, max_items: int = 5
) -> list[dict[str, Any]]:
    _validated_existing(backlog)
    if not 1 <= max_items <= 30:
        raise BacklogError("daily review cohort must contain between 1 and 30 items")
    pending = [row for row in backlog["items"] if row.get("status") == "unprocessed"]
    pending.sort(
        key=lambda row: (
            -float((row.get("priority") or {}).get("score") or 0),
            str(row.get("first_seen_at") or ""),
            row["source_key"],
        )
    )
    return pending[:max_items]


def mark_in_progress(
    backlog: Mapping[str, Any],
    selected_items: Iterable[Mapping[str, Any]],
    *,
    now: datetime,
    observation_id: str,
) -> dict[str, Any]:
    result = _validated_existing(backlog)
    result = json.loads(json.dumps(result, ensure_ascii=False))
    selected = {
        str(item.get("source_key") or ""): str(item.get("inbox_id") or "")
        for item in selected_items
    }
    if "" in selected:
        raise BacklogError("selected Review Inbox item is missing source identity")
    by_key = {row["source_key"]: row for row in result["items"]}
    missing = sorted(set(selected) - set(by_key))
    if missing:
        raise BacklogError("selected items are absent from backlog: " + ", ".join(missing))
    stamp = _iso(now)
    for source_key, inbox_id in selected.items():
        row = by_key[source_key]
        if row["status"] == "in_progress":
            continue
        if row["status"] != "unprocessed":
            raise BacklogError(
                f"cannot queue {source_key} from terminal status {row['status']}"
            )
        row.update(
            {
                "status": "in_progress",
                "status_label": STATUS_LABELS["in_progress"],
                "status_updated_at": stamp,
                "queued_at": stamp,
                "review_observation_id": observation_id,
                "inbox_id": inbox_id,
            }
        )
    result["updated_at"] = stamp
    counts = Counter(row["status"] for row in result["items"])
    result["summary"]["status_counts"] = {
        status: counts.get(status, 0) for status in sorted(STATUSES)
    }
    return result


def transition_status(
    backlog: Mapping[str, Any],
    *,
    source_key: str,
    status: str,
    now: datetime,
    actor: str,
    reason: str,
    evidence: str,
    reopen: bool = False,
) -> dict[str, Any]:
    result = _validated_existing(backlog)
    result = json.loads(json.dumps(result, ensure_ascii=False))
    if status not in STATUSES:
        raise BacklogError(f"unsupported X candidate status: {status}")
    row = next(
        (value for value in result["items"] if value["source_key"] == source_key),
        None,
    )
    if row is None:
        raise BacklogError(f"X candidate not found: {source_key}")
    before = row["status"]
    allowed = ALLOWED_TRANSITIONS[before]
    if before in TERMINAL_STATUSES and reopen and status == "unprocessed":
        allowed = {"unprocessed"}
    if status != before and status not in allowed:
        raise BacklogError(f"unsupported X candidate transition: {before} -> {status}")
    if not actor.strip() or not reason.strip() or not evidence.strip():
        raise BacklogError("status transition requires actor, reason, and evidence")
    stamp = _iso(now)
    row.update(
        {
            "status": status,
            "status_label": STATUS_LABELS[status],
            "status_updated_at": stamp,
            "resolution": {
                "from": before,
                "to": status,
                "actor": actor.strip(),
                "reason": reason.strip(),
                "evidence": evidence.strip(),
                "recorded_at": stamp,
            },
        }
    )
    result["updated_at"] = stamp
    counts = Counter(value["status"] for value in result["items"])
    result["summary"]["status_counts"] = {
        value: counts.get(value, 0) for value in sorted(STATUSES)
    }
    return result


def build_alerts(
    backlog: Mapping[str, Any], *, now: datetime, today: date
) -> dict[str, Any]:
    _validated_existing(backlog)
    now_utc = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    now_utc = now_utc.astimezone(timezone.utc)
    due_soon: list[dict[str, Any]] = []
    stale_high_confidence: list[dict[str, Any]] = []
    for row in backlog["items"]:
        if row["status"] in TERMINAL_STATUSES:
            continue
        priority = row.get("priority") or {}
        days_until = priority.get("days_until_event")
        if isinstance(days_until, int) and 0 <= days_until <= 7:
            due_soon.append(
                {
                    "source_key": row["source_key"],
                    "status": row["status"],
                    "event_date": priority.get("event_date"),
                    "days_until_event": days_until,
                    "source_url": (row.get("candidate") or {}).get("source_url") or "",
                }
            )
        first_seen = _parse_datetime(row.get("first_seen_at"))
        age = now_utc - first_seen if first_seen else timedelta(0)
        if (
            (row.get("confidence") or {}).get("tier") in HIGH_CONFIDENCE_TIERS
            and age >= timedelta(hours=24)
        ):
            stale_high_confidence.append(
                {
                    "source_key": row["source_key"],
                    "status": row["status"],
                    "age_hours": round(age.total_seconds() / 3600, 1),
                    "source_url": (row.get("candidate") or {}).get("source_url") or "",
                }
            )
    missing = list((backlog.get("carryover_check") or {}).get("missing_source_keys") or [])
    alerts = {
        "schema_version": 1,
        "generated_by": "x_candidate_backlog.py",
        "generated_at": _iso(now),
        "as_of_date": today.isoformat(),
        "summary": {
            "event_within_7_days_unresolved": len(due_soon),
            "high_confidence_over_24h_unresolved": len(stale_high_confidence),
            "overflow_not_carried": len(missing),
            "critical": len(missing),
            "warning": len(due_soon) + len(stale_high_confidence),
        },
        "alerts": {
            "event_within_7_days_unresolved": due_soon,
            "high_confidence_over_24h_unresolved": stale_high_confidence,
            "overflow_not_carried": missing,
        },
    }
    return alerts


def alerts_markdown(alerts: Mapping[str, Any]) -> str:
    summary = alerts["summary"]
    lines = [
        "# X候補バックログ 日次アラート",
        "",
        f"基準日: {alerts['as_of_date']}",
        "",
        f"- 開催7日以内で未解決: {summary['event_within_7_days_unresolved']}件",
        f"- 高信頼・24時間超未解決: {summary['high_confidence_over_24h_unresolved']}件",
        f"- 上限超過候補の持ち越し欠落: {summary['overflow_not_carried']}件",
    ]
    for heading, key in (
        ("開催7日以内", "event_within_7_days_unresolved"),
        ("高信頼・24時間超", "high_confidence_over_24h_unresolved"),
    ):
        rows = alerts["alerts"][key]
        if not rows:
            continue
        lines.extend(["", f"## {heading}", ""])
        for row in rows:
            suffix = row.get("event_date") or f"{row.get('age_hours')}h"
            lines.append(
                f"- `{row['source_key']}` / {row['status']} / {suffix} / {row.get('source_url') or '-'}"
            )
    if alerts["alerts"]["overflow_not_carried"]:
        lines.extend(["", "## 持ち越し欠落", ""])
        lines.extend(f"- `{key}`" for key in alerts["alerts"]["overflow_not_carried"])
    lines.extend(["", "---", "", "おと（Codex）", ""])
    return "\n".join(lines)


def _append_github_summary(markdown: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with Path(path).open("a", encoding="utf-8") as handle:
        handle.write(markdown)
        if not markdown.endswith("\n"):
            handle.write("\n")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    merge = sub.add_parser("merge", help="merge the latest bounded queue into the backlog")
    merge.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    merge.add_argument("--backlog", type=Path, default=DEFAULT_BACKLOG)
    merge.add_argument("--alerts-json", type=Path, default=DEFAULT_ALERT_JSON)
    merge.add_argument("--alerts-md", type=Path, default=DEFAULT_ALERT_MD)
    merge.add_argument("--today", type=date.fromisoformat)
    merge.add_argument("--now", type=datetime.fromisoformat)
    merge.add_argument("--append-github-summary", action="store_true")

    transition = sub.add_parser("transition", help="record an explicit lifecycle transition")
    transition.add_argument("--backlog", type=Path, default=DEFAULT_BACKLOG)
    transition.add_argument("--source-key", required=True)
    transition.add_argument("--status", choices=sorted(STATUSES), required=True)
    transition.add_argument("--actor", required=True)
    transition.add_argument("--reason", required=True)
    transition.add_argument("--evidence", required=True)
    transition.add_argument("--now", type=datetime.fromisoformat)
    transition.add_argument("--reopen", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    now = args.now or datetime.now(timezone.utc)
    if args.command == "merge":
        today = args.today or now.date()
        payload = load_json(args.input, {})
        existing = load_json(args.backlog, None)
        backlog = build_backlog(payload, existing, now=now, today=today)
        alerts = build_alerts(backlog, now=now, today=today)
        markdown = alerts_markdown(alerts)
        _atomic_write(args.backlog, backlog)
        _atomic_write(args.alerts_json, alerts)
        _atomic_write_text(args.alerts_md, markdown)
        if args.append_github_summary:
            _append_github_summary(markdown)
        if not backlog["carryover_check"]["passed"]:
            raise BacklogError("overflow candidates were not carried into the backlog")
        print(
            "x candidate backlog: "
            f"total={backlog['summary']['total']} "
            f"unprocessed={backlog['summary']['status_counts']['unprocessed']} "
            f"overflow_carried={backlog['summary']['latest_overflow_count']}"
        )
        return 0

    backlog = load_json(args.backlog, None)
    updated = transition_status(
        backlog,
        source_key=args.source_key,
        status=args.status,
        now=now,
        actor=args.actor,
        reason=args.reason,
        evidence=args.evidence,
        reopen=args.reopen,
    )
    _atomic_write(args.backlog, updated)
    print(f"x candidate status: {args.source_key} -> {args.status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
