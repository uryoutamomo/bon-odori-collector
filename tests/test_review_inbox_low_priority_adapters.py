import json
from pathlib import Path

import pytest

from review_inbox_source_adapter import adapt_source_payload
from review_inbox_low_priority_adapters import (
    AcceptedVenueSongAdapter, DailySongAdapter, DailyTermAdapter,
    HistoricalQualityAdapter, PublicationGapAdapter, build_snapshot,
)


ROOT = Path(__file__).resolve().parents[1]


def test_current_song_term_and_venue_pending_parity():
    for source_id in (
        "daily_song_candidate",
        "daily_term_candidate",
        "accepted_venue_song_missing_venue",
    ):
        snapshot = build_snapshot(source_id)
        assert snapshot["item_count"] == len(snapshot["items"]) > 0
        assert len({item["inbox_id"] for item in snapshot["items"]}) == snapshot["item_count"]


def test_venue_rows_with_the_same_semantic_identity_are_merged():
    rows = [
        {"term": "曲A", "suggested_venue": "日枝神社", "evidence_url": "https://example.com/a"},
        {"term": "曲B", "suggested_venue": "日枝神社", "evidence_url": "https://example.com/b"},
    ]
    items = adapt_source_payload(AcceptedVenueSongAdapter(), {"rows": rows})
    assert len(items) == 1
    assert len(items[0]["payload"]["source_rows"]) == 2


def test_semantic_identity_ignores_mutable_evidence_url():
    payload={"rows":[{"term":"盆ジョビ","canonical_song_name":"盆ジョビ","evidence_url":"https://x.com/a"}]}
    before=adapt_source_payload(DailySongAdapter(),payload)[0]
    payload["rows"][0]["evidence_url"]="https://x.com/b"
    after=adapt_source_payload(DailySongAdapter(),payload)[0]
    assert before["inbox_id"] == after["inbox_id"]


def test_cooccurrence_and_plain_term_use_finite_routes():
    payload={"rows":[{"term":"曲 × 会場","song_name":"曲","venue":"会場"},{"term":"やぐら","category":"用語","type":"設備"}]}
    items=adapt_source_payload(DailyTermAdapter(),payload)
    assert [item["kind"] for item in items] == ["song_research","term"]
    assert [item["recommended_action"] for item in items] == ["stage_song_venue_evidence","stage_term_candidate"]


def test_venue_quality_and_gap_routes_are_bounded():
    venue=adapt_source_payload(AcceptedVenueSongAdapter(),{"rows":[{"suggested_venue":"公園"}]})[0]
    quality=adapt_source_payload(HistoricalQualityAdapter(),{"review":[{"quality_review_id":"q1","event_name":"祭り","issue_codes":["historical_songs_missing"]}]})[0]
    gap=adapt_source_payload(PublicationGapAdapter(),{"rows":[{"gap_id":"g1","term":"差分","recommended_action":"needs_research"}]})[0]
    assert (venue["kind"],venue["recommended_action"]) == ("venue_candidate","stage_venue_candidate")
    assert quality["recommended_action"] == "needs_song_research"
    assert gap["recommended_action"] == "needs_research"


def test_partial_decisions_unknown_quality_and_gap_fail_closed():
    with pytest.raises(ValueError,match="partial"):
        adapt_source_payload(DailySongAdapter(),{"rows":[{"term":"曲","decision":"accept"}]})
    with pytest.raises(ValueError,match="unsupported decided"):
        adapt_source_payload(DailySongAdapter(),{"rows":[{"term":"曲","decision":"publish","decided_by":"x","decided_at":"now"}]})
    with pytest.raises(ValueError,match="unsupported historical quality issue"):
        adapt_source_payload(HistoricalQualityAdapter(),{"review":[{"quality_review_id":"q","issue_codes":["mystery"]}]})
    with pytest.raises(ValueError,match="unsupported publication gap action"):
        adapt_source_payload(PublicationGapAdapter(),{"rows":[{"gap_id":"g","recommended_action":"publish"}]})
