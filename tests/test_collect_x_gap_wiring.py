from pathlib import Path


def test_collect_builds_only_bounded_gap_driven_x_inbox_input():
    workflow=(Path(__file__).resolve().parents[1]/'.github/workflows/collect.yml').read_text(encoding='utf-8')
    assert 'python build_x_gap_candidates.py --limit 30' in workflow
    assert 'python review_inbox_adapters/x_gap_adapter.py' in workflow
    assert 'python build_x_review_lanes.py --input data/x_gap_candidates.json' in workflow
    assert 'data/review_inbox_adapted/x_gap.json' in workflow
