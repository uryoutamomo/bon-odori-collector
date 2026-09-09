#!/usr/bin/env python3
"""Compare current public export with the legacy postprocessor overlay.

This is a migration guard for C: before moving prediction/historical/season
fields into the RDB-side projection, verify that the public JSON remains
semantically identical to the current export behavior.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MASTER_DB = ROOT / "data" / "bon_odori_master.sqlite"
MASTER_MANIFEST = ROOT / "data" / "bon_odori_master_manifest.json"
SONG_OCCURRENCES_SNAPSHOT = ROOT / "data" / "public" / "event_song_occurrences_public.json"

# These files are read by export_public_events.py on the master_rdb path.  They
# have no environment override, so their hashes are included in the report to
# make a comparison reproducible without modifying the checkout's inputs.
FIXED_AUXILIARY_INPUTS = (
    ROOT / "data" / "event_date_predictions.json",
    ROOT / "data" / "event_date_update_candidates.json",
    ROOT / "data" / "public_event_overrides.json",
    ROOT / "data" / "public_fixed_date_rules.json",
    ROOT / "data" / "song_master_initial_registration.json",
    ROOT / "data" / "rdb_song_review_source.json",
)

ARTIFACTS = {
    "events_public.json": "json",
    "events_public.js": "text",
    "event_songs_public.json": "json",
    "public_event_source_map.json": "json",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def require_file(path: Path, label: str) -> Path:
    if not path.is_file():
        raise SystemExit(f"{label} is missing: {path}")
    return path


def provenance_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def validated_manifest(master_db: Path, manifest_path: Path) -> dict[str, Any]:
    """Return immutable DB provenance or refuse an unpaired DB/manifest."""
    require_file(master_db, "Master DB")
    require_file(manifest_path, "Master DB manifest")
    try:
        manifest = load_json(manifest_path)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Master DB manifest is invalid JSON: {manifest_path}") from exc
    expected = manifest.get("database_checksum") if isinstance(manifest, dict) else None
    if not isinstance(expected, str) or not expected:
        raise SystemExit(f"Master DB manifest has no database_checksum: {manifest_path}")
    actual = file_sha256(master_db)
    if actual != expected:
        raise SystemExit(
            f"Master DB checksum mismatch: expected={expected} actual={actual}"
        )
    return {
        "database_path": str(master_db),
        "database_sha256": actual,
        "manifest_path": str(manifest_path),
        "manifest_sha256": file_sha256(manifest_path),
        "manifest_database_checksum": expected,
        "artifact_fetch_source": (manifest.get("artifact_fetch") or {}).get("source"),
        "artifact_snapshot_id": (manifest.get("artifact") or {}).get("snapshot_id"),
    }


def fixed_input_provenance() -> dict[str, str]:
    paths = (*FIXED_AUXILIARY_INPUTS, SONG_OCCURRENCES_SNAPSHOT)
    return {
        provenance_path(require_file(path, "Required export input")): file_sha256(path)
        for path in paths
    }


@contextlib.contextmanager
def prepared_master_db(source: str | None):
    """Temporarily install a DB for older readiness callers.

    Keep this helper's established copy-to-checkout behavior.  The comparison
    guard itself uses export_public_events.py --master-db with an isolated copy.
    """
    source_path = Path(source).expanduser().resolve() if source else None
    if source_path and source_path != MASTER_DB.resolve():
        if MASTER_DB.exists():
            raise SystemExit(
                f"{MASTER_DB} already exists; omit --master-db or run in a clean worktree"
            )
        if not source_path.exists():
            raise SystemExit(f"--master-db not found: {source_path}")
        MASTER_DB.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, MASTER_DB)
        try:
            yield
        finally:
            try:
                MASTER_DB.unlink()
            except FileNotFoundError:
                pass
        return

    yield


def run(command: list[str], env: dict[str, str], cwd: Path, quiet: bool) -> None:
    if not quiet:
        print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, env=env, check=True)


def comparison_env(base: dict[str, str]) -> dict[str, str]:
    env = dict(base)
    # Some exporter helpers append notices to this workflow-only path.
    # Comparison runs must have no repository-external output channel.
    env.pop("GITHUB_STEP_SUMMARY", None)
    return env


def export_env(
    base: dict[str, str], out_dir: Path, report_path: Path, today: str, song_occurrences: Path
) -> dict[str, str]:
    env = comparison_env(base)
    env["BON_ODORI_PUBLIC_OUT_DIR"] = str(out_dir)
    env["BON_ODORI_PUBLIC_DATE_PREDICTION_REPORT"] = str(report_path)
    env["BON_ODORI_PUBLIC_EVENT_SOURCE_MAP_JSON"] = str(out_dir / "public_event_source_map.json")
    # Never inherit a Notion path or an output-directory-derived empty fallback.
    env["BON_ODORI_PUBLIC_SOURCE"] = "master_rdb"
    env["BON_ODORI_SONG_OCCURRENCES_JSON"] = str(song_occurrences)
    env["BON_ODORI_PUBLIC_TODAY"] = today
    return env


def export_once(
    python: str,
    out_dir: Path,
    target_year: int,
    today: str,
    master_db: Path,
    song_occurrences: Path,
    quiet: bool,
) -> Path:
    report_path = out_dir / "public_date_prediction_apply_result.json"
    env = export_env(os.environ, out_dir, report_path, today, song_occurrences)
    run(
        [
            python,
            "export_public_events.py",
            "--target-year",
            str(target_year),
            "--today",
            today,
            "--master-db",
            str(master_db),
        ],
        env=env,
        cwd=ROOT,
        quiet=quiet,
    )
    return out_dir / "events_public.json"


def apply_legacy_overlay(
    python: str, events_path: Path, target_year: int, today: str, quiet: bool
) -> None:
    events_js = events_path.with_suffix(".js")
    report_dir = events_path.parent
    run(
        [
            python,
            "-m",
            "public_json_postprocessors.apply_public_date_predictions",
            "--public-events",
            str(events_path),
            "--out-json",
            str(events_path),
            "--out-js",
            str(events_js),
            "--report",
            str(report_dir / "legacy_date_prediction_report.json"),
            "--target-year",
            str(target_year),
        ],
        env=comparison_env(os.environ),
        cwd=ROOT,
        quiet=quiet,
    )
    run(
        [
            python,
            "-m",
            "public_json_postprocessors.apply_public_historical_references",
            "--public-events",
            str(events_path),
            "--out-json",
            str(events_path),
            "--out-js",
            str(events_js),
            "--today",
            today,
            "--target-year",
            str(target_year),
            "--report",
            str(report_dir / "legacy_historical_reference_report.json"),
        ],
        env=comparison_env(os.environ),
        cwd=ROOT,
        quiet=quiet,
    )
    run(
        [
            python,
            "-m",
            "public_json_postprocessors.apply_public_season_hints",
            "--public-events",
            str(events_path),
            "--out-json",
            str(events_path),
            "--out-js",
            str(events_js),
            "--report",
            str(report_dir / "legacy_season_hint_report.json"),
            "--target-year",
            str(target_year),
        ],
        env=comparison_env(os.environ),
        cwd=ROOT,
        quiet=quiet,
    )


def first_diff(left: Any, right: Any, path: str = "$") -> dict[str, Any] | None:
    if type(left) is not type(right):
        return {"path": path, "left": left, "right": right, "reason": "type_mismatch"}
    if isinstance(left, dict):
        left_keys = set(left)
        right_keys = set(right)
        if left_keys != right_keys:
            return {
                "path": path,
                "left_only_keys": sorted(left_keys - right_keys),
                "right_only_keys": sorted(right_keys - left_keys),
                "reason": "key_mismatch",
            }
        for key in sorted(left):
            diff = first_diff(left[key], right[key], f"{path}.{key}")
            if diff:
                return diff
        return None
    if isinstance(left, list):
        if len(left) != len(right):
            return {"path": path, "left_len": len(left), "right_len": len(right), "reason": "length_mismatch"}
        for index, (left_item, right_item) in enumerate(zip(left, right)):
            diff = first_diff(left_item, right_item, f"{path}[{index}]")
            if diff:
                return diff
        return None
    if left != right:
        return {"path": path, "left": left, "right": right, "reason": "value_mismatch"}
    return None


def compare(
    target_year: int,
    today: str,
    python: str,
    quiet: bool,
    master_db: str | None = None,
    master_manifest: str | None = None,
) -> dict[str, Any]:
    return _compare_prepared(
        target_year=target_year,
        today=today,
        python=python,
        quiet=quiet,
        master_db=Path(master_db).expanduser().resolve() if master_db else MASTER_DB,
        master_manifest=Path(master_manifest).expanduser().resolve() if master_manifest else MASTER_MANIFEST,
    )


def _compare_prepared(
    target_year: int, today: str, python: str, quiet: bool, master_db: Path, master_manifest: Path
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="public-export-compare-") as tmp:
        tmp_dir = Path(tmp)
        provenance = {
            "public_source": "master_rdb",
            "master_db": validated_manifest(master_db, master_manifest),
            "fixed_auxiliary_inputs": {
                "source": "checkout-fixed exporter inputs; no comparison environment override",
                "sha256": fixed_input_provenance(),
                "verified_unchanged": False,
            },
            "git_commit": git_commit(),
        }
        isolated_db = tmp_dir / "inputs" / MASTER_DB.name
        isolated_db_provenance = copy_isolated_master_db(
            master_db, isolated_db, master_manifest
        )
        if (
            provenance["master_db"]["database_sha256"]
            != isolated_db_provenance["sha256_before"]
        ):
            raise SystemExit(
                "Master DB changed between manifest validation and isolated copy"
            )
        provenance["isolated_master_db"] = isolated_db_provenance
        # The exporter reads this snapshot as a fallback but does not generate
        # it.  Give each run its own immutable copy so output directories can
        # never turn a missing fallback into an empty result.
        current_fallback = tmp_dir / "inputs" / "current" / SONG_OCCURRENCES_SNAPSHOT.name
        legacy_fallback = tmp_dir / "inputs" / "legacy" / SONG_OCCURRENCES_SNAPSHOT.name
        for fallback in (current_fallback, legacy_fallback):
            fallback.parent.mkdir(parents=True)
            shutil.copy2(SONG_OCCURRENCES_SNAPSHOT, fallback)
        fallback_sha256 = provenance["fixed_auxiliary_inputs"]["sha256"][
            provenance_path(SONG_OCCURRENCES_SNAPSHOT)
        ]
        if file_sha256(current_fallback) != fallback_sha256 or file_sha256(legacy_fallback) != fallback_sha256:
            raise SystemExit("Song occurrence fallback copy checksum mismatch")
        current_path = export_once(
            python, tmp_dir / "current", target_year, today, isolated_db, current_fallback, quiet
        )
        legacy_path = export_once(
            python, tmp_dir / "legacy", target_year, today, isolated_db, legacy_fallback, quiet
        )
        apply_legacy_overlay(python, legacy_path, target_year, today, quiet)
        if fixed_input_provenance() != provenance["fixed_auxiliary_inputs"]["sha256"]:
            raise SystemExit("Required export inputs changed during comparison; refusing mixed provenance")
        provenance["fixed_auxiliary_inputs"]["verified_unchanged"] = True
        if (
            file_sha256(current_fallback) != fallback_sha256
            or file_sha256(legacy_fallback) != fallback_sha256
        ):
            raise SystemExit("Song occurrence fallback changed during comparison")
        verify_isolated_master_db(isolated_db, isolated_db_provenance)
        comparisons = compare_artifacts(current_path.parent, legacy_path.parent)
        current = load_json(current_path)
        legacy = load_json(legacy_path)
        equal = all(item["equal"] for item in comparisons.values())
        return {
            "status": "pass" if equal else "fail",
            "target_year": target_year,
            "today": today,
            "event_count_current": len(current),
            "event_count_legacy_overlay": len(legacy),
            "current_sha256": digest(current),
            "legacy_overlay_sha256": digest(legacy),
            "deep_equal": equal,
            "first_diff": first_comparison_diff(comparisons),
            "artifact_comparisons": comparisons,
            "provenance": provenance,
        }


def git_commit() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def sqlite_integrity_check(path: Path) -> str:
    require_file(path, "Isolated Master DB")
    with contextlib.closing(
        sqlite3.connect(f"{path.as_uri()}?mode=ro&immutable=1", uri=True)
    ) as connection:
        result = connection.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise SystemExit(f"Isolated Master DB integrity_check failed: {result}")
    return result


def reject_sqlite_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm", "-journal"):
        sidecar = Path(f"{path}{suffix}")
        if sidecar.exists():
            raise SystemExit(
                f"Master DB has SQLite sidecar and is not a single-file artifact: {sidecar}"
            )


def copy_isolated_master_db(
    source: Path, destination: Path, manifest_path: Path
) -> dict[str, Any]:
    """Copy a verified single-file artifact without opening or changing the source."""
    reject_sqlite_sidecars(source)
    source_sha256 = file_sha256(require_file(source, "Master DB"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if file_sha256(source) != source_sha256:
        raise SystemExit("Master DB changed while making isolated copy")
    destination_manifest = validated_manifest(destination, manifest_path)
    return {
        "sha256_before": destination_manifest["database_sha256"],
        "manifest_check": destination_manifest,
        "integrity_check_before": sqlite_integrity_check(destination),
    }


def verify_isolated_master_db(path: Path, provenance: dict[str, Any]) -> None:
    if file_sha256(path) != provenance["sha256_before"]:
        raise SystemExit("Isolated Master DB changed during comparison")
    reject_sqlite_sidecars(path)
    integrity = sqlite_integrity_check(path)
    if integrity != provenance["integrity_check_before"]:
        raise SystemExit("Isolated Master DB integrity state changed during comparison")
    provenance["sha256_after"] = file_sha256(path)
    provenance["integrity_check_after"] = integrity


def compare_files(left_path: Path, right_path: Path, kind: str) -> dict[str, Any]:
    require_file(left_path, "Comparison artifact")
    require_file(right_path, "Comparison artifact")
    left = load_json(left_path) if kind == "json" else left_path.read_text(encoding="utf-8")
    right = load_json(right_path) if kind == "json" else right_path.read_text(encoding="utf-8")
    equal = left == right
    return {
        "equal": equal,
        "current_sha256": file_sha256(left_path),
        "legacy_overlay_sha256": file_sha256(right_path),
        "first_diff": None if equal else first_diff(left, right),
    }


def compare_artifacts(current_dir: Path, legacy_dir: Path) -> dict[str, dict[str, Any]]:
    return {
        name: compare_files(current_dir / name, legacy_dir / name, kind)
        for name, kind in ARTIFACTS.items()
    }


def first_comparison_diff(comparisons: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    for name, comparison in comparisons.items():
        if not comparison["equal"]:
            return {"artifact": name, **(comparison["first_diff"] or {})}
    return None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare export_public_events.py with export plus legacy postprocessor overlay."
    )
    parser.add_argument("--today", required=True, help="YYYY-MM-DD date used by date-sensitive postprocessors")
    parser.add_argument("--target-year", type=int, required=True)
    parser.add_argument("--python", default=sys.executable, help="Python executable used for child commands")
    parser.add_argument(
        "--master-db",
        help="optional path copied to data/bon_odori_master.sqlite for this comparison",
    )
    parser.add_argument(
        "--master-manifest",
        help="manifest paired with --master-db; defaults to data/bon_odori_master_manifest.json",
    )
    parser.add_argument("--out-json", default="data/public_export_postprocessor_compare.json")
    parser.add_argument("--quiet", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = compare(
        target_year=args.target_year,
        today=args.today,
        python=args.python,
        quiet=args.quiet,
        master_db=args.master_db,
        master_manifest=args.master_manifest,
    )
    out_json = ROOT / args.out_json
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        "public export postprocessor comparison: "
        f"status={report['status']} "
        f"events={report['event_count_current']} "
        f"sha256={report['current_sha256']}"
    )
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
