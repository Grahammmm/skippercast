"""Exercise the audit CLIs' filesystem boundary without real GIS inputs or queries."""
import importlib
import json
from pathlib import Path
import sys

import pytest


pytestmark = pytest.mark.gis

REPORT = {"totals": {"blocks": 1}, "source_polygon_count": 1, "source_classes": {}}
PRIVATE = {"type": "FeatureCollection", "features": [{
    "type": "Feature", "properties": {"exportable": False},
    "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
}]}


@pytest.fixture(params=["point_buchon_2009_access_blocks", "point_buchon_rov_access_blocks",
                        "san_diego_substrate_lead"])
def cli(request, tmp_path, monkeypatch):
    # Import only in the survey tier; the core tier has no GIS packages.
    module = importlib.import_module(f"research.scripts.audit_{request.param}")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(module, "ROOT", tmp_path.resolve(), raising=False)
    Path("synthetic.json").write_text(json.dumps({"pair_reviews": [{
        "survey_id": "H11876", "bag_url": "synthetic/H11876_MB_2m_MLLW_2of5.bag",
    }]}))
    Path("research/catalog").mkdir(parents=True)
    Path("research/catalog/central-rov-2024-source.json").write_text("{}")
    calls = []

    def synthetic_input(*args):
        calls.append("input")

    if request.param == "san_diego_substrate_lead":
        def query():
            synthetic_input()
            return [], {}, json.dumps(PRIVATE).encode(), []

        monkeypatch.setattr(module, "query", query)
        monkeypatch.setattr(module, "review", lambda *args: REPORT.copy())
        args = ["--pairs", "synthetic.json", "--camera-cache", "synthetic.json", "--raw-output"]
    else:
        monkeypatch.setattr(module, "source_blocks", synthetic_input)
        monkeypatch.setattr(module, "build", lambda *args: (REPORT.copy(), PRIVATE))
        inputs = ["--mpas", "--federal", "--enc", "--character"]
        inputs += ["--bathy", "--rov"] if "rov" in request.param else ["--archive"]
        args = [option for flag in inputs for option in (flag, "synthetic.json")] + ["--private-blocks"]

    def run(private, report):
        monkeypatch.setattr(sys, "argv", [request.param, *args, str(private), "--output", str(report)])
        module.main()

    return run, calls


def snapshot():
    return {path: path.readlink() if path.is_symlink() else
            path.read_bytes() if path.is_file() else None for path in Path(".").rglob("*")}


@pytest.mark.parametrize("case", ["staging", "outside", "prefix", "traversal", "root-redirect",
                                 "private-redirect", "public-alias", "same", "report-alias",
                                 "hardlink", "overlapping", "report-directory"])
def test_unsafe_destinations_fail_before_work_or_writes(cli, case):
    run, calls = cli
    root = Path("var/review")
    private = root / "blocks.geojson"
    report = Path("research/receipts/report.json")
    if case == "staging":
        private = Path("dist/stage/blocks.geojson")
    elif case == "outside":
        private = Path.cwd() / "outside/blocks.geojson"
    elif case == "prefix":
        private = Path("var/review-staging/blocks.geojson")
    elif case == "traversal":
        private = root / "../../dist/blocks.geojson"
    elif case == "root-redirect":
        root.parent.mkdir()
        Path("dist").mkdir()
        root.symlink_to("../dist", target_is_directory=True)
    elif case == "private-redirect":
        root.mkdir(parents=True)
        private.symlink_to("../../dist/blocks.geojson")
    elif case == "public-alias":
        root.mkdir(parents=True)
        Path("dist").symlink_to(root, target_is_directory=True)
        private = Path("dist/blocks.geojson")
    elif case == "same":
        report = Path.cwd() / private
    elif case == "report-alias":
        report = Path("report.json")
        report.symlink_to(private)
    elif case == "hardlink":
        root.mkdir(parents=True)
        Path("dist").mkdir()
        public = Path("dist/existing.geojson")
        public.write_text("unchanged")
        private.hardlink_to(public)
    elif case == "overlapping":
        report = private / "report.json"
    else:
        report.mkdir(parents=True)

    before = snapshot()
    with pytest.raises(ValueError, match=r"var/review|distinct|regular file|hard link"):
        run(private, report)
    assert calls == []
    assert snapshot() == before


def test_private_and_aggregate_outputs_stay_separate(cli):
    run, calls = cli
    private = Path.cwd() / "var/review/nested/blocks.geojson"
    report = Path("research/receipts/report.json")
    run(private, report)
    assert calls == ["input"]
    assert json.loads(private.read_text()) == PRIVATE
    aggregate = json.loads(report.read_text())
    assert {key: value for key, value in aggregate.items() if key != "input_sha256"} == REPORT
