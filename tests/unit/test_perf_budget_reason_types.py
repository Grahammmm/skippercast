"""Size-budget history reasons must be nonblank strings (no str() coercion of JSON non-text)."""
import copy
import importlib.util
import json

import pytest

from tests._support import ROOT

SCRIPT = ROOT / "scripts" / "check_perf_budget.py"
spec = importlib.util.spec_from_file_location("check_perf_budget_rt", SCRIPT)
assert spec is not None and spec.loader is not None
cpb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cpb)

MSG = "g: every history entry needs a positive integer max_bytes and a reason"


def budget(*reasons):
    hist = [{"max_bytes": 100, "reason": r} for r in reasons]
    return {"budgets": {"g": {"label": "g", "max_bytes": 100, "history": hist}}}


@pytest.mark.parametrize("bad", [None, False, True, 0, 5, [], ["x"], {}, {"a": "b"}])
def test_nontext_history_reasons_refuse(bad):
    assert cpb.validate_budget(budget(bad)) == [MSG]


def test_all_history_reasons_are_checked():
    assert cpb.validate_budget(budget(None, "documented growth")) == [MSG]


def test_blank_or_missing_reasons_still_refuse():
    for r in ("", "   "):
        assert cpb.validate_budget(budget(r)) == [MSG]
    b = budget("x")
    del b["budgets"]["g"]["history"][0]["reason"]
    assert cpb.validate_budget(b) == [MSG]


@pytest.mark.parametrize("bad", [None, False, 0, [], {}])
def test_invalid_reason_main_stops_before_measurement(bad, tmp_path, monkeypatch, capsys):
    f = tmp_path / "b.json"
    f.write_text(json.dumps(budget(bad)))

    def boom(*a, **k):
        raise AssertionError("must not measure or render")

    monkeypatch.setattr(cpb, "measure", boom)
    monkeypatch.setattr(cpb, "render", boom)
    assert cpb.main(["--root", str(tmp_path), "--budget", str(f)]) == 1
    out = capsys.readouterr().out
    assert "BUDGET FILE PROBLEM" in out and "Build output missing" not in out


@pytest.mark.parametrize("ok", ["documented growth", "añadido ✓", "  padded  "])
def test_real_text_reasons_are_unchanged(ok):
    b = budget(ok)
    before = copy.deepcopy(b)
    assert cpb.validate_budget(b) == []
    assert b == before
