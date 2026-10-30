import builtins
import csv
import importlib.util
import json
import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/region_process"
spec = importlib.util.spec_from_file_location("region_intake", ROOT / "skills/skippercast-region-intake/scripts/region_intake.py")
ri = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ri)


@pytest.fixture
def world(tmp_path):
    for name in ("approved", "candidate"):
        (tmp_path / f"{name}.tif").write_bytes(name.encode())
    pairs = [("syn-approved", "approved"), ("syn-candidate", "candidate"), ("syn-restricted", "restricted"), ("syn-unlisted", "gone")]
    (tmp_path / "locations.json").write_text(json.dumps(
        {"schema_version": 1, "files": [{"source_id": s, "path": str(tmp_path / f"{n}.tif")} for s, n in pairs]}))
    (tmp_path / "screens.tsv").write_text((FIXTURE / "screens.tsv").read_text().replace("@TMP@", str(tmp_path)))
    state = {"region": json.loads((FIXTURE / "region.json").read_text()), "tmp": tmp_path,
             "sources": {s["id"]: s for s in json.loads((FIXTURE / "sources.json").read_text())["sources"]}}
    state["loader"] = lambda _id: (state["region"], state["sources"])
    return state


def run(w, name):
    tmp = w["tmp"]
    args = ["synthetic-bay", "--run", str(tmp / name), "--locations", str(tmp / "locations.json"), "--screens", str(tmp / "screens.tsv")]
    return ri.main(args, w["loader"]), tmp / name


def rows_of(folder):
    return list(csv.DictReader((folder / "INTAKE.csv").open()))


def test_four_rows_and_deterministic(world):
    code, first = run(world, "one")
    rows = rows_of(first)
    assert code == 0 and [r["use"] for r in rows] == ["publish", "held", "skip", "missing-file"]
    for row in rows:
        source = world["sources"][row["source_id"]]
        assert (row["review_status"], row["licence"]) == (source["review_status"], source["rights"]["license"])
    assert run(world, "two")[0] == 0
    assert (first / "INTAKE.csv").read_bytes() == (world["tmp"] / "two/INTAKE.csv").read_bytes()


def test_restricted_never_touched_and_unknown_id(world, monkeypatch, capsys):
    forbidden, calls = str(world["tmp"] / "restricted.tif"), []
    real_identity, real_stat, real_open = ri.file_identity, os.stat, builtins.open

    def guard(real):
        def wrapped(path, *a, **k):
            assert str(path) != forbidden, "restricted file touched"
            return real(path, *a, **k)
        return wrapped
    monkeypatch.setattr(ri, "file_identity", lambda p: (calls.append(str(p)), real_identity(p))[1])
    monkeypatch.setattr(os, "stat", guard(real_stat))
    monkeypatch.setattr(builtins, "open", guard(real_open))
    assert run(world, "one")[0] == 0
    monkeypatch.undo()
    assert calls and forbidden not in calls
    world["region"]["source_bindings"]["bathymetry"].append("nope")
    code, folder = run(world, "bad")
    assert code == 1 and "Unknown source nope bound to synthetic-bay" in capsys.readouterr().err
    assert not folder.exists()


def test_check(world, capsys):
    _, folder = run(world, "one")
    assert ri.main(["--check", str(folder)], world["loader"]) == 0
    assert "INTAKE OK 4 rows" in capsys.readouterr().out
    text = (folder / "INTAKE.csv").read_text()
    for edit in (text.replace(rows_of(folder)[0]["sha256"], "", 1), text.replace("syn-candidate,candidate,", "syn-candidate,approved,", 1)):
        (folder / "INTAKE.csv").write_text(edit)
        assert ri.main(["--check", str(folder)], world["loader"]) == 1
    inside = ["synthetic-bay", "--run", str(ri.REPO / "var/x"), "--locations", str(world["tmp"] / "locations.json")]
    assert ri.main(inside, world["loader"]) == 1 and not (ri.REPO / "var/x").exists()
