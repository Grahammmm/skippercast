"""Fleet Run IDs must match the whole documented grammar, not a prefix before a newline."""

import json

import pytest

from skippercast.fleet import runs
from skippercast.fleet.runs import Run

GOOD = "20261116T120000Z-abcdef"

BAD = [
    GOOD + "\n",
    GOOD + "\r",
    GOOD + "\r\n",
    "\n" + GOOD,
    GOOD + " ",
    GOOD + "\t",
    "20261116T120000Z-\nabcdef",
    GOOD + "x",
    GOOD + "/..",
    "20261116T1200Z-abcdef",
    "20261116t120000Z-abcdef",
    "20261116T120000z-abcdef",
    "20261116T120000Z-ABCDEF",
    "2026111/T120000Z-abcdef",
    "２０２６１１１６T120000Z-abcdef",
]


def _snapshot(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob("*"))


@pytest.mark.parametrize("bad", BAD)
def test_invalid_id_refused_without_creating_state(tmp_path, bad):
    with pytest.raises(ValueError, match="does not match"):
        Run("reg", bad, var=tmp_path)
    assert not tmp_path.exists() or _snapshot(tmp_path) == []


def test_trailing_lf_leaves_existing_run_untouched(tmp_path):
    run = Run("reg", GOOD, var=tmp_path)
    run.step_started("s", "sink")
    before_state = run.state_path.read_bytes()
    before_entries = _snapshot(tmp_path)
    with pytest.raises(ValueError):
        Run("reg", GOOD + "\n", var=tmp_path)
    assert run.state_path.read_bytes() == before_state
    assert _snapshot(tmp_path) == before_entries


def test_valid_id_resumes_exact_identity(tmp_path):
    run = Run("reg", GOOD, var=tmp_path)
    run.step_started("s", "sink")
    run.step_finished("s", {"n": 1})
    assert run.next_batch() == 0
    again = Run("reg", GOOD, var=tmp_path)
    assert again.id == GOOD
    assert again.state["steps"]["s"]["counts"] == {"n": 1}
    assert again.dir == run.dir
    assert [p.name for p in (tmp_path / "reg" / "runs").iterdir()] == [GOOD]
    assert json.loads(again.state_path.read_text(encoding="utf-8"))["run_id"] == GOOD


@pytest.mark.parametrize("supplied", [None, ""])
def test_default_id_generated(tmp_path, monkeypatch, supplied):
    monkeypatch.setattr(runs, "new_run_id", lambda: GOOD)
    assert Run("reg", supplied, var=tmp_path).id == GOOD


@pytest.mark.parametrize("ok", ["000000", "ffffff"])
def test_hex_boundaries_accepted(tmp_path, ok):
    rid = f"20261116T120000Z-{ok}"
    assert Run("reg", rid, var=tmp_path).id == rid
