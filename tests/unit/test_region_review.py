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
    assert code == 0 and all(c["verdict"] == "PASS" for c in packet["checks"]) and len(packet["checks"]) == 13
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


ECSRC = {**{s: {**e, "id": s, "adapter": "geotiff"} for s, e in SRC.items()},
         "s-x": {"id": "s-x", "adapter": "bluetopo-geotiff-source-review", "review_status": "approved", "vertical_datum": None}}
EC_IDS = ["ec-receipts-intact", "ec-no-deepening", "ec-independence", "ec-unresolved-stated", "ec-thresholds-version"]
FROZEN = {"schema": "region-review-v1", "banner": rr.BANNER, "region_id": "syn-bay", "build_sha256": "f" * 64, "author_runtime": "claude-opus-5-5",
          "author_family": "anthropic", "publishable": True, "held_reason": "none", "checks": [{"id": i, "verdict": "PASS", "detail": d} for i, d in (
              ("outputs-intact", "1 output(s) present, sha256 match"), ("provenance-complete", "provenance complete; source sha256 equal BUILD inputs"),
              ("datum-verbatim", "datums equal the catalog verbatim"), ("omitted-stated", "sources_omitted equals the recomputed list"),
              ("no-depth-crossings", "no contours of different depths cross or touch"), ("size-budget", "within MAX_BYTES and OVERVIEW_MAX_BYTES"),
              ("held-flags", "held flags, held_sources and locations agree"), ("supported-water", "supported_water_fraction 0.4 (coverage not judged here)"))]}


def sha(path):
    return rr.hashlib.sha256(path.read_bytes()).hexdigest()


def receipts(sid, refused=False):
    """Tiny check_receipt-valid receipts: one fill and one pair verifying against s-b; a REFUSED source has detect only."""
    head = {"ec_version": "1.0", "source_id": sid, "counts": {"measured": 4}, "disposition": "REFUSED" if refused else "FIX"}
    sig = [2, 2, "EPSG:26910", 4.0, -9.0, -1.0, -5.0]
    detect = head | {"schema": "ec-detect-v1", "path_sha256": SHA[sid], "cell_m": 4.0, "crs": "EPSG:26910", "width": 2, "height": 2, "nodata": None,
                     "pits": [], "spikes": [], "holes": [], "sentinel_cells": 0, "fixture": {"refused": refused, "reasons": ["synthetic"] * refused},
                     "sign": {"refused": False, "positive_fraction": None, "reason": None}, "duplicate_signature": sig}
    if refused:
        return {"EC-DETECT.json": detect}
    pair = {"second_source_id": "s-b", "second_file_sha256": SHA["s-b"], "independent": True, "reason": "ok", "datums": ["MLLW", "MLLW"], "comparable": True,
            "jointly_valid_cells": 9, "mean_signed_diff_m": 0.1, "mad_m": 0.1, "verified_cells": 5, "conflict_cells": 0, "datum_suspect": False}
    return {"EC-DETECT.json": detect, "EC-APPLY.json": head | {
        "schema": "ec-apply-v1", "detect_sha256": "1" * 64, "input_sha256": SHA[sid], "corrected_sha256": "2" * 64, "provenance_sha256": "3" * 64,
        "cell_m": 4.0, "duplicate_signature": sig, "deepened_cells": 0, "fixes": [{"kind": "hole", "cells": 1, "bbox": [0, 0, 4, 4], "before_min_m": -9.0, "after_m": -8.5}]},
        "verify/EC-VERIFY.json": head | {"schema": "ec-verify-v1", "apply_sha256": "4" * 64, "provenance_sha256": "5" * 64, "pairs": [pair], "disposition": "VERIFY"}}


def ec_run(tmp, monkeypatch, region, plant=None):
    """CLEAN plus a hashed ec/ tree (s-a corrected and verified, s-c REFUSED), EC.json, BUILD.json ec and EC properties on the
    output, incl. one unresolved-area overlapping contours; plant(docs, collection) edits before anything is hashed."""
    monkeypatch.setattr(rr, "loader", lambda _id: (region, ECSRC))
    make_run(tmp, region, CLEAN)
    build = json.loads((tmp / "BUILD.json").read_text())
    out, docs = tmp / build["outputs"][0]["path"], {"s-a": receipts("s-a"), "s-c": receipts("s-c", refused=True)}
    coll = json.loads(out.read_text())
    for f in coll["features"]:
        f["properties"]["provenance"] = "verified" if f["id"] == "a60" else "measured"
    coll["provenance"]["sources"][0] |= {"ec_version": "1.0", "provenance_counts": {"measured": 3, "filled": 0, "verified": 1, "unresolved": 1}}
    ring = [[-120.45, 35.45], [-120.35, 35.45], [-120.35, 35.65], [-120.45, 35.65], [-120.45, 35.45]]
    coll["features"].append({"type": "Feature", "id": "u1", "geometry": {"type": "Polygon", "coordinates": [ring]}, "properties": {
        "kind": "unresolved-area", "reason": "conflict", "blocks": 1, "shoal_hint_ft": 12.0, "source_id": "s-a", "survey_date": "2008",
        "vertical_datum": rr.dc.UNVERIFIED_DATUM}})
    if plant:
        plant(docs, coll)
    for sid, files in docs.items():
        for rel, doc in files.items():
            (tmp / "ec" / sid / rel).parent.mkdir(parents=True, exist_ok=True)
            (tmp / "ec" / sid / rel).write_text(json.dumps(doc))
        (tmp / "ec" / sid / "DONE").write_text(json.dumps([[rel, sha(tmp / "ec" / sid / rel)] for rel in files]))
    outputs = [{"path": p, "sha256": sha(tmp / p)} for p in sorted(q.relative_to(tmp).as_posix() for q in (tmp / "ec").rglob("*") if q.is_file())]
    ec_sha = rr.hashlib.sha256((json.dumps(outputs, sort_keys=True, separators=(",", ":")) + "\n").encode()).hexdigest()
    sources = [{"source_id": s, "status": "REFUSED" if s == "s-c" else "VERIFY", "counts": {"measured": 4}, "second_surveys": [],
                "second_survey_needed_cells": 0, "receipts": {k: f"ec/{s}/{r}" for k, r in zip(("detect", "apply", "verify"), docs[s])}} for s in docs]
    (tmp / "EC.json").write_text(json.dumps({
        "schema": "region-correct-v1", "ec_version": "1.0", "region_id": "syn-bay", "run": build["run"], "sources": sources, "operator_asks": [],
        "not_corrected": [{"source_id": "s-b", "reason": "use:skip"}], "inputs": [{"source_id": s, "sha256": SHA[s]} for s in docs],
        "outputs": outputs, "ec_sha256": ec_sha}))
    out.write_text(json.dumps(coll))
    build["outputs"][0]["sha256"] = sha(out)
    build["ec"] = {"ec_sha256": ec_sha, "ec_version": "1.0", "corrected": ["s-a"], "not_corrected": [{"source_id": "s-b", "reason": "use:skip"}]}
    (tmp / "BUILD.json").write_text(json.dumps(build))
    return rerun(tmp)


def rerun(tmp):
    (tmp / "REVIEW-PACKET/review.json").unlink()
    code = rr.main([str(tmp)])
    return code, json.loads((tmp / "REVIEW-PACKET/review.json").read_text())


def test_ec_run_passes_thirteen_and_a_run_without_ec_is_unchanged(tmp_path, region, monkeypatch):
    code, packet = make_run(tmp_path / "plain", region, CLEAN)
    assert code == 0 and {**packet, "checks": packet["checks"][:8]} == FROZEN
    assert packet["checks"][8:] == [{"id": i, "verdict": "PASS", "detail": "no ec/ folder"} for i in EC_IDS]
    code, packet = ec_run(tmp_path / "ec", monkeypatch, region)
    assert code == 0 and [c["id"] for c in packet["checks"]] == [c["id"] for c in FROZEN["checks"]] + EC_IDS
    assert all(c["verdict"] == "PASS" for c in packet["checks"]) and packet["publishable"] is True, packet["checks"]


@pytest.mark.parametrize("ident, needle, plant", [
    ("ec-no-deepening", "s-a: deepened_cells 1", lambda d, c: d["s-a"]["EC-APPLY.json"].update(deepened_cells=1)),
    ("ec-no-deepening", "s-a fix 0", lambda d, c: d["s-a"]["EC-APPLY.json"]["fixes"][0].update(after_m=-9.5)),
    ("ec-independence", "s-a pair 0 (s-x)", lambda d, c: d["s-a"]["verify/EC-VERIFY.json"]["pairs"][0].update(second_source_id="s-x")),
    ("ec-independence", "s-a pair 0 (s-b)", lambda d, c: d["s-a"]["verify/EC-VERIFY.json"]["pairs"][0].update(comparable=False)),
    ("ec-independence", "s-a pair 0 (s-b)", lambda d, c: d["s-a"]["verify/EC-VERIFY.json"]["pairs"][0].update(independent=False)),
    ("ec-independence", "s-a pair 0 (s-b)", lambda d, c: d["s-a"]["verify/EC-VERIFY.json"]["pairs"][0].update(mad_m=0.0)),
    ("ec-unresolved-stated", "source s-a counts 3", lambda d, c: (c["features"].pop(), c["provenance"]["sources"][0]["provenance_counts"].update(unresolved=3))),
    ("ec-unresolved-stated", "#u1: unresolved-area reason 'flat'", lambda d, c: c["features"][-1]["properties"].update(reason="flat")),
    ("ec-unresolved-stated", "#u1: unresolved-area reason 'hole'", lambda d, c: c["features"][-1]["properties"].update(reason="hole")),
    ("ec-unresolved-stated", "#a90: contour provenance 'guessed'", lambda d, c: c["features"][2]["properties"].update(provenance="guessed")),
    ("ec-thresholds-version", "s-c ec-detect-v1 ec_version '0.9'", lambda d, c: d["s-c"]["EC-DETECT.json"].update(ec_version="0.9")),
    ("ec-thresholds-version", "source s-a ec_version '0.9'", lambda d, c: c["provenance"]["sources"][0].update(ec_version="0.9")),
    ("no-depth-crossings", "#u1 (None ft)", lambda d, c: (c["features"][-1]["properties"].update(kind="contour", provenance="measured"), c["provenance"]["sources"][0]["provenance_counts"].update(unresolved=0)))])
def test_each_planted_ec_fault_fails_only_its_check(tmp_path, region, monkeypatch, ident, needle, plant):
    code, packet = ec_run(tmp_path, monkeypatch, region, plant)
    failed = [c for c in packet["checks"] if c["verdict"] == "FAIL"]
    assert code == 1 and [c["id"] for c in failed] == [ident] and needle in failed[0]["detail"], failed
    assert packet["publishable"] is False and packet["held_reason"] == f"check-failed:{ident}"


@pytest.mark.parametrize("needle, tamper", [
    ("ec/s-a/EC-DETECT.json: sha256 differs from DONE", lambda t: (t / "ec/s-a/EC-DETECT.json").write_text(
        (t / "ec/s-a/EC-DETECT.json").read_text().replace('"width": 2', '"width": 3'))),
    ("ec/s-a/extra.tif: differs from EC.json outputs", lambda t: (t / "ec/s-a/extra.tif").write_text("x")),
    ("ec/s-c/DONE missing or malformed", lambda t: (t / "ec/s-c/DONE").write_text("{}")),
    ("BUILD.json ec.ec_sha256 differs", lambda t: (t / "BUILD.json").write_text((t / "BUILD.json").read_text().replace('"ec_sha256": "', '"ec_sha256": "0'))),
    ("BUILD.json ec null, ec/ present", lambda t: (t / "BUILD.json").write_text((t / "BUILD.json").read_text().replace('"ec": {', '"ec": null, "x": {'))),
    ("EC.json absent or unreadable", lambda t: (t / "EC.json").write_text("{"))])
def test_tampered_ec_tree_fails_receipts_intact(tmp_path, region, monkeypatch, needle, tamper):
    ec_run(tmp_path, monkeypatch, region)
    tamper(tmp_path)
    code, packet = rerun(tmp_path)
    intact = {c["id"]: c for c in packet["checks"]}["ec-receipts-intact"]
    assert code == 1 and intact["verdict"] == "FAIL" and needle in intact["detail"] and packet["held_reason"] == "check-failed:ec-receipts-intact"


@pytest.mark.parametrize("value", [False, True, 0.0, "0", None, -1])
def test_deepened_cells_requires_integer_zero(tmp_path, region, monkeypatch, value):
    code, packet = ec_run(tmp_path, monkeypatch, region,
                          lambda d, c: d["s-a"]["EC-APPLY.json"].update(deepened_cells=value))
    assert code == 1 and not packet["publishable"]
    assert next(c for c in packet["checks"] if c["id"] == "ec-no-deepening")["verdict"] == "FAIL"


@pytest.mark.parametrize("provenance, expected", [(None, 0), ("measured", 0), ("guessed", 1)])
def test_uncorrected_contour_in_ec_run_has_optional_valid_provenance(tmp_path, region, monkeypatch, provenance, expected):
    def plant(docs, collection):
        props = next(f["properties"] for f in collection["features"] if f["properties"].get("source_id") == "s-b")
        props.pop("provenance")
        if provenance is not None:
            props["provenance"] = provenance
    code, packet = ec_run(tmp_path, monkeypatch, region, plant)
    assert code == expected, packet["checks"]
    assert packet["publishable"] is (expected == 0)
    assert next(c for c in packet["checks"] if c["id"] == "ec-unresolved-stated")["verdict"] == ("PASS" if expected == 0 else "FAIL")


def test_ec_contour_requires_provenance(tmp_path, region, monkeypatch):
    code, packet = ec_run(tmp_path, monkeypatch, region, lambda d, c: c["features"][0]["properties"].pop("provenance"))
    assert code == 1 and not packet["publishable"]
    assert next(c for c in packet["checks"] if c["id"] == "ec-unresolved-stated")["verdict"] == "FAIL"


@pytest.mark.gis
@pytest.mark.parametrize("b_name, verdict", [("H54321_MB_2m.tif", "PASS"), ("H12345_MB_2m.tif", "FAIL"), ("unknown.tif", "FAIL")])
def test_real_ec3_bag_acquisition_handoff(tmp_path, monkeypatch, region, b_name, verdict):
    np = pytest.importorskip("numpy")
    pytest.importorskip("rasterio")
    from tests.gis import test_ec_verify as ev
    producer = tmp_path / "producer"
    producer.mkdir()
    values = np.tile(-20.0 - 0.5 * np.arange(32), (32, 1)).astype("float32")
    adir = ev._a_dir(producer, values, np.full(values.shape, 10, "uint8"), source="s-a")
    entries = {**ECSRC, **{s: {**ECSRC[s], "adapter": "bag"} for s in ("s-a", "s-b")}}
    (producer / "entries.json").write_text(json.dumps(entries))
    b = ev._tif(producer / "H54321_MB_2m.tif", ev.survey(values, 0.3))
    doc, _, _ = ev._run(producer, "verified", [(b, "s-b", "MLLW")], a_source="s-a", extra=["--a-file", "BAG__H12345_MB_2m.bag"])
    assert doc["pairs"][0]["verified_cells"] == 1024 and doc["pairs"][0]["independent"]
    assert "a_file" not in doc and "second_file" not in doc["pairs"][0]
    run = tmp_path / "run"
    ec_run(run, monkeypatch, region, lambda d, c: d["s-a"].update({"verify/EC-VERIFY.json": doc,
           "EC-APPLY.json": json.loads((adir / "EC-APPLY.json").read_text())}))
    monkeypatch.setattr(rr, "loader", lambda _: (region, entries))
    (run / "INTAKE.csv").write_text("source_id,sha256,local_path\n"
        f"s-a,{sha(adir / 'input.tif')},/private/BAG__H12345_MB_2m.bag\n"
        f"s-b,{sha(b)},/private/{b_name}\n")
    seal_ec(run)
    code, packet = rerun(run)
    assert next(c for c in packet["checks"] if c["id"] == "ec-independence")["verdict"] == verdict
    assert code == (0 if verdict == "PASS" else 1)


def seal_ec(tmp):
    record = json.loads((tmp / "EC.json").read_text())
    record["outputs"] = [{"path": p.relative_to(tmp).as_posix(), "sha256": sha(p)}
                         for p in sorted((tmp / "ec").rglob("*")) if p.is_file()]
    record["ec_sha256"] = rr.hashlib.sha256((json.dumps(record["outputs"], sort_keys=True, separators=(",", ":")) + "\n").encode()).hexdigest()
    (tmp / "EC.json").write_text(json.dumps(record))
    build = json.loads((tmp / "BUILD.json").read_text())
    build["ec"]["ec_sha256"] = record["ec_sha256"]
    (tmp / "BUILD.json").write_text(json.dumps(build))


@pytest.mark.parametrize("fault", ["done", "source", "directory", "corrected", "receipt", "extra-receipt", "root-file"])
def test_rehashed_ec_omissions_fail_closed(tmp_path, region, monkeypatch, fault):
    ec_run(tmp_path, monkeypatch, region)
    record = json.loads((tmp_path / "EC.json").read_text())
    if fault == "done":
        path = tmp_path / "ec/s-a/DONE"
        path.write_text(json.dumps([p for p in json.loads(path.read_text()) if p[0] != "EC-APPLY.json"]))
    elif fault == "source":
        path = tmp_path / "ec/s-a/EC-APPLY.json"
        doc = json.loads(path.read_text())
        doc["deepened_cells"] = 1
        path.write_text(json.dumps(doc))
        done = path.parent / "DONE"
        done.write_text(json.dumps([[rel, sha(done.parent / rel)] for rel, _ in json.loads(done.read_text())]))
        record["sources"] = record["sources"][1:]
    elif fault == "directory":
        (tmp_path / "ec").rename(tmp_path / "parked")
        record.update(sources=[], inputs=[])
    elif fault == "corrected":
        build = json.loads((tmp_path / "BUILD.json").read_text())
        build["ec"]["corrected"] = []
        (tmp_path / "BUILD.json").write_text(json.dumps(build))
    elif fault == "root-file":
        (tmp_path / "ec/stray").write_text("unowned")
    elif fault == "extra-receipt":
        path = tmp_path / "ec/s-c/EC-APPLY.json"
        path.write_text(json.dumps(receipts("s-c")["EC-APPLY.json"]))
        done = path.parent / "DONE"
        pairs = json.loads(done.read_text())
        done.write_text(json.dumps(pairs + [[path.name, sha(path)]]))
    else:
        record["sources"][0]["receipts"].pop("apply")
    (tmp_path / "EC.json").write_text(json.dumps(record))
    seal_ec(tmp_path)
    code, packet = rerun(tmp_path)
    assert code == 1 and not packet["publishable"]
    assert next(c for c in packet["checks"] if c["id"] == "ec-receipts-intact")["verdict"] == "FAIL"
    if fault == "source":
        assert next(c for c in packet["checks"] if c["id"] == "ec-no-deepening")["verdict"] == "FAIL"


def test_check_requires_the_five_ec_rows(tmp_path, region, monkeypatch, capsys):
    ec_run(tmp_path, monkeypatch, region)
    rows = [f"| {c['id']} | PASS | confirmed |" for c in json.loads((tmp_path / "REVIEW-PACKET/review.json").read_text())["checks"]]
    head = f"# REVIEW syn-bay x\n{rr.MD_BANNER}\nBuild-SHA256: {'f' * 64}\nReviewer-Runtime: gpt-6.1-sol\nReviewer-Family: openai\n| check | verdict | reason |\n|---|---|---|\n"
    for drop in [None, *EC_IDS]:
        (tmp_path / "REVIEW.md").write_text(head + "".join(r + "\n" for r in rows if f"| {drop} |" not in r) + "| visual | not-visually-inspected | none |\nOverall: PASS\n")
        assert rr.main(["--check", str(tmp_path)]) == (0 if drop is None else 1)
        assert (f"check {drop} missing" in capsys.readouterr().err) is (drop is not None)
    assert len(rows) == 13
