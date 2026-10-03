#!/usr/bin/env python3
"""Verify that the occurrence-ID migration adds only its two public fields.

Uses the same verified input bundle and date matrix as the strict projection
comparator. This migration gate is deliberately limited to occurrence identity.
"""
import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

if __package__:
    from . import compare_public_projection_revisions as projection
else:
    import compare_public_projection_revisions as projection

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from public_export_support.occurrence_identity import index_events


IDENTITY_FIELDS = {"occurrence_id", "event_year"}


def verify_event_rows(baseline, candidate, source_map):
    """Require exact old payloads and metadata bound to every source-map row."""
    index_events(candidate, require_identity=True)
    mapped = source_map.get("rows", [])
    if len(mapped) != len(candidate) or len(baseline) != len(candidate):
        raise ValueError("event/source-map row counts changed")
    for old, new, source in zip(baseline, candidate, mapped):
        if IDENTITY_FIELDS & set(old):
            raise ValueError("baseline already contains occurrence metadata")
        if projection.canonical_json(old) != projection.canonical_json(
            {key: value for key, value in new.items() if key not in IDENTITY_FIELDS}
        ):
            raise ValueError("migration changed an existing public event field")
        if (new["occurrence_id"] != source.get("occurrence_id")
                or new["event_year"] != source.get("event_year")
                or projection.public_event_key(new) != source.get("public_event_key")):
            raise ValueError("public metadata does not match its source-map occurrence")


def verify(args):
    repo = args.candidate_repo.resolve()
    bundle = projection.verify_bundle(args.input_bundle, today=args.today, target_year=args.target_year)
    baseline_sha = projection.git_revision(repo, args.baseline_revision)
    if baseline_sha != bundle["metadata"]["git_sha"]:
        raise ValueError("baseline revision must match verified bundle metadata")
    cases = []
    with tempfile.TemporaryDirectory(prefix="bonsuke-occurrence-migration-") as temporary:
        root = Path(temporary)
        baseline, candidate = root / "baseline", root / "candidate"
        projection.snapshot_baseline(repo, baseline_sha, baseline)
        projection.snapshot_candidate(repo, candidate)
        checkouts = {"baseline": baseline, "candidate": candidate}
        databases, manifests = {}, {}
        for label, checkout in checkouts.items():
            databases[label] = root / label / "private-input" / "bon_odori_master.sqlite"
            manifests[label] = projection.copy_bundle_inputs(args.input_bundle, checkout, databases[label])
        runtime = {label: projection.runtime_source_manifest(checkout) for label, checkout in checkouts.items()}

        def export(label, output, today, year):
            checkout, db, manifest = checkouts[label], databases[label], manifests[label]
            projection.verify_isolated_inputs(checkout, db, manifest, bundle["hashes"])
            try:
                projection.export_once(checkout, output, db, today, year, sys.executable, True)
            finally:
                projection.verify_isolated_inputs(checkout, db, manifest, bundle["hashes"])
                if projection.runtime_source_manifest(checkout) != runtime[label]:
                    raise ValueError("runtime source changed during migration verification")

        seed = root / "seed"
        export("baseline", seed, f"{args.target_year}-01-01", args.target_year)
        matrix = projection.date_matrix(projection.load_json(seed / "events_public.json"),
            today=args.today, target_year=args.target_year,
            source_map=projection.load_json(seed / "public_event_source_map.json"))
        for case in matrix:
            outputs = {label: root / "runs" / case["name"] / label for label in checkouts}
            for label, output in outputs.items():
                export(label, output, case["today"], case["target_year"])
            old, new = outputs["baseline"], outputs["candidate"]
            source_map = projection.load_json(old / "public_event_source_map.json")
            verify_event_rows(projection.load_json(old / "events_public.json"),
                             projection.load_json(new / "events_public.json"), source_map)
            verify_event_rows(projection.parse_javascript_events(old / "events_public.js"),
                             projection.parse_javascript_events(new / "events_public.js"), source_map)
            for name in ("event_songs_public.json", "public_event_source_map.json"):
                if (old / name).read_bytes() != (new / name).read_bytes():
                    raise ValueError(f"migration changed {name}")
            cases.append({**case, "status": "pass", "event_count": len(source_map["rows"]),
                          "candidate_sha256": {name: projection.sha256(new / name) for name in projection.ARTIFACTS}})
            print(f"{case['name']}: pass ({len(source_map['rows'])} events)", flush=True)
        after = projection.verify_bundle(args.input_bundle, today=args.today, target_year=args.target_year)
        if after["hashes"] != bundle["hashes"]:
            raise ValueError("verified bundle changed")
        if args.normal_output:
            args.normal_output.mkdir(parents=True, exist_ok=True)
            for name in projection.ARTIFACTS:
                shutil.copy2(root / "runs" / "normal" / "candidate" / name, args.normal_output / name)
    return {"status": "pass", "contract": "only occurrence_id/event_year added; all old fields exact; songs/source_map byte equal",
            "baseline_revision": baseline_sha, "candidate_revision": projection.git_revision(repo, "HEAD"),
            "runtime_python_sha256": {label: projection.manifest_digest(value) for label, value in runtime.items()},
            "input_sha256": bundle["hashes"], "matrix": cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-bundle", required=True, type=Path)
    parser.add_argument("--baseline-revision", required=True)
    parser.add_argument("--candidate-repo", required=True, type=Path)
    parser.add_argument("--today", required=True)
    parser.add_argument("--target-year", required=True, type=int)
    parser.add_argument("--normal-output", type=Path)
    parser.add_argument("--out-json", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = verify(args)
    except (ValueError, projection.ComparisonError) as error:
        print(f"identity migration refused: {error}", file=sys.stderr)
        return 2
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
