"""Build the reviewed native-footprint coarse planning grid, without filling gaps.

Run with ``region.py coarse --region ID --out OUT --family ID --cell-m N``.
The bound ``OUT/ID/census.json`` supplies the region bbox and local tile pins.
"""

import hashlib
import json
import math
import re
from pathlib import Path
from xml.etree import ElementTree as ET

import numpy as np
import rasterio as rio
import shapely
from pyproj import CRS, Transformer
from rasterio.enums import MaskFlags, Resampling
from rasterio.io import MemoryFile
from rasterio.warp import reproject
from rasterio.windows import from_bounds
from scipy import ndimage
from shapely.geometry import box

from . import receipts, select

CODE_FILES = ('skippercast.relief.select',)

_CRS = "EPSG:3310"
_FINE_M = 2  # Common refinement of the reviewed, even-metre UTM pixel edges.
_ENV = dict(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR", GDAL_PAM_ENABLED="NO", GDAL_NUM_THREADS="1")


def _signature(path):
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _native_mosaic(tiles):
    # Verify every pin before GDAL opens any tile (including lazy VRT reads).
    pins = {}
    for path, expected_sha256, vertical in tiles:
        path = Path(path).resolve(strict=True)
        if vertical != "NAVD88-up":
            raise ValueError(f"Expected NAVD88-up for {path.name}")
        sig = _signature(path)
        with path.open("rb") as file:
            digest = hashlib.file_digest(file, "sha256").hexdigest()
        if digest != expected_sha256:
            raise ValueError(f"SHA-256 mismatch for {path.name}")
        pins[path] = sig

    layers = []
    native_crs = None
    for path in pins:
        with rio.open(path, driver="GTiff") as src:
            crs = CRS.from_user_input(src.crs) if src.crs else None
            if crs and crs.is_compound:
                crs, vertical = crs.sub_crs_list
                if vertical.to_epsg() != 5703:
                    raise ValueError(f"Expected NAVD88-up for {path.name}")
            if not crs or not crs.utm_zone or (native_crs is not None and crs != native_crs):
                raise ValueError("Planning tiles must share one horizontal UTM CRS")
            native_crs = crs
            t = src.transform
            if (t.a <= 0 or (t.b, t.d, t.e) != (0, 0, -t.a)
                    or any(v % _FINE_M for v in (t.a, t.c, t.f))
                    or src.dtypes[0] != "float32" or src.units[0] not in (None, "m", "metre")
                    or src.scales[0] != 1 or src.offsets[0] != 0
                    or any(flag not in (MaskFlags.nodata, MaskFlags.all_valid) for flag in src.mask_flag_enums[0])):
                raise ValueError(f"Unsupported native elevation grid: {path.name}")
            stamp = re.search(r"_(\d{8})$", path.stem)
            layers.append((-t.a, stamp[1] if stamp else "", str(path), src.bounds, src.shape, src.nodatavals[0]))

    west = min(bounds.left for _, _, _, bounds, _, _ in layers)
    north = max(bounds.top for _, _, _, bounds, _, _ in layers)
    east = max(bounds.right for _, _, _, bounds, _, _ in layers)
    south = min(bounds.bottom for _, _, _, bounds, _, _ in layers)
    vrt = ET.Element("VRTDataset", rasterXSize=str(int((east - west) / _FINE_M)),
                     rasterYSize=str(int((north - south) / _FINE_M)))
    assert native_crs is not None  # Every nonempty tile list supplies a validated CRS.
    ET.SubElement(vrt, "SRS").text = native_crs.to_wkt()
    ET.SubElement(vrt, "GeoTransform").text = f"{west},{_FINE_M},0,{north},0,{-_FINE_M}"
    dest = ET.SubElement(vrt, "VRTRasterBand", dataType="Float32", band="1")
    ET.SubElement(dest, "NoDataValue").text = "nan"
    # Later valid pixels win: finest spacing, newest filename date, then path.
    # Replicate each native pixel exactly within its footprint; never average overlaps.
    for spacing, _, path, b, (height, width), nodata in sorted(layers):
        scale = int(-spacing / _FINE_M)
        source = ET.SubElement(dest, "ComplexSource", resampling="nearest")
        ET.SubElement(source, "SourceFilename", relativeToVRT="0").text = path
        ET.SubElement(source, "SourceBand").text = "1"
        ET.SubElement(source, "SrcRect", xOff="0", yOff="0", xSize=str(width), ySize=str(height))
        ET.SubElement(source, "DstRect", xOff=str(int((b.left - west) / _FINE_M)),
                      yOff=str(int((north - b.top) / _FINE_M)), xSize=str(width * scale), ySize=str(height * scale))
        ET.SubElement(source, "NODATA").text = str(nodata) if nodata is not None else "nan"
    return ET.tostring(vrt), pins


def _hole_report(array, transform):
    """Classify missing components in the unbuffered region-bounds window."""
    if np.isinf(array).any():
        raise ValueError("Non-finite valid elevation")
    invalid = np.isnan(array)
    band = (array >= -91.44) & (array <= 0) & ~invalid
    cross = ndimage.generate_binary_structure(2, 1)
    touching = invalid & ndimage.binary_dilation(band, structure=cross)
    labels, count = ndimage.label(invalid, structure=cross)
    edge = set(np.unique(np.concatenate((labels[0], labels[-1], labels[:, 0], labels[:, -1])))) - {0}
    near = set(np.unique(labels[touching]))
    to_wgs = Transformer.from_crs(_CRS, "EPSG:4326", always_xy=True)

    def coord(row, col):
        lon, lat = to_wgs.transform(*(transform @ (int(col) + 0.5, int(row) + 0.5)))
        return [round(lon, 7), round(lat, 7)]

    strict, mixed = [], []
    for label, (rows, cols) in enumerate(ndimage.find_objects(labels, max_label=count), 1):
        if label not in near or label in edge:
            continue
        rr, cc = slice(rows.start - 1, rows.stop + 1), slice(cols.start - 1, cols.stop + 1)
        hole = labels[rr, cc] == label
        rim = ndimage.binary_dilation(hole, structure=cross) & ~hole
        in_band = int(np.count_nonzero(rim & band[rr, cc]))
        rim_cells = int(np.count_nonzero(rim))
        row, col = divmod(int(hole.argmax()), hole.shape[1])
        (strict if in_band == rim_cells else mixed).append(dict(
            cells=int(hole.sum()), sample_lonlat=coord(rr.start + row, cc.start + col),
            window_bbox_colrow=[cols.start, rows.start, cols.stop, rows.stop],
            rim_cells=rim_cells, rim_in_band_cells=in_band,
        ))
    edge_touch = touching & np.isin(labels, sorted(edge & near))
    rows, cols = np.nonzero(edge_touch)

    def order(hole):
        return -hole["cells"], hole["window_bbox_colrow"]

    return dict(
        method="Four-connected nodata components in the region-bounds window. A strict in-band hole has "
               "every valid cardinal rim cell in [-91.44, 0] m. Nodata itself has no depth. Mixed rims and "
               "edge-connected gaps are not verified shallow holes. No water mask or fill applied.",
        enclosed_total=count - len(edge), strict=sorted(strict, key=order), mixed_rim=sorted(mixed, key=order),
        edge_connected_components_touching_band=len(edge & near), edge_connected_cells_adjacent_to_band=len(rows),
        edge_connected_adjacent_first_last_lonlat=[coord(rows[0], cols[0]), coord(rows[-1], cols[-1])] if len(rows) else [],
    )


def build_coarse(tiles, bounds, *, cell_m):
    """Return (elevation, affine, hole report) for WGS84 (west, south, east, north).

    Tiles are local (path, SHA-256, 'NAVD88-up') triples on a common UTM
    projection. Mosaic band 1 on the exact 2 m refinement, then apply the
    reviewed single horizontal bilinear warp, with no additional smoothing.
    """
    west, south, east, north = bounds
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("Expected ordered WGS84 bounds")
    if not math.isfinite(cell_m) or cell_m <= 0:
        raise ValueError("Expected a positive finite cell size")
    if not tiles:
        raise ValueError("Expected at least one planning tile")
    to_grid = Transformer.from_crs("EPSG:4326", _CRS, always_xy=True)
    region = shapely.transform(box(*bounds).segmentize(0.02), to_grid.transform, interleaved=False)
    west, south, east, north = region.buffer(1000).bounds
    left, bottom = math.floor(west / cell_m), math.floor(south / cell_m)
    right, top = math.ceil(east / cell_m), math.ceil(north / cell_m)
    transform = rio.Affine(cell_m, 0, left * cell_m, 0, -cell_m, top * cell_m)
    array = np.full((top - bottom, right - left), np.nan, dtype="float32")
    with rio.Env(**_ENV):
        vrt, pins = _native_mosaic(tiles)
        with MemoryFile(vrt, ext=".vrt") as memory, memory.open() as source:
            reproject(rio.band(source, 1), array, dst_transform=transform, dst_crs=_CRS,
                      src_nodata=np.nan, dst_nodata=np.nan, resampling=Resampling.bilinear,
                      num_threads=1, warp_mem_limit=128)
        for path, signature in pins.items():
            if _signature(path) != signature:
                raise ValueError(f"Input changed during build: {path.name}")
    # Same outward-to-whole-cells window as the loader. Since the raster
    # contains the halo, this unbuffered window needs no extent clipping.
    window = from_bounds(*region.bounds, transform=transform)
    rows, cols = window.toslices()
    report = _hole_report(array[rows, cols], transform @ rio.Affine.translation(cols.start, rows.start))
    return array, transform, report


def write_coarse(path, array, transform):
    """Write the planning grid with fixed, single-threaded GeoTIFF options."""
    with rio.Env(**_ENV), rio.open(
        path, "w", driver="GTiff", count=1, dtype="float32", crs=_CRS, nodata=np.nan,
        transform=transform, width=array.shape[1], height=array.shape[0],
        tiled=True, blockxsize=256, blockysize=256, compress="DEFLATE", predictor=3,
        zlevel=6, num_threads=1,
    ) as dst:
        dst.write(array, 1)
        dst.set_band_description(1, "Elevation")
        dst.set_band_unit(1, "m")
        dst.update_tags(1, VERTICAL_DATUM="NAVD88 (EPSG:5703)", POSITIVE="up")
        dst.update_tags(AREA_OR_POINT="Area")


def add_arguments(parser):
    parser.add_argument('--family', required=True, help='coarse source family or its catalog ID')
    parser.add_argument('--cell-m', required=True, type=float, help='planning grid cell size in metres')


def plan(ctx):
    census = ctx.region.dir / 'census.json'
    params = {'family': ctx.args.family, 'cell_m': ctx.args.cell_m}
    inputs = [receipts.Input(census, 'census')]
    if not census.is_file():
        return receipts.Plan(inputs, params)  # Let the runner report a missing input.

    data = census.read_bytes()
    doc = json.loads(data)
    summary = doc['summary']
    tiles = []
    for row in sorted(doc['files'], key=lambda row: row['path']):
        family = row.get('family')
        if params['family'] not in (family, select.FAMILY_IDS.get(family)):
            continue
        path = select.local_path(ctx.region.resolve(row['path']))
        tiles.append((path, row))
        inputs.append(receipts.Input(path, 'coarse-tile'))
    ctx.coarse_job = (summary, receipts.sha256_bytes(data), tiles)
    return receipts.Plan(inputs, params)


def build(ctx, out_dir):
    summary, census_sha, rows = ctx.coarse_job
    family, cell_m = ctx.args.family, ctx.args.cell_m
    if summary['region'] != ctx.region.id:
        raise receipts.ReceiptError('census region mismatch')
    if not rows:
        raise receipts.Held(f'no census rows for family {family!r} in region {ctx.region.id!r}')

    tiles, pins = [], []
    for path, row in rows:
        expected = row.get('sha256_receipt') or row.get('sha256')
        observed = receipts.sha256_file(path)
        if observed != expected:
            raise receipts.Held(f'SHA-256 mismatch for {row["path"]}: expected {expected}, observed {observed}')
        pins.append({'path': row['path'], 'sha256': expected})
        # The census producer records the native CRS read from the TIFF. A
        # horizontal-only CRS does not attest to NAVD88 elevation.
        crs = CRS.from_user_input(row['crs']) if row.get('crs') else None
        if not crs or not crs.is_compound or crs.sub_crs_list[1].to_epsg() != 5703:
            raise ValueError(f'Expected NAVD88-up in census CRS for {row["path"]}')
        tiles.append((path, expected, 'NAVD88-up'))

    bounds = summary['bbox']
    array, transform, report = build_coarse(tiles, bounds, cell_m=cell_m)
    write_coarse(out_dir / 'coarse-3310.tif', array, transform)
    (out_dir / 'coarse.json').write_bytes(receipts.canonical({
        'region': ctx.region.id, 'bbox': bounds, 'family': family, 'cell_m': cell_m,
        'hole_report': report, 'inputs': {'census_sha256': census_sha, 'tiles': pins},
    }) + b'\n')
