#!/usr/bin/env python3
"""Default-off scheduled CAS dual-write for all B4 low-priority queues."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping

from review_inbox_low_priority_adapters import ADAPTERS, SOURCE_CONFIG, build_snapshot
from review_inbox_parity import load_adapted_snapshot
from review_inbox_production_wiring import MasterDbS3ArtifactStore, public_projection_digest
from review_inbox_shadow_execution_gate import require_explicit_environment as common_gates
from review_inbox_shadow_execution_gate import require_outside_cron_window, validate_public_today, write_report
from review_inbox_source_adapter import write_adapted_snapshot
from review_inbox_source_writer import ArtifactStore, SourceWriterError, run_source_shadow


CONFIRM = "RUN SCHEDULED LOW PRIORITY DUAL WRITE"
ENABLE_ENV = "REVIEW_INBOX_LOW_PRIORITY_SCHEDULED_ENABLED"
SOURCE_IDS = tuple(ADAPTERS)


def parse_sources(values: list[str]) -> dict[str, Path]:
    parsed: dict[str, Path] = {}
    for value in values:
        source_id, separator, path = value.partition("=")
        if not separator or source_id not in ADAPTERS or not path or source_id in parsed:
            raise SourceWriterError(f"invalid or duplicate --source: {value}")
        parsed[source_id] = Path(path).resolve()
    if set(parsed) != set(SOURCE_IDS):
        raise SourceWriterError("scheduled low-priority write requires all B4 sources")
    if len(set(parsed.values())) != len(parsed):
        raise SourceWriterError("scheduled low-priority input paths must be distinct")
    return parsed


def run_scheduled(args: argparse.Namespace, *, environ: Mapping[str,str] | None=None, now: datetime | None=None, store_factory: Callable[[argparse.Namespace],ArtifactStore] | None=None, digest_function: Callable[...,str]=public_projection_digest) -> dict:
    environ = os.environ if environ is None else environ
    if not args.execute: raise SourceWriterError("scheduled low-priority execution is off")
    if args.confirm != CONFIRM: raise SourceWriterError(f"--confirm must be exactly: {CONFIRM}")
    if environ.get(ENABLE_ENV,"").strip().lower() != "true": raise SourceWriterError("scheduled low-priority dual-write is off")
    flags = common_gates(environ,dual_write_mode="bulk",selection_mode="all",run_label="scheduled low-priority dual-write")
    require_outside_cron_window(now,run_label="scheduled low-priority dual-write")
    validate_public_today(args.public_today)
    observation = str(args.observation_id).strip()
    if not observation: raise SourceWriterError("--observation-id is required")
    sources = parse_sources(args.source)
    evidence_dir = Path(args.evidence_dir).resolve()
    if evidence_dir.exists() and any(evidence_dir.iterdir()): raise SourceWriterError("refusing to overwrite low-priority evidence")
    evidence_dir.mkdir(parents=True,exist_ok=True)
    snapshots = {}
    for source_id in SOURCE_IDS:
        try: snapshot = build_snapshot(source_id,sources[source_id])
        except (OSError,ValueError,TypeError) as exc: raise SourceWriterError(str(exc)) from exc
        if snapshot.get("source_id") != source_id or snapshot.get("selection",{}).get("mode") != "all": raise SourceWriterError(f"invalid low-priority snapshot: {source_id}")
        path=evidence_dir/f"{source_id}-snapshot.json"; write_adapted_snapshot(snapshot,path)
        snapshots[source_id]=load_adapted_snapshot(path)
    factory=store_factory or (lambda value: MasterDbS3ArtifactStore(bucket=value.bucket,prefix=value.prefix))
    store=factory(args); reports=[]
    for source_id in SOURCE_IDS:
        report=run_source_shadow(store=store,adapted_snapshot=snapshots[source_id],observation_id=f"{observation}-{source_id}",public_projection_digest=lambda db: digest_function(db,today=args.public_today),flags=flags,work_dir=(Path(args.work_dir)/source_id if args.work_dir else None))
        report["entrypoint"]={"name":"run_review_inbox_low_priority_scheduled.py","source_queue":source_id,"reader_mode":"legacy","legacy_writer_retained":True,"public_today":args.public_today}
        write_report(evidence_dir/f"{source_id}-report.json",report); reports.append(report)
    summary={"source_ids":list(SOURCE_IDS),"source_count":len(reports),"published_count":sum(bool(r["published"]) for r in reports),"unmapped_count":sum(r["reconciliation"]["summary"]["unmapped_count"] for r in reports),"rend":reports[-1]["rend"]["checksum"]}
    (evidence_dir/"summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source",action="append",default=[])
    parser.add_argument("--evidence-dir",type=Path,required=True); parser.add_argument("--observation-id",required=True); parser.add_argument("--public-today",required=True)
    parser.add_argument("--bucket",default=""); parser.add_argument("--prefix",default=""); parser.add_argument("--work-dir",type=Path); parser.add_argument("--execute",action="store_true"); parser.add_argument("--confirm",default="")
    return parser


def main(argv=None):
    args=build_parser().parse_args(argv); summary=run_scheduled(args); print(f"scheduled low-priority dual-write complete: sources={summary['source_count']} published={summary['published_count']} Rend={summary['rend']}")


if __name__ == "__main__": main()
