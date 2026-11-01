import csv, json, shutil
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
    [(tmp_path / f"{name}.tif").write_bytes(name.encode()) for name in set(FILES.values()) - {"restricted", "gone"}]
    (tmp_path / "loc.json").write_text(json.dumps({"schema_version": 1, "files": [{"source_id": s, "path": str(tmp_path / f"{n}.tif")} for s, n in FILES.items()]}))
    (tmp_path / "screens.tsv").write_text((FIXTURE / "screens.tsv").read_text().replace("@TMP@", str(tmp_path)))
    sources = {s["id"]: {**s, "adapter": "geotiff"} for s in json.loads((FIXTURE / "sources.json").read_text())["sources"]}
    sources.update({s: {**sources["syn-approved"], "id": s, "adapter": "bag" if s == "syn-bag" else "geotiff"} for s in ("syn-c3", "syn-c4", "syn-bag")})
    (region := json.loads((FIXTURE / "region.json").read_text()))["source_bindings"]["bathymetry"] += ["syn-c3", "syn-c4", "syn-bag"]
    w = {"tmp": tmp_path, "log": [], "refuse": set(), "lie": set(), "fail": None, "loader": lambda _id: (region, sources)}
    def run(cmd):  # fake EC tools: tiny schema-valid receipts (real input hashes) and rasters, never a real grid
        w["log"].append(cmd)
        tool, arg = Path(cmd[1]).name, lambda flag: cmd[cmd.index(flag) + 1]
        if tool == "region_intake.py": return SimpleNamespace(returncode=ri.main(["--check", cmd[3]], w["loader"]), stdout="", stderr="bad intake")
        if tool == "ec_detect.py":
            sign, sid = {"refused": (no := arg("--source-id") in w["refuse"]), "positive_fraction": 1.0, "reason": "all-positive" if no else None}, arg("--source-id")
            Path(arg("--receipt")).write_text(receipt("ec-detect-v1", sid, sign=sign, disposition="REFUSED" if no else "FIX", path_sha256="b" * 64 if sid in w["lie"] else rc.sha256(cmd[2])))
        elif tool == "ec_apply.py" and w["fail"] and cmd[2].endswith(w["fail"]): return SimpleNamespace(returncode=3, stdout="", stderr="apply refused: deepened 2 cells")
        elif tool == "ec_apply.py":
            for name in ("corrected.tif", "provenance.tif"): (Path(arg("--out-dir")) / name).write_text(name + Path(cmd[2]).name)
            (Path(arg("--out-dir")) / "EC-APPLY.json").write_text(receipt("ec-apply-v1", Path(arg("--out-dir")).name, disposition="FIX", input_sha256=rc.sha256(cmd[2])))
        else:
            out, sid, pair = Path(arg("--out-dir")), arg("--a-source"), fake(SCHEMAS["ec-verify-v1"]["pairs"][0])
            pairs = [{**pair, "second_source_id": b, "second_file_sha256": rc.sha256(cmd[i - 2]), "datum_suspect": (sid, b) == ("syn-c3", "syn-c4")} for i, b in enumerate(cmd) if cmd[i - 1] == "--b-source"]
            (out.mkdir() or out / "provenance.tif").write_text("p" + sid)
            (out / "EC-VERIFY.json").write_text(receipt("ec-verify-v1", sid, pairs=pairs, counts={"filled-hole": 5, "unresolved-hole": 3}))
        return SimpleNamespace(returncode=0, stdout="{}", stderr="")
    w["run"] = run; return w  # noqa: E702

def intake(w, name):
    assert ri.main(["synthetic-bay", "--run", str(w["tmp"] / name), "--locations", str(w["tmp"] / "loc.json"), "--screens", str(w["tmp"] / "screens.tsv")], w["loader"]) == 0
    return w["tmp"] / name

correct = lambda w, folder, *extra: rc.main(["synthetic-bay", "--run", str(folder), "--author-runtime", "claude-opus-5-5", "--author-family", "anthropic", *extra], w["run"], w["loader"])  # noqa: E731
chk = lambda w, folder: rc.main(["--check", str(folder)], w["run"], w["loader"])  # noqa: E731
tools = lambda w, since: [Path(c[1]).name for c in w["log"][since:]]  # noqa: E731
ec_lines = lambda capsys: [line for line in capsys.readouterr().out.splitlines() if line.startswith("EC ")]  # noqa: E731

def test_batches_resume_check_and_determinism(world, capsys):
    assert correct(world, folder := intake(world, "one")) == 0 and not (folder / "EC.json").exists() and ec_lines(capsys) == [f"EC {s} {LINE}" for s in CANDS[:3]] + ["EC BATCH-DONE 3/4"]
    assert chk(world, folder) == 1 and "EC.json" in capsys.readouterr().err
    assert [[c[i + 1] for i, x in enumerate(c) if x == "--b-source"] for c in world["log"] if c[1].endswith("ec_verify.py")] == [[s for s in CANDS if s != a] for a in CANDS[:3]]
    assert correct(world, folder) == 0 and ec_lines(capsys) == [f"EC syn-c4 {LINE}", "EC ALL-DONE 4 rows"] and sum(c[1].endswith("ec_detect.py") for c in world["log"]) == 4
    assert correct(world, folder) == 1 and "EC.json" in capsys.readouterr().err and chk(world, folder) == 0 and ec_lines(capsys) == ["EC OK 4 rows"]
    assert (record := json.loads((folder / "EC.json").read_text()))["not_corrected"] == [{"source_id": "syn-restricted", "reason": "use:skip"}, {"source_id": "syn-unlisted", "reason": "use:missing-file"}, {"source_id": "syn-bag", "reason": "unsupported-adapter:bag"}]
    assert record["operator_asks"] == [f"second-survey:{s}:3" for s in CANDS[:3]] + ["datum-suspect:syn-c3:syn-c4:1.0", "second-survey:syn-c4:3"]
    assert not any(bad in " ".join(c) for c in world["log"] for bad in ("restricted", "unlisted", "gone", "bag")) and correct(world, two := intake(world, "two")) == 0 and correct(world, two) == 0
    assert all((folder / n).read_bytes() == (two / n).read_bytes() for n in ("EC.json", "INTAKE-EC.csv"))
def test_refused_row_apply_stop_redo_and_handoff_mutations(world, capsys):
    world["refuse"], world["fail"] = {"syn-c3"}, "c4.tif"
    assert correct(world, folder := intake(world, "r"), "--batch", "9") == 0 and ec_lines(capsys)[2:] == ["EC syn-c3 REFUSED sign-all-positive", "EC BATCH-DONE 3/4"]
    assert [f for f, _ in json.loads((folder / "ec/syn-c3/DONE").read_text())] == ["EC-DETECT.json"] and correct(world, folder) == 1
    assert capsys.readouterr().err.startswith("EC STOP syn-c4 ec_apply exit 3: apply refused") and not (folder / "ec/syn-c4/DONE").exists() and (folder / "ec/syn-c4/EC-DETECT.json").exists()
    world["fail"], since = None, len(world["log"])
    assert correct(world, folder) == 0 and world["log"][since + 1][2].endswith("c4.tif") and tools(world, since) == ["region_intake.py", "ec_detect.py", "ec_apply.py", "ec_verify.py"]
    rows = {r["source_id"]: r for r in csv.DictReader(open(folder / "INTAKE-EC.csv"))}
    assert [rows["syn-c3"][k] for k in ("ec_status", "use", "held_reason", "provenance_path")] == ["REFUSED", "skip", "ec-refused:sign-all-positive", ""] and "refused:syn-c3:sign-all-positive" in json.loads((folder / "EC.json").read_text())["operator_asks"]
    assert (rows["syn-c4"]["ec_path"], rows["syn-bag"]["ec_status"], rows["syn-bag"]["ec_path"]) == ("ec/syn-c4/corrected.tif", "not_corrected", str(world["tmp"] / "bag.tif")) and chk(world, folder) == 0
    for i, (name, change) in enumerate([("INTAKE-EC.csv", lambda t: t.replace(",ec/syn-approved/corrected.tif,ec/syn-approved/verify/provenance.tif", ",/nonexistent/unreviewed.tif,")),
            ("INTAKE-EC.csv", lambda t: t.replace(",skip,ec-refused:sign-all-positive,", ",publish,none,")), ("EC.md", lambda t: t.replace("REFUSED", "PASS")),
            *[("EC.json", lambda t, k=k: rc.canonical({**json.loads(t), k: []}).decode()) for k in ("sources", "inputs")], ("EC.json", lambda t: t.replace(rows["syn-c4"]["sha256"], "c" * 64))]):
        old = ((copy := shutil.copytree(folder, world["tmp"] / f"m{i}")) / name).read_text()
        assert change(old) != old and (copy / name).write_text(change(old)) and chk(world, copy) == 1 and name in capsys.readouterr().err, name
def test_input_identity_and_escaping_links(world, capsys):
    folder, approved = intake(world, "i"), world["tmp"] / "approved.tif"
    assert approved.write_bytes(b"X" * 8) and correct(world, folder) == 1 and "syn-approved: input file sha256 differs from INTAKE.csv" in capsys.readouterr().err and "ec_detect.py" not in tools(world, 0)
    assert approved.write_bytes(b"approved") and world["lie"].add("syn-candidate") is None and correct(world, intake(world, "l")) == 1 and "syn-candidate: EC-DETECT.json path sha256 differs" in capsys.readouterr().err and world["lie"].clear() is None
    assert correct(world, folder := intake(world, "b")) == 0 and approved.write_bytes(b"Xpproved") and correct(world, folder) == 1
    assert "syn-approved: input file sha256 differs" in capsys.readouterr().err and not (folder / "EC.json").exists() and tools(world, len(world["log"]) - 1) == ["region_intake.py"]
    assert approved.write_bytes(b"approved") and correct(world, folder) == 0 and chk(world, folder) == 0 and approved.write_bytes(b"Xpproved") and chk(world, folder) == 1 and approved.write_bytes(b"approved")
    (keep := (outside := world["tmp"] / "outside") / "syn-approved" / "KEEP.txt").parent.mkdir(parents=True) or keep.write_text("synthetic sentinel outside the run")
    for i, (link, target, first) in enumerate([("ec", outside, False), ("ec/syn-approved", keep.parent, False), ("INTAKE-EC.csv", outside / "x.csv", True), ("EC.md", outside / "x.md", True)]):
        assert (correct(world, folder) == 0) if (folder := intake(world, f"s{i}")) and first else ((folder / "ec").mkdir() is None if "/" in link else True)
        assert (folder / link).symlink_to(target) is None and correct(world, folder) == 1 and "symlink refused" in capsys.readouterr().err and chk(world, folder) == 1
    assert sorted(p.relative_to(outside).as_posix() for p in outside.rglob("*")) == ["syn-approved", "syn-approved/KEEP.txt"]
def test_check_names_tampered_file_and_refusals_before_any_tool(world, capsys):
    assert correct(world, folder := intake(world, "t")) == 0 and correct(world, folder) == 0
    assert (apply := folder / "ec/syn-candidate/EC-APPLY.json").write_bytes(apply.read_bytes()[:-1]) and chk(world, folder) == 1 and "ec/syn-candidate/EC-APPLY.json" in capsys.readouterr().err
    fresh, since = intake(world, "f"), len(world["log"])
    assert correct(world, fresh, "--author-family", "Not A Family") == 1 and correct(world, ROOT / "var" / "ec-x") == 1
    (fresh / "INTAKE.csv").write_text((fresh / "INTAKE.csv").read_text().replace(",publish,", ",bogus,", 1))
    assert correct(world, fresh) == 1 and "EC STOP - region_intake" in capsys.readouterr().err and not (fresh / "ec").exists() and tools(world, since) == ["region_intake.py"]
    assert len(skill := (ROOT / "skills/skippercast-region-correct/SKILL.md").read_text().splitlines()) <= 70 and [h[3:].split(" (")[0] for h in skill if h.startswith("## ")] == ["Inputs", "Steps", "Outputs", "Never", "Golden case", "Changelog"]

def bag_only(w):  # every catalog source a BAG: no GeoTIFF candidate, region_intake still checks the real catalog
    region, sources = w["loader"]("synthetic-bay")
    return lambda _id: (region, {s: {**v, "adapter": "bag"} for s, v in sources.items()})
def test_zero_candidate_run_writes_empty_ec_and_passes_check_and_review_shape(world, capsys):
    folder, bag = intake(world, "z"), bag_only(world)
    assert rc.main(["synthetic-bay", "--run", str(folder), "--author-runtime", "claude-opus-5-5", "--author-family", "anthropic"], world["run"], bag) == 0
    assert ec_lines(capsys) == ["EC ALL-DONE 0 rows"] and (folder / "ec").is_dir() and not (folder / "ec").is_symlink() and list((folder / "ec").iterdir()) == []
    record = json.loads((folder / "EC.json").read_text())
    assert (record["sources"], record["inputs"], record["outputs"]) == ([], [], []) and {n["reason"] for n in record["not_corrected"]} >= {"unsupported-adapter:bag"}
    assert not any(Path(c[1]).name.startswith("ec_") for c in world["log"])
    assert rc.main(["--check", str(folder)], world["run"], bag) == 0 and ec_lines(capsys) == ["EC OK 0 rows"]
    rr = load("region_review", "skills/skippercast-region-review/scripts/region_review.py")
    assert rr.ec_tree(folder, {"ec": {"corrected": [], "ec_sha256": record["ec_sha256"]}}) == ([], record, [])
    (folder / "ec").rmdir()  # today's shape (no ec/) is exactly what review FAILs
    assert "ec/ absent or not a directory" in rr.ec_tree(folder, {"ec": {"corrected": [], "ec_sha256": record["ec_sha256"]}})[0]
def test_zero_candidate_resume_file_and_symlink_ec(world, capsys):
    bag, run = bag_only(world), lambda folder: rc.main(["synthetic-bay", "--run", str(folder), "--author-runtime", "r", "--author-family", "anthropic"], world["run"], bag)  # noqa: E731
    assert run(folder := intake(world, "a")) == 0 and (folder / "EC.json").replace(folder / "EC.json.tmp")
    want = (folder / "EC.json.tmp").read_bytes()
    assert run(folder) == 0 and (folder / "EC.json").read_bytes() == want and not (folder / "EC.json.tmp").exists() and (folder / "ec").is_dir()
    (bare := intake(world, "b")).joinpath("EC.json.tmp").write_bytes(want)  # interrupted before ec/ existed
    assert run(bare) == 0 and (bare / "EC.json").read_bytes() == want and (bare / "ec").is_dir() and capsys.readouterr()
    (filed := intake(world, "f")).joinpath("ec").write_text("not a directory")
    assert run(filed) == 1 and (err := capsys.readouterr().err).startswith("region_correct: ") and "File exists" in err and "Traceback" not in err
    assert not any((filed / n).exists() for n in ("EC.json", "EC.json.tmp", "EC.md", "INTAKE-EC.csv")) and (filed / "ec").read_text() == "not a directory"
    (linked := intake(world, "l")).joinpath("ec").symlink_to(outside := world["tmp"] / "outside")
    assert run(linked) == 1 and "ec: symlink refused" in capsys.readouterr().err and not outside.exists() and not (linked / "EC.json").exists()
