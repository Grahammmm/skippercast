"""F28-07 / SCA-601: offline controls for the private-block/receipt join.

Default pytest checks the desired admission contract and the real join's valid
and held controls. Opt-in ``python -m tests.unit.test_f28_07_audit`` probes the
unchanged join without the reference gate and exits nonzero on a contract gap.
Only invented bytes and aggregate counts are used; nothing is published.
"""
from contextlib import nullcontext
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace as NS

import pytest

from tests._support import ROOT

JOIN = ROOT / "research/scripts/audit_point_buchon_rov_cell_join.py"
PRODUCER = JOIN.with_name("audit_point_buchon_2009_access_blocks.py")
HOLD_FIELDS = {"mpa", "gea", "charted_danger"}
# Only the first block has synthetic observations. Preserve the join's fixed
# coverage totals with inert padding rows and three groups at the margin seams.
CLEAR = ((138, 1), (91, 1), (37, 1))
HELD = ((0, 0),) * 3
CASES = (
    ("matched_clear", CLEAR),
    ("matched_held", HELD),
    ("absent", "rejected"),
    ("empty", "rejected"),
    ("omitted", "rejected"),
    ("extra", "rejected"),
    ("non_boolean", "rejected"),
    ("unbound_receipt", "rejected"),
    ("other_run_same_count", "rejected"),
)


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def pair(case):
    holds: dict[str, object] = dict.fromkeys(sorted(HOLD_FIELDS), False)
    if case in {"matched_held", "other_run_same_count"}:
        holds["mpa"] = True
    elif case == "empty":
        holds = {}
    elif case == "omitted":
        del holds["gea"]
    elif case == "extra":
        holds["unknown_category"] = False
    elif case == "non_boolean":
        holds["charted_danger"] = 0
    props = {"exportable": False, "fishing_target": False,
             "nominal_source_datum_cell_counts": {"synthetic": 1}}
    if case != "absent":
        props["review_holds"] = holds
    feature = {"type": "Feature", "geometry": None, "properties": props}
    blocks = {"type": "FeatureCollection", "crs": "EPSG:32610", "features": [feature] * 181}
    screened_bytes = encoded(blocks)
    # Same frame, safety flags and feature count, but a different screening
    # run's first block (and thus different bytes). The receipt is not changed.
    if case == "other_run_same_count":
        blocks["features"][0] = {**feature, "properties": {**props, "review_holds": {**holds, "mpa": False}}}
    receipt = {
        "scope": "point-buchon-2009-csumb-original-100m-access-triage",
        "totals": {"blocks": 181}, "qualified_waypoints": 0,
        "fishing_target": False, "exportable": False,
        # Fixture-only proposed companion field; neither current script is changed.
        "private_research_blocks_sha256": sha256(screened_bytes).hexdigest(),
    }
    if case == "unbound_receipt":
        del receipt["private_research_blocks_sha256"]
    return encoded(blocks), receipt


def admitted(raw, receipt):
    """Reference gate: validate consumed bytes and every block before counting."""
    if sha256(raw).hexdigest() != receipt.get("private_research_blocks_sha256"):
        return False
    for feature in json.loads(raw)["features"]:
        flags = feature["properties"].get("review_holds")
        if not isinstance(flags, dict) or flags.keys() != HOLD_FIELDS:
            return False
        if any(type(value) is not bool for value in flags.values()):
            return False
    return True


def load_join(monkeypatch, tmp_path):
    """Stub only unrelated source pins, raster and geometry I/O, not the join."""
    pin = tmp_path / "pin.json"
    pin.write_bytes(encoded({"doi": "synthetic", "file_sha256": "synthetic"}))
    modules = {
        "numpy": NS(),  # source_depth_at is replaced below, not the caller
        "pyproj": NS(Transformer=NS(from_crs=lambda *a, **k: NS(transform=lambda x, y: x))),
        "rasterio": NS(),
        "shapely.geometry": NS(
            Point=lambda x, y: NS(distance=lambda boundary: round(x) // 2),
            shape=lambda geometry: NS(contains=lambda point: True, boundary=None),
        ),
        "shapely.strtree": NS(STRtree=lambda geometries: NS(query=lambda point: [0])),
        "research.scripts.audit_point_buchon_2009_csumb_products": NS(
            ARCHIVE_SHA256="synthetic", GRIDS=(("shallow",), ("deep",)),
            extract_grids=lambda *args: None, sha256_file=lambda path: "synthetic",
        ),
        "research.scripts.audit_point_buchon_original_pair": NS(
            EXPECTED_CLASS="synthetic", original_tiff=lambda path, kind: (path,),
            published_character_accuracy=lambda path: {},
        ),
        "research.scripts.build_central_rov_depth_evidence": NS(
            fetch=None, source_bytes=lambda *args: None,
        ),
    }
    with monkeypatch.context() as imports:
        for name, module in modules.items():
            imports.setitem(sys.modules, name, module)
        spec = importlib.util.spec_from_file_location("f28_07_join", JOIN)
        assert spec is not None and spec.loader is not None
        join = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(join)

    def open_grid(path):
        size = 5 if path.name == "deep" else 2
        return nullcontext(NS(crs="EPSG:32610" if path.name == "class" else "EPSG:26910",
                              res=(size, size), sample=lambda *a, **k: iter([[1]])))

    join.rasterio.open = open_grid
    monkeypatch.setattr(join, "PIN", pin)
    monkeypatch.setattr(join, "tempfile", NS(TemporaryDirectory=lambda: nullcontext(tmp_path)))
    monkeypatch.setattr(join, "source_depth_at", lambda x, *_: (70, 2) if round(x) % 2 else (None, None))
    return join


def run_join(case, raw, receipt, tmp_path, monkeypatch):
    join = load_join(monkeypatch, tmp_path)
    private, access, rov = (tmp_path / name for name in ("private.json", "access.json", "rov.csv"))
    private.write_bytes(raw)
    access.write_bytes(encoded(receipt))
    header = ("LongTerm_Region,Protection,Type,Avg.X,Avg.Y,Avg.Depth,SurveyYear,"
              "X10m_ID,MPAGroup,Propn_Hard,Lingcod," + ",".join(join.ROCKFISH))
    rows = [header]
    for edge, total, sampled in ((0, 47, 32), (10, 54, 36), (25, 37, 26)):
        for index in range(total):
            x = (edge * 2 + (index < sampled)) / 1000
            rows.append(f"Central,0,Reference,{x},0,70,2000,synthetic_{len(rows)},Point Buchon,0,0,"
                        + ",".join(["0"] * len(join.ROCKFISH)))
    # Preserve coverage without giving the padding any in-band observations.
    in_band = len(rows) - 1
    rov.write_text("\n".join(rows) + "\n" + "Central,0,Reference,0,0,0\n" * (10000 - in_band)
                   + "other\n" * (133506 - 10000))
    try:
        report = join.build(rov, tmp_path / "archive", tmp_path / "class", private, access, tmp_path / "meta")
    except ValueError:
        return "rejected"
    except KeyError as error:
        if case == "absent" and error.args == ("review_holds",):
            return "unhandled KeyError(review_holds)"
        raise
    for flag in ("fishing_target", "exportable", "full_route_and_fishing_date_cleared"):
        assert report[flag] is False
    counts = report["inward_block_sensitivity_m"]
    return tuple((counts[m]["partial_access_clear_subunits"], counts[m]["partial_access_clear_blocks"])
                 for m in ("0", "10", "25"))


def observe(case, tmp_path, monkeypatch, *, reference):
    raw, receipt = pair(case)
    if reference and not admitted(raw, receipt):
        return "rejected"
    return run_join(case, raw, receipt, tmp_path, monkeypatch)


@pytest.mark.parametrize(("case", "expected"), CASES, ids=[case for case, _ in CASES])
def test_partial_clear_requires_bound_blocks_and_complete_boolean_holds(case, expected, tmp_path, monkeypatch):
    # A count-only join trusts the wrong run; truthiness alone silently clears
    # empty, incomplete, extra or falsey non-boolean hold fields.
    assert observe(case, tmp_path, monkeypatch, reference=True) == expected


def main():
    print(f"join sha256={sha256(JOIN.read_bytes()).hexdigest()}")
    print(f"producer sha256={sha256(PRODUCER.read_bytes()).hexdigest()} (not executed)")
    gaps = 0
    for case, expected in CASES:
        with TemporaryDirectory(prefix="f28-07-") as temp, pytest.MonkeyPatch.context() as monkeypatch:
            actual = observe(case, Path(temp), monkeypatch, reference=False)
        # The contract also permits an explicitly held negative instead of rejecting it.
        checked = actual == expected or expected == "rejected" and actual == HELD
        gaps += not checked
        print(f"{'PASS' if checked else 'GAP'} {case}: expected {expected}; observed {actual}")
    print(f"Baseline contract gaps: {gaps}/{len(CASES)}")
    return int(gaps > 0)


if __name__ == "__main__":
    raise SystemExit(main())
