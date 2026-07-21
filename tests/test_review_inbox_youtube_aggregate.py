import copy
import json
import tempfile
from pathlib import Path

import pytest

from review_inbox_adapters.source_adapter import adapt_source_payload
from review_inbox_adapters.youtube_adapter import YouTubeActiveVideoAdapter
from review_inbox_adapters.youtube_aggregate import (
    PRECEDENCE,
    QUEUE_ORDER,
    build_aggregate_snapshot,
    composite_sha256,
    require_complete_aggregate,
)
from review_inbox_adapters.youtube_user_confirmation_adapter import YouTubeUserConfirmationAdapter
from review_inbox_adapters.youtube_year_backfill_adapter import YouTubeYearBackfillAdapter


def snapshot(adapter, payload, path):
    raw = json.dumps(payload, sort_keys=True).encode()
    items = adapt_source_payload(adapter, payload)
    import hashlib
    return {"source_id":"youtube_evidence","input_path":str(path),"input_sha256":hashlib.sha256(raw).hexdigest(),"input_size_bytes":len(raw),"item_count":len(items),"items":items,"selection":{"mode":"all","source_keys":[item["source_key"] for item in items]}}


def builders(active_payload, year_payload, user_payload):
    return {
        "active_builder": lambda path: snapshot(YouTubeActiveVideoAdapter({}), active_payload, path),
        "year_builder": lambda path: snapshot(YouTubeYearBackfillAdapter(), year_payload, path),
        "user_builder": lambda path: snapshot(YouTubeUserConfirmationAdapter(), user_payload, path),
    }


def test_real_aggregate_has_all_lineage_and_current_pending_set():
    root = Path(__file__).resolve().parents[1]
    result = build_aggregate_snapshot(
        root / "data/youtube_active_video_review.json",
        root / "data/youtube_year_backfill_review_queue.json",
        root / "data/youtube_user_confirmation_queue.json",
    )
    require_complete_aggregate(result)
    assert result["source_id"] == "youtube_evidence"
    assert result["item_count"] == sum(entry["item_count"] for entry in result["input_lineage"])
    assert [entry["queue"] for entry in result["input_lineage"]] == list(QUEUE_ORDER)
    assert result["aggregate"]["duplicate_count"] == 0


def test_duplicate_precedence_is_user_then_year_then_active_and_is_audited():
    active = {"rows":[{"action":"review_video_evidence","video_id":"same","video_url":"https://youtu.be/same","detected_event_date":"2025-01-01","title":"Active"}]}
    year = {"groups":[{"candidate_action":"merge_to_existing_candidate","event_name":"Year","target_year":2025,"videos":[{"url":"https://youtu.be/same","title":"Year"}]}]}
    user = {"items":[{"id":"user_2025","label":"User","video_url":"https://youtu.be/same","detected_event_date":"2025-01-01","recommended_decision":"exclude","options":["exclude"]}]}
    result = build_aggregate_snapshot(Path("active"), Path("year"), Path("user"), **builders(active, year, user))
    assert PRECEDENCE == ("user_confirmation", "year_backfill", "active_video")
    assert result["item_count"] == 1
    assert result["items"][0]["title"] == "User"
    resolution = result["aggregate"]["duplicate_resolutions"][0]
    assert resolution["selected_queue"] == "user_confirmation"
    assert [row["queue"] for row in resolution["dropped"]] == ["active_video", "year_backfill"]


def test_incomplete_or_mutated_aggregate_fails_closed():
    entries = [{"queue":queue,"path":queue,"sha256":"0"*64,"size_bytes":0,"item_count":0,"supporting_inputs":[]} for queue in QUEUE_ORDER]
    complete = {"source_id":"youtube_evidence","selection":{"mode":"all","source_keys":[]},"input_sha256":composite_sha256(entries),"input_size_bytes":0,"item_count":0,"items":[],"aggregate":{"complete":True,"schema_version":1,"required_queues":list(QUEUE_ORDER),"precedence_high_to_low":list(PRECEDENCE)},"input_lineage":entries}
    require_complete_aggregate(complete)
    for mutation in (
        {"aggregate":{}},
        {**copy.deepcopy(complete), "input_lineage": complete["input_lineage"][:-1]},
        {**copy.deepcopy(complete), "aggregate": {**complete["aggregate"], "precedence_high_to_low": list(QUEUE_ORDER)}},
        {**copy.deepcopy(complete), "input_sha256": "f" * 64},
    ):
        with pytest.raises(ValueError):
            require_complete_aggregate(mutation)


def test_wrong_source_or_partial_selection_is_rejected():
    empty = {"rows":[]}
    values = builders(empty, {"groups":[]}, {"items":[]})
    bad_source = values["active_builder"]
    values["active_builder"] = lambda path: {**bad_source(path), "source_id":"other"}
    with pytest.raises(ValueError, match="wrong source_id"):
        build_aggregate_snapshot(Path("a"), Path("y"), Path("u"), **values)
