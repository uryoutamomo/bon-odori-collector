#!/usr/bin/env python3
"""Sync X account scores into the Notion member list.

This is a stable entrypoint for local runs. It replaces ad-hoc
`python3 -c ...` one-liners so Codex approval can be scoped to this file.
"""

import argparse
import os
from pathlib import Path

from manual_apply_guards import LEGACY_NOTION_REPAIR_CONFIRMATION, require_confirmation


def load_dotenv(path=".env"):
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm", default="")
    args = parser.parse_args()

    load_dotenv()

    import collect

    cfg = collect._load_x_config() or {}
    accounts = collect.load_whitelist_accounts()
    if args.dry_run:
        print(f"accounts={len(accounts)}")
        return 0
    try:
        require_confirmation(
            True,
            args.confirm,
            LEGACY_NOTION_REPAIR_CONFIRMATION,
            "legacy X account score sync",
        )
    except ValueError as exc:
        parser.error(str(exc))
    collect._sync_x_account_scores_to_notion(accounts, cfg)
    print(f"accounts={len(accounts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
