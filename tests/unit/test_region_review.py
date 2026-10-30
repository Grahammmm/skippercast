import importlib.util
import json

import pytest

from tests._support import ROOT

spec = importlib.util.spec_from_file_location("region_review", ROOT / "skills/skippercast-region-review/scripts/region_review.py")
rr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rr)
SRC = {"s-a": {"review_status": "approved", "vertical_datum": None}, "s-b": {"review_status": "approved", "vertical_datum": "MLLW"},
       "s-c": {"review_status": "candidate", "vertical_datum": None}}
SHA = {s: s[-1] * 64 for s in SRC}
CLEAN = [("a60", "s-a", 60, [[-120.5, 35.5], [-120.4, 35.5]]), ("b60", "s-b", 60, [[-120.4, 35.5], [-120.3, 35.5]]),
         ("a90", "s-a", 90, [[-120.5, 35.6], [-120.3, 35.6]])]


@pytest.fixture
def region(monkeypatch):
    region = {"id": "syn-bay", "status": "active", "source_bindings": {"bathymetry": list(SRC)}}
    monkeypatch.setattr(rr, "loader", lambda _id: (region, SRC))
    return region


def make_run(tmp, region, lines, held=False, blank=None):
    ids = list(dict.fromkeys(s for _, s, _, _ in lines))
    datum = {s: SRC[s]["vertical_datum"] or rr.dc.UNVERIFIED_DATUM for s in ids}
    feats = [{"type": "Feature", "id": f, "geometry": {"type": "MultiLineString", "coordinates": [c]}, "properties": {
        "kind": "contour", "depth_ft": d, "source_id": s, "survey_date": "2008", "vertical_datum": datum[s]}} for f, s, d, c in lines]
    prov = {"region_id": "syn-bay", "units": "ft", "interval_ft": 30, "bounds": [-121, 35, -120, 36], "sources_omitted":
            rr.dc.omitted_sources(region, SRC, ids), "sources": [{"source_id": s, "sha256": SHA[s], "survey_date": "2008",
                                                                  "vertical_datum": "" if s == blank else datum[s]} for s in ids]}
    if held:
        prov |= {"publication_held": True, "held_sources": rr.dc.held_sources({"provenance": prov}, SRC)}
    rel = f"{'held' if held else 'candidate'}/syn-bay.geojson"
    (tmp / rel).parent.mkdir(parents=True)
    (tmp / rel).write_text(json.dumps({"type": "FeatureCollection", "provenance": prov, "features": feats}))
    build = {"region_id": "syn-bay", "build_sha256": "f" * 64, "profile": "opus-coder-bopus", "supported_water_fraction": 0.4,
             "run": {"author_runtime": "claude-opus-5-5", "author_family": "anthropic"}, "inputs": [{"source_id": s, "sha256": SHA[s]} for s in ids],
             "outputs": [{"path": rel, "sha256": rr.hashlib.sha256((tmp / rel).read_bytes()).hexdigest(), "publication_held": held}]}
    (tmp / "BUILD.json").write_text(json.dumps(build))
    return rr.main([str(tmp)]), json.loads((tmp / "REVIEW-PACKET/review.json").read_text())


def test_clean_run_passes_and_planted_faults_fail(tmp_path, region):
    code, packet = make_run(tmp_path / "clean", region, CLEAN)
    assert code == 0 and all(c["verdict"] == "PASS" for c in packet["checks"]) and len(packet["checks"]) == 8
    assert packet["publishable"] is True and packet["held_reason"] == "none" and packet["banner"] == rr.BANNER
    code, packet = make_run(tmp_path / "cross", region, CLEAN + [("x60", "s-a", 60, [[-120.45, 35.55], [-120.45, 35.65]])])
    crossing = {c["id"]: c for c in packet["checks"]}["no-depth-crossings"]
    assert code == 1 and crossing["verdict"] == "FAIL" and "#a90 (90 ft)" in crossing["detail"] and "#x60 (60 ft)" in crossing["detail"]
    code, packet = make_run(tmp_path / "datum", region, CLEAN, blank="s-b")
    datum = {c["id"]: c for c in packet["checks"]}["datum-verbatim"]
    assert code == 1 and datum["verdict"] == "FAIL" and "source s-b" in datum["detail"] and "s-a" not in datum["detail"]


@pytest.mark.parametrize("source_id", ["unlisted-source", None])
@pytest.mark.parametrize("datum", ["MLLW", "arbitrary datum"])
def test_feature_requires_a_listed_source(tmp_path, region, source_id, datum):
    make_run(tmp_path, region, CLEAN)
    build_path = tmp_path / "BUILD.json"
    build = json.loads(build_path.read_text())
    output = build["outputs"][0]
    path = tmp_path / output["path"]
    collection = json.loads(path.read_text())
    feature = collection["features"][1]
    feature["properties"].update(source_id=source_id, vertical_datum=datum)
    path.write_text(json.dumps(collection))
    output["sha256"] = rr.hashlib.sha256(path.read_bytes()).hexdigest()
    build_path.write_text(json.dumps(build))
    packet_path = tmp_path / "REVIEW-PACKET/review.json"
    packet_path.unlink()

    assert rr.main([str(tmp_path)]) == 1
    packet = json.loads(packet_path.read_text())
    checks = {c["id"]: c for c in packet["checks"]}
    for ident in ("provenance-complete", "datum-verbatim"):
        assert checks[ident]["verdict"] == "FAIL"
        assert "#b60" in checks[ident]["detail"]
    assert checks["outputs-intact"]["verdict"] == "PASS"
    assert packet["publishable"] is False


def test_check_requires_a_different_family_and_the_build_sha(tmp_path, region, capsys):
    make_run(tmp_path, region, CLEAN)
    rows = "".join(f"| {c['id']} | PASS | confirmed |\n" for c in json.loads((tmp_path / "REVIEW-PACKET/review.json").read_text())["checks"])
    good = (f"# REVIEW syn-bay {tmp_path.name}\n{rr.MD_BANNER}\nBuild-SHA256: {'f' * 64}\nReviewer-Runtime: gpt-6.1-sol\n"
            f"Reviewer-Family: openai\n| check | verdict | reason |\n|---|---|---|\n{rows}| visual | not-visually-inspected | none |\nOverall: PASS\n")
    for text, expected in ((good, 0), (good.replace("Family: openai", "Family: Anthropic "), 1), (good.replace("f" * 64, "e" * 64), 1)):
        (tmp_path / "REVIEW.md").write_text(text)
        assert rr.main(["--check", str(tmp_path)]) == expected
    err = capsys.readouterr()
    assert "REVIEW OK syn-bay PASS" in err.out and "line 5: Reviewer-Family" in err.err and "line 3: Build-SHA256" in err.err


def test_held_only_run_passes_unpublishable_and_draft_region(tmp_path, region):
    code, packet = make_run(tmp_path / "held", region, [("c60", "s-c", 60, [[-120.5, 35.5], [-120.4, 35.5]])], held=True)
    assert code == 0 and all(c["verdict"] == "PASS" for c in packet["checks"])
    assert packet["publishable"] is False and packet["held_reason"] == "source-candidate:s-c"
    region["status"] = "draft"
    code, packet = make_run(tmp_path / "draft", region, CLEAN, held=True)
    assert code == 0 and packet["publishable"] is False and packet["held_reason"] == "region-draft"
