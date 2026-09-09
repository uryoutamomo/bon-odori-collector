#!/usr/bin/env python3
"""Compare two exporter revisions against one verified R2 input bundle.

Unlike compare_public_export_postprocessors.py, this runner does not apply an
old postprocessor stack twice.  It snapshots the requested old git revision and
the supplied candidate checkout, installs the same verified DB and seven
supplemental inputs into both snapshots, then compares each public artifact for
the date boundaries derived from the actual bundle data.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_INPUTS = (
    "data/event_date_predictions.json",
    "data/event_date_update_candidates.json",
    "data/public_event_overrides.json",
    "data/public_fixed_date_rules.json",
    "data/song_master_initial_registration.json",
    "data/rdb_song_review_source.json",
    "data/public/event_song_occurrences_public.json",
)
ARTIFACTS = {
    "events_public.json": "json",
    "events_public.js": "javascript-events",
    "event_songs_public.json": "json",
    "public_event_source_map.json": "json",
}


class ComparisonError(RuntimeError):
    """A comparison precondition was not met."""


class ExportFailure(ComparisonError):
    """An exporter refused its inputs; retain both sides of that comparison."""

    def __init__(self, returncode: int, stderr: str, out_dir: Path):
        self.details = {
            "returncode": returncode,
            "error": next((line for line in reversed(stderr.splitlines()) if line.strip()), "export failed without stderr"),
            "artifacts_present": sorted(name for name in ARTIFACTS if (out_dir / name).exists()),
        }
        super().__init__(self.details["error"])


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise ComparisonError(f"{label} is missing: {path}")
    return path


def parse_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ComparisonError(f"date must be YYYY-MM-DD: {value!r}") from exc


def git_output(repository: Path, *args: str) -> str:
    try:
        return subprocess.check_output(["git", "-C", str(repository), *args], text=True).strip()
    except subprocess.CalledProcessError as exc:
        raise ComparisonError(f"git {' '.join(args)} failed for {repository}") from exc


def git_revision(repository: Path, revision: str) -> str:
    value = git_output(repository, "rev-parse", "--verify", f"{revision}^{{commit}}")
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise ComparisonError(f"not a full git commit: {revision}")
    return value


def shared_code_fix(repository: Path, revision: str) -> dict[str, Any]:
    """Return a narrow, reproducible patch which is safe to apply to both sides."""
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ComparisonError("--shared-code-fix must be a full 40-character commit")
    commit = git_revision(repository, revision)
    parents = git_output(repository, "rev-list", "--parents", "-n", "1", commit).split()
    if len(parents) != 2:
        raise ComparisonError("--shared-code-fix must name a single-parent commit")
    parent = parents[1]
    changed = git_output(repository, "diff-tree", "--no-commit-id", "--name-only", "-r", parent, commit).splitlines()
    if not changed or any(not path.endswith(".py") for path in changed):
        raise ComparisonError("--shared-code-fix must contain one or more Python-only path changes")
    try:
        patch = subprocess.check_output(["git", "-C", str(repository), "diff", "--binary", parent, commit])
    except subprocess.CalledProcessError as exc:
        raise ComparisonError("could not generate --shared-code-fix patch") from exc
    if not patch:
        raise ComparisonError("--shared-code-fix has no patch")
    return {
        "commit": commit,
        "parent": parent,
        "paths": changed,
        "selection_contract": "single-parent commit with Python-only path changes, applied identically to both isolated snapshots",
        "patch": patch,
        "patch_sha256": hashlib.sha256(patch).hexdigest(),
    }


def apply_shared_code_fix(root: Path, patch_path: Path, label: str) -> None:
    """Apply exactly once; a pre-applied or incompatible patch is a refusal."""
    for check in (True, False):
        command = ["git", "apply"]
        if check:
            command.append("--check")
        command.append(str(patch_path))
        result = subprocess.run(command, cwd=root, text=True, capture_output=True)
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise ComparisonError(f"shared code fix is already applied or cannot apply to {label}: {detail}")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ComparisonError(f"invalid JSON: {path}") from exc


def input_paths(bundle: Path) -> dict[str, Path]:
    return {
        "database": bundle / "master" / "bon_odori_master.sqlite",
        "manifest": bundle / "master" / "bon_odori_master_manifest.json",
        **{relative: bundle / relative for relative in REQUIRED_INPUTS},
    }


def reject_sqlite_sidecars(path: Path, label: str) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(f"{path}{suffix}")
        if sidecar.exists():
            raise ComparisonError(f"{label} has SQLite sidecar: {sidecar}")


def sqlite_checks(path: Path, label: str) -> None:
    reject_sqlite_sidecars(path, label)
    with contextlib.closing(sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ComparisonError(f"{label} integrity_check failed")
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_keys:
            raise ComparisonError(f"{label} foreign_key_check failed")


def verify_bundle(bundle: Path, *, today: str, target_year: int) -> dict[str, Any]:
    bundle = bundle.resolve()
    metadata_path = require_file(bundle / "bundle-metadata.json", "bundle metadata")
    metadata = load_json(metadata_path)
    if metadata.get("format") != "bon-odori-public-projection-inputs-v1":
        raise ComparisonError("unsupported input bundle format")
    if not isinstance(metadata.get("git_sha"), str) or not re.fullmatch(r"[0-9a-f]{40}", metadata["git_sha"]):
        raise ComparisonError("bundle metadata must identify a full collector commit")
    if metadata.get("today") != today or metadata.get("target_year") != target_year:
        raise ComparisonError("--today and --target-year must exactly match bundle metadata")
    paths = input_paths(bundle)
    for name, path in paths.items():
        require_file(path, f"bundle input {name}")
    declared = {
        metadata.get("inputs", {}).get("database", {}).get("path"): metadata.get("inputs", {}).get("database", {}).get("sha256"),
        metadata.get("inputs", {}).get("manifest", {}).get("path"): metadata.get("inputs", {}).get("manifest", {}).get("sha256"),
    }
    supplemental = metadata.get("inputs", {}).get("supplemental_json", [])
    if not isinstance(supplemental, list) or not all(isinstance(entry, dict) for entry in supplemental):
        raise ComparisonError("bundle metadata supplemental_json is invalid")
    supplemental_paths = [entry.get("path") for entry in supplemental]
    if len(supplemental_paths) != len(set(supplemental_paths)):
        raise ComparisonError("bundle metadata has duplicate supplemental input paths")
    for entry in supplemental:
        declared[entry.get("path")] = entry.get("sha256")
    expected_paths = {"master/bon_odori_master.sqlite", "master/bon_odori_master_manifest.json", *REQUIRED_INPUTS}
    if set(declared) != expected_paths:
        raise ComparisonError("bundle metadata does not declare exactly the DB, manifest, and seven inputs")
    hashes: dict[str, str] = {}
    for key, path in paths.items():
        relative = "master/bon_odori_master.sqlite" if key == "database" else "master/bon_odori_master_manifest.json" if key == "manifest" else key
        actual = sha256(path)
        if declared.get(relative) != actual:
            raise ComparisonError(f"bundle input hash mismatch: {relative}")
        hashes[relative] = actual
    hashes["bundle-metadata.json"] = sha256(metadata_path)
    for relative in REQUIRED_INPUTS:
        load_json(paths[relative])
    manifest = load_json(paths["manifest"])
    if manifest.get("database_checksum") != hashes["master/bon_odori_master.sqlite"]:
        raise ComparisonError("bundle manifest database_checksum does not match DB")
    sqlite_checks(paths["database"], "bundle DB")
    return {"metadata": metadata, "hashes": hashes, "bundle": str(bundle)}


def copy_bundle_inputs(bundle: Path, checkout: Path, isolated_db: Path) -> Path:
    paths = input_paths(bundle)
    isolated_db.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(paths["database"], isolated_db)
    isolated_manifest = isolated_db.with_name("bon_odori_master_manifest.json")
    shutil.copy2(paths["manifest"], isolated_manifest)
    for relative in REQUIRED_INPUTS:
        destination = checkout / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(paths[relative], destination)
    return isolated_manifest


def verify_isolated_inputs(checkout: Path, db: Path, manifest: Path, expected: dict[str, str]) -> None:
    """Refuse a run which modified its private DB or fixed supplemental inputs."""
    actual = {relative: sha256(require_file(checkout / relative, "isolated supplemental input")) for relative in REQUIRED_INPUTS}
    actual["master/bon_odori_master.sqlite"] = sha256(require_file(db, "isolated master DB"))
    actual["master/bon_odori_master_manifest.json"] = sha256(require_file(manifest, "isolated master manifest"))
    for relative, value in actual.items():
        if expected[relative] != value:
            raise ComparisonError(f"isolated input changed during comparison: {relative}")
    if load_json(manifest).get("database_checksum") != actual["master/bon_odori_master.sqlite"]:
        raise ComparisonError("isolated manifest no longer matches isolated master DB")
    sqlite_checks(db, "isolated master DB")


def snapshot_baseline(repository: Path, revision: str, destination: Path) -> None:
    destination.mkdir(parents=True)
    archive = subprocess.Popen(["git", "-C", str(repository), "archive", "--format=tar", revision], stdout=subprocess.PIPE)
    assert archive.stdout is not None
    try:
        with tarfile.open(fileobj=archive.stdout, mode="r|") as extracted:
            extracted.extractall(destination, filter="data")
    finally:
        archive.stdout.close()
    if archive.wait() != 0:
        raise ComparisonError(f"git archive failed for baseline {revision}")


def snapshot_manifest(root: Path) -> dict[str, str]:
    """Digest every copied source file so a dirty candidate is reproducible."""
    return {
        str(path.relative_to(root)): sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    }


def manifest_digest(manifest: dict[str, str]) -> str:
    return hashlib.sha256(canonical_json(manifest).encode("utf-8")).hexdigest()


def runtime_source_manifest(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): sha256(path)
        for path in sorted(root.rglob("*.py"))
        if path.is_file() and not path.is_symlink()
    }


def snapshot_candidate(repository: Path, destination: Path) -> None:
    destination.mkdir(parents=True)
    try:
        result = subprocess.run(
            ["git", "-C", str(repository), "ls-files", "-c", "-o", "--exclude-standard", "-z"],
            check=True, capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        raise ComparisonError(f"could not list candidate snapshot files: {repository}") from exc
    for encoded in result.stdout.split(b"\0"):
        if not encoded:
            continue
        relative = Path(os.fsdecode(encoded))
        if relative.is_absolute() or ".." in relative.parts:
            raise ComparisonError(f"unsafe candidate snapshot path: {relative}")
        source = repository / relative
        if not source.is_file() or source.is_symlink():
            continue
        copied = destination / relative
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, copied)


def export_once(checkout: Path, out_dir: Path, db: Path, today: str, target_year: int, python: str, quiet: bool) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.pop("GITHUB_STEP_SUMMARY", None)
    env.update({
        "BON_ODORI_PUBLIC_SOURCE": "master_rdb",
        "BON_ODORI_PUBLIC_OUT_DIR": str(out_dir),
        "BON_ODORI_PUBLIC_DATE_PREDICTION_REPORT": str(out_dir / "prediction_report.json"),
        "BON_ODORI_PUBLIC_EVENT_SOURCE_MAP_JSON": str(out_dir / "public_event_source_map.json"),
        "BON_ODORI_SONG_OCCURRENCES_JSON": str(checkout / "data/public/event_song_occurrences_public.json"),
        "BON_ODORI_PUBLIC_TODAY": today,
    })
    command = [python, "export_public_events.py", "--today", today, "--target-year", str(target_year), "--master-db", str(db)]
    if not quiet:
        print("+ " + " ".join(command), flush=True)
    result = subprocess.run(command, cwd=checkout, env=env, text=True, capture_output=True)
    if not quiet:
        print(result.stdout, end="")
    if result.returncode:
        raise ExportFailure(result.returncode, result.stderr, out_dir)
    missing = [name for name in ARTIFACTS if not (out_dir / name).is_file()]
    if missing:
        raise ComparisonError(f"export did not produce all artifacts: {', '.join(missing)}")


def parse_javascript_events(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"(?:const\s+EVENTS|window\.BON_ODORI_EVENTS)\s*=\s*(\[.*\])\s*;?\s*$", text, re.S)
    if not match:
        raise ComparisonError(f"could not parse events JavaScript artifact: {path}")
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ComparisonError(f"events JavaScript contains invalid JSON array: {path}") from exc


def first_diff(left: Any, right: Any, path: str = "$") -> dict[str, Any] | None:
    if type(left) is not type(right):
        return {"path": path, "reason": "type_mismatch", "left": left, "right": right}
    if isinstance(left, dict):
        if set(left) != set(right):
            return {"path": path, "reason": "key_mismatch", "left_only": sorted(set(left) - set(right)), "right_only": sorted(set(right) - set(left))}
        for key in sorted(left):
            found = first_diff(left[key], right[key], f"{path}.{key}")
            if found:
                return found
    elif isinstance(left, list):
        if len(left) != len(right):
            return {"path": path, "reason": "length_mismatch", "left_length": len(left), "right_length": len(right)}
        for index, (a, b) in enumerate(zip(left, right)):
            found = first_diff(a, b, f"{path}[{index}]")
            if found:
                return found
    elif left != right:
        return {"path": path, "reason": "value_mismatch", "left": left, "right": right}
    return None


def compare_artifact(baseline: Path, candidate: Path, kind: str) -> dict[str, Any]:
    byte_equal = baseline.read_bytes() == candidate.read_bytes()
    left = parse_javascript_events(baseline) if kind == "javascript-events" else load_json(baseline)
    right = parse_javascript_events(candidate) if kind == "javascript-events" else load_json(candidate)
    semantic_diff = first_diff(left, right)
    semantic_equal = semantic_diff is None
    return {
        "byte_equal": byte_equal,
        "semantic_equal": semantic_equal,
        "equal": byte_equal and semantic_equal,
        "baseline_sha256": sha256(baseline),
        "candidate_sha256": sha256(candidate),
        "first_semantic_diff": semantic_diff,
    }


def public_event_key(event: dict[str, Any]) -> str:
    return "|".join(str(event.get(key) or "") for key in ("name", "venue", "date", "date_end"))


def matrix_event(event: dict[str, Any], date_key: str, source_rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
    source = source_rows.get(public_event_key(event), {})
    return {
        "name": event.get("name"),
        "venue": event.get("venue"),
        "occurrence_id": source.get("occurrence_id"),
        "date_basis": event.get(date_key),
        "date_key": date_key,
        "public_state_axes": {
            "current_event_state": event.get("current_event_state"),
            "date_certainty_tier": event.get("date_certainty_tier"),
            "present": "current_event_state" in event or "date_certainty_tier" in event,
        },
        "stored_canonical_axes_preferred": None,
    }


def select_matrix_events(events: list[dict[str, Any]], target_year: int, source_rows: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    end_events = [(parse_date(str(event.get("date_end") or event.get("date"))), event) for event in events if event.get("date") and (event.get("date_end") or event.get("date"))]
    # Prefer a real occurrence in the requested year.  Historical rows from
    # target_year - 1 are still useful fallbacks for unusual sparse bundles.
    end_events = sorted((item for item in end_events if item[0].year == target_year), key=lambda item: (item[0], str(item[1].get("name")))) or sorted(end_events, key=lambda item: (item[0], str(item[1].get("name"))))
    historical_events = sorted(
        [(parse_date(str(event["historical_slide_date"])), event) for event in events if event.get("historical_slide_date")],
        key=lambda item: (item[0], str(item[1].get("name"))),
    )
    if not end_events:
        raise ComparisonError("could not derive an event end boundary from real exported data")
    if not historical_events:
        raise ComparisonError("could not derive a historical-slide expiry boundary from real exported data")
    end, end_event = end_events[0]
    historical_start, historical_event = historical_events[0]
    return ({"date": end, "event": matrix_event(end_event, "date_end", source_rows)}, {"date": historical_start, "event": matrix_event(historical_event, "historical_slide_date", source_rows)})


def date_matrix(seed_events: list[dict[str, Any]], *, today: str, target_year: int, source_map: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    source_rows = {row.get("public_event_key"): row for row in (source_map or {}).get("rows", []) if isinstance(row, dict) and isinstance(row.get("public_event_key"), str)}
    end_boundary, historical_boundary = select_matrix_events(seed_events, target_year, source_rows)
    end, historical_start = end_boundary["date"], historical_boundary["date"]
    base = parse_date(today)
    rows = [
        ("normal", base, target_year),
        ("event_end_previous_day", end - dt.timedelta(days=1), target_year),
        ("event_end_day", end, target_year),
        ("event_end_next_day", end + dt.timedelta(days=1), target_year),
        # Historical slide expiry is start-based: a slide remains on its start
        # day and expires only when today is after that date.
        ("historical_start_day", historical_start, target_year),
        ("historical_start_next_day", historical_start + dt.timedelta(days=1), target_year),
        ("year_end_target_year_fixed", dt.date(target_year, 12, 31), target_year),
        ("year_start_target_year_fixed", dt.date(target_year + 1, 1, 1), target_year),
        ("year_start_target_year_advanced", dt.date(target_year + 1, 1, 1), target_year + 1),
    ]
    return [
        {"name": name, "today": value.isoformat(), "target_year": year,
         "matrix_boundaries": {"event_end": end_boundary["event"], "historical_expiry": historical_boundary["event"]}}
        for name, value, year in rows
    ]


def compare(*, input_bundle: Path, baseline_revision: str, candidate_repo: Path, today: str, target_year: int, python: str, quiet: bool, shared_code_fix_revision: str | None = None) -> dict[str, Any]:
    candidate_repo = candidate_repo.resolve()
    bundle = verify_bundle(input_bundle, today=today, target_year=target_year)
    baseline_sha = git_revision(candidate_repo, baseline_revision)
    if bundle["metadata"]["git_sha"] != baseline_sha:
        raise ComparisonError("baseline revision must match input bundle metadata git_sha exactly")
    candidate_sha = git_revision(candidate_repo, "HEAD")
    shared_fix = shared_code_fix(candidate_repo, shared_code_fix_revision) if shared_code_fix_revision else None
    source_hashes_before = dict(bundle["hashes"])
    with tempfile.TemporaryDirectory(prefix="public-projection-revisions-") as raw:
        temp = Path(raw)
        baseline_root, candidate_root = temp / "baseline", temp / "candidate"
        snapshot_baseline(candidate_repo, baseline_sha, baseline_root)
        snapshot_candidate(candidate_repo, candidate_root)
        isolated_inputs = {}
        for root, label in ((baseline_root, "baseline"), (candidate_root, "candidate")):
            db = temp / "inputs" / label / "bon_odori_master.sqlite"
            manifest = copy_bundle_inputs(input_bundle, root, db)
            isolated_inputs[label] = (root, db, manifest)
        source_snapshots_before = {
            label: snapshot_manifest(root)
            for label, (root, _db, _manifest) in isolated_inputs.items()
        }
        shared_fix_snapshots = None
        if shared_fix:
            patch_path = temp / "shared-code-fix.patch"
            patch_path.write_bytes(shared_fix["patch"])
            for label, (root, _db, _manifest) in isolated_inputs.items():
                apply_shared_code_fix(root, patch_path, label)
            source_snapshots = {
                label: snapshot_manifest(root)
                for label, (root, _db, _manifest) in isolated_inputs.items()
            }
            shared_fix_snapshots = {
                label: {
                    "source_sha256_before": manifest_digest(source_snapshots_before[label]),
                    "source_sha256_after": manifest_digest(source_snapshots[label]),
                }
                for label in isolated_inputs
            }
        else:
            source_snapshots = source_snapshots_before
        runtime_sources = {
            label: runtime_source_manifest(root)
            for label, (root, _db, _manifest) in isolated_inputs.items()
        }

        def run_checked(label: str, out_dir: Path, case_today: str, case_year: int):
            root, db, manifest = isolated_inputs[label]
            verify_isolated_inputs(root, db, manifest, source_hashes_before)
            try:
                export_once(root, out_dir, db, case_today, case_year, python, quiet)
            except ExportFailure as exc:
                return exc.details
            finally:
                verify_isolated_inputs(root, db, manifest, source_hashes_before)
                if runtime_source_manifest(root) != runtime_sources[label]:
                    raise ComparisonError(f"runtime Python source changed during comparison: {label}")
            return None

        seed_dir = temp / "seed"
        seed_failure = run_checked("baseline", seed_dir, f"{target_year}-01-01", target_year)
        if seed_failure:
            raise ComparisonError(f"baseline seed export failed: {seed_failure['error']}")
        matrix = date_matrix(
            load_json(seed_dir / "events_public.json"),
            today=today,
            target_year=target_year,
            source_map=load_json(seed_dir / "public_event_source_map.json"),
        )
        cases = []
        for row in matrix:
            case_root = temp / "runs" / row["name"]
            baseline_out, candidate_out = case_root / "baseline", case_root / "candidate"
            baseline_failure = run_checked("baseline", baseline_out, row["today"], row["target_year"])
            candidate_failure = run_checked("candidate", candidate_out, row["today"], row["target_year"])
            if baseline_failure or candidate_failure:
                matching_refusal = bool(
                    baseline_failure == candidate_failure
                    and baseline_failure
                    and not baseline_failure["artifacts_present"]
                    and baseline_failure["error"].startswith("ValueError: public song projection refused invalid rows:")
                )
                cases.append({
                    **row, "status": "blocked" if matching_refusal else "fail",
                    "refusal_parity": matching_refusal,
                    "export_failures": {"baseline": baseline_failure, "candidate": candidate_failure},
                    "artifacts": {},
                })
                print(f"{row['name']}: {cases[-1]['status']} (no four-output parity)", flush=True)
                continue
            artifacts = {name: compare_artifact(baseline_out / name, candidate_out / name, kind) for name, kind in ARTIFACTS.items()}
            baseline_events = load_json(baseline_out / "events_public.json")
            candidate_events = load_json(candidate_out / "events_public.json")
            cases.append({**row, "status": "pass" if all(item["equal"] for item in artifacts.values()) else "fail", "event_count": {"baseline": len(baseline_events), "candidate": len(candidate_events)}, "artifacts": artifacts})
            print(f"{row['name']}: {cases[-1]['status']} ({len(candidate_events)} events)", flush=True)
        bundle_after = verify_bundle(input_bundle, today=today, target_year=target_year)
        if bundle_after["hashes"] != source_hashes_before:
            raise ComparisonError("input bundle changed during comparison")
    passed = all(case["status"] == "pass" for case in cases)
    status = "pass" if passed else "fail" if any(case["status"] == "fail" for case in cases) else "blocked"
    return {
        "status": status,
        "comparison_mode": "shared_code_fix_parity" if shared_fix else "original_parity",
        "full_four_output_parity": passed,
        "generated_by": "scripts/compare_public_projection_revisions.py",
        "baseline_revision": baseline_sha,
        "candidate_revision": candidate_sha,
        "source_snapshots": {
            label: {
                "stage": "after_verified_bundle_inputs_overlay",
                "sha256": manifest_digest(manifest),
                "files": manifest,
                "runtime_python_sha256": manifest_digest(runtime_sources[label]),
            }
            for label, manifest in source_snapshots.items()
        },
        "shared_code_fix": None if not shared_fix else {
            key: value for key, value in shared_fix.items() if key != "patch"
        } | {"snapshots": shared_fix_snapshots},
        "today": today,
        "target_year": target_year,
        "input_bundle": {"path": bundle["bundle"], "metadata": bundle["metadata"], "sha256": source_hashes_before},
        "matrix": cases,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-bundle", required=True, type=Path, help="verified, decrypted input-bundle directory")
    parser.add_argument("--baseline-revision", required=True, help="fixed old exporter commit")
    parser.add_argument("--shared-code-fix", help="full single-parent Python-only commit applied identically to both isolated snapshots")
    parser.add_argument("--candidate-repo", type=Path, default=ROOT, help="new checkout, including uncommitted implementation")
    parser.add_argument("--today", required=True, help="must match bundle metadata YYYY-MM-DD")
    parser.add_argument("--target-year", required=True, type=int, help="must match bundle metadata")
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--out-json", required=True, type=Path, help="report destination outside public data")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = compare(input_bundle=args.input_bundle, baseline_revision=args.baseline_revision, candidate_repo=args.candidate_repo, today=args.today, target_year=args.target_year, python=args.python, quiet=args.quiet, shared_code_fix_revision=args.shared_code_fix)
    except ComparisonError as exc:
        print(f"comparison refused: {exc}", file=sys.stderr)
        return 2
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fix = report.get("shared_code_fix")
    print(
        f"public projection revision comparison: mode={report['comparison_mode']} "
        f"status={report['status']} cases={len(report['matrix'])} "
        f"shared_code_fix={fix['commit'] if fix else 'none'}"
    )
    return {"pass": 0, "fail": 1, "blocked": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
