import json
from pathlib import Path

import pytest

from review_inbox_adapters.source_adapter import adapt_source_payload
from review_inbox_adapters.low_priority_adapters import (
    AcceptedVenueSongAdapter, DailySongAdapter, DailyTermAdapter,
    HistoricalQualityAdapter, PublicationGapAdapter, build_snapshot,
)
from review_inbox_adapters.backlog_decision_overlay import (
    DecisionOverlayError, apply_overlay,
)
from review_inbox_adapters.parity import item_payload_hash


ROOT = Path(__file__).resolve().parents[1]


def test_current_song_term_and_venue_pending_parity():
    for source_id in (
        "daily_song_candidate",
        "daily_term_candidate",
        "accepted_venue_song_missing_venue",
    ):
        snapshot = build_snapshot(source_id, decision_overlay_path=None)
        assert snapshot["item_count"] == len(snapshot["items"]) > 0
        assert len({item["inbox_id"] for item in snapshot["items"]}) == snapshot["item_count"]


def test_exact_decision_overlay_closes_only_the_frozen_payload():
    item = adapt_source_payload(DailyTermAdapter(), {"rows": [{"term": "輪踊り", "category": "用語", "type": "設備"}]})[0]
    snapshot = {"source_id": "daily_term_candidate", "item_count": 1, "items": [item]}
    decision = {
        "source_id": item["source_id"], "source_key": item["source_key"],
        "inbox_id": item["inbox_id"], "source_payload_hash": item_payload_hash(item),
        "decision": "採用", "actor_type": "agent", "actor_id": "おと（Codex）/Terra",
        "decided_at": "2026-08-18T00:00:00+09:00", "reason_detail": "evidence",
    }
    result = apply_overlay(snapshot, {"schema_version": 1, "decisions": [decision]})
    assert result["item_count"] == 0
    assert result["decision_overlay"]["applied_count"] == 1

    changed = dict(item)
    changed["payload"] = {**item["payload"], "evidence_text": "changed"}
    stale = apply_overlay({**snapshot, "items": [changed]}, {"schema_version": 1, "decisions": [decision]})
    assert stale["item_count"] == 1
    assert stale["decision_overlay"]["stale_count"] == 1


def test_decision_overlay_fails_closed_on_identity_or_vocabulary_errors():
    item = adapt_source_payload(DailyTermAdapter(), {"rows": [{"term": "輪踊り", "category": "用語", "type": "設備"}]})[0]
    snapshot = {"source_id": "daily_term_candidate", "item_count": 1, "items": [item]}
    base = {
        "source_id": item["source_id"], "source_key": item["source_key"],
        "inbox_id": "wrong", "source_payload_hash": item_payload_hash(item),
        "decision": "採用", "actor_type": "agent", "actor_id": "oto",
        "decided_at": "2026-08-18T00:00:00+09:00", "reason_detail": "evidence",
    }
    with pytest.raises(DecisionOverlayError, match="identity mismatch"):
        apply_overlay(snapshot, {"schema_version": 1, "decisions": [base]})
    with pytest.raises(DecisionOverlayError, match="unsupported decision"):
        apply_overlay(snapshot, {"schema_version": 1, "decisions": [{**base, "inbox_id": item["inbox_id"], "decision": "publish"}]})
    with pytest.raises(DecisionOverlayError, match="unsupported decision"):
        apply_overlay(snapshot, {"schema_version": 1, "decisions": [{**base, "inbox_id": item["inbox_id"], "decision": "保留"}]})


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


def test_publication_gap_accepts_every_action_the_builder_emits():
    """許可リストが生成側の語彙から遅れると dual-write が止まる。

    2026-07-25 の collect は build_publication_gap_review.py が出す
    review_and_apply_event_occurrence_to_master_rdb を
    PublicationGapAdapter が知らず、
    "unsupported publication gap action" で失敗していた。
    """
    import re
    from pathlib import Path

    from review_inbox_adapters.low_priority_adapters import PUBLICATION_GAP_ACTIONS

    builder = Path(__file__).resolve().parents[1] / "public_export_support" / "build_publication_gap_review.py"
    emitted = set(re.findall(r'"recommended_action":\s*"([^"]+)"', builder.read_text(encoding="utf-8")))

    assert emitted, "builder から recommended_action を読み取れていない"
    assert emitted <= PUBLICATION_GAP_ACTIONS, sorted(emitted - PUBLICATION_GAP_ACTIONS)


def test_publication_gap_adapts_rdb_apply_action():
    items = list(
        adapt_source_payload(
            PublicationGapAdapter(),
            {"rows": [{"gap_id": "g1", "term": "テスト", "recommended_action": "review_and_apply_event_occurrence_to_master_rdb"}]},
        )
    )

    assert [item["recommended_action"] for item in items] == [
        "review_and_apply_event_occurrence_to_master_rdb"
    ]
