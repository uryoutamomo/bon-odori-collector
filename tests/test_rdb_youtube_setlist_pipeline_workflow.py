from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/rdb-youtube-setlist-pipeline.yml"


def test_weekly_pipeline_runs_the_rdb_native_stages_in_order() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    extract = text.index("- name: Extract YouTube setlists")
    setlist = text.index("- name: Dry-run setlist occurrence apply")
    calibrate = text.index("- name: Dry-run direct probability calibration")
    inherit = text.index("- name: Dry-run historical probability inheritance")
    audit = text.index("- name: Audit dry-run public projection")
    publish = text.index("- name: Publish Master RDB with CAS")
    refetch = text.index("- name: Re-fetch and verify published Master RDB")
    assert extract < setlist < calibrate < inherit < audit < publish < refetch
    assert "cron: '0 21 * * 0'" in text
    assert "python -m youtube_channels.extract_youtube_setlists" in text


def test_pipeline_keeps_dry_run_before_apply_and_uses_cas() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.index("- name: Audit dry-run public projection") < text.index(
        "- name: Apply setlist occurrences"
    )
    assert '--expect-remote-checksum "${{ steps.fetched.outputs.sha }}"' in text
    assert "--force" not in text
    assert "group: bon-odori-master-rdb" in text
    assert "cancel-in-progress: false" in text


def test_pipeline_never_commits_public_json_or_writes_notion() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "git push" not in text
    assert "git add data/public" not in text
    assert "notion" not in text.casefold()
    assert text.count("python export_public_events.py") == 1
