#!/usr/bin/env python3
"""Evaluate master RDB migration freeze groups for workflows."""

import argparse
import json
import sys
from pathlib import Path


DEFAULT_FREEZE_FILE = Path("data/master_rdb_migration_freeze.json")


def load_policy(path):
    if not path.exists():
        return {"exists": False, "malformed": False, "data": {}}
    try:
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {"exists": True, "malformed": True, "data": {}}
    if not isinstance(data, dict):
        return {"exists": True, "malformed": True, "data": {}}
    return {"exists": True, "malformed": False, "data": data}


def is_group_frozen(policy, group):
    if not policy["exists"]:
        return False
    if policy["malformed"]:
        return True

    data = policy["data"]
    if data.get("active") is False:
        return False

    groups = data.get("freeze_groups")
    if isinstance(groups, dict):
        group_policy = groups.get(group)
        if not isinstance(group_policy, dict):
            return True
        return group_policy.get("active") is not False

    # Legacy freeze file: top-level active=true meant every listed migration
    # output was frozen. Keep the safe behavior until freeze_groups is present.
    return bool(data.get("active"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=["is-frozen", "is-released", "explain"],
        help="Return status for a freeze group. is-frozen exits 0 when frozen; is-released exits 0 when not frozen.",
    )
    parser.add_argument("group")
    parser.add_argument("--freeze-file", type=Path, default=DEFAULT_FREEZE_FILE)
    args = parser.parse_args()

    policy = load_policy(args.freeze_file)
    frozen = is_group_frozen(policy, args.group)

    if args.command == "explain":
        state = "frozen" if frozen else "released"
        if not policy["exists"]:
            reason = "freeze file not found"
        elif policy["malformed"]:
            reason = "freeze file malformed"
        elif not isinstance(policy["data"].get("freeze_groups"), dict):
            reason = "legacy top-level active freeze"
        else:
            reason = "freeze_groups"
        print(f"{args.group}: {state} ({reason})")
        return 0

    if args.command == "is-frozen":
        return 0 if frozen else 1
    return 1 if frozen else 0


if __name__ == "__main__":
    sys.exit(main())
