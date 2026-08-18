from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/apply-reviewed-change-requests.yml"


def test_workflow_requires_reviewed_path_and_explicit_confirmation() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "data/change_requests/*_reviewed.json" in text
    assert "APPLY REVIEWED CHANGE REQUESTS" in text
    assert "if: ${{ inputs.apply }}" in text


def test_workflow_dry_runs_before_apply_and_verifies_every_stage() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    dry_run = text.index("- name: Dry-run reviewed requests")
    apply = text.index("- name: Apply reviewed requests")
    publish = text.index("- name: Publish Master RDB with CAS")
    refetch = text.index("- name: Re-fetch and verify published Master RDB")
    assert dry_run < apply < publish < refetch
    assert text.count("python -m scripts.verify_review_backlog_application") == 3


def test_workflow_uses_serialized_cas_publish_without_force() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "group: bon-odori-master-rdb" in text
    assert "cancel-in-progress: false" in text
    assert '--expect-remote-checksum "${{ steps.fetched.outputs.sha }}"' in text
    assert "--force" not in text
