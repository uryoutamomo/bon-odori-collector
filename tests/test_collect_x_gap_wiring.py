from pathlib import Path


def test_collect_builds_only_bounded_gap_driven_x_inbox_input():
    workflow=(Path(__file__).resolve().parents[1]/'.github/workflows/collect.yml').read_text(encoding='utf-8')
    assert 'python build_x_gap_candidates.py --limit 30' in workflow
    assert 'python x_candidate_backlog.py merge' in workflow
    assert '--backlog data/x_candidate_backlog.json' in workflow
    assert '--daily-limit 5' in workflow
    assert 'python review_inbox_adapters/x_gap_adapter.py' in workflow
    assert 'python build_x_review_lanes.py --input data/x_gap_candidates.json' in workflow
    assert 'data/review_inbox_adapted/x_gap.json' in workflow


def test_collect_wires_default_off_five_item_cohort_with_cas_and_alert_artifacts():
    workflow=(Path(__file__).resolve().parents[1]/'.github/workflows/collect.yml').read_text(encoding='utf-8')
    assert "vars.REVIEW_INBOX_X_GAP_DUAL_WRITE_ENABLED == 'true'" in workflow
    assert 'REVIEW_INBOX_DUAL_WRITE_MODE: cohort' in workflow
    assert 'REVIEW_INBOX_CAS_PUBLISH_ENABLED: \'true\'' in workflow
    assert 'REVIEW_INBOX_READER_MODE: inbox' in workflow
    assert 'python run_review_inbox_x_gap_scheduled.py' in workflow
    assert "--confirm 'RUN SCHEDULED X GAP COHORT DUAL WRITE'" in workflow
    assert 'data/x_candidate_backlog_alerts.json' in workflow
    assert 'data/x_candidate_backlog_alerts.md' in workflow
