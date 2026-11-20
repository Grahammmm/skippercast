"""Contracts for the released nearshore tokens and their generated projections."""

from hashlib import sha256
import json
from math import sqrt
import shutil
import subprocess
import sys

import pytest

from skippercast import style
from tests._support import ROOT

GEN = "scripts/style/gen_style.py"
RELEASE = "style/nearshore-v1.0.0.json"


def test_load_verifies_release_and_freezes_nested_values(tmp_path, monkeypatch):
    # A writable descendant or an unchecked edit makes a pinned render unreproducible.
    loaded = style.load()
    assert loaded.version == "nearshore-v1.0.0"
    assert style.load(loaded.version)["version"] == loaded["version"]
    with pytest.raises(TypeError):
        loaded["shading"]["hillshade"]["ve_min"] = 1
    with pytest.raises(TypeError):
        loaded["depth_ramp"]["stops_ft"][0][0] = 1
    with pytest.raises(ValueError, match="legacy builder"):
        style.load("deep-fixed-v1")

    raw = (ROOT / RELEASE).read_bytes()
    assert sha256(raw).hexdigest() == "fecc2af86e3313d16c630af22386d91567d7124753a48545f03f3f5271a786aa"
    shutil.copyfile(ROOT / "style/index.json", tmp_path / "index.json")
    (tmp_path / "nearshore-v1.0.0.json").write_bytes(raw + b"\n")  # still the same JSON
    monkeypatch.setattr(style, "_STYLE_DIR", tmp_path)
    with pytest.raises(ValueError, match="sha256 mismatch"):
        style.load()


def test_group_views_expose_only_their_groups_and_match_the_index(tmp_path):
    # Contract: render code reads through views (design 1.1), and a view's groups are the ones
    # its index digest was made from. Bugs caught: a paint key readable by a render path (or hidden
    # by .get), the two MSK-1 leaks, and a groups.json edit without regenerated digests.
    loaded = style.load()
    baked = loaded.view("baked")
    assert baked["rock_piles"]["fill_mix"] == loaded["rock_piles"]["fill_mix"]
    assert set(baked["rock_piles"]) == {"fill", "fill_mix", "overview_strength", "overview_rule", "closeup_min_zoom"}
    for read in (lambda: baked["rock_piles"]["outline"], lambda: baked["typography"],
                 lambda: baked.get("contours"), lambda: baked["acceptance"], lambda: baked.digest("paint")):
        with pytest.raises(style.StyleGroupError):
            read()
    assert "typography" not in baked and "typography" not in set(baked)
    assert "features_by_cell_m" in baked["resolution_tiers"]  # moved from paint (piles gate)
    assert loaded.view("contours")["pier_view"]["contours_tier"] == "pier"  # moved from paint
    assert loaded.view("baked", "habitat")["rock_piles"]["label"]["nms_m"] == 28.0
    assert baked.digest("baked") == loaded.digest("baked")
    for groups in ((), ("meta",)):
        with pytest.raises(ValueError):
            loaded.view(*groups)

    for name in ("index.json", "groups.json", "nearshore-v1.0.0.json"):
        shutil.copyfile(ROOT / "style" / name, tmp_path / name)
    assert style.load(root=tmp_path).view("baked")["surface"] == loaded["surface"]
    rules = json.loads((tmp_path / "groups.json").read_bytes())
    rules["resolution_tiers.features_by_cell_m"] = "paint"
    (tmp_path / "groups.json").write_text(json.dumps(rules), encoding="utf-8")
    with pytest.raises(ValueError, match="disagrees with the index digests"):
        style.load(root=tmp_path)


def test_ve_and_vrm_use_cell_size_not_zoom_or_linear_vrm():
    loaded = style.load()
    assert [loaded.ve_for(cell) for cell in (1, 2, 4, 10)] == pytest.approx([2.35, 3, 3.82, 5], abs=.01)
    assert style.ve_for(2) == 3 and loaded.ve_for(10) == 5
    table = loaded["derived"]["rock_piles"]["vrm_hard_min_by_cell_m"]
    for cell, minimum in table:
        assert loaded.vrm_hard_min(cell) == minimum
    for (a, x), (b, y) in zip(table, table[1:]):
        assert loaded.vrm_hard_min(sqrt(a * b)) == pytest.approx(sqrt(x * y))


def test_srgb_ramp_and_zoom_interpolate_and_clamp():
    # Linear-light blending, channel rounding, or extrapolation gives different values.
    loaded = style.load()
    assert loaded.ramp_rgb(0) == tuple(bytes.fromhex("EAF8F4"))
    assert loaded.ramp_rgb(5) == (219.5, 243.5, 238)
    last = loaded["depth_ramp"]["stops_ft"][-1][1]
    assert loaded.ramp_rgb(2000) == tuple(bytes.fromhex(last[1:]))
    assert [style.zinterp(((7, 20), (9, 30)), z) for z in (0, 8, 10)] == [20, 25, 30]


@pytest.mark.parametrize(("zoom", "cell", "view", "tier"), [
    (15, 2, None, "z15"), (15, 4, None, "z13"), (16, 1, "pier", "pier"), (13, 10, None, "z11"),
    (16, 4, "pier", "z13"), (7, 2, None, "z8"), (15, 1, "pier", "pier"), (16, 2, None, "z15"),
])
def test_contours_gate_tiers_by_native_cell_and_pier_view(zoom, cell, view, tier):
    # Picking by zoom alone would fabricate detail at coarse resolutions. The pier tier is the
    # pier view's only (kit reference contour_tier); a z16 map view keeps the z15 tier.
    assert style.contour_tier(zoom, cell, view)["name"] == tier


def test_resolution_table_uses_coarser_tier_between_entries():
    loaded = style.load()
    assert "rock_piles" in loaded.features_for(2)
    assert "rock_piles" not in loaded.features_for(4)
    assert "rock_piles" not in loaded.features_for(2.01)
    assert loaded.native_max_zoom(2) == 16
    assert loaded.native_max_zoom(2.01) == 14


def check(root):
    return subprocess.run([sys.executable, GEN, "--check"], cwd=root, capture_output=True, text=True)


def test_parity_keys_are_canonical_hashes_of_their_members():
    # Contract: kit_parity, the tiles provenance (MSK-4) and QA (MSK-8) derive the same parity and
    # oracle keys (design 5.2). Bugs caught: a member left out of a key (stale parity reused after
    # an engine, epoch, runtime, look or kit change) or a key format that differs between callers.
    from skippercast.style import parity
    h = [sha256(bytes([i])).hexdigest() for i in range(6)]
    runtime = {"python": "3.13.5", "numpy": "2.5.3", "scipy": "1.17.1"}
    members = dict(engine_digest=h[0], engine_epoch=1, runtime=runtime, baked=h[1], kit_zip_sha256=h[2],
                   files_manifest_sha256=h[3], oracle_key=h[4])
    key = parity.parity_key(**members)
    doc = {"engine_digest": h[0], "engine_epoch": 1, "runtime": runtime, "baked": h[1],
           "fixtures": {"kit_zip_sha256": h[2], "files_manifest_sha256": h[3]}, "oracle_key": h[4]}
    assert key == sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    for name, other in (("engine_digest", h[5]), ("engine_epoch", 2), ("runtime", {**runtime, "scipy": "1.18.1"}),
                        ("baked", h[5]), ("kit_zip_sha256", h[5]), ("files_manifest_sha256", h[5]), ("oracle_key", h[5])):
        assert parity.parity_key(**{**members, name: other}) != key, name
    for name, bad in (("runtime", {**runtime, "pillow": "13"}), ("baked", "B"), ("engine_epoch", True)):
        with pytest.raises(ValueError):
            parity.parity_key(**{**members, name: bad})
    refs, venv = dict(zip(parity.REFERENCE_FILES, h)), {"venv": "kit pins"}
    oracle = parity.oracle_key(h[2], h[3], refs, venv, {"case": ["$FX/dem.tif"]})
    assert oracle != parity.oracle_key(h[2], h[3], refs, venv, {"case": ["$FX/dem.tif", "--class"]})
    assert len(parity.engine_digest()) == 64


def test_generator_check_matches_checkout():
    # CI catches missed regeneration even when only the checked-in output changed.
    result = check(ROOT)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(("drift", "diagnostic"), [
    ("release", "sha256 mismatch"),
    ("unassigned", "unassigned style key: rock_piles.future_knob"),
    ("digest", "index digests disagree"),
    ("projection", "generated file drift: web/map/nearshore-style.gen.ts"),
])
def test_generator_check_refuses_drift_without_writing(tmp_path, drift, diagnostic):
    # Independently trip the raw-byte pin, group coverage, digest and projection checks.
    paths = [GEN, "src/skippercast/__init__.py", "src/skippercast/style/__init__.py", RELEASE,
             "style/index.json", "style/groups.json", "web/tokens.css",
             "web/map/nearshore-style.gen.ts", "packages/coast/src/palette.ts"]
    for name in paths:
        dest = tmp_path / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, dest)

    release = tmp_path / RELEASE
    manifest = tmp_path / "style/index.json"
    ts = tmp_path / "web/map/nearshore-style.gen.ts"
    if drift == "projection":
        ts.write_bytes(ts.read_bytes() + b"// stale\n")
    else:
        tokens = json.loads(release.read_bytes())
        if drift == "unassigned":
            tokens["rock_piles"]["future_knob"] = True
        else:
            tokens["shading"]["hillshade"]["ve_min"] += 1
        raw = json.dumps(tokens).encode()
        release.write_bytes(raw)
        if drift != "release":
            index = json.loads(manifest.read_bytes())
            index["versions"][index["default"]]["sha256"] = sha256(raw).hexdigest()
            manifest.write_text(json.dumps(index), encoding="utf-8")

    def snapshot():
        return {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    before = snapshot()
    result = check(tmp_path)
    assert result.returncode == 1, result.stderr
    assert diagnostic in result.stderr
    assert snapshot() == before
