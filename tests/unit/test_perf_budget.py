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


def startup_budget(each=300, anyfile=1000):
    return {"budgets": {
        "startup": entry(each, kind="largest_matching", label="Startup data", globs=["dist/client/regions/*/atlas-marks.json"]),
        "any": entry(anyfile, kind="largest_matching", label="Any site file", globs=["dist/client/**/*"], exclude=["dist/client/assets/"]),
    }}


def test_oversized_startup_file_not_on_any_list_fails(tree, tmp_path):
    marks = tree / "dist/client/regions/morro-bay/atlas-marks.json"
    marks.parent.mkdir(parents=True)
    marks.write_bytes(b"m" * 200)
    assert run(tree, startup_budget(), tmp_path).returncode == 0
    marks.write_bytes(b"m" * 5000)  # the 15 MB regression, scaled down
    r = run(tree, startup_budget(), tmp_path)
    assert r.returncode == 1 and "OVER BUDGET: Startup data" in r.stdout and "atlas-marks.json" in r.stdout
    # A data file no list names is caught by the catch-all.
    marks.write_bytes(b"m" * 200)
    other = tree / "dist/client/data/new-thing.json"
    other.parent.mkdir(parents=True)
    other.write_bytes(b"o" * 5000)
    r = run(tree, startup_budget(), tmp_path)
    assert r.returncode == 1 and "OVER BUDGET: Any site file" in r.stdout and "new-thing.json" in r.stdout
    # Raising the catch-all needs a reason, like every other budget.
    b = startup_budget(anyfile=6000)
    b["budgets"]["any"]["history"].append({"max_bytes": 6000, "reason": "new data file"})
    b["budgets"]["any"]["max_bytes"] = 6000
    assert run(tree, b, tmp_path).returncode == 0


def test_no_matching_files_is_an_error_not_a_pass(tree, tmp_path):
    r = run(tree, startup_budget(), tmp_path)
    assert r.returncode != 0


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


def test_parallel_app_shell_stays_in_first_load_budget(tree, tmp_path):
    client = tree / "dist/client"
    path = client / ".vite/manifest.json"
    manifest = json.loads(path.read_text())
    manifest["app.html"] = {"file": "assets/boot.js", "dynamicImports": ["../web/app/main.tsx", "map.js"]}
    manifest["../web/app/main.tsx"] = manifest["landing.html"]
    (client / "assets/boot.js").write_bytes(b"b" * 10)
    path.write_text(json.dumps(manifest))
    b = budget(js=159)
    for key in ["js", "css"]:
        b["budgets"][key]["entry"] = "app.html"
    res = cpb.measure(tree, b)
    assert res["js"]["bytes"] == 160  # bootstrap + shell + shared, not the optional 900-byte map
    assert res["css"]["bytes"] == 30
    assert "OVER BUDGET: Landing scripts" in run(tree, b, tmp_path).stdout
    del manifest["../web/app/main.tsx"]
    path.write_text(json.dumps(manifest))
    with pytest.raises(KeyError):
        cpb.measure(tree, b)  # a lost mandatory-shell manifest entry fails closed


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


@pytest.mark.parametrize("bad", [
    [], {}, {"budgets": []}, {"budgets": {"js": "x"}},
    {"budgets": {"js": {"max_bytes": 5, "history": ["x"]}}},
])
def test_misshaped_budget_is_reported_not_raised(bad):
    assert cpb.validate_budget(bad)


@pytest.mark.parametrize("v", [True, 0, -5, 1.5])
def test_bad_max_bytes_is_reported(v):
    b = budget()
    b["budgets"]["js"]["history"][-1]["max_bytes"] = v
    b["budgets"]["js"]["max_bytes"] = v
    assert cpb.validate_budget(b)
    b2 = budget()
    b2["budgets"]["js"]["max_bytes"] = v
    assert cpb.validate_budget(b2)


def test_max_bytes_one_is_accepted():
    assert cpb.validate_budget({"budgets": {"js": entry(1)}}) == []


@pytest.mark.parametrize("content", [None, "{"])
def test_unreadable_budget_file_is_one_problem_line(tmp_path, content, capsys):
    f = tmp_path / "b.json"
    if content is not None:
        f.write_text(content)
    assert cpb.main(["--budget", str(f)]) == 1
    out = capsys.readouterr().out
    assert out.count("BUDGET FILE PROBLEM") == 1 and "Traceback" not in out


BAD_CEILINGS = [0, -1, True, False, 1.0, "1", None]


@pytest.mark.parametrize("v", BAD_CEILINGS)
def test_bad_current_ceiling_with_valid_history_is_named(v):
    b = budget()
    b["budgets"]["js"]["max_bytes"] = v
    assert cpb.validate_budget(b) == ["js: max_bytes must be a positive integer"]


def test_true_current_ceiling_does_not_pass_by_equality_with_history_one():
    b = {"budgets": {"js": entry(1)}}
    b["budgets"]["js"]["max_bytes"] = True
    assert cpb.validate_budget(b) == ["js: max_bytes must be a positive integer"]


@pytest.mark.parametrize("v", BAD_CEILINGS)
def test_bad_earlier_history_entry_is_caught_even_if_last_is_valid(v):
    b = budget()
    b["budgets"]["js"]["history"].insert(0, {"max_bytes": v, "reason": "old"})
    assert cpb.validate_budget(b) == ["js: every history entry needs a positive integer max_bytes and a reason"]


@pytest.mark.parametrize("v", [0, True])
def test_main_refuses_bad_ceiling_before_measure_or_render(tmp_path, monkeypatch, capsys, v):
    b = budget()
    b["budgets"]["js"]["max_bytes"] = v
    b["budgets"]["js"]["history"][-1]["max_bytes"] = v
    f = tmp_path / "b.json"
    f.write_text(json.dumps(b))

    def boom(*a, **k):
        raise AssertionError("measure/render must not run")

    monkeypatch.setattr(cpb, "measure", boom)
    monkeypatch.setattr(cpb, "render", boom)
    assert cpb.main(["--root", str(tmp_path), "--budget", str(f)]) == 1
    out = capsys.readouterr().out
    assert "BUDGET FILE PROBLEM" in out and "positive integer" in out and "Traceback" not in out


def test_large_positive_ceiling_is_valid():
    assert cpb.validate_budget({"budgets": {"js": entry(10**12)}}) == []
