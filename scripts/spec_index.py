#!/usr/bin/env python3
"""Build and check the machine-readable index for docs/spec."""
import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

REQUIRED = ("id", "layer", "title", "owns", "depends_on", "invariants", "verified_by", "updated_for")
INV_HEADING = re.compile(r"^### (INV-[A-Za-z0-9]+-\d+)\s+(.+?)\s*$", re.M)
TEST_LINE = re.compile(r"^- \*\*守っているテスト\*\*:\s*(.+?)\s*$", re.M)
MD_LINK = re.compile(r"(?<!\!)\[[^]]+\]\(([^)#]+)(?:#[^)]+)?\)")


def git(root, *args, check=True):
    p = subprocess.run(["git", *args], cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and p.returncode:
        raise RuntimeError(p.stderr.strip())
    return p.stdout.strip()


def scalar(value):
    value = value.strip()
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    if value in ("[]", ""):
        return [] if value == "[]" else ""
    return value


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    data, key = {}, None
    for raw in text[4:end].splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw.startswith("  - ") and key:
            data.setdefault(key, []).append(scalar(raw[4:]))
        elif ":" in raw:
            key, value = raw.split(":", 1)
            key, value = key.strip(), ([] if not value.strip() else scalar(value))
            data[key] = value
    return data, text[end + 4:].lstrip("\n")


def specs(root):
    result = []
    for path in sorted((root / "docs/spec").rglob("*.md")):
        if path.name == "index.json":
            continue
        fm, body = frontmatter(path)
        result.append((path.relative_to(root).as_posix(), fm, body))
    return result


def expand(root, patterns):
    files = set()
    tracked = git(root, "ls-files").splitlines()
    for pattern in patterns if isinstance(patterns, list) else []:
        # Path.match correctly handles both foo/** and ordinary glob patterns.
        files.update(p for p in tracked if Path(p).match(pattern) or (pattern.endswith("/**") and p.startswith(pattern[:-2])))
    return sorted(files)


def parse_invariants(body):
    body = re.sub(r"```.*?```", "", body, flags=re.S)
    found = {}
    matches = list(INV_HEADING.finditer(body))
    for i, match in enumerate(matches):
        section = body[match.end():matches[i + 1].start() if i + 1 < len(matches) else len(body)]
        test_match = TEST_LINE.search(section)
        raw = test_match.group(1).strip() if test_match else "**なし（要追加）**"
        tests = [] if "なし（要追加）" in raw else re.findall(r"`([^`]+)`", raw)
        found[match.group(1)] = {"title": match.group(2), "tests": tests, "has_test": bool(tests)}
    return found


def test_exists(root, test):
    file_name, sep, function = test.partition("::")
    path = root / file_name
    return path.is_file() and (not sep or function in path.read_text(encoding="utf-8"))


def validate(root, rows):
    errors, warnings, ids, owners = [], [], {}, {}
    for path, fm, body in rows:
        missing = [k for k in REQUIRED if k not in fm]
        if missing: errors.append(f"{path}: missing front matter keys: {', '.join(missing)}")
        ident = fm.get("id")
        if ident:
            if ident in ids: errors.append(f"duplicate id: {ident}")
            ids[ident] = path
        owned = expand(root, fm.get("owns", []))
        for pattern in fm.get("owns", []) if isinstance(fm.get("owns"), list) else []:
            if not expand(root, [pattern]): errors.append(f"{path}: owns matches no files: {pattern}")
        for file in owned:
            if file in owners: errors.append(f"{file}: owned by both {owners[file]} and {ident}")
            owners[file] = ident
        parsed = parse_invariants(body)
        declared = set(fm.get("invariants", []) if isinstance(fm.get("invariants"), list) else [])
        if declared != set(parsed): errors.append(f"{path}: front matter invariants do not match INV headings")
        for inv in parsed.values():
            for test in inv["tests"]:
                if not test_exists(root, test): errors.append(f"{path}: invariant test not found: {test}")
        for target in MD_LINK.findall(body):
            if not (root / path).parent.joinpath(target).resolve().is_file(): errors.append(f"{path}: broken relative link: {target}")
    for path, fm, _ in rows:
        for dep in fm.get("depends_on", []) if isinstance(fm.get("depends_on"), list) else []:
            if dep not in ids: errors.append(f"{path}: unknown dependency: {dep}")
    return errors, warnings, owners


def staleness(root, base, files):
    if not base or subprocess.run(["git", "cat-file", "-e", base + "^{commit}"], cwd=root).returncode:
        return None
    log = git(root, "log", "--format=%H", base + "..HEAD", "--", *files) if files else ""
    changed = git(root, "diff", "--name-only", base + "..HEAD", "--", *files).splitlines() if files else []
    return {"commits_since": len([x for x in log.splitlines() if x]), "files_changed_since": len(set(changed))}


def build(root):
    rows = specs(root); _, _, owners = validate(root, rows)
    source = [p for p in git(root, "ls-files", "*.py").splitlines() if not p.startswith(("legacy/", "tests/"))]
    output = {"generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "generated_for_commit": git(root, "rev-parse", "--short", "HEAD"), "specs": {}, "invariants": {}, "file_to_spec": owners, "coverage": {"tracked_source_files": len(source), "owned": len(set(source) & set(owners)), "unowned": len(set(source) - set(owners)), "unowned_samples": sorted(set(source) - set(owners))[:20]}}
    for path, fm, body in rows:
        ident = fm.get("id")
        if not ident: continue
        owned = expand(root, fm.get("owns", []))
        output["specs"][ident] = {k: fm.get(k, []) if k in ("owns", "depends_on", "invariants", "verified_by") else fm.get(k) for k in ("layer", "title", "owns", "depends_on", "invariants", "verified_by", "updated_for")}
        output["specs"][ident].update({"path": path, "owned_files": owned, "staleness": staleness(root, fm.get("updated_for"), owned)})
        for inv_id, inv in parse_invariants(body).items(): output["invariants"][inv_id] = {"spec": ident, **inv}
    return output


def impact(index, files):
    matches = [(f, index["file_to_spec"].get(f)) for f in files]
    hits = sorted({s for _, s in matches if s})
    if not matches: return "影響する仕様はありません。"
    lines = ["## 仕様への影響", "", "| 変更ファイル | 仕様 | 不変条件 |", "| --- | --- | --- |"]
    for f, spec in matches:
        invs = ", ".join(index["specs"][spec]["invariants"]) if spec else "—"
        lines.append(f"| `{f}` | {spec or '未記述'} | {invs} |")
    indirect = sorted({dep for s in hits for dep in index["specs"][s]["depends_on"]})
    if indirect: lines += ["", "### 間接的に影響しうる仕様", "", *[f"- {x}" for x in indirect]]
    unowned = [f for f, s in matches if not s]
    if unowned: lines += ["", "### 未記述領域", "", *[f"- `{x}`" for x in unowned], "", "未記述領域なのでソースを直接読む必要があります。"]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--root", default=".")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build"); b.add_argument("--out", required=True)
    sub.add_parser("check")
    i = sub.add_parser("impact"); i.add_argument("--files", nargs="*")
    args = parser.parse_args(); root = Path(args.root).resolve()
    if args.cmd == "check":
        errors, warnings, _ = validate(root, specs(root))
        for msg in warnings: print("warning: " + msg, file=sys.stderr)
        for msg in errors: print("error: " + msg, file=sys.stderr)
        return bool(errors)
    index = build(root)
    if args.cmd == "build": (root / args.out).resolve().write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"); return False
    files = args.files if args.files else git(root, "diff", "--name-only", "origin/main...HEAD").splitlines()
    print(impact(index, files)); return False
if __name__ == "__main__": raise SystemExit(main())
