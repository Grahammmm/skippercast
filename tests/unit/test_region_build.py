import importlib.util
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
