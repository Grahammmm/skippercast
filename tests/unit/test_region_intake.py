import builtins
import csv
import importlib.util
import json
import os

import pytest

from tests._support import FIXTURES, ROOT

FIXTURE = FIXTURES / "region_process"
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


def test_outside_only_is_counted_without_download_gap(world):
    world["region"]["source_bindings"]["bathymetry"] = ["syn-approved"]
    path = world["tmp"] / "locations.json"
    path.write_text(json.dumps({"schema_version": 1, "files": [
        {"source_id": "syn-approved", "path": str(world["tmp"] / "outside.tif"), "bbox": [0, 0, 1, 1]}]}))
    code, folder = run(world, "outside")
    assert code == 0 and rows_of(folder) == []
    text = (folder / "INTAKE.md").read_text()
    assert "out-of-bounds entries not listed: 1" in text
    assert "operator: one G ask" not in text


@pytest.mark.parametrize("failure", ["empty", "directory", "permission", "io"])
def test_invalid_data_fails_before_write(world, monkeypatch, capsys, failure):
    path = world["tmp"] / "approved.tif"
    if failure == "empty":
        path.write_bytes(b"")
    elif failure == "directory":
        path.unlink()
        path.mkdir()
    else:
        original = ri.file_identity
        def unreadable(name):
            if name == str(path):
                raise PermissionError("denied") if failure == "permission" else OSError("read failed")
            return original(name)
        monkeypatch.setattr(ri, "file_identity", unreadable)
    code, folder = run(world, "bad-data")
    assert code == 1 and str(path) in capsys.readouterr().err
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


def test_check_rejects_never_read_and_foreign_reason(world, monkeypatch, capsys):
    _, folder = run(world, "one")
    rows = rows_of(folder)
    restricted = world["tmp"] / "restricted.tif"
    restricted.write_bytes(b"x")

    def rewrite(row):
        with (folder / "INTAKE.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, ri.COLUMNS, lineterminator="\n")
            writer.writeheader()
            writer.writerows([row])

    forbidden, real_stat, real_open = str(restricted), os.stat, builtins.open

    def guard(real):
        def wrapped(path, *a, **k):
            assert str(path) != forbidden, "never-read path touched"
            return real(path, *a, **k)
        return wrapped
    monkeypatch.setattr(os, "stat", guard(real_stat))
    monkeypatch.setattr(builtins, "open", guard(real_open))
    base = next(r for r in rows if r["source_id"] == "syn-restricted")
    for use in ("held", "publish"):
        rewrite({**base, "use": use, "held_reason": "none", "local_path": forbidden, "sha256": "a" * 64, "bytes": "1"})
        assert ri.main(["--check", str(folder)], world["loader"]) == 1
        assert "Row 1 field use" in capsys.readouterr().err
    monkeypatch.undo()
    held = next(r for r in rows if r["use"] == "held")
    for reason in ("source-candidate:WRONG-ID", "missing-file:WRONG-ID"):
        rewrite({**held, "held_reason": reason})
        assert ri.main(["--check", str(folder)], world["loader"]) == 1
        assert "Row 1 field held_reason" in capsys.readouterr().err
    rewrite(held)
    assert ri.main(["--check", str(folder)], world["loader"]) == 0


def joined_run(w, listed, extra):
    tmp, loc = w["tmp"], json.loads((w["tmp"] / "locations.json").read_text())
    loc["files"][0]["screened_path"] = listed
    (tmp / "locations.json").write_text(json.dumps(loc))
    with (tmp / "screens.tsv").open("a") as handle:
        handle.writelines(f"{tmp / t}\t{v}\t\t{s}\n" for t, v, s in extra)
    code, folder = run(w, "joined")
    return code, folder, rows_of(folder)[0] if code == 0 else None


def test_screened_path_joins_without_touching(world, monkeypatch):
    derived, calls = str(world["tmp"] / "d/approved__r000000_c000000.tif"), []
    real_identity, real_stat, real_open = ri.file_identity, os.stat, builtins.open
    def guard(real):
        return lambda path, *a, **k: (str(path) != derived or pytest.fail("screened path touched"), real(path, *a, **k))[1]
    monkeypatch.setattr(ri, "file_identity", lambda p: (calls.append(str(p)), real_identity(p))[1])
    monkeypatch.setattr(os, "stat", guard(real_stat))
    monkeypatch.setattr(builtins, "open", guard(real_open))
    code, folder, row = joined_run(world, derived, [("d/approved__r000000_c000000.tif", "PASS-SPARSE", "rx")])
    monkeypatch.undo()
    assert code == 0 and (row["screen"], row["screen_receipt"], row["use"]) == ("PASS-SPARSE", "rx", "publish")
    assert calls and derived not in calls and "- screens joined via screened_path: 1 entries" in (folder / "INTAKE.md").read_text()


@pytest.mark.parametrize("verdicts,more,want", [
    (["PASS", "PASS-SPARSE"], [], ("PASS-SPARSE", "a;b", "publish")),
    (["PASS", "FLAG"], [], ("FLAG", "b", "skip")),
    (["PASS", None], [], ("UNSCREENED", "", "publish")),
    (["PASS", "PASS"], [("e/approved_elevation_r0_c0.tif", "FLAG", "c")], ("FLAG", "c", "skip")),  # unlisted sibling
    (["PASS", "PASS"], [("d/approved__r0_c0.tif", "FLAG", "z")], ("FLAG", "z", "skip")),  # stale FLAG under a later PASS
    (["PASS", "PASS"], [("d/approved__r0_c1.tif", "FLAG", "bo"), ("d/approved__r0_c0.tif", "FLAG", "ao"), ("e/approved_r9.tif", "FLAG", "cs")], ("FLAG", "ao;bo;cs", "skip")),
    (["PASS", "PASS"], [("e/notapproved_r0.tif", "FLAG", "c"), ("e/approvedx_r0.tif", "FLAG", "c")], ("PASS", "a;b", "publish")),
])
def test_screened_path_verdict_precedence(world, verdicts, more, want):
    names = ["d/approved__r0_c0.tif", "d/approved__r0_c1.tif"]
    extra = more + [(n, v, s) for n, v, s in zip(names, verdicts, "ab") if v]
    code, _, row = joined_run(world, [str(world["tmp"] / n) for n in names], extra)
    assert code == 0 and (row["screen"], row["screen_receipt"], row["use"]) == want


@pytest.mark.parametrize("listed", ["d/approved__r0_c0.tif", [], "@/d/other__r0_c0.tif", ["@/d/approved__r0_c0.tif"] * 2, [7]])
def test_bad_screened_path_writes_nothing(world, capsys, listed):
    fix = lambda p: p.replace("@", str(world["tmp"])) if isinstance(p, str) else p  # noqa: E731
    listed = [fix(p) for p in listed] if isinstance(listed, list) else fix(listed)
    code, folder, _ = joined_run(world, listed, [])
    want = listed if "other" in str(listed) else str(world["tmp"] / "approved.tif")
    assert code == 1 and want in capsys.readouterr().err and not folder.exists()


def bbox_run(w, bbox, name="bbox"):
    loc = json.loads((w["tmp"] / "locations.json").read_text())
    if bbox != "absent":
        loc["files"][0]["bbox"] = bbox
    (w["tmp"] / "locations.json").write_text(json.dumps(loc))  # NaN/Infinity written as JSON NaN/Infinity
    return run(w, name)


@pytest.mark.parametrize("bbox", [
    "-122,36,-121,37", [-122, 36, -121], [-122, 36, -121, 37, 0], [], {"w": -122}, 5,
    [-122, "36", -121, 37], [True, 36, -121, 37], [-122, 36, -121, False], [None, 36, -121, 37],
    [float("nan"), 36, -121, 37], [-122, 36, float("inf"), 37], [-122, float("-inf"), -121, 37],
    [-122, 37, -121, 36],  # south > north
])
def test_malformed_bbox_is_named_error_and_writes_nothing(world, capsys, bbox):
    code, folder = bbox_run(world, bbox)
    err = capsys.readouterr().err
    want = f"region_intake: Locations entry bbox invalid ({world['tmp'] / 'approved.tif'}): need [west, south, east, north] finite numbers"
    assert code == 1 and err.strip() == want and "Traceback" not in err
    assert not folder.exists() and not (folder / "INTAKE.csv").exists()


@pytest.mark.parametrize("bbox,use,outside", [
    ("absent", "publish", 0), (None, "publish", 0), ([-120.8, 35.2, -120.2, 35.8], "publish", 0),
    ([-121, 35, -120, 36], "publish", 0), ([-120.5, 35.5, -120.5, 35.5], "publish", 0),  # edges and a point
    ([-123, 36.5, -122, 37], None, 1), ([0.5, 0, 1.5, 1], None, 1),  # valid but outside: counted, not refused
    ([-120.2, 35.2, -120.8, 35.8], "publish", 0),  # west > east is not refused
])
def test_valid_or_unknown_bbox_behaves_as_before(world, bbox, use, outside):
    code, folder = bbox_run(world, bbox)
    assert code == 0
    first = [r["use"] for r in rows_of(folder) if r["source_id"] == "syn-approved"]
    assert first == ([use] if use else []), first
    assert f"out-of-bounds entries not listed: {outside}" in (folder / "INTAKE.md").read_text()


@pytest.mark.parametrize("value,want", [(None, "undeclared"), ("absent", "undeclared"), (2, "2"), (0, "0"), (0.5, "0.5")])
def test_native_resolution_null_or_absent_reads_undeclared(world, value, want):
    for sid in ("syn-approved", "syn-restricted"):  # a data row and a never-read skip row
        world["sources"][sid].pop("native_resolution_m", None)
        if value != "absent":
            world["sources"][sid]["native_resolution_m"] = value
    code, folder = run(world, "res")
    cells = {r["source_id"]: r["native_cell_m"] for r in rows_of(folder)}
    assert code == 0 and (cells["syn-approved"], cells["syn-restricted"]) == (want, want)
    assert cells["syn-candidate"] == "8"


def test_check_accepts_folder_written_with_empty_native_cell(world, capsys):
    world["sources"]["syn-approved"]["native_resolution_m"] = None
    _, folder = run(world, "old")
    rows = rows_of(folder)
    assert rows[0]["native_cell_m"] == "undeclared"
    with (folder / "INTAKE.csv").open("w", newline="") as handle:  # as the old code wrote a null resolution
        writer = csv.DictWriter(handle, ri.COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows({**r, "native_cell_m": ""} for r in rows)
    capsys.readouterr()
    assert ri.main(["--check", str(folder)], world["loader"]) == 0
    assert "INTAKE OK 4 rows" in capsys.readouterr().out
