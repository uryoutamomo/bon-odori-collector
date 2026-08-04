import pytest

from review_inbox_adapters.source_writer import SourceWriterError
from song_candidate_finite_actions import (
    GENERATOR_NAME,
    build_reviewed_payload_from_domain_stage,
    validate_reviewed_payload,
)


def decision(**overrides):
    base = {
        "source_inbox_id": "inbox_song_1",
        "source_id": "daily_song_candidate",
        "source_key": "song_candidate|x-status:1",
        "candidate_title": "炭坑節",
        "action": "register_song",
        "reviewed_by": "内田さん",
        "reviewed_at": "2026-08-05T09:00:00+09:00",
        "source_url": "",
        "note": "",
    }
    base.update(overrides)
    return base


def payload(*decisions, write_mode="reviewed_finite_actions", schema_version=1, generated_by=GENERATOR_NAME):
    rows = list(decisions) or [decision()]
    return {
        "schema_version": schema_version,
        "generated_by": generated_by,
        "write_mode": write_mode,
        "decision_count": len(rows),
        "decisions": rows,
    }


def test_validate_accepts_all_four_finite_actions():
    rows = [
        decision(source_inbox_id="i1", action="register_song"),
        decision(source_inbox_id="i2", action="add_song_alias", target_song_id="song_abc"),
        decision(source_inbox_id="i3", action="reject_song"),
        decision(source_inbox_id="i4", action="hold"),
    ]
    decisions = validate_reviewed_payload(payload(*rows))
    assert [d.action for d in decisions] == ["register_song", "add_song_alias", "reject_song", "hold"]
    assert decisions[1].target_song_id == "song_abc"
    assert decisions[0].target_song_id is None


def test_add_song_alias_requires_target_song_id():
    with pytest.raises(SourceWriterError, match="requires target_song_id"):
        validate_reviewed_payload(payload(decision(action="add_song_alias")))


def test_target_song_id_forbidden_outside_add_song_alias():
    with pytest.raises(SourceWriterError, match="only valid for add_song_alias"):
        validate_reviewed_payload(payload(decision(action="register_song", target_song_id="song_abc")))


def test_unknown_field_is_rejected():
    row = decision()
    row["extra_field"] = "surprise"
    with pytest.raises(SourceWriterError, match="unknown field"):
        validate_reviewed_payload(payload(row))


def test_unknown_action_is_rejected():
    with pytest.raises(SourceWriterError, match="unsupported action"):
        validate_reviewed_payload(payload(decision(action="delete_song")))


def test_empty_title_is_rejected():
    with pytest.raises(SourceWriterError, match="candidate_title"):
        validate_reviewed_payload(payload(decision(candidate_title="")))


def test_partial_review_metadata_is_rejected():
    with pytest.raises(SourceWriterError, match="reviewed_by"):
        validate_reviewed_payload(payload(decision(reviewed_by="")))


def test_reviewed_at_requires_timezone():
    with pytest.raises(SourceWriterError, match="timezone"):
        validate_reviewed_payload(payload(decision(reviewed_at="2026-08-05T09:00:00")))


def test_duplicate_source_inbox_id_is_rejected():
    rows = [decision(source_inbox_id="dup"), decision(source_inbox_id="dup")]
    with pytest.raises(SourceWriterError, match="duplicate"):
        validate_reviewed_payload(payload(*rows))


def test_decision_count_mismatch_is_rejected():
    bad = payload(decision())
    bad["decision_count"] = 2
    with pytest.raises(SourceWriterError, match="decision_count"):
        validate_reviewed_payload(bad)


def test_unknown_top_level_field_is_rejected():
    bad = payload()
    bad["extra_top_level_field"] = "surprise"
    with pytest.raises(SourceWriterError, match="unknown top-level field"):
        validate_reviewed_payload(bad)


def test_untrusted_generator_is_rejected():
    bad = payload(generated_by="some_other_script.py")
    with pytest.raises(SourceWriterError, match="not trusted"):
        validate_reviewed_payload(bad)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", 2),
        ("write_mode", "staged_only"),
        ("write_mode", "accept"),
    ],
)
def test_generic_stage_or_accept_packets_are_not_trusted(field, value):
    bad = payload()
    bad[field] = value
    with pytest.raises(SourceWriterError):
        validate_reviewed_payload(bad)


def test_builder_defaults_to_hold_and_never_infers_register():
    rows = [
        {
            "domain_stage_type": "song_candidate",
            "domain_candidate": {
                "source_inbox_id": "inbox_song_a",
                "source_id": "daily_song_candidate",
                "source_key": "song_candidate|a",
                "kind": "song",
                "payload": {"canonical_song_name": "河内音頭"},
            },
        }
    ]
    built = build_reviewed_payload_from_domain_stage(
        rows,
        reviewed_by="内田さん",
        reviewed_at="2026-08-05T09:00:00+09:00",
    )
    assert built["decisions"][0]["action"] == "hold"
    assert built["write_mode"] == "reviewed_finite_actions"
    validate_reviewed_payload(built)


def test_builder_stamps_its_own_generator_name():
    rows = [
        {
            "domain_stage_type": "song_candidate",
            "domain_candidate": {
                "source_inbox_id": "inbox_song_z",
                "source_id": "daily_song_candidate",
                "source_key": "song_candidate|z",
                "kind": "song",
                "payload": {"canonical_song_name": "花笠音頭"},
            },
        }
    ]
    built = build_reviewed_payload_from_domain_stage(
        rows,
        reviewed_by="内田さん",
        reviewed_at="2026-08-05T09:00:00+09:00",
    )
    assert built["generated_by"] == GENERATOR_NAME


def test_builder_prefers_evidence_url_over_source_url_field():
    # review_inbox_adapters/low_priority_adapters.py common_item() puts the
    # real evidence link on the payload as evidence_url, not source_url.
    rows = [
        {
            "domain_stage_type": "song_candidate",
            "domain_candidate": {
                "source_inbox_id": "inbox_song_e",
                "source_id": "daily_song_candidate",
                "source_key": "song_candidate|e",
                "kind": "song",
                "payload": {
                    "canonical_song_name": "秋田音頭",
                    "evidence_url": "https://example.com/evidence",
                    "source_url": "https://example.com/ignored",
                },
            },
        }
    ]
    built = build_reviewed_payload_from_domain_stage(
        rows,
        reviewed_by="内田さん",
        reviewed_at="2026-08-05T09:00:00+09:00",
    )
    assert built["decisions"][0]["source_url"] == "https://example.com/evidence"


def test_builder_only_applies_explicitly_supplied_actions():
    rows = [
        {
            "domain_stage_type": "song_candidate",
            "domain_candidate": {
                "source_inbox_id": "inbox_song_b",
                "source_id": "daily_song_candidate",
                "source_key": "song_candidate|b",
                "kind": "song",
                "payload": {"canonical_song_name": "東京音頭"},
            },
        }
    ]
    built = build_reviewed_payload_from_domain_stage(
        rows,
        reviewed_by="内田さん",
        reviewed_at="2026-08-05T09:00:00+09:00",
        actions_by_source_inbox_id={"inbox_song_b": "register_song"},
    )
    assert built["decisions"][0]["action"] == "register_song"


def test_builder_skips_rows_that_are_not_song_candidate_domain_stage():
    rows = [
        {"domain_stage_type": "venue_candidate", "domain_candidate": {"kind": "venue"}},
        {
            "domain_stage_type": "song_candidate",
            "domain_candidate": {
                "source_inbox_id": "inbox_song_c",
                "source_id": "daily_song_candidate",
                "source_key": "song_candidate|c",
                "kind": "song",
                "payload": {"term": "阿波踊り"},
            },
        },
    ]
    built = build_reviewed_payload_from_domain_stage(
        rows,
        reviewed_by="内田さん",
        reviewed_at="2026-08-05T09:00:00+09:00",
    )
    assert built["decision_count"] == 1
    assert built["decisions"][0]["source_inbox_id"] == "inbox_song_c"
    assert built["decisions"][0]["candidate_title"] == "阿波踊り"
