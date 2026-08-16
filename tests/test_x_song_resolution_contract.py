import json

import pytest

from master_rdb.master_db import init_db
from review_inbox_adapters.x_song_resolution_contract import (
    apply_results,
    build_packet_set,
    catalog_snapshot,
    load_packet_sets,
    sha256_json,
    validate_packet_set,
)


NOW = "2026-08-16T00:00:00+00:00"
MODEL = "test-model"
PROMPT_SHA = "1" * 64


def observation(**overrides):
    value = {
        "observation_schema_version": 2,
        "observation_id": "xsong2_1",
        "claim_family_id": "xsclaim_1",
        "tweet_id": "tweet_1",
        "url": "https://x.example/tweet_1",
        "posted_at": "2026-08-15T12:00:00+09:00",
        "account": "@official",
        "officiality": "registered_official_social",
        "event_name": "試験盆踊り",
        "event_name_in_text": True,
        "event_report_verified": True,
        "song_name": "東京音頭",
        "claim_type": "announced",
        "evidence_quote": "曲目は東京音頭です",
        "origin": "events",
        "event_date_start": "2026-08-20",
        "event_date_end": "2026-08-20",
        "event_venue_name": "試験公園",
        "event_ward": "足立区",
        "event_quote": "試験公園で試験盆踊りを開催",
        "event_context_valid": True,
        "event_report_id": "xevr_1",
        "report_event_id": "xevt_1",
        "event_dependency_key": "event-family-1",
        "claim_type_conflict": False,
        "batch_id": "batch_1",
        "score": 5,
        "text": "試験公園で試験盆踊りを開催。曲目は東京音頭です",
        "first_seen_at": NOW,
    }
    value.update(overrides)
    return value


def seed_songs(conn):
    for song_id, title, status in [
        ("song_tokyo", "東京音頭", "active"),
        ("song_daitokyo", "大東京音頭", "有効"),
        ("song_candidate", "東京ニュー音頭", "候補"),
        ("song_rejected", "大人の部", "無効"),
    ]:
        conn.execute(
            """
            INSERT INTO songs (
              song_id, canonical_title, normalized_title, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (song_id, title, title, status, NOW, NOW),
        )
    conn.execute(
        """
        INSERT INTO song_aliases (song_id, alias, normalized_alias, source)
        VALUES ('song_tokyo', 'Tokyo Ondo', 'tokyoondo', 'test')
        """
    )


def make_db(tmp_path):
    conn = init_db(tmp_path / "master.sqlite")
    seed_songs(conn)
    conn.commit()
    return conn


def result_for(packet, action, selected_song_id=None, **extra):
    value = {
        "packet_id": packet["packet_id"],
        "action": action,
        "selected_song_id": selected_song_id,
        "reason_code": "reviewed",
    }
    value.update(extra)
    return {"schema": "x_song_resolution_results_v2", "results": [value]}


def entries(packet_set):
    return {
        packet["packet_id"]: {"packet": packet, "packet_set": packet_set}
        for packet in packet_set["packets"]
    }


def test_retrieval_packet_freezes_full_candidate_rows_and_forbids_new_song(tmp_path):
    conn = make_db(tmp_path)
    packet_set = build_packet_set(
        conn, {"observations": [observation()]}, phase="retrieval", generated_at=NOW
    )
    packet = packet_set["packets"][0]

    assert packet["allowed_actions"] == ["match_song", "candidate_missing", "unresolved"]
    assert "new_song" not in packet["allowed_actions"]
    assert packet["candidate_rows"][0]["song_id"] == "song_tokyo"
    assert packet["candidate_rows"][0]["aliases"][0]["alias"] == "Tokyo Ondo"
    assert packet["candidate_set_sha256"] == sha256_json(packet["candidate_rows"])
    assert packet["catalog_snapshot_sha256"] == sha256_json(packet_set["catalog_snapshot"])
    validate_packet_set(packet_set)


def test_non_fact_conflict_legacy_and_eventless_observations_are_excluded(tmp_path):
    conn = make_db(tmp_path)
    ledger = {
        "observations": [
            observation(observation_id="unknown", claim_type="unknown"),
            observation(observation_id="conflict", claim_type_conflict=True),
            observation(observation_id="legacy", observation_schema_version=1),
            observation(
                observation_id="eventless",
                event_name=None,
                event_name_in_text=True,
                event_context_valid=True,
            ),
        ]
    }
    packet_set = build_packet_set(conn, ledger, phase="retrieval", generated_at=NOW)
    assert packet_set["packets"] == []
    assert {row["reason"] for row in packet_set["excluded"]} == {
        "non_fact_claim", "claim_type_conflict", "legacy_observation",
        "insufficient_event_identity",
    }


def test_candidate_missing_must_be_recorded_before_novelty_packet(tmp_path):
    conn = make_db(tmp_path)
    ledger = {"observations": [observation()]}
    assert build_packet_set(conn, ledger, phase="novelty", generated_at=NOW)["packets"] == []

    retrieval = build_packet_set(conn, ledger, phase="retrieval", generated_at=NOW)
    packet = retrieval["packets"][0]
    report = apply_results(
        conn,
        ledger,
        entries(retrieval),
        result_for(packet, "candidate_missing"),
        actor_id="oto-local",
        model_id=MODEL,
        prompt_sha256=PROMPT_SHA,
        decided_at=NOW,
    )
    assert report == {"applied": 1, "no_op": 0, "result_count": 1}

    novelty = build_packet_set(conn, ledger, phase="novelty", generated_at=NOW)
    novelty_packet = novelty["packets"][0]
    assert novelty_packet["depends_on_decision_id"]
    assert novelty_packet["allowed_actions"] == ["match_song", "new_song", "unresolved"]
    assert novelty_packet["candidate_rows"] == catalog_snapshot(conn)


def test_apply_is_ledger_only_uses_local_actor_and_exact_retry_is_noop(tmp_path):
    conn = make_db(tmp_path)
    ledger = {"observations": [observation()]}
    packet_set = build_packet_set(conn, ledger, phase="retrieval", generated_at=NOW)
    packet = packet_set["packets"][0]
    payload = result_for(
        packet,
        "match_song",
        "song_tokyo",
        actor_id="untrusted",
        model_id="untrusted-model",
        prompt_sha256="f" * 64,
    )
    before_songs = conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0]

    first = apply_results(
        conn, ledger, entries(packet_set), payload, actor_id="oto-local",
        model_id=MODEL, prompt_sha256=PROMPT_SHA, decided_at=NOW
    )
    second = apply_results(
        conn, ledger, entries(packet_set), payload, actor_id="oto-local",
        model_id=MODEL, prompt_sha256=PROMPT_SHA, decided_at=NOW
    )

    assert first["applied"] == 1
    assert second["no_op"] == 1
    row = conn.execute(
        "SELECT actor_id, model_id, prompt_sha256, action, selected_song_id "
        "FROM x_song_resolution_decisions"
    ).fetchone()
    assert tuple(row) == ("oto-local", MODEL, PROMPT_SHA, "match_song", "song_tokyo")
    assert conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0] == before_songs
    assert conn.execute("SELECT COUNT(*) FROM occurrence_songs").fetchone()[0] == 0


def test_current_snapshot_decision_is_not_packetized_again(tmp_path):
    conn = make_db(tmp_path)
    ledger = {"observations": [observation()]}
    packet_set = build_packet_set(conn, ledger, phase="retrieval", generated_at=NOW)
    packet = packet_set["packets"][0]
    apply_results(
        conn,
        ledger,
        entries(packet_set),
        result_for(packet, "unresolved"),
        actor_id="oto-local",
        model_id=MODEL,
        prompt_sha256=PROMPT_SHA,
        decided_at=NOW,
    )

    unchanged = build_packet_set(conn, ledger, phase="retrieval", generated_at=NOW)
    assert unchanged["packets"] == []
    assert unchanged["excluded"] == [{
        "observation_id": "xsong2_1",
        "reason": "already_decided_current_snapshot",
    }]

    conn.execute(
        """
        INSERT INTO songs (
          song_id, canonical_title, normalized_title, status, created_at, updated_at
        ) VALUES ('song_new_context', '新しい音頭', '新しい音頭', '候補', ?, ?)
        """,
        (NOW, NOW),
    )
    changed = build_packet_set(conn, ledger, phase="retrieval", generated_at=NOW)
    assert len(changed["packets"]) == 1
    assert changed["packets"][0]["packet_id"] != packet["packet_id"]


def test_resolved_song_is_not_reopened_by_unrelated_catalog_change(tmp_path):
    conn = make_db(tmp_path)
    ledger = {"observations": [observation()]}
    packet_set = build_packet_set(conn, ledger, phase="retrieval", generated_at=NOW)
    packet = packet_set["packets"][0]
    apply_results(
        conn,
        ledger,
        entries(packet_set),
        result_for(packet, "match_song", "song_tokyo"),
        actor_id="oto-local",
        model_id=MODEL,
        prompt_sha256=PROMPT_SHA,
        decided_at=NOW,
    )
    conn.execute(
        """
        INSERT INTO songs (
          song_id, canonical_title, normalized_title, status, created_at, updated_at
        ) VALUES ('song_unrelated', '無関係音頭', '無関係音頭', '候補', ?, ?)
        """,
        (NOW, NOW),
    )

    packet_set = build_packet_set(conn, ledger, phase="retrieval", generated_at=NOW)
    assert packet_set["packets"] == []
    assert packet_set["excluded"] == [{
        "observation_id": "xsong2_1",
        "reason": "identity_already_resolved",
    }]


def test_apply_rejects_tampered_packet_stale_catalog_and_unoffered_selection(tmp_path):
    conn = make_db(tmp_path)
    ledger = {"observations": [observation()]}
    packet_set = build_packet_set(conn, ledger, phase="retrieval", generated_at=NOW, limit=1)
    packet = packet_set["packets"][0]

    tampered = json.loads(json.dumps(packet_set))
    tampered["packets"][0]["candidate_rows"][0]["canonical_title"] = "改ざん"
    with pytest.raises(ValueError, match="packet hash mismatch|candidate set hash mismatch"):
        validate_packet_set(tampered)

    with pytest.raises(ValueError, match="frozen candidate set"):
        apply_results(
            conn,
            ledger,
            entries(packet_set),
            result_for(packet, "match_song", "song_daitokyo"),
            actor_id="oto-local",
            model_id=MODEL,
            prompt_sha256=PROMPT_SHA,
            decided_at=NOW,
        )

    conn.execute("UPDATE songs SET status='無効' WHERE song_id='song_tokyo'")
    conn.commit()
    with pytest.raises(ValueError, match="stale song catalog"):
        apply_results(
            conn,
            ledger,
            entries(packet_set),
            result_for(packet, "candidate_missing"),
            actor_id="oto-local",
            model_id=MODEL,
            prompt_sha256=PROMPT_SHA,
            decided_at=NOW,
        )


def test_duplicate_packet_id_across_files_is_rejected(tmp_path):
    conn = make_db(tmp_path)
    packet_set = build_packet_set(
        conn, {"observations": [observation()]}, phase="retrieval", generated_at=NOW
    )
    paths = [tmp_path / "a.json", tmp_path / "b.json"]
    for path in paths:
        path.write_text(json.dumps(packet_set, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValueError, match="across input files"):
        load_packet_sets(paths)
