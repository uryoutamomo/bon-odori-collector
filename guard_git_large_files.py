"""Guard against committing files near GitHub's hard file-size limit."""

import argparse
import subprocess
from pathlib import Path


DEFAULT_WARN_MIB = 50
DEFAULT_BLOCK_MIB = 95
SCRIPT_NAME = "guard_git_large_files.py"


def mib_to_bytes(value):
    return int(value * 1024 * 1024)


def format_mib(size_bytes):
    return f"{size_bytes / 1024 / 1024:.2f} MiB"


def tracked_files(root):
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        stdout=subprocess.PIPE,
    )
    return [Path(item.decode("utf-8")) for item in result.stdout.split(b"\0") if item]


def classify_files(root, paths, warn_bytes, block_bytes):
    rows = []
    for rel_path in paths:
        full_path = root / rel_path
        if not full_path.is_file():
            continue
        size = full_path.stat().st_size
        if size >= block_bytes:
            severity = "block"
        elif size >= warn_bytes:
            severity = "warn"
        else:
            continue
        rows.append({"path": str(rel_path), "size_bytes": size, "severity": severity})
    rows.sort(key=lambda row: (-row["size_bytes"], row["path"]))
    return rows


def render(rows, warn_mib, block_mib):
    lines = [
        f"{SCRIPT_NAME}: warn>={warn_mib}MiB block>={block_mib}MiB",
    ]
    if not rows:
        lines.append("no tracked files exceed warning threshold")
        return "\n".join(lines)
    for row in rows:
        lines.append(f"{row['severity']} {row['path']} {format_mib(row['size_bytes'])}")
    return "\n".join(lines)


def run(args):
    root = Path(args.root).resolve()
    warn_bytes = mib_to_bytes(args.warn_mib)
    block_bytes = mib_to_bytes(args.block_mib)
    if warn_bytes >= block_bytes:
        raise SystemExit("--warn-mib must be smaller than --block-mib")
    paths = [Path(item) for item in args.paths] if args.paths else tracked_files(root)
    rows = classify_files(root, paths, warn_bytes, block_bytes)
    print(render(rows, args.warn_mib, args.block_mib))
    return 1 if any(row["severity"] == "block" for row in rows) else 0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    parser.add_argument("--warn-mib", type=float, default=DEFAULT_WARN_MIB)
    parser.add_argument("--block-mib", type=float, default=DEFAULT_BLOCK_MIB)
    parser.add_argument("paths", nargs="*")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
