"""Size budget check (SC-PERF-BUDGET-1): pass, fail and raise-the-budget paths on a synthetic tree."""
import copy
import importlib.util
import json
import subprocess
import sys

import pytest

from tests._support import ROOT

SCRIPT = ROOT / "scripts" / "check_perf_budget.py"
spec = importlib.util.spec_from_file_location("check_perf_budget", SCRIPT)
assert spec is not None and spec.loader is not None
cpb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cpb)


def entry(max_bytes, reason="test reason", **kw):
    return {"label": kw.pop("label", "x"), "max_bytes": max_bytes, "history": [{"max_bytes": max_bytes, "reason": reason}], **kw}


@pytest.fixture
def tree(tmp_path):
    """A tiny built site: landing.js (100 B) imports shared.js (50 B) and lazily map.js (900 B)."""
    client = tmp_path / "dist/client"
    (client / "assets").mkdir(parents=True)
    (client / ".vite").mkdir()
    for name, size in {"landing.js": 100, "shared.js": 50, "map.js": 900, "landing.css": 30}.items():
        (client / "assets" / name).write_bytes(b"a" * size)
    (tmp_path / "data.json").write_bytes(b"d" * 200)
    manifest = {
        "landing.html": {"file": "assets/landing.js", "imports": ["shared.js"], "dynamicImports": ["map.js"], "css": ["assets/landing.css"]},
        "shared.js": {"file": "assets/shared.js"},
        "map.js": {"file": "assets/map.js"},
    }
    (client / ".vite/manifest.json").write_text(json.dumps(manifest))
    return tmp_path


def budget(js=200, css=40, largest=1000, data=300):
    return {"budgets": {
        "js": entry(js, kind="first_load_js", entry="landing.html", label="Landing scripts"),
        "css": entry(css, kind="first_load_css", entry="landing.html", label="Landing styles"),
        "big": entry(largest, kind="largest_built_file", label="Largest file"),
        "data": entry(data, kind="files", paths=["data.json"], label="Data"),
    }}


def run(tree, b, tmp_path):
    f = tmp_path / "budget.json"
    f.write_text(json.dumps(b))
    return subprocess.run([sys.executable, str(SCRIPT), "--root", str(tree), "--budget", str(f)], capture_output=True, text=True)


def test_first_load_counts_static_imports_only(tree):
    res = cpb.measure(tree, budget())
    assert res["js"]["bytes"] == 150  # landing 100 + shared 50; the lazy 900-byte map is not first-load
    assert res["css"]["bytes"] == 30
    assert res["big"]["bytes"] == 900  # but the largest-file budget does see it
    assert res["data"]["bytes"] == 200


def test_pass(tree, tmp_path):
    r = run(tree, budget(), tmp_path)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout and "OVER BUDGET" not in r.stdout
    assert "Landing scripts" in r.stdout and "0.1 KB" in r.stdout  # plain table with sizes


def test_fail_names_the_group_and_how_to_raise(tree, tmp_path):
    r = run(tree, budget(js=100), tmp_path)
    assert r.returncode == 1
    assert "OVER BUDGET: Landing scripts" in r.stdout
    assert "assets/landing.js" in r.stdout and "perf-budget.md" in r.stdout
    assert "FAIL" in r.stdout


def test_a_big_data_file_fails(tree, tmp_path):
    (tree / "data.json").write_bytes(b"d" * 5000)
    r = run(tree, budget(), tmp_path)
    assert r.returncode == 1 and "OVER BUDGET: Data" in r.stdout


def test_raise_budget_needs_a_reason(tree, tmp_path):
    over = budget(js=100)
    assert run(tree, over, tmp_path).returncode == 1
    # Raising the number alone is refused.
    bare = copy.deepcopy(over)
    bare["budgets"]["js"]["max_bytes"] = 400
    r = run(tree, bare, tmp_path)
    assert r.returncode == 1 and "does not match the last history entry" in r.stdout
    # A history entry with a reason is accepted.
    raised = copy.deepcopy(over)
    raised["budgets"]["js"]["max_bytes"] = 400
    raised["budgets"]["js"]["history"].append({"max_bytes": 400, "reason": "adds the tide chart"})
    r = run(tree, raised, tmp_path)
    assert r.returncode == 0, r.stdout


def test_empty_reason_is_refused():
    b = budget()
    b["budgets"]["js"]["history"][-1]["reason"] = "  "
    assert cpb.validate_budget(b)


def test_missing_build_says_what_to_do(tmp_path):
    f = tmp_path / "b.json"
    f.write_text(json.dumps(budget()))
    r = subprocess.run([sys.executable, str(SCRIPT), "--root", str(tmp_path), "--budget", str(f)], capture_output=True, text=True)
    assert r.returncode == 1 and "pnpm build" in r.stdout


def test_committed_budget_file_is_valid():
    b = json.loads(cpb.DEFAULT_BUDGET.read_text())
    assert cpb.validate_budget(b) == []
    assert b["budgets"]
