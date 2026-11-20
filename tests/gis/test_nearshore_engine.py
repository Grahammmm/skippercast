"""Contracts of the nearshore render engine (MSK-3): kit rules, group views and pinned goldens."""

import ast
from hashlib import sha256
import importlib.util
import json
import re
import sys

import numpy as np
import pytest

from skippercast import style
from skippercast.relief import nearshore
from tests._support import ROOT

GOLDENS = ROOT / "tests/fixtures/style/nearshore-v1.0.0"


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/style/{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


GOLD = _script("make_synthetic_goldens")
png8 = sys.modules["png8"]  # imported by the goldens script from scripts/style/
STYLE = style.load()
BAKED = STYLE.view("baked")
ACC = STYLE["acceptance"]  # meta: QA thresholds, never read by the engine


@pytest.fixture(scope="module")
def grids():
    return GOLD.synthetic_grids()


@pytest.fixture(scope="module")
def renders(grids):
    return {cell: GOLD.render(BAKED, *grid) for cell, grid in grids.items()}


def _golden(name):
    return png8.decode((GOLDENS / name).read_bytes())


def _lstar(rgb):
    """CIE L* of 8-bit sRGB (D65), as skimage's rgb2lab used by the kit's compare.py."""
    c = rgb / 255.0
    linear = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    y = linear @ np.array([0.212671, 0.715160, 0.072169])
    return 116 * np.where(y > 0.008856, np.cbrt(y), 7.787 * y + 16 / 116) - 16


@pytest.mark.parametrize("cell", GOLD.CELLS)
def test_rerender_matches_goldens_within_kit_tolerance(renders, cell):
    # Contract: the committed engine goldens are what the engine renders (acceptance.base,
    # acceptance.piles). Bug caught: any look change (VE, shade, ramp, pile rule) without new goldens.
    images, piles, _ = renders[cell]
    base = ACC["base"]
    for kind in ("closeup", "overview", "nopiles"):
        diff = np.abs(images[kind].astype(float) - _golden(f"s{cell}m_{kind}.png").astype(float))
        assert diff.reshape(-1, 3).mean(axis=0).max() <= base["mean_abs_per_channel_max"], kind
        assert np.percentile(diff.reshape(-1, 3), 99, axis=0).max() <= base["p99_abs_per_channel_max"], kind
    golden_mask = _golden(f"s{cell}m_mask.png")[..., 0] > 127
    mask = images["mask"] > 127
    union = (mask | golden_mask).sum()
    assert (1.0 if union == 0 else (mask & golden_mask).sum() / union) >= ACC["piles"]["mask_iou_min"]
    expected = json.loads((GOLDENS / "metrics.json").read_text())["grids"][f"s{cell}m"]["piles"]
    assert abs(len(piles) - expected) / max(expected, 1) <= ACC["piles"]["count_rel_max"]


def test_cross_resolution_lstar_spread(renders):
    # Contract: the cell-size VE keeps relief contrast equal at 1, 2 and 4 m (kit section 5.2,
    # acceptance.cross_resolution). Bug caught: VE by zoom or a constant VE (1.04/0.92 in the kit).
    x = ACC["cross_resolution"]
    lstar = {}
    for cell, (images, _, _) in renders.items():
        a, f = images["nopiles"].astype(float), 4 // cell
        rows, cols = a.shape[0] // f * f, a.shape[1] // f * f
        a = a[:rows, :cols].reshape(rows // f, f, cols // f, f, 3).mean(axis=(1, 3))
        lstar[cell] = _lstar(a)
    for cell in (1, 4):
        ratio = lstar[cell].std() / lstar[2].std()
        assert x["water_Lstar_std_ratio"][0] <= ratio <= x["water_Lstar_std_ratio"][1], (cell, ratio)
        assert abs(lstar[cell].mean() - lstar[2].mean()) <= x["water_Lstar_mean_abs_diff_max"]


def test_golden_set_is_pinned_to_engine_epoch():
    # Contract: regenerated goldens need a new ENGINE_EPOCH row (design 5.1); goldens stay small.
    # Bug caught: a look change that silently rewrites the goldens under the old epoch.
    pngs = sorted(GOLDENS.glob("*.png"))
    epochs = json.loads((GOLDENS / "epochs.json").read_text())
    assert {p.name: sha256(p.read_bytes()).hexdigest() for p in pngs} == epochs[str(nearshore.ENGINE_EPOCH)]
    for path in pngs:
        assert path.stat().st_size <= 60_000 and max(_golden(path.name).shape[:2]) <= 256, path.name


def _boulder_field(size_m, cell, boulders, land_x=None, holes=()):
    """Flat -10 m bottom with rough Gaussian boulders (x, y, height m), optional land and holes."""
    n = int(size_m / cell)
    centres = (np.arange(n) + 0.5) * cell
    x, y = np.meshgrid(centres, centres)
    z = np.full((n, n), -10.0)
    rng = np.random.default_rng(7)
    rough = rng.random((n, n)) * 0.3
    for bx, by, height in boulders:
        bump = height * np.exp(-((x - bx) ** 2 + (y - by) ** 2) / (2 * 6.0 ** 2))
        z += bump + rough * (bump > 0.3)
    if land_x is not None:
        z[x >= land_x] = 2.0
    for hx, hy, radius in holes:
        z[(x - hx) ** 2 + (y - hy) ** 2 < radius ** 2] = np.nan
    return z, (0.0, 0.0, n * cell, n * cell)


def test_no_piles_on_cells_coarser_than_the_pile_limit(grids, renders):
    # Contract: coarse_rule (cells > rock_piles.max_cell_m: no detection, no tint).
    # Bug caught: detecting on 4 m BlueTopo, where the kit measured IoU 0.63 only.
    assert renders[4][1] == [] and not renders[4][0]["mask"].any()
    assert np.array_equal(renders[4][0]["closeup"], renders[4][0]["nopiles"])
    limit = BAKED["derived"]["rock_piles"]["max_cell_m"]
    for cell, expect in ((limit, True), (limit * 1.25, False)):
        z, bounds = _boulder_field(160, cell, [(80, 80, 4.0)])
        assert bool(nearshore.Nearshore(z, cell, bounds, BAKED).piles()[1]) is expect, cell


def test_piles_keep_their_distance_from_no_data_and_land():
    # Contract: candidates lie more than min_dist_from_nodata_m from no data and more than
    # min_dist_from_land_m from land (kit section 4). Bug caught: distances in cells, or a
    # swapped/missing zone term that puts piles on the edge of a gap or the beach.
    rule = BAKED["derived"]["rock_piles"]
    z, bounds = _boulder_field(160, 1.0, [(40, 62, 4.0), (138, 100, 4.0), (70, 125, 4.0)],
                               land_x=150, holes=[(40, 40, 6)])
    engine = nearshore.Nearshore(z, 1.0, bounds, BAKED)
    mask, piles = engine.piles()
    assert mask.any()
    rows, cols = np.nonzero(mask)
    nodata_r, nodata_c = np.nonzero(engine.nodata)
    land_r, land_c = np.nonzero(engine.land)
    d_nodata = np.hypot(rows[:, None] - nodata_r, cols[:, None] - nodata_c).min(axis=1)
    d_land = np.hypot(rows[:, None] - land_r, cols[:, None] - land_c).min(axis=1)
    assert d_nodata.min() > rule["min_dist_from_nodata_m"] and d_land.min() > rule["min_dist_from_land_m"]
    peaks = {(round(p["x"] / 10), round(p["y"] / 10)) for p in piles}
    assert (7, 3) in peaks  # the free boulder (x 70 m, y 125 m from the south edge = 35 m from the north)
    assert all(p["basis"] == "relief" for p in piles)


def test_no_data_pixels_are_exactly_the_no_data_colour(grids, renders):
    # Contract: step 8 repaints every no-data cell with surface.no_data. Bug caught: the
    # nearest-filled elevation leaking into the picture, or tint/land paint over a gap.
    colour = tuple(bytes.fromhex(BAKED["surface"]["no_data"]["color"][1:]))
    for cell, (z, _, _) in grids.items():
        hole = ~np.isfinite(z)
        assert hole.any()
        for kind in ("closeup", "overview", "nopiles"):
            assert {tuple(px) for px in renders[cell][0][kind][hole]} == {colour}


def test_vertical_exaggeration_follows_cell_size(grids):
    # Contract: ve_rule by cell size (kit 5.2). Bug caught: VE by zoom or the constant reference VE.
    examples = BAKED["shading"]["hillshade"]["ve_by_cell_m_examples"]
    for cell, (z, size, bounds) in grids.items():
        assert nearshore.Nearshore(z, size, bounds, BAKED).ve == pytest.approx(examples[str(cell)], abs=.01)
    z, bounds = _boulder_field(200, 10.0, [])
    assert nearshore.Nearshore(z, 10.0, bounds, BAKED).ve == BAKED.ve_for(10) == examples["10"]


def test_chunks_with_the_tile_buffer_match_the_whole_render():
    # Contract: absolute thresholds and metre kernels make a buffered chunk equal the whole
    # (kit section 4, design 3.2). Bug caught: per-window percentiles or kernels wider than the buffer.
    z = np.vstack([GOLD.surface_1m(seed)[0] for seed in (11, 12)])
    rows, cols = z.shape
    buffer = int(BAKED["shading"]["tile_buffer_m"])
    whole = nearshore.Nearshore(z, 1.0, (0, 0, cols, rows), BAKED)
    half = rows // 2
    parts = []
    for top, bottom, crop in ((0, half + buffer, slice(0, half)), (half - buffer, rows, slice(buffer, None))):
        engine = nearshore.Nearshore(z[top:bottom], 1.0, (0, rows - bottom, cols, rows - top), BAKED)
        parts.append((engine.base("closeup")[crop], engine.piles()[0][crop]))
    assert whole.piles()[1]
    stitched = np.vstack([image for image, _ in parts])
    assert np.abs(nearshore.to_bytes(stitched).astype(int) - nearshore.to_bytes(whole.base("closeup"))).max() <= 1
    assert np.array_equal(np.vstack([mask for _, mask in parts]), whole.piles()[0])


def test_engine_and_helpers_read_only_their_views(grids):
    # Contract: render code reads style values only through its group view (design 1.1), so the
    # baked/contours digests cover everything it reads. Bug caught: a helper or engine step that
    # depends on a paint key, or an engine that accepts the whole style file.
    z, cell, bounds = grids[2]
    for wrong in (STYLE, STYLE.view("baked", "paint"), STYLE.view("paint")):
        with pytest.raises(TypeError):
            nearshore.Nearshore(z, cell, bounds, wrong)
    with pytest.raises(style.StyleGroupError):
        BAKED["rock_piles"]["outline"]
    with pytest.raises(style.StyleGroupError):
        BAKED.get("typography")
    assert "features_by_cell_m" in BAKED["resolution_tiers"] and "legend_note" not in BAKED["resolution_tiers"]
    assert BAKED.ve_for(2) == STYLE.ve_for(2) and BAKED.vrm_hard_min(1.5) == STYLE.vrm_hard_min(1.5)
    assert "rock_piles" in BAKED.features_for(2) and BAKED.native_max_zoom(1) == 17
    assert BAKED.zinterp(((0, 0), (2, 4)), 1) == 2
    engine = nearshore.Nearshore(z, cell, bounds, BAKED)
    depths = np.array([[0.0, 7.5, 95.0, 2000.0]])
    probe = nearshore.Nearshore(-depths / nearshore.FT_PER_M, cell, (0, 0, 4 * cell, cell), BAKED)
    expected = np.array([BAKED.ramp_rgb(d) for d in probe.depth_ft[0]]) / 255
    assert np.allclose(probe.depth_rgb()[0], expected)
    contours = STYLE.view("contours")
    with pytest.raises(TypeError):
        engine.contour_depth(BAKED, 15)
    for zoom, view, name in ((15, None, "z15"), (17, "pier", "pier"), (13, None, "z13")):
        tier, depth = engine.contour_depth(contours, zoom, view)
        assert tier["name"] == name
        assert np.isnan(depth[~engine.water]).all() and np.isfinite(depth[engine.water]).all()
    habitat = STYLE.view("baked", "habitat")
    label = habitat["rock_piles"]["label"]
    piles = engine.piles()[1]
    labels = nearshore.pile_labels(piles, habitat, cell)
    assert 0 < len(labels) <= label["max_per_view"]
    assert [p["height_m"] for p in labels] == sorted((p["height_m"] for p in labels), reverse=True)
    assert all(np.hypot(a["x"] - b["x"], a["y"] - b["y"]) > label["nms_m"] for a in labels for b in labels if a is not b)
    assert nearshore.pile_labels(piles, habitat, label["max_cell_m"] * 2) == []
    with pytest.raises(TypeError):
        nearshore.pile_labels(piles, BAKED, cell)


def _numbers(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub) and _numbers(node.operand) is not None:
        return -_numbers(node.operand)
    return None


def test_engine_has_no_token_literals():
    # Contract: values live only in the token file (kit header; design 5.1). Bug caught: a copied
    # threshold, gain, colour or kernel size that a style bump would not change.
    tree = ast.parse((ROOT / "src/skippercast/relief/nearshore.py").read_text())
    literals, negated = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.UnaryOp) and _numbers(node) is not None:
            literals.add(_numbers(node))
            negated.add(id(node.operand))
    literals |= {_numbers(n) for n in ast.walk(tree) if _numbers(n) is not None and id(n) not in negated}
    strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]

    def leaves(value):
        if isinstance(value, dict):
            for item in value.values():
                yield from leaves(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                yield from leaves(item)
        else:
            yield value

    raw = json.loads((ROOT / "style/nearshore-v1.0.0.json").read_text())
    tokens = {v for v in leaves(raw) if isinstance(v, (int, float)) and not isinstance(v, bool)}
    structural = {0, 1, 2, 0.5}  # indices, unit factors, squares, the pixel centre
    assert literals & tokens <= structural, sorted(literals & tokens - structural)
    assert not [s for s in strings if re.search(r"#[0-9A-Fa-f]{6}", s)]
    colours = {v[1:].lower() for v in leaves(raw) if isinstance(v, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", v)}
    source = (ROOT / "src/skippercast/relief/nearshore.py").read_text().lower()
    assert colours and not [c for c in colours if c in source]
