import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RISKY_CONNECT_TARGETS = {
    "master_db",
    "target_db",
}


def _is_sqlite_connect(call):
    func = call.func
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "connect"
        and isinstance(func.value, ast.Name)
        and func.value.id == "sqlite3"
    )


def _target_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if (
        isinstance(node, ast.Attribute)
        and node.attr in {"master_db", "db"}
        and isinstance(node.value, ast.Name)
        and node.value.id == "args"
    ):
        return f"args.{node.attr}"
    return ""


def test_master_db_paths_use_non_creating_connection_helper():
    violations = []
    for path in ROOT.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_sqlite_connect(node) or not node.args:
                continue
            target = _target_name(node.args[0])
            if target in RISKY_CONNECT_TARGETS or target in {"args.master_db", "args.db"}:
                violations.append(f"{path.name}:{node.lineno} sqlite3.connect({target})")

    assert violations == []
