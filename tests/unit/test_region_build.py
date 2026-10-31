import csv
import importlib.util
import io
import json
from types import SimpleNamespace

import pytest

from tests._support import FIXTURES, ROOT

FIXTURE = FIXTURES / "region_process"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ri = load("region_intake", "skills/skippercast-region-intake/scripts/region_intake.py")
rb = load("region_build", "skills/skippercast-region-build/scripts/region_build.py")
LINE = [[-120.5, 35.5], [-120.4, 35.5]]


@pytest.fixture
def world(tmp_path):
    for name in ("approved", "candidate"):
        (tmp_path / f"{name}.tif").write_bytes(name.encode())
    pairs = [("syn-approved", "approved"), ("syn-candidate", "candidate"), ("syn-restricted", "restricted"), ("syn-unlisted", "gone")]
    (tmp_path / "loc.json").write_text(json.dumps({"schema_version": 1, "files": [{"source_id": s, "path": str(tmp_path / f"{n}.tif")} for s, n in pairs]}))
    (tmp_path / "screens.tsv").write_text((FIXTURE / "screens.tsv").read_text().replace("@TMP@", str(tmp_path)))
    sources = {s["id"]: {**s, "adapter": "geotiff"} for s in json.loads((FIXTURE / "sources.json").read_text())["sources"]}
    w = {"tmp": tmp_path, "sources": sources, "region": json.loads((FIXTURE / "region.json").read_text()), "log": [], "refuse": False}
    w["loader"] = lambda _id: (w["region"], w["sources"])
    return w


def build(w, name, edit=None):
    folder = w["tmp"] / name
    assert ri.main(["synthetic-bay", "--run", str(folder), "--locations", str(w["tmp"] / "loc.json"), "--screens", str(w["tmp"] / "screens.tsv")], w["loader"]) == 0
    if edit:
        (folder / "INTAKE.csv").write_text(edit((folder / "INTAKE.csv").read_text()))

    def run(cmd):
        w["log"].append(cmd)
        name, ok = cmd[1].rsplit("/", 1)[-1], SimpleNamespace(returncode=0, stderr="", stdout="{}")
        if name == "region_intake.py":
            return SimpleNamespace(returncode=ri.main(["--check", cmd[3]], w["loader"]), stderr="bad intake", stdout="")
        if name == "preflight_native_grid.py":
            refused = SimpleNamespace(returncode=2, stdout="", stderr="preflight refused: crs: none")
            return refused if w["refuse"] else SimpleNamespace(returncode=0, stderr="", stdout=json.dumps({"preflight": "pass", "path": cmd[2]}))
        feats = [{"geometry": {"coordinates": [LINE]}, "properties": {"kind": k, "depth_ft": 30}} for k in ("contour", "survey-edge")]
        out = rb.Path(cmd[5])
        out.parent.mkdir(parents=True)
        out.write_text(json.dumps({"provenance": {"sources": [{"supported_blocks": 100}]}, "features": feats}))
        return ok
    code = rb.main(["synthetic-bay", "--run", str(folder), "--author-runtime", "claude-opus-5-5", "--author-family", "anthropic"], run, w["loader"])
    return code, folder, [c for c in w["log"] if c[1].endswith("build_depth_contours.py")]


def test_two_calls_build_json_and_deterministic(world):
    code, folder, calls = build(world, "one")
    assert code == 0 and [c[4:] for c in calls] == [
        ["--output", str(folder / "candidate/synthetic-bay.geojson"), "--grid", f"syn-approved={world['tmp'] / 'approved.tif'}"],
        ["--held-output", str(folder / "held/synthetic-bay.geojson"), "--grid", f"syn-candidate={world['tmp'] / 'candidate.tif'}"]]
    record = json.loads((folder / "BUILD.json").read_text())
    assert [(o["path"], o["sha256"], o["publication_held"], o["held_reason"]) for o in record["outputs"]] == [
        ("candidate/synthetic-bay.geojson", rb.hashlib.sha256((folder / "candidate/synthetic-bay.geojson").read_bytes()).hexdigest(), False, "none"),
        ("held/synthetic-bay.geojson", rb.hashlib.sha256((folder / "held/synthetic-bay.geojson").read_bytes()).hexdigest(), True, "source-candidate:syn-candidate")]
    assert record["not_built"] == [{"source_id": "syn-restricted", "reason": "skip"}, {"source_id": "syn-unlisted", "reason": "missing-file:syn-unlisted"}]
    assert build(world, "two")[0] == 0 and (folder / "BUILD.json").read_bytes() == (world["tmp"] / "two/BUILD.json").read_bytes()
    for cmd in world["log"]:
        assert not any(bad in " ".join(cmd) for bad in ("syn-restricted", "syn-unlisted", "restricted.tif", "gone.tif"))


def test_failed_check_and_row_selection(world):
    code, folder, calls = build(world, "blank", lambda t: t.replace(t.split("\n")[1].split(",")[5], "", 1))
    assert code == 1 and not (folder / "BUILD.json").exists() and not calls
    world["sources"]["syn-candidate"]["adapter"] = "vector"
    code, folder, calls = build(world, "dup", lambda t: t + t.split("\n")[1] + "\n")
    record = json.loads((folder / "BUILD.json").read_text())
    assert code == 0 and not calls and record["outputs"] == [] and record["held_reason"] == "no-buildable-input"
    assert {"source_id": "syn-candidate", "reason": "unsupported-adapter:vector"} in record["not_built"]
    assert {"source_id": "syn-approved", "reason": "multi-file-source:syn-approved:2"} in record["not_built"]


def test_preflight_refusal_stops_before_builder_and_terrain_section(world, capsys):
    world["refuse"] = True
    code, folder, calls = build(world, "refused")
    assert code == 1 and not calls and not (folder / "BUILD.json").exists()
    assert "preflight_native_grid.py approved.tif" in capsys.readouterr().err
    terrain = (ROOT / "skills/skippercast-region-build/SKILL.md").read_text().split("## Terrain\n")[1].split("\n## ")[0]
    assert "S-030" in terrain and "coast-statewide-runsheet.md" in terrain and "skippercast-map-coast/SKILL.md" in terrain
    assert "```" not in terrain and "python" not in terrain


PRE_EC7_PLAIN_SHA256 = "4da049170e833cdfa34e69cd2927df0b038ac081618feaab81cad5278b5847e7"  # pre-EC7 BUILD.json, plain P2 run (main b7e96e63)
EC_STATUS = {"syn-approved": "FIX", "syn-candidate": "VERIFY", "syn-refused": "REFUSED"}
EC_JSON = {"schema": "region-correct-v1", "ec_version": "1.0", "ec_sha256": "e" * 64, "not_corrected": [{"source_id": "syn-plain", "reason": "synthetic"}],
           "sources": [{"source_id": s, "status": v} for s, v in EC_STATUS.items()]}


def ec_setup(w, monkeypatch):
    """Two more approved sources (syn-plain stays not_corrected, syn-refused is REFUSED) and a faked region_correct.py --check."""
    loc, w["correct_rc"], new = json.loads((w["tmp"] / "loc.json").read_text()), 0, ("syn-plain", "syn-refused")
    for sid in new:
        (w["tmp"] / f"{sid}.tif").write_bytes(sid.encode())
        w["sources"][sid] = {**w["sources"]["syn-approved"], "id": sid}
        w["region"]["source_bindings"]["bathymetry"].append(sid)
        loc["files"].append({"source_id": sid, "path": str(w["tmp"] / f"{sid}.tif")})
    (w["tmp"] / "loc.json").write_text(json.dumps(loc))
    (w["tmp"] / "screens.tsv").write_text((w["tmp"] / "screens.tsv").read_text() + "".join(f"{w['tmp']}/{s}.tif\tPASS\t\t{w['tmp']}/verdicts.jsonl\n" for s in new))
    real, fake = rb.call, lambda cmd: w["log"].append(cmd) or SimpleNamespace(returncode=w["correct_rc"], stderr="EC STOP syn-approved ec_verify", stdout="EC OK")  # noqa: E731
    monkeypatch.setattr(rb, "call", lambda run, cmd: real(fake if cmd[1].endswith("region_correct.py") else run, cmd))


def ec_edit(w, name, change=None, ec_json=True):
    """INTAKE edit hook that leaves INTAKE.csv alone and writes the synthetic EC4 output into the run folder."""
    def edit(text):
        folder, rows = w["tmp"] / name, list(csv.DictReader(io.StringIO(text)))
        for row in rows:
            sid, status = row["source_id"], EC_STATUS.get(row["source_id"], "not_corrected")
            fixed = status in ("FIX", "VERIFY")
            row.update(ec_status=status, ec_path=f"ec/{sid}/corrected.tif" if fixed else row["local_path"],
                       provenance_path=f"ec/{sid}/provenance.tif" if fixed else "",
                       **({"use": "skip", "held_reason": "ec-refused:sign"} if status == "REFUSED" else {}))
            for kind in ("corrected", "provenance") if fixed else ():
                (folder / f"ec/{sid}").mkdir(parents=True, exist_ok=True)
                (folder / f"ec/{sid}/{kind}.tif").write_bytes(f"{sid}-{kind}".encode())
            (change or {}).get(sid, lambda r: None)(row)
        with open(folder / "INTAKE-EC.csv", "w", newline="") as handle:
            (writer := csv.DictWriter(handle, list(rows[0]))).writeheader()
            writer.writerows(rows)
        if ec_json:
            (folder / "EC.json").write_text(json.dumps(EC_JSON))
        return text
    return edit


def test_ec_run_builds_from_corrected_grids_with_provenance(world, monkeypatch):
    ec_setup(world, monkeypatch)
    code, folder, calls = build(world, "ec", ec_edit(world, "ec"))
    ec, tmp, log = (lambda sid, kind: str(folder / f"ec/{sid}/{kind}.tif")), world["tmp"], world["log"]
    assert code == 0 and [c[1].rsplit("/", 1)[-1] for c in log[:2]] == ["region_intake.py", "region_correct.py"]
    assert log[1][2:] == ["--check", str(folder)] and [c[2] for c in log if c[1].endswith("preflight_native_grid.py")] == [
        ec("syn-approved", "corrected"), str(tmp / "syn-plain.tif"), ec("syn-candidate", "corrected")]
    assert [c[4:] for c in calls] == [
        ["--output", str(folder / "candidate/synthetic-bay.geojson"), "--grid", f"syn-approved={ec('syn-approved', 'corrected')}",
         "--grid", f"syn-plain={tmp / 'syn-plain.tif'}", "--provenance", f"syn-approved={ec('syn-approved', 'provenance')}"],
        ["--held-output", str(folder / "held/synthetic-bay.geojson"), "--grid", f"syn-candidate={ec('syn-candidate', 'corrected')}",
         "--provenance", f"syn-candidate={ec('syn-candidate', 'provenance')}"]] and not any("syn-refused" in " ".join(cmd) for cmd in log)
    record, sha = json.loads((folder / "BUILD.json").read_text()), lambda b: rb.hashlib.sha256(b).hexdigest()
    assert record["ec"] == {"ec_sha256": json.loads((folder / "EC.json").read_text())["ec_sha256"], "ec_version": "1.0",
                            "corrected": ["syn-approved", "syn-candidate"], "not_corrected": [{"source_id": "syn-plain", "reason": "synthetic"}]}
    assert {"source_id": "syn-refused", "reason": "ec-refused:sign"} in record["not_built"] and record["inputs"] == [
        {"source_id": "syn-approved", "sha256": sha(b"approved"), "ec_sha256": sha(b"syn-approved-corrected")},
        {"source_id": "syn-plain", "sha256": sha(b"syn-plain")},
        {"source_id": "syn-candidate", "sha256": sha(b"candidate"), "ec_sha256": sha(b"syn-candidate-corrected")}]


def test_no_ec_input_unchanged_and_bad_ec_input_exits_1(world, monkeypatch, capsys):
    code, folder, _ = build(world, "plain")
    data = (folder / "BUILD.json").read_bytes()
    assert code == 0 and json.loads(data)["ec"] is None and data.endswith(b',"ec":null}\n')
    assert rb.hashlib.sha256(data.replace(b',"ec":null}', b"}")).hexdigest() == PRE_EC7_PLAIN_SHA256
    ec_setup(world, monkeypatch)
    escape = lambda key, value: {"syn-approved": lambda r: r.update({key: value})}  # noqa: E731
    cases = {"no-ec-json": ({}, False, 0, "INTAKE-EC.csv without EC.json"),
             "dotdot": (escape("ec_path", "../approved.tif"), True, 0, "inside the run folder"),
             "absolute": (escape("ec_path", str(world["tmp"] / "approved.tif")), True, 0, "inside the run folder"),
             "empty": (escape("ec_path", ""), True, 0, "inside the run folder"),
             "prov-escape": (escape("provenance_path", "../../provenance.tif"), True, 0, "inside the run folder"),
             "refused-not-skip": ({"syn-refused": lambda r: r.update(use="publish")}, True, 0, "REFUSED row syn-refused"),
             "check-fails": ({}, True, 1, "region_correct.py --check")}
    for name, (change, ec_json, rc, message) in cases.items():
        world["log"][:], world["correct_rc"] = [], rc
        code, folder, _ = build(world, name, ec_edit(world, name, change, ec_json))
        assert code == 1 and not (folder / "BUILD.json").exists() and message in capsys.readouterr().err, name
        assert not any(c[1].endswith(("preflight_native_grid.py", "build_depth_contours.py")) for c in world["log"]), name


def test_skill_md_ec_delta_keeps_sections_and_golden_case():
    text = (ROOT / "skills/skippercast-region-build/SKILL.md").read_text()
    assert len(text.splitlines()) <= 70 and "skill_version: 1.2" in text and "- 1.1: reads INTAKE-EC.csv" in text
    assert [line[3:] for line in text.splitlines() if line.startswith("## ")] == ["Inputs", "Steps", "Outputs", "Never", "Terrain", "Golden case", "Changelog"]
    assert text.split("## Golden case\n\n")[1].split("\n\n## ")[0] == "`morro-bay` (real run M2) over the three USGS GeoTIFFs: " \
        "`candidate/morro-bay.geojson` must equal the committed\n`catalog/depth-contours/morro-bay.geojson` in features **and** provenance: " \
        "run `scripts/golden_compare.py morro-bay --run <dir>`.\nAny verdict other than `equal` is a spec-gap note naming the keys it lists."
