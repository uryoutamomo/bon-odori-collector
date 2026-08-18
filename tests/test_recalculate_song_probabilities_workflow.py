from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/recalculate-song-probabilities.yml"


def test_workflow_is_manual_and_requires_explicit_apply_confirmation() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "push:" not in text
    assert "APPLY SONG PROBABILITY RECALCULATION" in text
    assert "target_year must be a four-digit year from 2000 through 2100" in text
    assert "if: ${{ inputs.apply }}" in text


def test_workflow_runs_full_dry_run_before_apply_and_audits_all_exports() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    dry_calibration = text.index("- name: Dry-run direct song calibration")
    dry_inheritance = text.index("- name: Dry-run historical song inheritance")
    dry_export = text.index("- name: Audit dry-run public projection")
    apply_calibration = text.index("- name: Apply direct song calibration")
    apply_inheritance = text.index("- name: Apply historical song inheritance")
    apply_parity = text.index("- name: Verify dry-run and applied song rows match")
    publish = text.index("- name: Publish Master RDB with CAS")
    refetch = text.index("- name: Re-fetch and verify published Master RDB")
    refetch_parity = text.index("- name: Verify published song rows match applied rows")
    assert (
        dry_calibration
        < dry_inheritance
        < dry_export
        < apply_calibration
        < apply_inheritance
        < apply_parity
        < publish
        < refetch
        < refetch_parity
    )
    assert text.count("python export_public_events.py") == 3
    assert text.count("--recalculate-existing") == 2
    assert text.count('--target-year "$TARGET_YEAR"') >= 7
    assert "dry-run and applied target-year song rows differ" in text
    assert "published and applied target-year song rows differ" in text


def test_workflow_uses_serialized_cas_and_exports_refetched_public_data() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "group: bon-odori-master-rdb" in text
    assert "cancel-in-progress: false" in text
    assert '--expect-remote-checksum "${{ steps.fetched.outputs.sha }}"' in text
    assert "--force" not in text
    assert 'BON_ODORI_PUBLIC_OUT_DIR="$RUNNER_TEMP/public-refetch"' in text
    assert "${{ runner.temp }}/public-refetch/" in text
