import json
from datetime import date, datetime, timezone

import pytest

from x_candidate_backlog import BacklogError, build_backlog, build_ingress_audit, main, select_daily_cohort


NOW = datetime(2026, 10, 3, 16, tzinfo=timezone.utc)


def backlog():
    candidates = [{
        "source_key": f"x:{index}",
        "candidate_id": f"candidate-{index}",
        "candidate_kind": "missing_date",
        "priority_score": 100 - index,
        "observed_dates": ["2026-10-04"],
        "source_officiality": {"classification": "registered_official_social"},
        "matched_occurrence": {"venue_area": "確認用区"},
    } for index in range(8)]
    return build_backlog(
        {"candidates": candidates, "archived_candidates": []}, None,
        now=datetime(2026, 10, 1, tzinfo=timezone.utc), today=date(2026, 10, 1),
    )


def test_audit_explains_existing_cohort_and_capacity_without_mutation():
    snapshot = backlog()
    original = json.dumps(snapshot, sort_keys=True)
    expected = [row["source_key"] for row in select_daily_cohort(snapshot)]
    report = build_ingress_audit(snapshot, now=NOW)
    assert [row["source_key"] for row in report["selected"]] == expected
    assert report["summary"] == {
        "status_counts": {"unprocessed": 8}, "daily_limit": 5,
        "unprocessed": 8, "selected": 5, "deferred": 3,
        "minimum_batches_without_new_arrivals": 2, "unknown_or_future_first_seen": 0,
    }
    assert report["by_explicit_area"]["確認用区"] == {"unprocessed": 8, "selected": 5, "waiting_over_24h": 8}
    assert {row["source_key"] for row in report["oldest_deferred"]} == {"x:5", "x:6", "x:7"}
    assert report["canonical_review_inbox_status_checked"] is False
    assert report["automatic_publication_enabled"] is False
    assert json.dumps(snapshot, sort_keys=True) == original


def test_unknown_geography_and_invalid_age_are_reported_without_guessing():
    snapshot = backlog()
    snapshot["items"][0]["candidate"]["matched_occurrence"] = None
    snapshot["items"][0]["candidate"]["source_text"] = "東京都中央区のお祭り"
    snapshot["items"][0]["first_seen_at"] = "broken"
    snapshot["items"][1]["first_seen_at"] = "2026-10-05T00:00:00+00:00"
    report = build_ingress_audit(snapshot, now=NOW)
    assert report["summary"]["unknown_or_future_first_seen"] == 2
    assert report["by_explicit_area"]["unknown"]["unprocessed"] == 1
    assert report["selected"][0]["wait_hours"] is None
    assert report["selected"][1]["wait_hours"] is None
    assert "中央区" not in report["by_explicit_area"]


def test_processed_states_are_counted_but_never_selected():
    snapshot = backlog()
    for index, status in enumerate(("in_progress", "registered", "rejected")):
        snapshot["items"][index]["status"] = status
    report = build_ingress_audit(snapshot, now=NOW)
    assert report["summary"]["unprocessed"] == 5
    assert report["summary"]["deferred"] == 0
    assert [row["source_key"] for row in report["selected"]] == [f"x:{index}" for index in range(3, 8)]
    assert report["summary"]["status_counts"]["in_progress"] == 1


def test_audit_cli_only_prints_and_does_not_write_snapshot_or_alerts(tmp_path, capsys):
    path = tmp_path / "backlog.json"
    original = json.dumps(backlog(), ensure_ascii=False).encode()
    path.write_bytes(original)
    assert main(["audit", "--backlog", str(path), "--now", NOW.isoformat()]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["unprocessed"] == 8
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]


def test_missing_and_malformed_audit_inputs_are_not_empty_queues(tmp_path):
    path = tmp_path / "backlog.json"
    with pytest.raises(FileNotFoundError):
        main(["audit", "--backlog", str(path)])
    path.write_text("broken")
    with pytest.raises(json.JSONDecodeError):
        main(["audit", "--backlog", str(path)])
    with pytest.raises(BacklogError):
        build_ingress_audit(None, now=NOW)
    with pytest.raises(BacklogError):
        build_ingress_audit(backlog(), now=NOW, max_items=0)
