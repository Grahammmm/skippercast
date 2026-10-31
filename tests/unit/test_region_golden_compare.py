import copy
import importlib.util
import json

import pytest

from tests._support import ROOT

spec = importlib.util.spec_from_file_location("golden_compare", ROOT / "skills/skippercast-region-build/scripts/golden_compare.py")
gc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gc)
LINE = {"type": "LineString", "coordinates": [[-120.9, 35.3], [-120.8, 35.3]]}
DOC = {"type": "FeatureCollection", "schema_version": 1,
       "provenance": {"region_id": "morro-bay", "units": "ft", "sources": ["usgs-a"], "method": "marching squares"},
       "features": [{"type": "Feature", "properties": {"depth_ft": d}, "geometry": copy.deepcopy(LINE)} for d in (60, 120)]}


def listing(*folders):
    return [sorted((str(p), p.lstat().st_size, p.lstat().st_mtime_ns) for p in f.rglob("*")) for f in folders]


@pytest.fixture
def world(tmp_path):
    run, catalog = tmp_path / "run", tmp_path / "catalog"
    (run / "candidate").mkdir(parents=True)
    catalog.mkdir()
    (catalog / "morro-bay.geojson").write_text(json.dumps(DOC))
    return run, catalog


def go(world, capsys, candidate=None, region="morro-bay", raw=None, run=None):
    folder, catalog = world
    if raw is not None or candidate is not None:
        (folder / "candidate" / f"{region}.geojson").write_text(raw if raw is not None else json.dumps(candidate))
    before = listing(folder, catalog)
    code = gc.main([region, "--run", str(run or folder)], catalog_root=catalog)
    assert listing(folder, catalog) == before  # read-only: names, sizes and mtimes unchanged
    out, err = capsys.readouterr()
    return code, out, err


def report(world, capsys, candidate=None, **kw):
    code, out, err = go(world, capsys, candidate, **kw)
    assert err == "" and len(out.splitlines()) == 1
    assert out.strip() == json.dumps(json.loads(out), sort_keys=True)
    return code, json.loads(out)


def edited(fn):
    doc = copy.deepcopy(DOC)
    fn(doc)
    return doc


@pytest.mark.parametrize("raw,same_bytes", [(json.dumps(DOC), True), (json.dumps(DOC, indent=2), False)], ids=["identical", "reindented"])
def test_same_json_is_equal(world, capsys, raw, same_bytes):
    code, r = report(world, capsys, raw=raw)
    assert (code, r["verdict"], r["bytes_equal"], r["features_equal"], r["feature_counts"]) == (0, "equal", same_bytes, True, [2, 2])
    assert r["provenance"] == {"added": [], "removed": [], "changed": []} and r["top_level_changed"] == []


def test_sg1_added_provenance_key_is_provenance_only(world, capsys):
    code, r = report(world, capsys, edited(lambda d: d["provenance"].update(sources_omitted=[])))
    assert (code, r["verdict"], r["features_equal"]) == (1, "provenance-only", True)
    assert r["provenance"] == {"added": ["sources_omitted"], "removed": [], "changed": []}


def test_changed_and_removed_provenance_keys_sorted(world, capsys):
    code, r = report(world, capsys, edited(lambda d: (d["provenance"].update(units="m", method="x"), d["provenance"].pop("sources"))))
    assert code == 1 and r["provenance"] == {"added": [], "removed": ["sources"], "changed": ["method", "units"]}
    code, r = report(world, capsys, edited(lambda d: d.update(provenance="none")))  # non-object provenance counts as {}
    assert (code, r["verdict"], r["provenance"]["removed"]) == (1, "provenance-only", ["method", "region_id", "sources", "units"])


@pytest.mark.parametrize("change", [
    lambda d: d["features"][0]["geometry"]["coordinates"][0].__setitem__(0, -120.91),
    lambda d: d["features"].reverse(),
    lambda d: (d["features"].pop(), d["provenance"].update(x=1)),
], ids=["coordinate", "order", "dropped-plus-provenance"])
def test_feature_difference(world, capsys, change):
    code, r = report(world, capsys, edited(change))
    assert (code, r["verdict"], r["features_equal"]) == (1, "features-differ", False)
    assert r["features_sha256"]["candidate"] != r["features_sha256"]["catalog"]


def test_top_level_key_difference(world, capsys):
    code, r = report(world, capsys, edited(lambda d: d.update(schema_version=2)))
    assert (code, r["verdict"], r["top_level_changed"], r["provenance"]["changed"]) == (1, "provenance-only", ["schema_version"], [])
    code, r = report(world, capsys, edited(lambda d: d.pop("type")))
    assert (code, r["top_level_changed"]) == (1, ["type"])


def test_values_never_printed(world, capsys):
    (world[1] / "morro-bay.geojson").write_text(json.dumps(edited(lambda d: d["provenance"].update(method="SECRET-SENTINEL"))))
    code, out, _ = go(world, capsys, DOC)
    assert code == 1 and '"changed": ["method"]' in out and "SECRET" not in out and "marching" not in out


def refused(world, capsys, **kw):
    code, out, err = go(world, capsys, **kw)
    assert (code, out) == (2, "") and err.startswith("golden_compare: ") and len(err.splitlines()) == 1
    return err


def test_held_only_run_refused(world, capsys):
    (world[0] / "held").mkdir()
    (world[0] / "held" / "morro-bay.geojson").write_text(json.dumps(DOC))
    assert "no candidate output (held or unbuilt run)" in refused(world, capsys)


@pytest.mark.parametrize("raw", ["{not json", "[]", json.dumps({"features": {}}), json.dumps({"type": "x"})])
def test_malformed_candidate_refused(world, capsys, raw):
    assert "candidate is not" in refused(world, capsys, raw=raw)


def test_missing_or_malformed_catalog_refused(world, capsys):
    (world[1] / "morro-bay.geojson").write_text(json.dumps({"features": "x"}))
    assert "catalog is not" in refused(world, capsys, candidate=DOC)
    (world[1] / "morro-bay.geojson").unlink()
    assert "catalog file missing" in refused(world, capsys)


@pytest.mark.parametrize("region", ["../x", "Morro", "morro--bay", "x-", ""])
def test_bad_region_id_refused(world, capsys, region):
    assert "region id" in refused(world, capsys, region=region)


def test_run_inside_repository_refused(world, capsys):
    assert "outside the repository" in refused(world, capsys, run=ROOT / "tests")
    assert "outside the repository" in refused(world, capsys, run=ROOT)


def test_candidate_symlink_out_of_run_refused(world, capsys, tmp_path):
    (tmp_path / "outside.geojson").write_text(json.dumps(DOC))
    (world[0] / "candidate" / "morro-bay.geojson").symlink_to(tmp_path / "outside.geojson")
    assert "outside the run folder" in refused(world, capsys)
