import pytest

from review_inbox_adapters.source_writer import SourceWriterError
from song_candidate_finite_actions import (
    GENERATOR_NAME,
    build_reviewed_payload_from_decision_stage,
    build_reviewed_payload_from_domain_stage,
    validate_reviewed_payload,
)


def staged_song_row(action="register_song", **overrides):
    expected = {
        "register_song": ("accepted", "domain_stage"),
        "add_song_alias": ("accepted", "domain_stage"),
        "reject_song": ("rejected", "no_apply"),
        "hold": ("hold", "no_apply"),
    }[action]
    candidate = {
        "source_inbox_id": f"inbox_{action}",
        "source_id": "daily_song_candidate",
        "source_key": f"song:{action}",
        "source_url": f"https://example.com/{action}",
        "kind": "song",
        "finite_action": action,
        "target_song_id": "song_existing" if action == "add_song_alias" else None,
        "payload": {"canonical_song_name": f"{action}曲"},
        "write_mode": "reviewed_finite_action",
    }
    candidate.update(overrides.pop("candidate_overrides", {}))
    row = {
        "domain_stage_type": "song_candidate",
        "note": "画面で確認",
        "inbox_update": {
            "inbox_id": candidate["source_inbox_id"],
            "decision": expected[0],
            "decided_by": "内田さん",
            "decided_at": "2026-08-05T09:00:00+09:00",
            "decision_route": expected[1],
        },
        "domain_candidate": candidate,
    }
    row.update(overrides)
    return row


def staged_payload(*rows, generated_by="review_inbox_decision_stage.py", write_mode="reviewed_song_finite_actions"):
    values = list(rows) or [staged_song_row()]
    return {
        "schema_version": 1,
        "generated_by": generated_by,
        "source_id": "review_inbox",
        "write_mode": write_mode,
        "decision_count": len(values),
        "rows": values,
    }


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


def test_builder_preserves_explicit_empty_candidate_source_url():
    rows = [
        {
            "domain_stage_type": "song_candidate",
            "domain_candidate": {
                "source_inbox_id": "inbox_song_empty_url",
                "source_id": "daily_song_candidate",
                "source_key": "song_candidate|empty-url",
                "source_url": "",
                "kind": "song",
                "payload": {
                    "canonical_song_name": "秋田音頭",
                    "evidence_url": "https://example.com/evidence",
                },
            },
        }
    ]
    built = build_reviewed_payload_from_domain_stage(
        rows,
        reviewed_by="内田さん",
        reviewed_at="2026-08-05T09:00:00+09:00",
    )
    assert built["decisions"][0]["source_url"] == ""


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


def test_decision_stage_builder_preserves_actionable_actions_and_lifecycle():
    built = build_reviewed_payload_from_decision_stage(
        staged_payload(
            staged_song_row("register_song"),
            staged_song_row("add_song_alias"),
            staged_song_row("reject_song"),
        )
    )

    assert [row["action"] for row in built["decisions"]] == [
        "register_song",
        "add_song_alias",
        "reject_song",
    ]
    assert built["decisions"][1]["target_song_id"] == "song_existing"
    assert built["decisions"][0]["reviewed_by"] == "内田さん"
    assert built["decisions"][0]["source_url"] == "https://example.com/register_song"
    assert built["decisions"][0]["note"] == "画面で確認"


def test_decision_stage_builder_rejects_hold_in_p4_action_packet():
    with pytest.raises(SourceWriterError, match="must remain pending"):
        build_reviewed_payload_from_decision_stage(
            staged_payload(staged_song_row("hold"))
        )


def test_decision_stage_builder_rejects_lifecycle_mismatch():
    row = staged_song_row("reject_song")
    row["inbox_update"]["decision"] = "accepted"
    with pytest.raises(SourceWriterError, match="lifecycle mismatch"):
        build_reviewed_payload_from_decision_stage(staged_payload(row))


@pytest.mark.parametrize(
    "overrides,match",
    [
        ({"generated_by": "manual.json"}, "generated_by"),
        ({"write_mode": "staged_only"}, "write_mode"),
    ],
)
def test_decision_stage_builder_rejects_untrusted_envelopes(overrides, match):
    stage = staged_payload()
    stage.update(overrides)
    with pytest.raises(SourceWriterError, match=match):
        build_reviewed_payload_from_decision_stage(stage)
