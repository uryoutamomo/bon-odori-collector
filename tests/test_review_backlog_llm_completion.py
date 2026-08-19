import json
from pathlib import Path

from scripts.build_publication_gap_song_identity_llm_decisions import (
    GAP_TYPE,
    NEW_SONG_TARGETS,
    NOISE_TITLES,
)
from review_console.data import build_inventory, decision_overlay_auto_resolution
from review_inbox_adapters.backlog_decision_overlay import ALLOWED_DECISIONS


ROOT = Path(__file__).resolve().parents[1]


def read_json(relative: str) -> dict:
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def test_new_finite_decision_vocabularies_are_explicit():
    assert ALLOWED_DECISIONS["historical_reference_quality"] == {
        "過去実績として維持",
        "過去実績から外す",
    }
    assert ALLOWED_DECISIONS["publication_gap"] == {
        "既存曲へ統合",
        "曲名ノイズとして除外",
        "新規曲候補として維持",
        "2026年根拠なし",
        "公開同期対象",
    }
    assert ALLOWED_DECISIONS["x_gap"] == {"公式確認待ち"}
    assert all("保留" not in values for values in ALLOWED_DECISIONS.values())


def test_song_identity_judgments_partition_all_147_current_gaps():
    source = read_json("data/publication_gap_review.json")
    source_titles = {
        row["song_name"] for row in source["rows"] if row.get("gap_type") == GAP_TYPE
    }
    decisions = read_json("data/publication_gap_song_identity_llm_decisions.json")
    decision_titles = {row["raw_song_name"] for row in decisions["decisions"]}

    assert len(source_titles) == len(decision_titles) == 147
    assert source_titles == decision_titles
    assert NOISE_TITLES <= source_titles
    assert set(NEW_SONG_TARGETS) <= source_titles
    assert decisions["summary"] == {
        "total": 147,
        "既存曲へ統合": 84,
        "曲名ノイズとして除外": 55,
        "新規曲候補として維持": 8,
        "unresolved": 0,
    }
    assert all(
        row["target_catalog_match"] is not None
        for row in decisions["decisions"]
        if row["decision"] == "既存曲へ統合"
    )


def test_completion_overlays_close_exact_items_without_hiding_new_work():
    general = read_json("data/review_backlog_decision_overlay.json")
    youtube = read_json("data/review_backlog_youtube_decision_overlay.json")
    inbox_rows = read_json("data/review_inbox.json")["items"]
    inventory = build_inventory(root=ROOT, reader_mode="inbox")

    assert general["summary"]["new_current_decisions"] == 258
    assert youtube["summary"]["current_item_count"] == 274
    assert youtube["summary"]["current_exact_count"] == 274
    assert youtube["summary"]["new_current_decisions"] == 247
    assert youtube["summary"]["prior_current_decisions"] == 27
    assert general["summary"]["new_current_decisions"] + youtube["summary"]["new_current_decisions"] == 505

    inventory_by_key = {item["key"]: item for item in inventory["items"]}
    exact_rows = [
        row
        for row in inbox_rows
        if decision_overlay_auto_resolution(row, ROOT) is not None
    ]
    assert exact_rows
    for row in exact_rows:
        key = "|".join((row["inbox_id"], row["source_id"], row["source_key"]))
        assert inventory_by_key[key]["status"] == "closed"
        assert inventory_by_key[key]["auto_resolution"]["decision"] == "auto_frozen_review_decision"

    raw_by_key = {
        "|".join((row["inbox_id"], row["source_id"], row["source_key"])): row
        for row in inbox_rows
    }
    for item in inventory["items"]:
        if item["status"] == "pending":
            assert decision_overlay_auto_resolution(raw_by_key[item["key"]], ROOT) is None
