import json
from datetime import date, datetime, timezone

import pytest

from review_inbox_adapters.x_gap_adapter import build_daily_cohort_snapshot
from x_candidate_backlog import (
    BacklogError,
    build_alerts,
    build_backlog,
    mark_in_progress,
    select_daily_cohort,
    transition_status,
)


NOW = datetime(2026, 8, 18, 0, 0, tzinfo=timezone.utc)
TODAY = date(2026, 8, 18)


def candidate(
    index: int,
    *,
    event_date: str = "2026-08-25",
    official: bool = False,
    matched: bool = False,
) -> dict:
    return {
        "candidate_id": f"candidate-{index}",
        "source_key": f"x:{index}",
        "candidate_kind": "missing_date" if matched else "official_new_event",
        "priority_score": 100 - index,
        "event_year": 2026,
        "observed_dates": [event_date],
        "source_url": f"https://x.com/example/status/{index}",
        "source_text": f"試験盆踊り {event_date} 試験公園",
        "source_officiality": {
            "classification": (
                "registered_official_social" if official else "unknown_or_personal_social"
            )
        },
        "matched_occurrence": (
            {
                "occurrence_id": f"occ-{index}",
                "event_name": "試験盆踊り",
                "venue": "試験公園",
            }
            if matched
            else None
        ),
        "voice": {"has_media": True},
    }


def payload(selected: list[dict], overflow: list[dict]) -> dict:
    return {
        "generated_at": NOW.isoformat(),
        "candidates": selected,
        "archived_candidates": overflow,
    }


def test_overflow_is_persisted_and_terminal_lifecycle_survives_next_merge():
    rows = [candidate(index) for index in range(8)]
    first = build_backlog(payload(rows[:3], rows[3:]), None, now=NOW, today=TODAY)
    assert first["summary"]["total"] == 8
    assert first["summary"]["latest_overflow_count"] == 5
    assert first["carryover_check"]["passed"] is True

    rejected = transition_status(
        first,
        source_key="x:4",
        status="rejected",
        now=NOW,
        actor="おと（Codex）",
        reason="対象地域外",
        evidence="daily-review-20260818.json",
    )
    second = build_backlog(
        payload([rows[0]], []),
        rejected,
        now=datetime(2026, 8, 19, tzinfo=timezone.utc),
        today=date(2026, 8, 19),
    )
    by_key = {row["source_key"]: row for row in second["items"]}
    assert len(by_key) == 8
    assert by_key["x:4"]["status"] == "rejected"
    assert by_key["x:4"]["present_in_latest"] is False
    assert by_key["x:4"]["priority"]["days_until_event"] == 6


def test_due_soon_and_official_candidates_are_prioritized_then_selected_five():
    rows = [candidate(index, event_date=f"2026-09-{10 + index:02d}") for index in range(6)]
    rows.append(candidate(99, event_date="2026-08-20", official=True, matched=True))
    backlog = build_backlog(payload(rows, []), None, now=NOW, today=TODAY)
    selected = select_daily_cohort(backlog, max_items=5)
    assert len(selected) == 5
    assert selected[0]["source_key"] == "x:99"
    assert selected[0]["confidence"]["tier"] == "high_existing_official"
    assert selected[0]["confidence"]["automatic_publication_enabled"] is False


def test_daily_snapshot_is_an_explicit_partial_cohort_and_queueing_is_post_write(tmp_path):
    rows = [candidate(index) for index in range(7)]
    backlog = build_backlog(payload(rows, []), None, now=NOW, today=TODAY)
    backlog_path = tmp_path / "backlog.json"
    backlog_path.write_text(json.dumps(backlog, ensure_ascii=False), encoding="utf-8")

    snapshot = build_daily_cohort_snapshot(backlog_path, max_items=5)
    assert snapshot["item_count"] == 5
    assert snapshot["selection"]["mode"] == "cohort"
    assert snapshot["selection"]["cohort"] == "daily_canary"
    assert {row["status"] for row in backlog["items"]} == {"unprocessed"}

    queued = mark_in_progress(
        backlog,
        snapshot["items"],
        now=NOW,
        observation_id="github-1-1",
    )
    status_counts = queued["summary"]["status_counts"]
    assert status_counts["in_progress"] == 5
    assert status_counts["unprocessed"] == 2


def test_alerts_cover_due_high_confidence_and_carryover_failure():
    row = candidate(1, event_date="2026-08-20", official=True)
    old = datetime(2026, 8, 16, tzinfo=timezone.utc)
    backlog = build_backlog(payload([], [row]), None, now=old, today=date(2026, 8, 16))
    backlog["carryover_check"] = {
        "passed": False,
        "missing_source_keys": ["x:lost"],
    }
    alerts = build_alerts(backlog, now=NOW, today=TODAY)
    assert alerts["summary"] == {
        "event_within_7_days_unresolved": 1,
        "high_confidence_over_24h_unresolved": 1,
        "overflow_not_carried": 1,
        "critical": 1,
        "warning": 2,
    }


def test_terminal_status_requires_explicit_reopen_and_transition_evidence():
    backlog = build_backlog(payload([candidate(1)], []), None, now=NOW, today=TODAY)
    rejected = transition_status(
        backlog,
        source_key="x:1",
        status="rejected",
        now=NOW,
        actor="おと（Codex）",
        reason="重複",
        evidence="review.json",
    )
    with pytest.raises(BacklogError, match="unsupported X candidate transition"):
        transition_status(
            rejected,
            source_key="x:1",
            status="unprocessed",
            now=NOW,
            actor="おと（Codex）",
            reason="再調査",
            evidence="review-2.json",
        )
    reopened = transition_status(
        rejected,
        source_key="x:1",
        status="unprocessed",
        now=NOW,
        actor="おと（Codex）",
        reason="根拠更新",
        evidence="review-2.json",
        reopen=True,
    )
    assert reopened["items"][0]["status"] == "unprocessed"
