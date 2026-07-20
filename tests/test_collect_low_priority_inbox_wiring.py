import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_low_priority_wiring_is_default_off_complete_and_ordered():
    workflow=(ROOT/".github/workflows/collect.yml").read_text()
    assert "vars.REVIEW_INBOX_LOW_PRIORITY_DUAL_WRITE_ENABLED == 'true'" in workflow
    assert "python build_missing_venue_review_from_song_associations.py" in workflow
    assert "python build_historical_reference_quality_review.py" in workflow
    assert "python build_publication_gap_review.py" not in workflow
    assert "python run_review_inbox_low_priority_scheduled.py" in workflow
    for source in ("daily_song_candidate","daily_term_candidate","accepted_venue_song_missing_venue","historical_reference_quality","publication_gap"):
        assert f"--source {source}=" in workflow
    assert workflow.index("Build and commit low-priority legacy review queues") < workflow.index("Dual-write low-priority queues to review inbox") < workflow.index("Commit low-priority inbox projection")
    assert "REVIEW_INBOX_READER_MODE: legacy" in workflow
    assert "REVIEW_INBOX_LEGACY_WRITER_ENABLED: 'true'" in workflow
    gap=json.loads((ROOT/"data/publication_gap_review.json").read_text())
    assert len(gap["rows"]) == 159
