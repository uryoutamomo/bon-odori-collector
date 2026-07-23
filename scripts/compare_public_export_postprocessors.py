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
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MASTER_DB = ROOT / "data" / "bon_odori_master.sqlite"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


@contextlib.contextmanager
def prepared_master_db(source: str | None):
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


def export_env(base: dict[str, str], out_dir: Path, report_path: Path, today: str) -> dict[str, str]:
    env = dict(base)
    env["BON_ODORI_PUBLIC_OUT_DIR"] = str(out_dir)
    env["BON_ODORI_PUBLIC_DATE_PREDICTION_REPORT"] = str(report_path)
    env["BON_ODORI_PUBLIC_EVENT_SOURCE_MAP_JSON"] = str(out_dir / "public_event_source_map.json")
    env["BON_ODORI_PUBLIC_TODAY"] = today
    return env


def export_once(
    python: str, out_dir: Path, target_year: int, today: str, quiet: bool
) -> Path:
    report_path = out_dir / "public_date_prediction_apply_result.json"
    env = export_env(os.environ, out_dir, report_path, today)
    run(
        [
            python,
            "export_public_events.py",
            "--target-year",
            str(target_year),
            "--today",
            today,
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
        env=dict(os.environ),
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
        env=dict(os.environ),
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
        env=dict(os.environ),
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
) -> dict[str, Any]:
    with prepared_master_db(master_db):
        return _compare_prepared(
            target_year=target_year, today=today, python=python, quiet=quiet
        )


def _compare_prepared(
    target_year: int, today: str, python: str, quiet: bool
) -> dict[str, Any]:
    if not MASTER_DB.exists():
        raise SystemExit(f"Master DB is missing: {MASTER_DB}")
    with tempfile.TemporaryDirectory(prefix="public-export-compare-") as tmp:
        tmp_dir = Path(tmp)
        current_path = export_once(
            python, tmp_dir / "current", target_year, today, quiet
        )
        legacy_path = export_once(
            python, tmp_dir / "legacy", target_year, today, quiet
        )
        apply_legacy_overlay(python, legacy_path, target_year, today, quiet)

        current = load_json(current_path)
        legacy = load_json(legacy_path)
        equal = current == legacy
        return {
            "status": "pass" if equal else "fail",
            "target_year": target_year,
            "today": today,
            "event_count_current": len(current),
            "event_count_legacy_overlay": len(legacy),
            "current_sha256": digest(current),
            "legacy_overlay_sha256": digest(legacy),
            "deep_equal": equal,
            "first_diff": None if equal else first_diff(current, legacy),
        }


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
