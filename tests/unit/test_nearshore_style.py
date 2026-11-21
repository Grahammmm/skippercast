"""Contracts for the released nearshore tokens and their generated projections."""

from hashlib import sha256
import json
from math import sqrt
import re
import shutil
import subprocess
import sys

import pytest

from skippercast import style
from tests._support import ROOT

GEN = "scripts/style/gen_style.py"
RELEASE = "style/nearshore-v1.0.0.json"
LAYERS = "style/layers-v1.0.0.json"
STACKING = "style/stacking-v1.0.0.json"
FRAGMENT = "style/generated/maplibre-layers-v1.0.0.json"


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


def copy_generator(tmp_path):
    paths = [GEN, "src/skippercast/__init__.py", "src/skippercast/style/__init__.py", RELEASE,
             "style/index.json", "style/groups.json", "web/tokens.css",
             "web/map/nearshore-style.gen.ts", "packages/coast/src/palette.ts",
             "scripts/style/layers_fragment.py", LAYERS, STACKING, FRAGMENT, "web/map/layers-style.gen.ts"]
    for name in paths:
        dest = tmp_path / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, dest)


def add_version(root, version, edit, status="rolling"):
    """Release a copy of v1.0.0 as `version` after `edit`, registered in index.json without digests."""
    tokens = json.loads((root / RELEASE).read_bytes())
    tokens["version"] = version  # a paint key
    edit(tokens)
    raw = json.dumps(tokens).encode()
    (root / f"style/{version}.json").write_bytes(raw)
    manifest = root / "style/index.json"
    index = json.loads(manifest.read_bytes())
    index["versions"][version] = {"file": f"{version}.json", "sha256": sha256(raw).hexdigest(), "status": status}
    manifest.write_text(json.dumps(index), encoding="utf-8")


def generate(root):
    return subprocess.run([sys.executable, GEN], cwd=root, capture_output=True, text=True)


def looks(root):
    ts = (root / "web/map/nearshore-style.gen.ts").read_text(encoding="utf-8")
    return json.loads(re.search(r"(?s)export const NEARSHORE_LOOKS = (\{.*?\n\}) as const;", ts)[1])


DEFAULT_BAKED = json.loads((ROOT / "style/index.json").read_bytes())["versions"]["nearshore-v1.0.0"]["digests"]["baked"]


def test_paint_only_bump_shares_one_look(tmp_path):
    # MSK-2 amendment A3 case 1: a paint-only version draws the same relief, so it must not fork the legend chips.
    copy_generator(tmp_path)
    css_before = (tmp_path / "web/tokens.css").read_bytes()
    add_version(tmp_path, "nearshore-v1.0.1",
                lambda t: t["overlays"]["field_opacity_by_zoom"][0].__setitem__(1, 0.7))
    result = generate(tmp_path)
    assert result.returncode == 0, result.stderr
    table = looks(tmp_path)
    assert set(table) == {DEFAULT_BAKED, "deep-fixed-v1"}
    assert table[DEFAULT_BAKED]["versions"] == ["nearshore-v1.0.0", "nearshore-v1.0.1"]
    assert (tmp_path / "web/tokens.css").read_bytes() == css_before
    assert check(tmp_path).returncode == 0


def test_baked_bump_adds_a_second_look_with_its_own_colours(tmp_path):
    # A3 case 2: a baked change is a new look; regions still on the old tiles keep the old chips.
    copy_generator(tmp_path)
    add_version(tmp_path, "nearshore-v1.1.0", lambda t: t["depth_ramp"]["stops_ft"][0].__setitem__(1, "#EAF8F5"))
    result = generate(tmp_path)
    assert result.returncode == 0, result.stderr
    table = looks(tmp_path)
    (new,) = set(table) - {DEFAULT_BAKED, "deep-fixed-v1"}
    assert table[new]["versions"] == ["nearshore-v1.1.0"]
    prefix = f"--skn-look-{new[:12]}-depth-"
    assert table[new]["chips"][0]["cssVar"] == f"{prefix}0"
    assert table[DEFAULT_BAKED]["chips"][0]["cssVar"] == "--skn-depth-ns-0"
    css = (tmp_path / "web/tokens.css").read_text(encoding="utf-8")
    assert f"  {prefix}0: #EAF8F5;\n" in css
    assert new in (tmp_path / "packages/coast/src/palette.ts").read_text(encoding="utf-8")
    assert check(tmp_path).returncode == 0


@pytest.mark.parametrize("where", ["pointer", "previous"])
def test_check_refuses_a_pointer_whose_look_left_the_index(tmp_path, where):
    # A3: retiring a version while a pointer (or the lineage it can roll back to) names its look strands the legend.
    copy_generator(tmp_path)
    style_member = {"baked": "f" * 64, "contours": None, "habitat": None, "built_with": "nearshore-v0.9.0"}
    pointer = {"region": "fixture"}
    if where == "pointer":
        pointer["style"] = style_member
    else:
        pointer["previous"] = {"style": style_member}
    relief = tmp_path / "catalog/relief"
    relief.mkdir(parents=True)
    (relief / "fixture.json").write_text(json.dumps(pointer), encoding="utf-8")
    result = check(tmp_path)
    assert result.returncode == 1
    assert f"catalog/relief/fixture.json: {where} look {'f' * 64} is missing from LOOKS" in result.stderr
    # contours null is a valid member: naming the released look passes.
    style_member["baked"] = DEFAULT_BAKED
    (relief / "fixture.json").write_text(json.dumps(pointer), encoding="utf-8")
    assert check(tmp_path).returncode == 0, check(tmp_path).stderr
    # A still-retained baked look must not hide the loss of a separately named contour group.
    style_member["contours"] = "f" * 64
    (relief / "fixture.json").write_text(json.dumps(pointer), encoding="utf-8")
    result = check(tmp_path)
    assert result.returncode == 1
    assert f"{where} contours {'f' * 64} is missing from CONTOUR_TIERS" in result.stderr


@pytest.mark.parametrize(("drift", "diagnostic"), [
    ("release", "sha256 mismatch"),
    ("unassigned", "unassigned style key: rock_piles.future_knob"),
    ("digest", "index digests disagree"),
    ("projection", "generated file drift: web/map/nearshore-style.gen.ts"),
    ("layer-colour", "layers-v1.0.0: sha256 mismatch"),
    ("missing-layer-var", "generated file drift: web/tokens.css"),
    ("extra-layer-var", "generated file drift: web/tokens.css"),
    ("fragment-byte", f"generated file drift: {FRAGMENT}"),
    ("fragment-pin", "fragment canonical sha256 mismatch"),
    ("layer-module", "generated file drift: web/map/layers-style.gen.ts"),
])
def test_generator_check_refuses_drift_without_writing(tmp_path, drift, diagnostic):
    # Independently trip the raw-byte pin, group coverage, digest and projection checks.
    copy_generator(tmp_path)

    release = tmp_path / RELEASE
    manifest = tmp_path / "style/index.json"
    ts = tmp_path / "web/map/nearshore-style.gen.ts"
    if drift == "projection":
        ts.write_bytes(ts.read_bytes() + b"// stale\n")
    elif drift == "layer-colour":
        path = tmp_path / LAYERS
        raw = path.read_bytes()
        first = re.search(rb'"#[0-9a-fA-F]{6}"', raw)
        assert first is not None
        replacement = b'"#123456"' if first[0] != b'"#123456"' else b'"#654321"'
        path.write_bytes(raw[:first.start()] + replacement + raw[first.end():])
    elif drift in {"missing-layer-var", "extra-layer-var"}:
        css = tmp_path / "web/tokens.css"
        raw = css.read_bytes()
        if drift == "missing-layer-var":
            css.write_bytes(re.sub(rb"(?m)^  --skl-[^\n]+\n", b"", raw, count=1))
        else:
            css.write_bytes(raw.replace(b"  /* skl:end */", b"  --skl-orphan: #123456;\n  /* skl:end */"))
    elif drift == "fragment-byte":
        path = tmp_path / FRAGMENT
        # Same parsed fragment: check must require exact output bytes, not just its digest.
        path.write_bytes(path.read_bytes().removesuffix(b"\n") + b" ")
    elif drift == "fragment-pin":
        index = json.loads(manifest.read_bytes())
        index["layers"][index["layers_default"]]["fragment_canonical_sha256"] = "0" * 64
        manifest.write_text(json.dumps(index), encoding="utf-8")
    elif drift == "layer-module":
        path = tmp_path / "web/map/layers-style.gen.ts"
        path.write_bytes(path.read_bytes() + b"// stale\n")
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


def test_layer_loader_resolves_the_released_stack_and_leaves_prose():
    # The released SST opacity must follow stacking; treating prose as a path would reject this release.
    layers = style.load_layers()
    base = style.load()
    assert layers["layers"]["sst-fill"]["opacity"] == base["overlays"]["field_opacity_by_zoom"]
    raw = json.loads((ROOT / LAYERS).read_bytes())
    assert layers["regional_base"]["land_rule"] == raw["regional_base"]["land_rule"]
    with pytest.raises(TypeError):
        layers["layers"]["sst-fill"]["opacity"][0][1] = 1
    with pytest.raises(TypeError):
        layers["stacking"]["z_order"][0]["z"] = 1


@pytest.mark.parametrize(("path", "diagnostic"), [(LAYERS, "layers-v1.0.0"), (STACKING, "stacking-v1.0.0.json")])
def test_layer_loader_refuses_both_changed_raw_files(tmp_path, path, diagnostic):
    copy_generator(tmp_path)
    release = tmp_path / path
    release.write_bytes(release.read_bytes() + b"\n")
    with pytest.raises(ValueError, match=rf"{re.escape(diagnostic)}: sha256 mismatch"):
        style.load_layers(root=tmp_path / "style")


@pytest.mark.parametrize(("value", "diagnostic"), [
    ("base:depth_ramp.stops_ft.0.1", None),
    ("base:depth_ramp.stops_ft.999.1", "unresolvable layer reference"),
    ("stacking:missing", "unresolvable layer reference"),
    ("stacking:cycle", "layer reference depth exceeds 8"),
    (None, "base_tokens.version does not match"),
])
def test_layer_loader_validates_reference_paths_and_pinned_base(tmp_path, value, diagnostic):
    # Validly rehash altered inputs so a pin error cannot mask bad paths, cycles or a wrong base release.
    copy_generator(tmp_path)
    path = tmp_path / LAYERS
    tokens = json.loads(path.read_bytes())
    tokens["probe"] = value
    if value is None:
        tokens["base_tokens"]["version"] = "0.0.0"
    raw = json.dumps(tokens).encode()
    path.write_bytes(raw)
    manifest = tmp_path / "style/index.json"
    index = json.loads(manifest.read_bytes())
    entry = index["layers"][index["layers_default"]]
    entry["sha256"] = sha256(raw).hexdigest()
    if value == "stacking:cycle":
        path = tmp_path / STACKING
        stack = json.loads(path.read_bytes())
        stack["cycle"] = "stacking:cycle"
        raw = json.dumps(stack).encode()
        path.write_bytes(raw)
        entry["stacking_sha256"] = sha256(raw).hexdigest()
    manifest.write_text(json.dumps(index), encoding="utf-8")
    if diagnostic:
        with pytest.raises(ValueError, match=diagnostic):
            style.load_layers(root=tmp_path / "style")
    else:
        assert style.load_layers(root=tmp_path / "style")["probe"] == style.load()["depth_ramp"]["stops_ft"][0][1]
