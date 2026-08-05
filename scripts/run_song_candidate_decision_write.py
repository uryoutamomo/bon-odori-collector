#!/usr/bin/env python3
"""Default-off CAS writer for reviewed song-candidate inbox decisions.

This is phase 1 of the P4 production path. It writes only the reviewed
``review_inbox_items`` lifecycle. The resulting Rend checksum must then be
used as Rstart for ``apply_song_candidate_finite_actions.py``. Keeping the two
phases explicit makes a partial failure safely retryable and auditable.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from review_inbox_adapters.decision_writer import (
    DecisionWriterFlags,
    load_decision_payload,
    run_decision_write,
    validate_decision_payload,
)
from review_inbox_adapters.production_wiring import MasterDbS3ArtifactStore, public_projection_digest
from review_inbox_adapters.shadow_execution_gate import (
    require_outside_cron_window,
    validate_expected_rstart,
    validate_public_today,
    write_report,
)
from review_inbox_adapters.source_writer import ArtifactStore, SourceWriterError
from song_candidate_finite_actions import build_reviewed_payload_from_decision_stage


CONFIRM = "WRITE SONG CANDIDATE DECISIONS"
ENVIRONMENT_GATE_NAMES = (
    "REVIEW_INBOX_DECISION_WRITE_MODE",
    "REVIEW_INBOX_CAS_PUBLISH_ENABLED",
    "REVIEW_INBOX_READER_MODE",
    "REVIEW_INBOX_LEGACY_WRITER_ENABLED",
)
ACTION_LIFECYCLE = {
    "register_song": ("accepted", "domain_stage"),
    "add_song_alias": ("accepted", "domain_stage"),
    "reject_song": ("rejected", "no_apply"),
    "hold": ("hold", "no_apply"),
}


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SourceWriterError(f"invalid song action stage JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise SourceWriterError("song action stage root must be an object")
    return payload


def require_explicit_environment(environ: Mapping[str, str]) -> DecisionWriterFlags:
    missing = [name for name in ENVIRONMENT_GATE_NAMES if name not in environ]
    if missing:
        raise SourceWriterError(
            "song decision write requires explicit environment gates: " + ", ".join(missing)
        )
    flags = DecisionWriterFlags.from_env(environ)
    if flags.decision_write_mode not in {"canary", "bulk"}:
        raise SourceWriterError(
            "song decision write mode must be explicitly set to canary or bulk"
        )
    return flags


def expected_targets_and_lifecycle(
    action_stage: dict[str, Any],
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    finite_payload = build_reviewed_payload_from_decision_stage(action_stage)
    targets: dict[str, dict[str, str]] = {}
    lifecycle: dict[str, dict[str, str]] = {}
    for decision in finite_payload["decisions"]:
        inbox_id = decision["source_inbox_id"]
        if inbox_id in targets:
            raise SourceWriterError(f"duplicate song decision target: {inbox_id}")
        lifecycle_decision, decision_route = ACTION_LIFECYCLE[decision["action"]]
        targets[inbox_id] = {
            "source_id": decision["source_id"],
            "source_key": decision["source_key"],
        }
        lifecycle[inbox_id] = {
            "decision": lifecycle_decision,
            "decided_by": decision["reviewed_by"],
            "decided_at": decision["reviewed_at"],
            "decision_route": decision_route,
        }
    return targets, lifecycle


def validate_pair(
    decision_payload: dict[str, Any],
    action_stage: dict[str, Any],
) -> dict[str, dict[str, str]]:
    updates = validate_decision_payload(decision_payload)
    targets, lifecycle = expected_targets_and_lifecycle(action_stage)
    if {row["inbox_id"] for row in updates} != set(targets):
        raise SourceWriterError("decision updates and song finite actions must target the same inbox IDs")
    for update in updates:
        expected = lifecycle[update["inbox_id"]]
        if any(update[field] != expected[field] for field in expected):
            raise SourceWriterError(
                f"decision lifecycle does not match finite action: {update['inbox_id']}"
            )
    return targets


def freeze_evidence(paths: list[Path], output_dir: Path) -> list[str]:
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise SourceWriterError(f"refusing to overwrite frozen evidence directory: {output_dir}")
    output_dir.mkdir(parents=True)
    frozen: list[str] = []
    for source in paths:
        destination = output_dir / Path(source).name
        destination.write_bytes(Path(source).read_bytes())
        frozen.append(str(destination))
    return frozen


def run_batch(
    args: argparse.Namespace,
    *,
    environ: Mapping[str, str] | None = None,
    now: datetime | None = None,
    store_factory: Callable[[argparse.Namespace], ArtifactStore] | None = None,
    digest_function: Callable[..., str] = public_projection_digest,
) -> dict[str, Any]:
    environ = os.environ if environ is None else environ
    if not args.execute:
        raise SourceWriterError("song decision execution is off; pass --execute after explicit GO")
    if args.confirm != CONFIRM:
        raise SourceWriterError(f"--confirm must be exactly: {CONFIRM}")
    flags = require_explicit_environment(environ)
    require_outside_cron_window(now, run_label="song candidate decision write")
    expected_rstart = validate_expected_rstart(args.expect_rstart_checksum)
    validate_public_today(args.public_today)

    decision_path = Path(args.staged_decisions).resolve()
    action_path = Path(args.staged_actions).resolve()
    report_path = Path(args.report_out).resolve()
    if len({decision_path, action_path, report_path}) != 3:
        raise SourceWriterError("decision input, action input, and report output must differ")
    if report_path.exists():
        raise SourceWriterError(f"refusing to overwrite decision report: {report_path}")

    decision_payload, decision_sha = load_decision_payload(decision_path)
    action_payload = load_json(action_path)
    targets = validate_pair(decision_payload, action_payload)
    flags.require_write(len(targets))
    frozen = freeze_evidence([decision_path, action_path], args.frozen_evidence_dir)

    factory = store_factory or (
        lambda value: MasterDbS3ArtifactStore(bucket=value.bucket, prefix=value.prefix)
    )
    report = run_decision_write(
        store=factory(args),
        staged_payload=decision_payload,
        staged_payload_sha256=decision_sha,
        expected_targets=targets,
        public_projection_digest=lambda db: digest_function(
            db, target_year=args.public_target_year, today=args.public_today
        ),
        expected_rstart_checksum=expected_rstart,
        flags=flags,
        work_dir=Path(args.work_dir) if args.work_dir else None,
    )
    report["entrypoint"] = {
        "name": "scripts/run_song_candidate_decision_write.py",
        "confirm": "matched",
        "public_today": args.public_today,
        "cron_window_checked": True,
        "frozen_evidence": frozen,
        "next_step": "use Rend checksum as apply_song_candidate_finite_actions.py Rstart",
    }
    write_report(report_path, report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged-decisions", type=Path, required=True)
    parser.add_argument("--staged-actions", type=Path, required=True)
    parser.add_argument("--frozen-evidence-dir", type=Path, required=True)
    parser.add_argument("--report-out", type=Path, required=True)
    parser.add_argument("--expect-rstart-checksum", required=True)
    parser.add_argument("--public-target-year", type=int, required=True)
    parser.add_argument("--public-today", required=True)
    parser.add_argument("--bucket", default="")
    parser.add_argument("--prefix", default="")
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm", default="")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_batch(args)
    print(
        "song decision write complete: "
        f"published={report['published']} no_op={report['no_op']} Rend={report['rend']['checksum']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
