"""Budget headroom (SC-CI-2): WARN from 97%, fail only above the number, and the drift bot's arithmetic and file edits."""
import importlib.util
import json
import re
import shutil
import subprocess
import sys

import pytest

from tests._support import ROOT

SCRIPTS = ROOT / "scripts"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cpb = load("check_perf_budget")
bd = load("budget_drift")


def test_warn_ratio_is_the_same_in_both_checkers():
    mjs = (SCRIPTS / "check_client.mjs").read_text()
    assert re.search(r"const WARN_RATIO = 0\.97;", mjs)
    assert cpb.WARN_RATIO == 0.97 == bd.WARN_RATIO


@pytest.mark.parametrize("used,status", [(0, "OK"), (9_699, "OK"), (9_700, "WARN"), (9_999, "WARN"), (10_000, "WARN"), (10_001, "OVER BUDGET")])
def test_status_thresholds(used, status):
    assert cpb.status_of(used, 10_000) == status


@pytest.mark.parametrize("measured,expected", [(305_509, 321_000), (29_488, 31_000), (1_000, 2_000), (1_904, 2_000), (1_905, 3_000)])
def test_ceiling_is_measured_plus_5_percent_rounded_up_to_1000(measured, expected):
    assert bd.ceiling_for(measured) == expected
    assert bd.ceiling_for(measured) >= measured * 1.05


def test_new_ceiling_is_never_inside_the_warn_band():
    # Otherwise the bot would reopen its own pull request on the next run.
    for measured in range(1, 5_000_000, 997):
        assert measured < bd.WARN_RATIO * bd.ceiling_for(measured) or measured < 1_000


def test_cause_is_one_plain_line():
    assert bd.clean_cause("Fix\nthe `thing`\x00\u202e\r\n  now" + "x" * 500).count("\n") == 0
    assert len(bd.clean_cause("y" * 500)) == 160
    assert bd.clean_cause("") == "main, commit not named"


def tiny_tree(tmp_path, js_bytes):
    client = tmp_path / "dist/client"
    (client / "assets").mkdir(parents=True)
    (client / ".vite").mkdir()
    (client / "assets/landing.js").write_bytes(b"a" * js_bytes)
    (client / ".vite/manifest.json").write_text(json.dumps({"landing.html": {"file": "assets/landing.js"}}))
    return tmp_path


def budget_file(tmp_path, max_bytes):
    f = tmp_path / "budget.json"
    f.write_text(json.dumps({"budgets": {"js": {"label": "Landing scripts", "kind": "first_load_js", "entry": "landing.html",
                                                "max_bytes": max_bytes, "history": [{"max_bytes": max_bytes, "reason": "start"}]}}}))
    return f


def run_check(tmp_path, f):
    return subprocess.run([sys.executable, str(SCRIPTS / "check_perf_budget.py"), "--root", str(tmp_path), "--budget", str(f)],
                          capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"})


def test_a_budget_at_98_percent_passes_with_a_warning(tmp_path):
    tree = tiny_tree(tmp_path, 980)
    r = run_check(tree, budget_file(tmp_path, 1000))
    assert r.returncode == 0, r.stdout
    assert "WARN" in r.stdout and "98.0% of its budget" in r.stdout and "PASS" in r.stdout and "OVER BUDGET" not in r.stdout
    assert "::warning" not in r.stdout  # annotations only inside GitHub Actions


def test_a_budget_at_96_percent_is_quiet_and_one_byte_over_fails(tmp_path):
    tree = tiny_tree(tmp_path, 960)
    r = run_check(tree, budget_file(tmp_path, 1000))
    assert r.returncode == 0 and "WARN" not in r.stdout
    over = tmp_path / "over"
    over.mkdir()
    r = run_check(tiny_tree(over, 1001), budget_file(over, 1000))
    assert r.returncode == 1 and "OVER BUDGET: Landing scripts" in r.stdout


def test_actions_annotation(tmp_path):
    tree = tiny_tree(tmp_path, 990)
    f = budget_file(tmp_path, 1000)
    r = subprocess.run([sys.executable, str(SCRIPTS / "check_perf_budget.py"), "--root", str(tree), "--budget", str(f)],
                       capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "GITHUB_ACTIONS": "true"})
    assert r.returncode == 0 and "::warning title=Size budget near its ceiling::Landing scripts is at 99.0%" in r.stdout


@pytest.fixture
def repo_copy(tmp_path, monkeypatch):
    """The real budget files copied into tmp, so --apply edits never touch the checkout."""
    for name in ("perf-budget.json", "startup-budget.json"):
        shutil.copy(SCRIPTS / name, tmp_path / name)
    monkeypatch.setattr(bd, "PERF_FILE", tmp_path / "perf-budget.json")
    monkeypatch.setattr(bd, "STARTUP_FILE", tmp_path / "startup-budget.json")
    return tmp_path


def real_budgets():
    return json.loads((SCRIPTS / "perf-budget.json").read_text()), json.loads((SCRIPTS / "startup-budget.json").read_text())


def test_committed_budget_files_are_consistent():
    assert bd.check_files() == []


def test_client_targets_cover_precache_and_both_pages(repo_copy):
    startup = json.loads(bd.STARTUP_FILE.read_text())
    meas = {"precache": {"install": 1, "pack_shell": 2}, "bundles": {"app.html": {"js": 3, "css": 4}, "landing.html": {"js": 5, "css": 6}}}
    keys = {t["key"] for t in bd.client_targets(startup, meas)}
    assert keys == {"precache/install_raw_max", "precache/pack_shell_raw_max", "bundles/app.html/js_gzip_max", "bundles/app.html/css_gzip_max",
                    "bundles/landing.html/js_gzip_max", "bundles/landing.html/css_gzip_max"}


def test_apply_raises_only_budgets_at_97_percent_and_is_then_quiet(repo_copy, tmp_path, monkeypatch):
    startup = json.loads(bd.STARTUP_FILE.read_text())
    perf = json.loads(bd.PERF_FILE.read_text())
    pack = startup["precache"]["pack_shell_raw_max"]
    install = startup["precache"]["install_raw_max"]
    css_max = startup["bundles"]["app.html"]["css_gzip_max"]
    meas = {"precache": {"install": install // 2, "pack_shell": pack - 3},   # pack shell 3 B under its number; install far under
            "bundles": {"app.html": {"js": 10, "css": css_max + 7}}}          # app css 7 B OVER its number (main red today)
    # perf groups are measured from a built tree; stand in for the measurement
    perf_meas = {n: {"bytes": spec["max_bytes"] // 2, "files": []} for n, spec in perf["budgets"].items()}
    perf_meas["landing_js"]["bytes"] = perf["budgets"]["landing_js"]["max_bytes"] - 12
    monkeypatch.setattr(bd.cpb, "measure", lambda root, budget: perf_meas)
    props = bd.propose(tmp_path, meas, "abc1234567 Some feature")
    assert {p["key"] for p in props} == {"landing_js", "precache/pack_shell_raw_max", "bundles/app.html/css_gzip_max"}
    bd.apply_perf(props)
    bd.apply_startup(props)

    new_perf = json.loads(bd.PERF_FILE.read_text())
    js = new_perf["budgets"]["landing_js"]
    assert js["max_bytes"] == bd.ceiling_for(perf_meas["landing_js"]["bytes"]) == js["history"][-1]["max_bytes"]
    assert "abc1234567 Some feature" in js["history"][-1]["reason"] and len(js["history"]) == len(perf["budgets"]["landing_js"]["history"]) + 1
    assert new_perf["budgets"]["app_css"] == perf["budgets"]["app_css"]  # untouched groups are byte-identical
    assert cpb.validate_budget(new_perf) == []

    text = bd.STARTUP_FILE.read_text()
    new_startup = json.loads(text)
    assert new_startup["precache"]["pack_shell_raw_max"] == bd.ceiling_for(pack - 3)
    assert new_startup["precache"]["install_raw_max"] == install
    assert new_startup["bundles"]["app.html"]["css_gzip_max"] == bd.ceiling_for(css_max + 7)
    assert new_startup["bundles"]["app.html"]["js_gzip_max"] == startup["bundles"]["app.html"]["js_gzip_max"]
    assert new_startup["bundles"]["landing.html"] == startup["bundles"]["landing.html"]
    assert {e["budget"] for e in new_startup["drift_history"]} == {"precache/pack_shell_raw_max", "bundles/app.html/css_gzip_max"}
    # Everything else in the file, including the long comments and the one-line page budgets, is untouched.
    assert new_startup["morro-bay"] == startup["morro-bay"]
    assert new_startup["precache"]["comment"] == startup["precache"]["comment"]
    assert '"landing.html": {"js_gzip_max": 184320, "css_gzip_max": 24576}' in text
    assert bd.check_files() == []

    # The same measurements against the new numbers: no more drift (the bot would not reopen its pull request).
    meas2 = {"precache": meas["precache"], "bundles": meas["bundles"]}
    assert bd.propose(tmp_path, meas2, "abc") == []


def test_a_second_drift_appends_to_the_history_in_order(repo_copy, tmp_path, monkeypatch):
    startup = json.loads(bd.STARTUP_FILE.read_text())
    pack = startup["precache"]["pack_shell_raw_max"]
    monkeypatch.setattr(bd.cpb, "measure", lambda root, budget: {n: {"bytes": 1, "files": []} for n in budget["budgets"]})
    first = bd.propose(tmp_path, {"precache": {"pack_shell": pack}}, "first")
    bd.apply_startup(first)
    mid = json.loads(bd.STARTUP_FILE.read_text())["precache"]["pack_shell_raw_max"]
    second = bd.propose(tmp_path, {"precache": {"pack_shell": mid - 1}}, "second")
    bd.apply_startup(second)
    hist = json.loads(bd.STARTUP_FILE.read_text())["drift_history"]
    assert [h["reason"].split("(")[1].split(")")[0] for h in hist[-2:]] == ["first", "second"]
    assert hist[-2]["max_bytes"] < hist[-1]["max_bytes"]
    assert json.loads(bd.STARTUP_FILE.read_text())["precache"]["pack_shell_raw_max"] == hist[-1]["max_bytes"]
    assert bd.check_files() == []


def test_a_hand_edited_number_without_a_history_entry_is_refused_once_the_bot_has_written_one(repo_copy, tmp_path, monkeypatch):
    monkeypatch.setattr(bd.cpb, "measure", lambda root, budget: {n: {"bytes": 1, "files": []} for n in budget["budgets"]})
    near = json.loads(bd.STARTUP_FILE.read_text())["precache"]["pack_shell_raw_max"] - 1
    bd.apply_startup(bd.propose(tmp_path, {"precache": {"pack_shell": near}}, "bot"))
    text = bd.STARTUP_FILE.read_text()
    bd.STARTUP_FILE.write_text(re.sub(r'("pack_shell_raw_max":\s*)\d+', r"\g<1>9999999", text))
    problems = bd.check_files()
    assert problems and "pack_shell_raw_max" in problems[0] and "drift_history" in problems[0]


def test_the_cli_check_and_missing_build_messages(tmp_path):
    ok = subprocess.run([sys.executable, str(SCRIPTS / "budget_drift.py"), "--check"], capture_output=True, text=True)
    assert ok.returncode == 0 and "consistent" in ok.stdout
    r = subprocess.run([sys.executable, str(SCRIPTS / "budget_drift.py"), "--root", str(tmp_path)], capture_output=True, text=True)
    assert r.returncode == 1 and "pnpm build" in r.stdout


def test_pull_request_body_names_every_row_and_the_rollback(repo_copy, tmp_path, monkeypatch):
    monkeypatch.setattr(bd.cpb, "measure", lambda root, budget: {n: {"bytes": 1, "files": []} for n in budget["budgets"]})
    near = json.loads(bd.STARTUP_FILE.read_text())["precache"]["pack_shell_raw_max"] - 1_000
    props = bd.propose(tmp_path, {"precache": {"pack_shell": near}}, "abc1234567 A feature")
    body = bd.body_markdown(props, "abc1234567 A feature", tmp_path)
    assert "precache/pack_shell_raw_max" in body and f"{near:,}" in body and "abc1234567 A feature" in body and "Roll back" in body
