"""The four128 window pre-scan judges windows exactly as the harness does (T08-FIX3).

Synthetic data only: a numpy-backed fake raster for the lattice/selection run, and
the synthetic BAG fixture for parity with the harness's own observer. The cached
H11952 BAG is never opened here (the fixture forbids real native cache paths).
"""
import builtins
import hashlib
import importlib.util
import io
import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

import numpy as np
import pytest
from rasterio.io import MemoryFile
from rasterio.windows import Window

from skippercast.coastal.authenticated_v1 import observer, planner
from skippercast.coastal.authenticated_v1.policy import evaluate
from skippercast.coastal.authenticated_v1.supplement import summarize
from tests._support import FIXTURES, ROOT
from tests.gis.test_authenticated_worker_v1 import capture, fixture  # noqa: F401 (pytest fixture)

SCRIPT = ROOT / "research" / "scripts" / "coastal_four128_window_scan.py"


@pytest.fixture
def scan():
    spec = importlib.util.spec_from_file_location("coastal_four128_window_scan", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


BLOCK = dict(schema="vertical-v1", sign="positive_up", units="m", datum="MLLW", datum_realization="unknown",
             scale=1.0, offset=0.0, scale_offset_applied=False, conflicts=[],
             evidence=[dict(kind="raster_header", source_sha256="a" * 64, header_sha256="b" * 64, facts={})])
HEADER = dict(driver="BAG", scales=[1.0, 1.0], offsets=[0.0, 0.0], units=[None, None])


class FakeRaster:
    """Lattice-aligned 128 x 128 reads: -20 m elevation, 0.25 m uncertainty, plus edits."""
    nodatavals = (1000000.0, 1000000.0)

    def __init__(self, edits):
        self.edits = edits
        self.reads = []

    def read(self, band, *, window, masked):
        assert masked is True and (window.width, window.height) == (128, 128)
        key = (int(window.col_off), int(window.row_off))
        self.reads.append((band, key))
        values = np.full((128, 128), -20.0 if band == 1 else 0.25, dtype="float32")
        mask = np.zeros((128, 128), dtype=bool)
        for (b, r, c), value in self.edits.get(key, {}).items():
            if b == band:
                if value is np.ma.masked:
                    mask[r, c] = True
                    values[r, c] = 1000000.0
                else:
                    values[r, c] = value
        return np.ma.MaskedArray(values, mask=mask)


def masked_pairs(n):
    return {(band, 3, i): np.ma.masked for band in (1, 2) for i in range(n)}


def footprints(scan, positions):
    t = scan.transformers()
    return {(c, r): scan.footprint(c, r, t) for c, r, _, _ in positions}


def test_window_verdicts_follow_the_strict_policy(scan):
    edits = {(4018, 3488): masked_pairs(18),
             (4146, 3488): {(2, 0, 0): 1.2},
             (3890, 3616): {(1, 0, 0): 5.0},           # depth -5 m: below 0
             (4018, 3616): {(1, 0, 0): -91.43},        # depth 91.43 m: valid
             (4146, 3616): {(1, 0, 0): -91.44},        # FLOAT32 -91.44 is 91.44000244 m: beyond 91.44
             (4146, 3360): {(2, 0, 0): 0.0},           # uncertainty must be > 0
             (3762, 3360): {(2, 0, 0): 1.0}}           # 1 m inclusive, valid
    positions = [p for p in scan.candidates() if p[:2] in edits]
    records = {tuple(r["window"][:2]): r for r in
               scan.scan(FakeRaster(edits), BLOCK, HEADER, positions, footprints(scan, positions))}
    b = records[(4018, 3488)]
    assert (b["eligible"], b["mask_invalid"], b["fully_valid"]) == (16366, 18, False)
    assert scan.control_check(b, None) == []
    assert records[(4146, 3488)]["uncertainty_out_of_range"] == 1 and not records[(4146, 3488)]["fully_valid"]
    assert records[(3890, 3616)]["depth_finite_below_0"] == 1 and not records[(3890, 3616)]["fully_valid"]
    assert records[(4018, 3616)]["fully_valid"] and records[(4018, 3616)]["depth_max_m"] == pytest.approx(91.43)
    assert records[(4146, 3616)]["depth_finite_above_91_44"] == 1 and not records[(4146, 3616)]["fully_valid"]
    assert records[(4146, 3360)]["uncertainty_nonpositive"] == 1 and not records[(4146, 3360)]["fully_valid"]
    assert records[(3762, 3360)]["fully_valid"] and records[(3762, 3360)]["uncertainty_max_m"] == 1.0
    assert all(r["policy_holds"] == [] for r in records.values() if r["fully_valid"])


def test_selection_rule_on_a_synthetic_raster(scan):
    """Nearest valid window to B wins; a distance tie goes to the lowest maximum uncertainty."""
    edits = {(4018, 3488): masked_pairs(18),
             (4146, 3488): {(2, 5, 5): 1.01},
             (3890, 3616): {(1, 9, 9): 1.0},
             (4018, 3616): masked_pairs(1),
             (4146, 3360): {(2, 1, 1): 0.40},
             (4146, 3616): {(2, 1, 1): 0.30}}
    raster = FakeRaster(edits)
    positions = scan.candidates()
    records = scan.scan(raster, BLOCK, HEADER, positions, footprints(scan, positions))
    assert len(records) == 61 and len(raster.reads) == 122
    chosen = scan.select(records)
    assert chosen["window"] == [4146, 3616, 128, 128] and chosen["chebyshev_from_b"] == 1
    assert chosen["fits_slot_b_order"] is False
    # With that window poisoned too, the 0.40 m window at the same distance is next.
    edits[(4146, 3616)] = {(1, 0, 0): np.nan}
    records = scan.scan(FakeRaster(edits), BLOCK, HEADER, positions, footprints(scan, positions))
    assert scan.select(records)["window"] == [4146, 3360, 128, 128]
    assert {tuple(r["window"][:2]) for r in records if not r["fully_valid"]} == {
        (4018, 3488), (4146, 3488), (3890, 3616), (4018, 3616), (4146, 3616)}


def test_control_mismatch_is_reported(scan):
    positions = [p for p in scan.candidates() if p[:2] == (4018, 3488)]
    record = scan.scan(FakeRaster({(4018, 3488): masked_pairs(17)}), BLOCK, HEADER, positions,
                       footprints(scan, positions))[0]
    problems = scan.control_check(record, None)
    assert any("mask_invalid 17" in p for p in problems)
    doc = dict(counts=dict(record["counts"], eligible=1), array_hashes=record["array_hashes"],
               uncertainty=dict(minimum=record["uncertainty_min_m"], maximum=record["uncertainty_max_m"]))
    assert "counts differ from the attempt-4 diagnostics" in scan.control_check(record, doc)


def test_every_lattice_footprint_has_its_segment_margin(scan):
    fps = footprints(scan, scan.candidates())
    assert all(fp["segment_contained_10m"] == (fp["epsg3310_margin_m"] >= 10) for fp in fps.values())
    a = scan.footprint(3890, 3488, scan.transformers())
    assert a["native_bounds"] == [728871, 3818923, 729127, 3819179]


def test_parity_with_the_harness_observer_on_a_synthetic_bag(fixture, scan):
    """Same window, same verdict: the scan's arrays hash identically to the harness collector's."""
    root, bag, row, xmlsha, source, spec, grant = fixture
    with capture(fixture) as view:
        header = planner.read_header(view, source, row, xmlsha)
        captured = []
        observer.observe_snapshot(view, root, source, window=[0, 0, 16, 16], vertical=header["vertical"],
                                  source_row=row, metadata_sha256=xmlsha, collector=captured.append)
    harness = summarize(captured[0], "harness")
    data = bag.read_bytes()
    with mock.patch.object(scan, "METADATA_SHA256", xmlsha):
        xml, digest = scan.embedded_metadata(data)
    with MemoryFile(data) as memory, memory.open(driver="BAG") as dataset:
        block = scan.vertical_block(dataset, xml, "H11879", row["sha256"])
        head = dict(driver=dataset.driver, scales=list(dataset.scales), offsets=list(dataset.offsets),
                    units=list(dataset.units))
        window = Window(0, 0, 16, 16)
        ours = scan.evaluate_window(dataset.read(1, window=window, masked=True),
                                    dataset.read(2, window=window, masked=True),
                                    tuple(dataset.nodatavals), block, head, "parity")
    assert digest == xmlsha
    assert ours["array_hashes"] == harness["array_hashes"]
    assert ours["counts"] == harness["counts"]
    assert (ours["uncertainty_min_m"], ours["uncertainty_max_m"]) == (
        harness["uncertainty"]["minimum"], harness["uncertainty"]["maximum"])
    assert harness["counts"]["eligible"] < 256  # the fixture's poisoned first rows
    assert evaluate(harness, dict(header=head))["holds"]


def test_source_is_opened_once_and_hash_checked(scan):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "x.bag"
        path.write_bytes(b"abc")
        with mock.patch.multiple(scan, SOURCE_SHA256=hashlib.sha256(b"abc").hexdigest(), SOURCE_BYTES=3):
            assert scan.read_source(path) == b"abc"
            with pytest.raises(RuntimeError, match="once per invocation"):
                scan.read_source(path)
        scan.OPENS.clear()
        with pytest.raises(ValueError, match="pinned sha256"):
            scan.read_source(path)


def test_dry_run_never_opens_the_source(scan):
    with tempfile.TemporaryDirectory(dir=FIXTURES) as tmp:
        tmp = Path(tmp)
        source = tmp / "source.bag"
        source.write_bytes(b"not read")
        amendment = tmp / "v3.json"
        amendment.write_text(json.dumps(dict(amendment_revision=3, source=dict(window_prescan_charged_bytes=73515136))))
        real_open = builtins.open

        def guarded(path, *args, **kwargs):
            assert Path(path) != source, "dry run opened the source"
            return real_open(path, *args, **kwargs)
        sha = hashlib.sha256(amendment.read_bytes()).hexdigest()
        with mock.patch.object(scan, "AMENDMENT_SHA256", sha), mock.patch.object(builtins, "open", guarded), \
                mock.patch.object(io, "open", guarded), mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            rc = scan.main(["--dry-run", "--source", str(source), "--receipt", str(tmp / "r.json"),
                            "--amendment", str(amendment)])
        assert rc == 0 and scan.OPENS == [] and not (tmp / "r.json").exists()
        assert json.loads(out.getvalue())["source_opened"] is False
