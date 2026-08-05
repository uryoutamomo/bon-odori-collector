#!/usr/bin/env python3
"""Build a trusted P4 finite-action payload from review-console staging.

This command is pure file transformation. It does not open the Master RDB,
write review lifecycle state, publish S3 artifacts, or change public data.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from review_inbox_adapters.source_writer import SourceWriterError
from song_candidate_finite_actions import build_reviewed_payload_from_decision_stage


def load_stage(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SourceWriterError(f"invalid song decision stage JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise SourceWriterError("song decision stage root must be an object")
    return payload


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged-actions", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.staged_actions.resolve() == args.out_json.resolve():
        raise SourceWriterError("staged input and finite payload output must differ")
    payload = build_reviewed_payload_from_decision_stage(load_stage(args.staged_actions))
    write_json_atomic(args.out_json, payload)
    print(f"wrote {args.out_json} ({payload['decision_count']} finite actions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
