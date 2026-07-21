#!/usr/bin/env python3
"""Build a deterministic reference inventory for root-level Python files."""

from __future__ import annotations

import argparse
import ast
from collections import Counter
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JSON = ROOT / "docs" / "root-python-inventory-20260721.json"
DEFAULT_MARKDOWN = ROOT / "docs" / "root-python-inventory-20260721.md"
TEXT_SUFFIXES = {".json", ".md", ".py", ".sh", ".toml", ".txt", ".yaml", ".yml"}
GENERATED_PATHS = {
    "docs/root-python-inventory-20260721.json",
    "docs/root-python-inventory-20260721.md",
}

# These are intentionally still in root because current code imports or invokes
# them. Their policy is legacy/manual, but moving them would be a code refactor,
# not a no-reference archive operation.
RETAINED_LEGACY_DEPENDENCIES = {
    "apply_retrospective_ready_venue_events.py",
    "apply_weekly_harvest_human13_decisions.py",
    "apply_weekly_song_final_corrections.py",
    "apply_weekly_song_review_decisions.py",
    "register_song_master_initial.py",
    "sync_x_account_scores.py",
}


def tracked_paths(root: Path) -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [root / raw.decode() for raw in result.stdout.split(b"\0") if raw]


def imported_root_modules(path: Path, root_modules: set[str]) -> set[str]:
    if path.suffix != ".py":
        return set()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return set()
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            candidates = [alias.name.split(".", 1)[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            candidates = [node.module.split(".", 1)[0]]
        else:
            continue
        found.update(candidate for candidate in candidates if candidate in root_modules)
    return found


def reference_buckets(root: Path, root_files: list[Path]) -> dict[str, dict[str, list[str]]]:
    names = {path.name for path in root_files}
    stems = {path.stem for path in root_files}
    references = {
        name: {"workflow": [], "source": [], "test": [], "docs": [], "data": [], "legacy": []}
        for name in names
    }
    for path in tracked_paths(root):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in GENERATED_PATHS or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        imported = imported_root_modules(path, stems)
        for name in names:
            if relative == name:
                continue
            referenced = name in text or Path(name).stem in imported
            if not referenced:
                continue
            if relative.startswith(".github/workflows/"):
                bucket = "workflow"
            elif relative.startswith("tests/"):
                bucket = "test"
            elif relative.startswith("docs/"):
                bucket = "docs"
            elif relative.startswith("data/"):
                bucket = "data"
            elif relative.startswith("legacy/"):
                bucket = "legacy"
            elif path.suffix == ".py":
                bucket = "source"
            else:
                continue
            references[name][bucket].append(relative)
    for buckets in references.values():
        for paths in buckets.values():
            paths.sort()
    return references


def classify(name: str, refs: dict[str, list[str]]) -> str:
    if name in RETAINED_LEGACY_DEPENDENCIES:
        return "retained_legacy_dependency"
    if refs["workflow"]:
        return "workflow_entrypoint"
    if refs["source"]:
        return "source_dependency"
    if refs["test"]:
        return "test_supported_manual"
    if refs["docs"]:
        return "documented_manual"
    return "review_candidate"


def build_inventory(root: Path, as_of: str) -> dict:
    root_files = sorted(path for path in root.glob("*.py") if path.is_file())
    refs_by_name = reference_buckets(root, root_files)
    items = []
    for path in root_files:
        refs = refs_by_name[path.name]
        items.append(
            {
                "path": path.name,
                "classification": classify(path.name, refs),
                "references": refs,
            }
        )
    counts = Counter(item["classification"] for item in items)
    legacy_count = sum(1 for path in (root / "legacy").rglob("*.py") if path.is_file())
    return {
        "schema_version": 1,
        "as_of": as_of,
        "summary": {
            "root_python_count": len(items),
            "legacy_python_count": legacy_count,
            "classification_counts": dict(sorted(counts.items())),
        },
        "classification_rules": {
            "workflow_entrypoint": "Referenced by a GitHub Actions workflow.",
            "source_dependency": "Imported or invoked by non-test, non-legacy Python code.",
            "retained_legacy_dependency": "Manual/legacy policy applies, but current root code still depends on it.",
            "test_supported_manual": "No live code reference; tests still exercise or inventory it.",
            "documented_manual": "No live code/test reference; an operations document still names it.",
            "review_candidate": "No workflow, live-code, test, or docs reference; review before moving.",
        },
        "items": items,
    }


def render_markdown(inventory: dict) -> str:
    summary = inventory["summary"]
    counts = summary["classification_counts"]
    candidates = [
        item["path"]
        for item in inventory["items"]
        if item["classification"] == "review_candidate"
    ]
    lines = [
        "# Root Python inventory",
        "",
        f"基準日: {inventory['as_of']} JST",
        "",
        "この台帳は参照シグナルの棚卸しであり、`review_candidate` を自動削除・自動移動しない。",
        "移動前に用途・生成物・git履歴を個別確認する。",
        "",
        "## Summary",
        "",
        "| metric | count |",
        "| --- | ---: |",
        f"| root `*.py` | {summary['root_python_count']} |",
        f"| `legacy/**/*.py` | {summary['legacy_python_count']} |",
    ]
    for classification, count in sorted(counts.items()):
        lines.append(f"| `{classification}` | {count} |")
    lines.extend(
        [
            "",
            "## Review candidates",
            "",
            "workflow・現役Python・tests・docsから参照されない候補。名前だけで退役判断しない。",
            "",
        ]
    )
    lines.extend(f"- `{path}`" for path in candidates)
    lines.extend(
        [
            "",
            "## Regenerate",
            "",
            "```bash",
            "python3 scripts/build_root_python_inventory.py --as-of 2026-07-21",
            "```",
            "",
            "署名: おと（Codex）",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    args = parser.parse_args()
    inventory = build_inventory(ROOT, args.as_of)
    args.json.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.markdown.write_text(render_markdown(inventory), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
