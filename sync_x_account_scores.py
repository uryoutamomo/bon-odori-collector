#!/usr/bin/env python3
"""Sync X account scores into the Notion member list.

This is a stable entrypoint for local runs. It replaces ad-hoc
`python3 -c ...` one-liners so Codex approval can be scoped to this file.
"""

import os
import sys
from pathlib import Path


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
    load_dotenv()

    import collect

    cfg = collect._load_x_config() or {}
    accounts = collect.load_whitelist_accounts()
    if "--dry-run" in sys.argv:
        print(f"accounts={len(accounts)}")
        return 0
    collect._sync_x_account_scores_to_notion(accounts, cfg)
    print(f"accounts={len(accounts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
