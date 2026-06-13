#!/usr/bin/env python3
"""Compare Notion X whitelist accounts with local x_whitelist voices."""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def norm_handle(value: object) -> str:
    return str(value or "").strip().lstrip("@").casefold()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full machine-readable result.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=40,
        help="Maximum number of missing/extra handles to print in text mode.",
    )
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")

    import collect

    voices_path = ROOT / "data" / "voices.json"
    voices = json.loads(voices_path.read_text(encoding="utf-8"))
    accounts = collect.load_whitelist_accounts()

    listed = {norm_handle(a.get("handle")) for a in accounts if norm_handle(a.get("handle"))}
    seen = {
        norm_handle(v.get("account"))
        for v in voices
        if v.get("source") == "x_whitelist" and norm_handle(v.get("account"))
    }

    missing = sorted(listed - seen)
    extra = sorted(seen - listed)
    result = {
        "listed": len(listed),
        "seen_x_whitelist": len(seen),
        "missing_count": len(missing),
        "missing": missing,
        "extra_seen_not_listed": extra,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"listed={result['listed']}")
    print(f"seen_x_whitelist={result['seen_x_whitelist']}")
    print(f"missing_count={result['missing_count']}")
    if missing:
        print("missing:")
        for handle in missing[: args.limit]:
            print(f"- {handle}")
        if len(missing) > args.limit:
            print(f"... and {len(missing) - args.limit} more")
    if extra:
        print("extra_seen_not_listed:")
        for handle in extra[: args.limit]:
            print(f"- {handle}")
        if len(extra) > args.limit:
            print(f"... and {len(extra) - args.limit} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
