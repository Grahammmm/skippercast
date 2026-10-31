import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from skippercast.platform.seafloor_ec import EC_VERSION, SCHEMAS
from tests._support import FIXTURES, ROOT
from tests.unit.test_region_build import load, ri

FIXTURE = FIXTURES / "region_process"
CANDS = ["syn-approved", "syn-candidate", "syn-c3", "syn-c4"]
FILES = {"syn-approved": "approved", "syn-candidate": "candidate", "syn-restricted": "restricted", "syn-unlisted": "gone", "syn-c3": "c3", "syn-c4": "c4", "syn-bag": "bag"}
DEF = {"str": "x", "num": 1.0, "int": 0, "bool": False, "list": [], "sha256": "a" * 64, "bbox": [0, 0, 1, 1], "sig": [0] * 7, "datums": ["MLLW", "MLLW"], "disposition": "PASS", "counts": {}}
LINE = "PASS filled=5 pit=0 verified=0 conflict=0 unresolved=3"
rc = load("region_correct", "skills/skippercast-region-correct/scripts/region_correct.py")
fake = lambda spec: {k: fake(v) if isinstance(v, dict) else [] if isinstance(v, list) else DEF[v.rstrip("?")] for k, v in spec.items()}  # noqa: E731
receipt = lambda kind, sid, **kw: json.dumps({**fake(SCHEMAS[kind]), "schema": kind, "ec_version": EC_VERSION, "source_id": sid, **kw})  # noqa: E731

@pytest.fixture
def world(tmp_path):
    for name in set(FILES.values()) - {"restricted", "gone"}:
        (tmp_path / f"{name}.tif").write_bytes(name.encode())
    (tmp_path / "loc.json").write_text(json.dumps({"schema_version": 1, "files": [{"source_id": s, "path": str(tmp_path / f"{n}.tif")} for s, n in FILES.items()]}))
    (tmp_path / "screens.tsv").write_text((FIXTURE / "screens.tsv").read_text().replace("@TMP@", str(tmp_path)))
    sources = {s["id"]: {**s, "adapter": "geotiff"} for s in json.loads((FIXTURE / "sources.json").read_text())["sources"]}
    sources.update({s: {**sources["syn-approved"], "id": s, "adapter": "bag" if s == "syn-bag" else "geotiff"} for s in ("syn-c3", "syn-c4", "syn-bag")})
    region = json.loads((FIXTURE / "region.json").read_text())
    region["source_bindings"]["bathymetry"] += ["syn-c3", "syn-c4", "syn-bag"]
    w = {"tmp": tmp_path, "log": [], "refuse": set(), "fail": None, "loader": lambda _id: (region, sources)}

    def run(cmd):  # fake EC tools: tiny schema-valid receipts and rasters, never a real grid
        w["log"].append(cmd)
        tool, arg = Path(cmd[1]).name, lambda flag: cmd[cmd.index(flag) + 1]
        if tool == "region_intake.py":
            return SimpleNamespace(returncode=ri.main(["--check", cmd[3]], w["loader"]), stdout="", stderr="bad intake")
        if tool == "ec_detect.py":
            sign = {"refused": (no := arg("--source-id") in w["refuse"]), "positive_fraction": 1.0, "reason": "all-positive" if no else None}
            Path(arg("--receipt")).write_text(receipt("ec-detect-v1", arg("--source-id"), sign=sign, disposition="REFUSED" if no else "FIX"))
        elif tool == "ec_apply.py" and w["fail"] and cmd[2].endswith(w["fail"]):
            return SimpleNamespace(returncode=3, stdout="", stderr="apply refused: deepened 2 cells")
        elif tool == "ec_apply.py":
            for name in ("corrected.tif", "provenance.tif"):
                (Path(arg("--out-dir")) / name).write_text(name + Path(cmd[2]).name)
            (Path(arg("--out-dir")) / "EC-APPLY.json").write_text(receipt("ec-apply-v1", Path(arg("--out-dir")).name, disposition="FIX"))
        else:
            out, sid, pair = Path(arg("--out-dir")), arg("--a-source"), fake(SCHEMAS["ec-verify-v1"]["pairs"][0])
            pairs = [{**pair, "second_source_id": b, "datum_suspect": (sid, b) == ("syn-c3", "syn-c4")} for i, b in enumerate(cmd) if cmd[i - 1] == "--b-source"]
            out.mkdir()
            (out / "provenance.tif").write_text("p" + sid)
            (out / "EC-VERIFY.json").write_text(receipt("ec-verify-v1", sid, pairs=pairs, counts={"filled-hole": 5, "unresolved-hole": 3}))
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")
    w["run"] = run
    return w

def intake(w, name):
    assert ri.main(["synthetic-bay", "--run", str(w["tmp"] / name), "--locations", str(w["tmp"] / "loc.json"), "--screens", str(w["tmp"] / "screens.tsv")], w["loader"]) == 0
    return w["tmp"] / name

def correct(w, folder, *extra):
    return rc.main(["synthetic-bay", "--run", str(folder), "--author-runtime", "claude-opus-5-5", "--author-family", "anthropic", *extra], w["run"], w["loader"])

def ec_lines(capsys):
    return [line for line in capsys.readouterr().out.splitlines() if line.startswith("EC ")]

def test_batches_resume_check_and_determinism(world, capsys):
    assert correct(world, folder := intake(world, "one")) == 0 and not (folder / "EC.json").exists() and ec_lines(capsys) == [f"EC {s} {LINE}" for s in CANDS[:3]] + ["EC BATCH-DONE 3/4"]
    assert rc.main(["--check", str(folder)], world["run"]) == 1 and "EC.json" in capsys.readouterr().err
    assert [[c[i + 1] for i, x in enumerate(c) if x == "--b-source"] for c in world["log"] if c[1].endswith("ec_verify.py")] == [[s for s in CANDS if s != a] for a in CANDS[:3]]
    assert correct(world, folder) == 0 and ec_lines(capsys) == [f"EC syn-c4 {LINE}", "EC ALL-DONE 4 rows"] and sum(c[1].endswith("ec_detect.py") for c in world["log"]) == 4
    assert correct(world, folder) == 1 and "EC.json" in capsys.readouterr().err and rc.main(["--check", str(folder)], world["run"]) == 0 and ec_lines(capsys) == ["EC OK 4 rows"]
    assert (record := json.loads((folder / "EC.json").read_text()))["not_corrected"] == [
        {"source_id": "syn-restricted", "reason": "use:skip"}, {"source_id": "syn-unlisted", "reason": "use:missing-file"}, {"source_id": "syn-bag", "reason": "unsupported-adapter:bag"}]
    assert record["operator_asks"] == [f"second-survey:{s}:3" for s in CANDS[:3]] + ["datum-suspect:syn-c3:syn-c4:1.0", "second-survey:syn-c4:3"]
    assert not any(bad in " ".join(c) for c in world["log"] for bad in ("restricted", "unlisted", "gone", "bag")) and correct(world, two := intake(world, "two")) == 0 and correct(world, two) == 0
    assert all((folder / n).read_bytes() == (two / n).read_bytes() for n in ("EC.json", "INTAKE-EC.csv"))

def test_refused_row_and_apply_stop_redo(world, capsys):
    world["refuse"], world["fail"] = {"syn-c3"}, "c4.tif"
    assert correct(world, folder := intake(world, "r"), "--batch", "9") == 0 and ec_lines(capsys)[2:] == ["EC syn-c3 REFUSED sign-all-positive", "EC BATCH-DONE 3/4"]
    assert [f for f, _ in json.loads((folder / "ec/syn-c3/DONE").read_text())] == ["EC-DETECT.json"] and correct(world, folder) == 1
    assert capsys.readouterr().err.startswith("EC STOP syn-c4 ec_apply exit 3: apply refused") and not (folder / "ec/syn-c4/DONE").exists() and (folder / "ec/syn-c4/EC-DETECT.json").exists()
    world["fail"], since = None, len(world["log"])
    assert correct(world, folder) == 0 and world["log"][since + 1][2].endswith("c4.tif") and [Path(c[1]).name for c in world["log"][since:]] == ["region_intake.py", "ec_detect.py", "ec_apply.py", "ec_verify.py"]
    rows = {r["source_id"]: r for r in csv.DictReader(open(folder / "INTAKE-EC.csv"))}
    assert [rows["syn-c3"][k] for k in ("ec_status", "use", "held_reason", "provenance_path")] == ["REFUSED", "skip", "ec-refused:sign-all-positive", ""]
    assert (rows["syn-c4"]["ec_path"], rows["syn-bag"]["ec_status"], rows["syn-bag"]["ec_path"]) == ("ec/syn-c4/corrected.tif", "not_corrected", str(world["tmp"] / "bag.tif")) and rc.main(["--check", str(folder)], world["run"]) == 0
    assert "refused:syn-c3:sign-all-positive" in json.loads((folder / "EC.json").read_text())["operator_asks"]

def test_check_names_tampered_file_and_refusals_before_any_tool(world, capsys):
    assert correct(world, folder := intake(world, "t")) == 0 and correct(world, folder) == 0
    (apply := folder / "ec/syn-candidate/EC-APPLY.json").write_bytes(apply.read_bytes()[:-1])
    assert rc.main(["--check", str(folder)], world["run"]) == 1 and "ec/syn-candidate/EC-APPLY.json" in capsys.readouterr().err
    fresh, since = intake(world, "f"), len(world["log"])
    assert correct(world, fresh, "--author-family", "Not A Family") == 1 and correct(world, ROOT / "var" / "ec-x") == 1
    (fresh / "INTAKE.csv").write_text((fresh / "INTAKE.csv").read_text().replace(",publish,", ",bogus,", 1))
    assert correct(world, fresh) == 1 and "EC STOP - region_intake" in capsys.readouterr().err and not (fresh / "ec").exists() and [Path(c[1]).name for c in world["log"][since:]] == ["region_intake.py"]
    skill = (ROOT / "skills/skippercast-region-correct/SKILL.md").read_text().splitlines()
    assert [h[3:].split(" (")[0] for h in skill if h.startswith("## ")] == ["Inputs", "Steps", "Outputs", "Never", "Golden case", "Changelog"] and len(skill) <= 70
