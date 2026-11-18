"""F06-14 / SCA-579: VR refinement caps ignore the aggregate of all output lattices.

Offline fixture with synthetic lattice descriptors only; no BAG, no GIS stack.
`_bounded` checks the lattice count and the largest lattice, never their sum, so
two individually legal groups over the aggregate cap reach bulk allocation.
The strict xfail states the wanted outcome (hold with zero TIFFs written) and
turns into a failure, to be removed, once an aggregate preflight exists.
"""
import pytest

from skippercast.coastal.handoff import vr_refinements as vr


def _group(index, side):
    return dict(id=f"synthetic-lattice{index:04d}", width=side, height=side, members=[])


# Each lattice is under MAX_OUTPUT_CELLS; two together exceed it.
SIDE = int((vr.MAX_OUTPUT_CELLS * 0.6) ** 0.5)


def test_valid_control_single_lattice_within_caps():
    group = _group(0, SIDE)
    assert group["width"] * group["height"] <= vr.MAX_OUTPUT_CELLS
    vr._bounded([group])


def test_affected_control_two_legal_lattices_exceed_aggregate_but_pass_bounds():
    groups = [_group(0, SIDE), _group(1, SIDE)]
    assert all(g["width"] * g["height"] <= vr.MAX_OUTPUT_CELLS for g in groups)
    assert sum(g["width"] * g["height"] for g in groups) > vr.MAX_OUTPUT_CELLS
    vr._bounded(groups)  # observation: no aggregate bound exists today


def _emit_with_synthetic_groups(monkeypatch, tmp_path, groups):
    reached = []

    def bulk_fill(_model, group):
        reached.append(group["id"])
        raise RuntimeError("bulk allocation reached")

    monkeypatch.setattr(vr, "_read_source", lambda *a, **k: {"supergrids": [], "nodata": -9999.0, "survey_id": "SYN"})
    monkeypatch.setattr(vr, "_gdal_probe", lambda *a, **k: None)
    monkeypatch.setattr(vr, "_probe_sample", lambda *a, **k: [])
    monkeypatch.setattr(vr, "_place", lambda *a, **k: groups)
    monkeypatch.setattr(vr, "_expected_tags", lambda *a, **k: {})
    monkeypatch.setattr(vr, "_fill", bulk_fill)
    source = {"sha256": "0" * 64}
    try:
        vr.emit(tmp_path, source, source_row={}, metadata_sha256="0" * 64, output_dir="out")
    except Exception as error:  # noqa: BLE001 - the outcome is what is observed
        return error, reached
    return None, reached


def test_affected_control_emit_reaches_bulk_allocation(monkeypatch, tmp_path):
    error, reached = _emit_with_synthetic_groups(monkeypatch, tmp_path, [_group(0, SIDE), _group(1, SIDE)])
    assert isinstance(error, RuntimeError) and reached == ["synthetic-lattice0000"]


@pytest.mark.xfail(strict=True, reason="F06-14: no aggregate output-cell/byte preflight")
def test_aggregate_over_cap_holds_before_any_allocation(monkeypatch, tmp_path):
    error, reached = _emit_with_synthetic_groups(monkeypatch, tmp_path, [_group(0, SIDE), _group(1, SIDE)])
    assert isinstance(error, ValueError) and not reached
    assert not list(tmp_path.rglob("*.tif"))
