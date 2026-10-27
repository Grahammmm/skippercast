"""Read-only pre-scan of candidate four128 windows on the cached H11952 BAG (T08-FIX3).

Attempt 4 of the 2026-10-19 four128 trial held at B-acquire: window B
[4018,3488,128,128] has 18 mask-invalid BAG cells, so the strict fixed-patch
policy (all 16,384 pairs eligible) refused it. G decision 2026-10-19 21:10 PDT
(option A): scan candidate windows on the cached BAG, replace B with a fully
valid window, and keep the strict policy unchanged.

Each candidate is judged with the harness's own functions, not a copy of them:
the adapter's read and validity (adapter_bag.read_snapshot_window), the
observer's sentinel gate and depth normalisation (observer: valid &= raw !=
nodata; vertical.to_depth(raw, block, valid=valid)), supplement.summarize and
policy.evaluate under the contained four-window profile. A window is fully
valid only when the policy has no hold (all 16,384 pairs mask-valid, raw
finite, 0 <= depth <= 91.44 m inclusive, 0 < productUncert <= 1 m).

Source access: the BAG is opened once per invocation. Its bytes are read once
into memory and hashed; the embedded metadata (h5py) and the raster (GDAL BAG
driver through a rasterio MemoryFile) are read from those same bytes, so every
array comes from the hashed bytes and the file is opened exactly once. The
dry run (--dry-run) never opens the BAG. Nothing is written except the receipt,
which is refused under a mission root or a scratch directory and is never
overwritten. The scan is evidence of mask/range validity only: native quality
stays unverified and nothing here admits, accepts or publishes a window.

--select-block RECEIPT reads the charged run's receipt (and its erratum), ranks
the fully valid 2x2 blocks by BLOCK_RULE and writes block-selection.json beside
it. It never opens the source: the window set moved as a whole block because
grant_identity admits only a contiguous 2x2 block and window D was also
mask-invalid (Fable ruling, RULING).
"""
import argparse
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import sys

SCHEMA = "coastal-four128-window-prescan-v1"
SOURCE_SHA256 = "0cb528795f939e9238e9b11f52279940a2365b2b4b6f52d9f9db8aea82b235fa"
SOURCE_BYTES = 36757568
METADATA_SHA256 = "a23f24509355c3eece8b785d3d69af9df4bd1dd4a9f49bd890d08088d88210ee"
SOURCE_NAME = "H11952_MB_2m_MLLW_2of4.bag"  # cache source.json url
SURVEY_ID = "H11952"
GRID_SHAPE = (10495, 10034)  # rows, cols
AFFINE = (2, 0, 721091, 0, -2, 3826155)
NATIVE_CRS = "EPSG:26910"
SIDE = 128
CELLS = SIDE * SIDE
# Fixed windows of the attempt-4 set; B is the failed window under replacement.
FIXED = {"A": (3890, 3488), "C": (3890, 3360), "D": (4018, 3360)}
FAILED_B = (4018, 3488)
CONTROL_B = dict(eligible=16366, mask_invalid=18)
ORIGIN = (3890, 3360)  # lattice origin (col, row)
STEPS = range(-3, 5)  # k, j in -3..4: 8 x 8 = 64 positions
SEGMENT_ID = "seg:3310:-50000:-395000:5000"
SEGMENT_BBOX = (-50000, -395000, -45000, -390000)
SEGMENT_MARGIN_M = 10
AMENDMENT_SHA256 = "448f16fcc136168f79676d393eb2e14ae25eb98cda79d32d13c7d2c0e434f693"
PRESCAN_CHARGED = 73515136  # two opens charged in amendment v3; this run uses one
OPEN_CHARGE = SOURCE_BYTES
DENSIFY = 64
EXECUTION_PROFILE = "coastal-contained-windows-v3"
RULE = ("Among candidates that are fully valid (policy.evaluate has no hold: all 16,384 pairs "
        "mask-valid, raw finite, 0 <= depth <= 91.44 m inclusive, 0 < productUncert <= 1 m), "
        "whose EPSG:3310 footprint lies inside segment " + SEGMENT_ID + " bbox "
        "[-50000,-395000,-45000,-390000] with >= 10 m margin, and that do not overlap A "
        "[3890,3488], C [3890,3360] or D [4018,3360]: pick the smallest Chebyshev lattice "
        "distance from [4018,3488]; ties -> lowest maximum uncertainty; then lowest (row, col).")

# Block selection (Fable ruling, t_c8b57dcc comment by fable-2nd-look 21:50 PDT).
# grant_identity admits the larger profile only as a contiguous 2x2 block in the
# order A=[c0,r1], B=[c1,r1], C=[c0,r0], D=[c1,r0], and window D [4018,3360] has
# 962 mask-invalid cells, so the whole block moves. --select-block reads the one
# charged run's receipt and never opens the source.
RECEIPT_SHA256 = "40dc9406998eae85fd438c512e73c13bd4b0fd789f5e32ba3cbd6b90985ed2f0"
ERRATUM_NAME = "prescan-receipt.erratum.json"
ERRATUM_SHA256 = "665e64756f80ef67720051dd03821fd63410057e6a9c10c0f36ef236cd3eec24"
BLOCK_SCHEMA = "coastal-four128-block-selection-v1"
BLOCK_SELECTION_NAME = "block-selection.json"
BLOCK_ORIGIN = (3890, 3360)  # origin (min col, min row) of the attempt-4 block
BLOCK_RULE = ("among 2x2 blocks whose four windows are all fully valid and segment-contained, take the "
              "smallest Chebyshev lattice distance of the block origin (min col, min row) from the original "
              "origin [3890,3360]; ties -> lowest max uncertainty over the four windows; ties -> lowest "
              "(row, col) of the origin.")
RULING = "t_c8b57dcc comment by fable-2nd-look 21:50 PDT"

OPENS = []  # every open of the source BAG made by this process


def lattice():
    """The 64 lattice positions as (col, row, k, j), row-major from the north-west."""
    return [(ORIGIN[0] + 128 * k, ORIGIN[1] + 128 * j, k, j) for j in STEPS for k in STEPS]


def chebyshev(k, j):
    """Lattice distance from the failed B position (k=1, j=1)."""
    return max(abs(k - 1), abs(j - 1))


def overlaps(a, b, side=SIDE):
    return a[0] < b[0] + side and b[0] < a[0] + side and a[1] < b[1] + side and b[1] < a[1] + side


def candidates():
    """Lattice minus A/C/D; the failed B stays in as the control."""
    fixed = set(FIXED.values())
    return [p for p in lattice() if (p[0], p[1]) not in fixed]


def native_bounds(col, row, side=SIDE):
    a, _, c0, _, e, f0 = AFFINE
    return [c0 + a * col, f0 + e * (row + side), c0 + a * (col + side), f0 + e * row]


def union_bounds(windows):
    """Integer native bounds [x0, y0, x1, y1] of the union of [col, row, w, h] windows."""
    a, _, c0, _, e, f0 = AFFINE
    return [c0 + a * min(w[0] for w in windows), f0 + e * max(w[1] + w[3] for w in windows),
            c0 + a * max(w[0] + w[2] for w in windows), f0 + e * min(w[1] for w in windows)]


def order_key(window):
    """grant_identity's deterministic southern-first west/east window order."""
    return (-window[1], window[0])


def fits_slot_b(col, row):
    """Can [col,row] replace B at index 1 without reordering A, C, D?"""
    windows = [FIXED["A"], (col, row), FIXED["C"], FIXED["D"]]
    return (windows == sorted(windows, key=order_key)
            and not any(overlaps(a, b) for i, a in enumerate(windows) for b in windows[i + 1:]))


def footprint(col, row, transformers):
    """EPSG:3310 corners and densified-edge bbox; CRS84 bbox for information."""
    x0, y0, x1, y1 = native_bounds(col, row)
    to3310, to84 = transformers
    corners = [[x0, y1], [x1, y1], [x1, y0], [x0, y0]]  # NW, NE, SE, SW
    pts = []
    for i in range(DENSIFY + 1):
        t = i / DENSIFY
        pts += [(x0 + t * (x1 - x0), y0), (x0 + t * (x1 - x0), y1),
                (x0, y0 + t * (y1 - y0)), (x1, y0 + t * (y1 - y0))]
    p3 = [to3310.transform(x, y) for x, y in pts]
    p84 = [to84.transform(x, y) for x, y in pts]
    b3 = [min(p[0] for p in p3), min(p[1] for p in p3), max(p[0] for p in p3), max(p[1] for p in p3)]
    b84 = [min(p[0] for p in p84), min(p[1] for p in p84), max(p[0] for p in p84), max(p[1] for p in p84)]
    m = SEGMENT_MARGIN_M
    sx0, sy0, sx1, sy1 = SEGMENT_BBOX
    inside = b3[0] >= sx0 + m and b3[1] >= sy0 + m and b3[2] <= sx1 - m and b3[3] <= sy1 - m
    return dict(native_bounds=[x0, y0, x1, y1],
                epsg3310_corners_nw_ne_se_sw=[list(to3310.transform(x, y)) for x, y in corners],
                epsg3310_bbox=b3, crs84_bbox=b84,
                epsg3310_margin_m=min(b3[0] - sx0, b3[1] - sy0, sx1 - b3[2], sy1 - b3[3]),
                segment_contained_10m=inside)


def transformers():
    from pyproj import Transformer
    return (Transformer.from_crs(NATIVE_CRS, "EPSG:3310", always_xy=True),
            Transformer.from_crs(NATIVE_CRS, "OGC:CRS84", always_xy=True))


def evaluate_window(elevation, uncertainty, nodatavals, block, header, label):
    """Harness verdict for one window from the two masked band reads.

    Mirrors adapter_bag.read_snapshot_window (validity), observer (sentinel gate
    and to_depth with valid=), then calls supplement.summarize and policy.evaluate."""
    import numpy as np
    from skippercast.coastal import vertical
    from skippercast.coastal.authenticated_v1.adapter_bag import (
        MINIMUM_DEPTH_FT, MAXIMUM_DEPTH_FT, METERS_PER_FOOT, MAX_PRODUCT_UNCERTAINTY_M)
    from skippercast.coastal.authenticated_v1.supplement import summarize
    from skippercast.coastal.authenticated_v1.policy import evaluate
    elevation = elevation.astype("float32")
    uncertainty = uncertainty.astype("float32")
    elevation_values = elevation.filled(np.nan)
    uncertainty_values = uncertainty.filled(np.nan)
    valid = (~np.ma.getmaskarray(elevation) & ~np.ma.getmaskarray(uncertainty)
             & np.isfinite(elevation_values) & np.isfinite(uncertainty_values))
    adapter_depth = vertical.to_depth(elevation, block, nodata=1e6).astype("float32")
    legacy = (valid & (adapter_depth >= MINIMUM_DEPTH_FT * METERS_PER_FOOT)
              & (adapter_depth <= MAXIMUM_DEPTH_FT * METERS_PER_FOOT)
              & (uncertainty_values > 0) & (uncertainty_values <= MAX_PRODUCT_UNCERTAINTY_M))
    # observer: an internal mask cannot make an explicit sentinel into a sounding.
    raw = elevation_values
    if nodatavals[0] is not None and np.isfinite(nodatavals[0]):
        valid &= raw != nodatavals[0]
    if nodatavals[1] is not None and np.isfinite(nodatavals[1]):
        valid &= uncertainty_values != nodatavals[1]
    depth = vertical.to_depth(raw, block, valid=valid)
    arrays = dict(raw_elevation_data=np.asarray(elevation.data).copy(),
                  raw_uncertainty_data=np.asarray(uncertainty.data).copy(),
                  elevation_mask=np.ma.getmaskarray(elevation).copy(),
                  uncertainty_mask=np.ma.getmaskarray(uncertainty).copy(),
                  source_pair_valid=valid.copy(), depth=depth.copy(),
                  legacy_25_300ft_uncertainty_0_1m=legacy.copy())
    diagnostics = summarize(arrays, "prescan:" + label)
    verdict = evaluate(diagnostics, dict(header=header), execution_profile=EXECUTION_PROFILE,
                       configuration=dict(window_side=SIDE, window_count=4))
    counts, unc = diagnostics["counts"], diagnostics["uncertainty"]
    finite = valid & np.isfinite(depth)
    return dict(
        eligible=counts["eligible"], mask_invalid=counts["mask_invalid"],
        elevation_mask_invalid=counts["elevation_mask_invalid"],
        uncertainty_mask_invalid=counts["uncertainty_mask_invalid"],
        mask_valid_raw_nonfinite=counts["mask_valid_raw_nonfinite"],
        mask_valid_raw_finite_source_invalid=counts["mask_valid_raw_finite_source_invalid"],
        normalized_nonfinite=counts["normalized_nonfinite"],
        depth_finite_out_of_range=counts["valid_but_out_of_range"],
        depth_finite_below_0=counts["finite_below_0"], depth_finite_above_91_44=counts["finite_above_91_44"],
        uncertainty_out_of_range=unc["nonpositive"] + unc["above_1m"],
        uncertainty_nonpositive=unc["nonpositive"], uncertainty_above_1m=unc["above_1m"],
        depth_min_m=float(depth[finite].min()) if finite.any() else None,
        depth_max_m=float(depth[finite].max()) if finite.any() else None,
        uncertainty_min_m=unc["minimum"], uncertainty_max_m=unc["maximum"],
        policy_holds=verdict["holds"], fully_valid=verdict["paired_eligibility_quality_pass"] is True,
        counts=counts, array_hashes=diagnostics["array_hashes"])


def scan(dataset, block, header, positions, footprints):
    """One record per (col, row, k, j) position, all read through one open dataset."""
    from rasterio.windows import Window
    records = []
    for col, row, k, j in positions:
        window = Window(col, row, SIDE, SIDE)
        elevation = dataset.read(1, window=window, masked=True)
        uncertainty = dataset.read(2, window=window, masked=True)
        verdict = evaluate_window(elevation, uncertainty, tuple(dataset.nodatavals), block, header,
                                  f"{col}:{row}")
        records.append(dict(window=[col, row, SIDE, SIDE], lattice_k=k, lattice_j=j,
                            chebyshev_from_b=chebyshev(k, j),
                            overlaps_a_c_d=any(overlaps((col, row), w) for w in FIXED.values()),
                            fits_slot_b_order=fits_slot_b(col, row),
                            **footprints[(col, row)], **verdict))
    return records


def select(records):
    """The fixed selection rule (RULE); None when no candidate qualifies."""
    eligible = [r for r in records if r["fully_valid"] and r["segment_contained_10m"]
                and not r["overlaps_a_c_d"]]
    if not eligible:
        return None
    return min(eligible, key=lambda r: (r["chebyshev_from_b"], r["uncertainty_max_m"],
                                        r["window"][1], r["window"][0]))


def block_windows(col, row, side=SIDE):
    """A, B, C, D of the 2x2 block with origin (min col, min row): southern row first."""
    return [[col, row + side, side, side], [col + side, row + side, side, side],
            [col, row, side, side], [col + side, row, side, side]]


def ranked_blocks(records, origin=BLOCK_ORIGIN, side=SIDE):
    """Every 2x2 block of fully valid, segment-contained windows, ranked by BLOCK_RULE.

    records carry window, fully_valid, segment_contained_10m and uncertainty_max_m
    (the receipt's candidates plus its reference windows)."""
    by_window = {}
    for r in records:
        key = tuple(r["window"][:2])
        if key in by_window:
            raise ValueError(f"duplicate window {list(key)} in the candidate table")
        by_window[key] = r

    def usable(key):
        r = by_window.get(key)
        return r is not None and r["fully_valid"] is True and r["segment_contained_10m"] is True

    blocks = []
    for col, row in sorted(by_window):
        windows = block_windows(col, row, side)
        if not all(usable((w[0], w[1])) for w in windows):
            continue
        dx, dy = col - origin[0], row - origin[1]
        if dx % side or dy % side:
            raise ValueError("candidate window is off the lattice")
        blocks.append(dict(origin=[col, row], chebyshev_from_origin=max(abs(dx), abs(dy)) // side,
                           max_uncertainty_m=max(by_window[(w[0], w[1])]["uncertainty_max_m"] for w in windows),
                           windows=windows, native_bounds=union_bounds(windows)))
    blocks.sort(key=lambda b: (b["chebyshev_from_origin"], b["max_uncertainty_m"], b["origin"][1], b["origin"][0]))
    for rank, block in enumerate(blocks, 1):
        block["rank"] = rank
    return blocks


def select_block(records, origin=BLOCK_ORIGIN, side=SIDE):
    """The block BLOCK_RULE picks; None when no 2x2 block qualifies."""
    blocks = ranked_blocks(records, origin, side)
    return blocks[0] if blocks else None


def control_check(record, control_doc):
    """Window B must reproduce attempt 4's harness diagnostics exactly."""
    problems = []
    for key, value in CONTROL_B.items():
        if record[key] != value:
            problems.append(f"{key} {record[key]} != expected {value}")
    if control_doc is not None:
        if record["counts"] != control_doc["counts"]:
            problems.append("counts differ from the attempt-4 diagnostics")
        if record["array_hashes"] != control_doc["array_hashes"]:
            problems.append("array hashes differ from the attempt-4 diagnostics")
        expected = control_doc["uncertainty"]
        if (record["uncertainty_min_m"], record["uncertainty_max_m"]) != (expected["minimum"], expected["maximum"]):
            problems.append("uncertainty range differs from the attempt-4 diagnostics")
    return problems


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_source(path):
    """The single open of the source BAG: read all bytes once and hash them."""
    path, sha256, size = Path(path), SOURCE_SHA256, SOURCE_BYTES
    OPENS.append(str(path))
    if len(OPENS) != 1:
        raise RuntimeError("the source BAG may be opened once per invocation")
    with open(path, "rb") as handle:
        data = handle.read(size + 1)
    if len(data) != size or hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError("source BAG bytes differ from the pinned sha256/size")
    return data


def embedded_metadata(data):
    """BAG_root/metadata read with h5py from the hashed bytes, as the adapter reads it."""
    import h5py
    expected = METADATA_SHA256
    with h5py.File(io.BytesIO(data), "r") as original:
        if "BAG_root" not in original:
            raise ValueError("source is not a regular BAG HDF5 product")
        root = original["BAG_root"]
        if "varres_refinements" in root and root["varres_refinements"].size > 0:
            raise ValueError("variable-resolution BAG is not accepted")
        if not {"elevation", "uncertainty", "metadata"} <= set(root.keys()):
            raise ValueError("BAG must contain elevation, uncertainty and metadata")
        if root["elevation"].shape != root["uncertainty"].shape:
            raise ValueError("BAG depth and uncertainty grids do not align")
        if root["metadata"].size > 1_000_000:
            raise ValueError("oversized BAG metadata")
        xml = root["metadata"][:].tobytes().decode("utf-8").rstrip("\0")
    digest = hashlib.sha256(xml.encode()).hexdigest()
    if digest != expected:
        raise ValueError("embedded BAG metadata hash differs from the pinned value")
    return xml, digest


def vertical_block(dataset, xml, survey_id, source_sha256):
    """The adapter's vertical route: from_raster + require_resolved(None, ...)."""
    from skippercast.coastal import vertical
    from skippercast.platform.bottom_targets import bag_metadata
    metadata = bag_metadata(xml, survey_id, strict=True)
    if metadata["vertical_datum"] != "MLLW" or metadata["uncertainty_type"] != "productUncert":
        raise ValueError("BAG must declare MLLW and productUncert")
    # metadata_bag.inspect_metadata's audited BAG FSD 2.0 elevation convention.
    metadata["elevation_convention"] = {
        "sign": "positive_up", "units": "m", "array": "BAG_root/elevation",
        "reference_crs_role": "vertical_reference_coordinate",
        "specification": "BAG FSD 2.0 / Release 2.0.1 (2022-12-01)",
        "ref": "https://bag.readthedocs.io/en/master/fsd/FSD-AxiomaticDefs.html"}
    observed = vertical.from_raster(dataset, source_sha256=source_sha256, bag_metadata=metadata)
    return vertical.require_resolved(None, observed, [vertical.evidence_from_observation(observed)])


def check_grid(dataset):
    from pyproj import CRS
    shape, affine, epsg = GRID_SHAPE, AFFINE, int(NATIVE_CRS.split(":")[1])
    if dataset.driver != "BAG" or dataset.count != 2:
        raise ValueError("expected a two-band regular BAG")
    if (dataset.height, dataset.width) != tuple(shape) or [float(v) for v in list(dataset.transform)[:6]] != [float(v) for v in affine]:
        raise ValueError("BAG grid shape/affine differs from the four128 grid")
    crs = CRS.from_user_input(dataset.crs)
    parts = crs.sub_crs_list if crs.is_compound else [crs]
    horizontal = [p for p in parts if p.is_projected or p.is_bound]
    if len(horizontal) != 1:
        raise ValueError("one horizontal CRS required")
    h = horizontal[0].source_crs if horizontal[0].is_bound else horizontal[0]
    if h.to_epsg() != epsg:
        raise ValueError("horizontal CRS differs from EPSG:26910")


def library_versions():
    import h5py
    import numpy
    import pyproj
    import rasterio
    return dict(python=sys.version.split()[0], numpy=numpy.__version__, h5py=h5py.__version__,
                hdf5=h5py.version.hdf5_version, rasterio=rasterio.__version__,
                gdal=rasterio.__gdal_version__, pyproj=pyproj.__version__, proj=pyproj.proj_version_str,
                proj_network=bool(pyproj.network.is_network_enabled()))


def harness_hashes():
    import skippercast.coastal.authenticated_v1.adapter_bag as adapter
    import skippercast.coastal.authenticated_v1.observer as observer
    import skippercast.coastal.authenticated_v1.policy as policy
    import skippercast.coastal.authenticated_v1.supplement as supplement
    import skippercast.coastal.vertical as vertical
    return {m.__name__: sha256_file(m.__file__) for m in (adapter, observer, supplement, policy, vertical)}


def check_receipt_path(path):
    path = Path(path).absolute()
    if any(part == "scratch" or part.startswith("mission") for part in path.parts):
        raise ValueError("the receipt may not be written under a mission root or scratch")
    if path.exists():
        raise ValueError("refusing to overwrite an existing receipt")
    return path


def check_amendment(path):
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != AMENDMENT_SHA256:
        raise ValueError("budget amendment v3 sha256 differs from the pinned value")
    doc = json.loads(data)
    if doc["source"]["window_prescan_charged_bytes"] != PRESCAN_CHARGED or doc.get("amendment_revision") != 3:
        raise ValueError("amendment v3 does not charge the two pre-scan opens")
    return dict(path=str(path), sha256=AMENDMENT_SHA256, amendment_revision=3,
                window_prescan_charged_bytes=PRESCAN_CHARGED, opens_charged=2,
                this_run_open_bytes=OPEN_CHARGE)


def write_receipt(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(document, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
    return hashlib.sha256(data).hexdigest()


def plan(args):
    """Everything that needs no source access: lattice, footprints, paths."""
    receipt = check_receipt_path(args.receipt)
    amendment = check_amendment(args.amendment)
    if args.segment:
        segment = json.loads(Path(args.segment).read_text())
        if segment.get("segment_id") != SEGMENT_ID or segment.get("bbox") != list(SEGMENT_BBOX) \
                or segment.get("crs") != "EPSG:3310":
            raise ValueError("segment document differs from the pinned segment")
    region = json.loads(Path(args.region).read_text()) if args.region else None
    controls = {}
    for item in args.control:
        label, _, path = item.partition("=")
        if label not in ("A", "B") or not path:
            raise ValueError("--control takes A=PATH or B=PATH")
        data = Path(path).read_bytes()
        controls[label] = dict(path=path, sha256=hashlib.sha256(data).hexdigest(), doc=json.loads(data))
    t = transformers()
    positions = candidates()
    reference = [(c, r, (c - ORIGIN[0]) // 128, (r - ORIGIN[1]) // 128) for c, r in FIXED.values()]
    footprints = {(c, r): footprint(c, r, t) for c, r, _, _ in positions + reference}
    if region is not None:
        for fp in footprints.values():
            b = fp["crs84_bbox"]
            fp["product_region_contained"] = all(region["bounds"][i] <= b[i] for i in (0, 1)) and all(b[i] <= region["bounds"][i] for i in (2, 3))
            fp["product_fishing_bounds_contained"] = all(region["fishing_bounds"][i] <= b[i] for i in (0, 1)) and all(b[i] <= region["fishing_bounds"][i] for i in (2, 3))
    return dict(receipt=receipt, amendment=amendment, region=region, controls=controls,
                positions=positions, reference=reference, footprints=footprints)


def run(args, prepared):
    from rasterio import Env
    from rasterio.io import MemoryFile
    data = read_source(args.source)
    xml, metadata_sha = embedded_metadata(data)
    with Env(GDAL_PAM_ENABLED="NO", GDAL_NUM_THREADS="1"), MemoryFile(data) as memory:
        with memory.open(driver="BAG") as dataset:
            check_grid(dataset)
            block = vertical_block(dataset, xml, SURVEY_ID, SOURCE_SHA256)
            header = dict(driver=dataset.driver, scales=list(dataset.scales), offsets=list(dataset.offsets),
                          units=list(dataset.units), nodata=list(dataset.nodatavals),
                          shape=[dataset.height, dataset.width], transform=list(dataset.transform)[:6])
            records = scan(dataset, block, header, prepared["positions"], prepared["footprints"])
            reference = scan(dataset, block, header, prepared["reference"], prepared["footprints"])
    return metadata_sha, block, header, records, reference


def grant_admits(windows):
    """grant_identity admits the window set, in this order, under both four128 profiles."""
    from skippercast.coastal.authenticated_v1.profiles import CONTAINED, LARGER, grant_identity
    base = dict(schema="block-selection-check", source={}, source_root="-", source_relative_path="-",
                window_set=[list(w) for w in windows])
    grants = (dict(base, execution_profile=LARGER),
              dict(base, execution_profile=CONTAINED, window_side=SIDE, window_count=len(windows)))
    return all(grant_identity(g)["window_set"] == windows for g in grants)


def select_block_document(receipt_path, code_head=None):
    """The block-selection document from the verified pre-scan receipt; never opens the source."""
    receipt_path = Path(receipt_path)
    receipt_data = receipt_path.read_bytes()
    if hashlib.sha256(receipt_data).hexdigest() != RECEIPT_SHA256:
        raise ValueError("pre-scan receipt sha256 differs from the pinned charged-run receipt")
    erratum_path = receipt_path.parent / ERRATUM_NAME
    erratum_data = erratum_path.read_bytes()
    if hashlib.sha256(erratum_data).hexdigest() != ERRATUM_SHA256:
        raise ValueError("pre-scan erratum sha256 differs from the pinned erratum")
    receipt, erratum = json.loads(receipt_data), json.loads(erratum_data)
    if (receipt.get("schema") != SCHEMA or receipt["source"]["opens"] != 1
            or receipt["controls"]["B"]["match"] is not True
            or erratum["receipt"]["sha256"] != RECEIPT_SHA256 or erratum["candidate_table_affected"] is not False):
        raise ValueError("receipt is not a matched one-open pre-scan, or the erratum touches the table")
    records = receipt["candidates"] + receipt["reference_fixed_windows"]
    blocks = ranked_blocks(records)
    if not blocks:
        raise ValueError("no fully valid segment-contained 2x2 block in the candidate table")
    chosen = blocks[0]
    by_window = {tuple(r["window"][:2]): r for r in records}
    per_window = [dict(label=label, window=w, **{k: by_window[(w[0], w[1])].get(k) for k in (
        "fully_valid", "eligible", "mask_invalid", "uncertainty_min_m", "uncertainty_max_m",
        "segment_contained_10m", "epsg3310_margin_m", "native_bounds", "product_region_contained",
        "product_fishing_bounds_contained")}) for label, w in zip("ABCD", chosen["windows"])]
    from skippercast.coastal.coordinator import ordered_trial
    return dict(
        schema=BLOCK_SCHEMA, created_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        task="t_c8b57dcc (T08-FIX3)", ruling=RULING, authority="G decision 2026-10-19 21:10 PDT, option A",
        script=dict(path="research/scripts/coastal_four128_window_scan.py", sha256=sha256_file(__file__)),
        code_head=code_head,
        receipt=dict(path=str(receipt_path), sha256=RECEIPT_SHA256, status=receipt["status"],
                     opens=receipt["source"]["opens"], control_b_match=True),
        erratum=dict(path=str(erratum_path), sha256=ERRATUM_SHA256),
        source_opened=False, source_bytes_read=0, network_requests=0,
        rule=BLOCK_RULE, block_origin_reference=list(BLOCK_ORIGIN),
        ranked_blocks=[dict(rank=b["rank"], origin=b["origin"], chebyshev_from_origin=b["chebyshev_from_origin"],
                            max_uncertainty_m=b["max_uncertainty_m"]) for b in blocks],
        chosen=dict(origin=chosen["origin"], chebyshev_from_origin=chosen["chebyshev_from_origin"],
                    max_uncertainty_m=chosen["max_uncertainty_m"], windows=per_window),
        LARGER_WINDOWS=chosen["windows"], LARGER_BOUNDS=chosen["native_bounds"],
        grant_identity_admits=grant_admits(chosen["windows"]),
        ordered_trial_matches=(ordered_trial.LARGER_WINDOWS == chosen["windows"]
                               and ordered_trial.LARGER_BOUNDS == chosen["native_bounds"]),
        evidence_scope="Selection over the pre-scan's mask/range verdicts only; native quality UNVERIFIED, "
                       "accepted_pairs 0, publication false, no admission.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", help="cached source.bag (read-only)")
    parser.add_argument("--receipt", help="new receipt path (never overwritten)")
    parser.add_argument("--amendment", help="signed budget amendment v3")
    parser.add_argument("--control", action="append", default=[], help="A=PATH or B=PATH attempt-4 diagnostics.json")
    parser.add_argument("--segment", help="independent four128 segment document (cross-check)")
    parser.add_argument("--region", help="product region.json (informational containment)")
    parser.add_argument("--code-head", help="git head of the code root (recorded)")
    parser.add_argument("--dry-run", action="store_true", help="plan only; never opens the BAG")
    parser.add_argument("--select-block", metavar="RECEIPT",
                        help="rank 2x2 blocks from an existing receipt and write block-selection.json beside it; "
                             "never opens the source")
    args = parser.parse_args(argv)
    if args.select_block:
        if args.source or args.receipt or args.dry_run or args.control:
            parser.error("--select-block takes only the receipt (and --code-head)")
        out = check_receipt_path(Path(args.select_block).parent / BLOCK_SELECTION_NAME)
        document = select_block_document(args.select_block, args.code_head)
        sha = write_receipt(out, document)
        print(json.dumps(dict(block_selection=str(out), sha256=sha, source_opened=bool(OPENS),
                              chosen_origin=document["chosen"]["origin"], LARGER_WINDOWS=document["LARGER_WINDOWS"],
                              LARGER_BOUNDS=document["LARGER_BOUNDS"],
                              grant_identity_admits=document["grant_identity_admits"],
                              ordered_trial_matches=document["ordered_trial_matches"]), indent=2))
        return 0 if not OPENS and document["grant_identity_admits"] and document["ordered_trial_matches"] else 2
    if not (args.source and args.receipt and args.amendment):
        parser.error("--source, --receipt and --amendment are required")
    prepared = plan(args)
    if args.dry_run:
        print(json.dumps(dict(dry_run=True, source_opened=False, source_present=Path(args.source).is_file(),
                              receipt=str(prepared["receipt"]), amendment=prepared["amendment"],
                              controls={k: v["path"] for k, v in prepared["controls"].items()},
                              candidates=len(prepared["positions"]),
                              segment_contained=sum(prepared["footprints"][(c, r)]["segment_contained_10m"]
                                                    for c, r, _, _ in prepared["positions"])), indent=2))
        return 0 if not OPENS else 1
    if "B" not in prepared["controls"]:
        raise ValueError("the charged run needs --control B=<attempt-4 B diagnostics.json>")
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    metadata_sha, block, header, records, reference = run(args, prepared)
    try:
        return finish(args, prepared, started, metadata_sha, block, header, records, reference)
    except Exception:
        # The one charged open must never be lost: keep the raw scan beside the receipt path.
        salvage = Path(str(prepared["receipt"]) + ".salvage.json")
        fd = os.open(salvage, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, "w") as handle:
            json.dump(dict(started=started, metadata_sha256=metadata_sha, opens=len(OPENS), block=block,
                           header=header, records=records, reference=reference), handle, default=str)
        raise


def finish(args, prepared, started, metadata_sha, block, header, records, reference):
    by_window = {tuple(r["window"][:2]): r for r in records}
    ref_by_window = {tuple(r["window"][:2]): r for r in reference}
    problems = control_check(by_window[FAILED_B], prepared["controls"]["B"]["doc"])
    controls = dict(B=dict(window=list(FAILED_B) + [SIDE, SIDE], expected=CONTROL_B,
                           diagnostics=dict(path=prepared["controls"]["B"]["path"], sha256=prepared["controls"]["B"]["sha256"]),
                           problems=problems, match=not problems))
    if "A" in prepared["controls"]:
        a = ref_by_window[FIXED["A"]]
        doc = prepared["controls"]["A"]["doc"]
        a_problems = [k for k in ("counts", "array_hashes") if a[k] != doc[k]]
        controls["A"] = dict(window=list(FIXED["A"]) + [SIDE, SIDE],
                             diagnostics=dict(path=prepared["controls"]["A"]["path"], sha256=prepared["controls"]["A"]["sha256"]),
                             problems=a_problems, match=not a_problems)
    chosen = None if problems else select(records)
    status = ("CONTROL_MISMATCH" if problems else "NO_QUALIFYING_CANDIDATE" if chosen is None
              else "CHOSEN" if chosen["fits_slot_b_order"] else "CHOSEN_BREAKS_WINDOW_ORDER")
    for r in records + reference:  # array hashes are kept only for the two control windows
        if tuple(r["window"][:2]) not in (FAILED_B, FIXED["A"]):
            del r["array_hashes"]
    document = dict(
        schema=SCHEMA, status=status, created_utc=started,
        finished_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        task="t_c8b57dcc (T08-FIX3)", authority="G decision 2026-10-19 21:10 PDT, option A",
        script=dict(path="research/scripts/coastal_four128_window_scan.py", sha256=sha256_file(__file__)),
        code_head=args.code_head, harness_sha256=harness_hashes(), libraries=library_versions(),
        source=dict(path=str(Path(args.source)), sha256=SOURCE_SHA256, bytes=SOURCE_BYTES, name=SOURCE_NAME,
                    metadata_sha256=metadata_sha, opens=len(OPENS),
                    access="one read of the file into memory; sha256 over those bytes; h5py metadata and "
                           "GDAL BAG raster read from the same bytes (rasterio MemoryFile)"),
        budget=dict(prepared["amendment"], bytes_charged_this_run=OPEN_CHARGE, opens_this_run=len(OPENS),
                    remaining_charged_opens=1, remaining_open_owner="sol-reviewer verification"),
        network_requests=0, downloads=0, writes=["this receipt only"],
        grid=dict(shape=list(GRID_SHAPE), affine=list(AFFINE), native_crs=NATIVE_CRS, header=header),
        vertical_block=block,
        segment=dict(segment_id=SEGMENT_ID, bbox=list(SEGMENT_BBOX), crs="EPSG:3310", margin_m=SEGMENT_MARGIN_M),
        product_region=None if prepared["region"] is None else dict(id=prepared["region"]["id"], bounds=prepared["region"]["bounds"],
                                                                    fishing_bounds=prepared["region"]["fishing_bounds"], informational=True),
        criteria=dict(execution_profile=EXECUTION_PROFILE, window_side=SIDE, pairs=CELLS,
                      depth_m=[0, 91.44], depth_inclusive=True, uncertainty_m="(0, 1]",
                      functions=["adapter_bag.read_snapshot_window validity (lines 211-221)",
                                 "observer sentinel gate + vertical.to_depth(raw, block, valid=valid)",
                                 "supplement.summarize", "policy.evaluate"]),
        lattice=dict(origin=list(ORIGIN), step=128, k=list(STEPS), j=list(STEPS), positions=64,
                     excluded=dict(A=list(FIXED["A"]), C=list(FIXED["C"]), D=list(FIXED["D"])),
                     control=list(FAILED_B), candidates=len(records)),
        controls=controls, rule=RULE, chosen=None if chosen is None else dict(
            window=chosen["window"], chebyshev_from_b=chosen["chebyshev_from_b"],
            uncertainty_max_m=chosen["uncertainty_max_m"], fits_slot_b_order=chosen["fits_slot_b_order"],
            native_bounds=chosen["native_bounds"]),
        reference_fixed_windows=reference, candidates=records,
        evidence_scope="Mask/range validity of the cached BAG cells under the strict fixed-patch policy only; "
                       "native quality UNVERIFIED, accepted_pairs 0, publication false, no admission.")
    sha = write_receipt(prepared["receipt"], document)
    print(json.dumps(dict(status=status, receipt=str(prepared["receipt"]), receipt_sha256=sha,
                          opens=len(OPENS), controls={k: v["match"] for k, v in controls.items()},
                          chosen=document["chosen"]), indent=2))
    return 0 if status == "CHOSEN" else 2


if __name__ == "__main__":
    sys.exit(main())
