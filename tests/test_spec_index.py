"""Behavioural tests for scripts/spec_index.py's public CLI."""
import subprocess
import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts/spec_index.py"
module_spec = importlib.util.spec_from_file_location("spec_index", SCRIPT)
spec_index = importlib.util.module_from_spec(module_spec); module_spec.loader.exec_module(spec_index)

def git(root, *args):
    subprocess.run(["git", *args], cwd=root, check=True, stdout=subprocess.PIPE)

def write_spec(root, name="one.md", extra="", body=""):
    p = root / "docs/spec" / name; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("---\nid: L1-one\nlayer: L1\ntitle: One\nowns:\n  - app.py\ndepends_on: []\ninvariants: []\nverified_by: []\nupdated_for: HEAD\n---\n" + body + extra)

def run(root, *args):
    return subprocess.run(["python3", str(SCRIPT), "--root", str(root), *args], text=True, capture_output=True)

def base(tmp_path):
    git(tmp_path, "init"); git(tmp_path, "config", "user.email", "t@x"); git(tmp_path, "config", "user.name", "t")
    (tmp_path / "app.py").write_text("def ok(): pass\n"); write_spec(tmp_path); git(tmp_path, "add", "."); git(tmp_path, "commit", "-m", "base")

def test_build_schema_and_impact_cases(tmp_path):
    base(tmp_path); assert run(tmp_path, "check").returncode == 0
    assert run(tmp_path, "build", "--out", "out.json").returncode == 0
    assert 'L1-one' in (tmp_path / 'out.json').read_text()
    assert 'L1-one' in run(tmp_path, 'impact', '--files', 'app.py').stdout
    assert '未記述領域' in run(tmp_path, 'impact', '--files', 'other.py').stdout
    assert '影響する仕様はありません' in spec_index.impact(spec_index.build(tmp_path), [])

def test_missing_required_key(tmp_path):
    base(tmp_path); p=tmp_path/'docs/spec/one.md'; p.write_text(p.read_text().replace('title: One\n','')); assert run(tmp_path,'check').returncode

def test_duplicate_id(tmp_path):
    base(tmp_path); write_spec(tmp_path,'two.md'); assert run(tmp_path,'check').returncode

def test_unmatched_owns(tmp_path):
    base(tmp_path); p=tmp_path/'docs/spec/one.md'; p.write_text(p.read_text().replace('app.py','gone.py')); assert run(tmp_path,'check').returncode

def test_overlapping_owns(tmp_path):
    base(tmp_path); write_spec(tmp_path,'two.md'); p=tmp_path/'docs/spec/two.md'; p.write_text(p.read_text().replace('id: L1-one','id: L1-two')); assert run(tmp_path,'check').returncode

def test_unknown_dependency(tmp_path):
    base(tmp_path); p=tmp_path/'docs/spec/one.md'; p.write_text(p.read_text().replace('depends_on: []','depends_on:\n  - unknown')); assert run(tmp_path,'check').returncode

def test_invariant_set_mismatch(tmp_path):
    base(tmp_path); p=tmp_path/'docs/spec/one.md'; p.write_text(p.read_text().replace('invariants: []','invariants:\n  - INV-ONE-001')); assert run(tmp_path,'check').returncode

def test_missing_invariant_test(tmp_path):
    base(tmp_path); p=tmp_path/'docs/spec/one.md'; p.write_text(p.read_text().replace('invariants: []','invariants:\n  - INV-ONE-001')+'\n### INV-ONE-001 title\n- **守っているテスト**: `tests/no.py::test_no`\n'); assert run(tmp_path,'check').returncode

def test_broken_relative_link(tmp_path):
    base(tmp_path); p=tmp_path/'docs/spec/one.md'; p.write_text(p.read_text()+'[broken](missing.md)'); assert run(tmp_path,'check').returncode
