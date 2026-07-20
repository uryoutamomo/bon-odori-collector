#!/usr/bin/env python3
"""Run the local bon-odori review console."""

from __future__ import annotations

import argparse
import json
import os

from review_console import data
from review_console.server import serve


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8751)
    parser.add_argument("--inventory", action="store_true", help="write source inventory files and exit")
    parser.add_argument("--export", action="store_true", help="export reviewed decisions and exit")
    parser.add_argument("--stage-apply", action="store_true", help="write staged decision files and exit")
    parser.add_argument(
        "--reader-mode",
        choices=data.REVIEW_CONSOLE_READER_MODES,
        help="select the console reader; default is REVIEW_CONSOLE_READER_MODE or inbox",
    )
    parser.add_argument(
        "--preview-reader-modes",
        action="store_true",
        help="compare legacy/canary/inbox inventories read-only and exit without writing inventory files",
    )
    args = parser.parse_args()

    if args.reader_mode:
        os.environ[data.REVIEW_CONSOLE_READER_MODE_ENV] = args.reader_mode
    elif data.REVIEW_CONSOLE_READER_MODE_ENV not in os.environ:
        os.environ[data.REVIEW_CONSOLE_READER_MODE_ENV] = data.DEFAULT_REVIEW_CONSOLE_CLI_READER_MODE
    data.review_console_reader_mode()

    if args.preview_reader_modes:
        preview = data.build_reader_mode_preview()
        print(json.dumps(preview, ensure_ascii=False, indent=2, sort_keys=True))
        if not preview["ok"]:
            raise SystemExit(1)
        return

    if args.inventory:
        inventory = data.write_inventory()
        print(
            "inventory: "
            f"sources={len(inventory['sources'])} "
            f"pending={inventory['totals']['pending']} "
            f"path={data.rel_path(data.INVENTORY_MD_PATH)}"
        )
        return
    if args.export:
        exported = data.export_decisions()
        print(f"exported decisions: count={exported['decision_count']} path={data.rel_path(data.EXPORT_PATH)}")
        return
    if args.stage_apply:
        result = data.stage_apply(write=True)
        print(
            "staged decisions: "
            f"count={result['decision_count']} "
            f"files={len(result['staged_files'])} "
            f"dir={data.rel_path(data.STAGED_DIR)}"
        )
        return
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
