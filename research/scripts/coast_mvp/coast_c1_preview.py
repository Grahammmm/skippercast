"""Offline C1-native rights inventory and honest hillshade fallback (no C2 jobs).

Reads only the named C1 manifest, elevation and contributor; never fetches URLs.
Outputs are private research previews, not a licence/datum/publication decision.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
from html import escape
import json
import math
from pathlib import Path
import re
import struct
import zlib
from urllib.parse import urlsplit

WARNING = "NOT FOR NAVIGATION — research preview; review_required"
DATA_CAVEAT = ("Vertical datums are unresolved; no vertical reconciliation or navigation accuracy is claimed. "
               "Blank areas are withheld/unsupported, not a land or water classification. ")
CAVEAT = DATA_CAVEAT + "C1 hillshade fallback only: no C2 contours, terrain-RGB tiles or C3 viewer acceptance."
CSS = """body{margin:0;background:#0c1824;color:#e5eef3;font:16px system-ui,sans-serif}
header{padding:15px 26px;background:#342b19;border-bottom:2px solid #d8ae59;color:#ffe1a0}
h1{font-size:25px;margin:10px 0}h2{font-size:20px;color:#b9e2e5}p{line-height:1.5}
main{padding:16px 26px}a{color:#8ed5eb}code{overflow-wrap:anywhere;font-size:12px}
.layout{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:20px}
.figure{background:#142331;padding:12px;border:1px solid #304554;border-radius:8px}
.figure img{width:100%;height:650px;object-fit:contain;image-rendering:auto}
aside{font-size:14px}section{padding:12px 0;border-bottom:1px solid #36505a}
.small{font-size:13px;color:#acc1cc}.pill{color:#fae1a0}.legend{height:12px;
background:linear-gradient(90deg,#e4d9a3 0%,#69c7c7 STOP100,#246985 STOP500,#152b52 100%);margin:8px 0}
nav a{margin-right:15px}ul{padding-left:18px}footer{font-size:13px;color:#bdcbd1;margin-top:8px}
"""


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}: nonempty text required")
    return value


def https_url(value: object) -> str:
    value = text(value, "citation")
    url = urlsplit(value)
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or any(c.isspace() for c in value)):
        raise ValueError("citation must be credential-free HTTPS")
    return value


def validate_manifest(manifest: dict) -> list[dict]:
    """Accept the native C1 schema, without inventing C5 clearance fields."""
    if type(manifest.get("schema_version")) is not int or manifest["schema_version"] != 1:
        raise ValueError("C1 schema_version=1 required")
    if manifest.get("units") != "m" or manifest.get("value_convention") != "elevation_positive_up":
        raise ValueError("C1 metres positive-up required")
    counts = manifest.get("contributor_cells")
    if not isinstance(counts, dict) or not isinstance(manifest.get("sources"), list):
        raise ValueError("C1 sources and contributor_cells required")
    seen, ids, used = set(), set(), []
    for row in manifest["sources"]:
        code = row.get("code")
        source_id = text(row.get("id"), "id")
        if type(code) is not int or code <= 0 or code in seen or source_id in ids:
            raise ValueError("unique positive source codes and IDs required")
        seen.add(code)
        ids.add(source_id)
        cells = counts.get(str(code), 0)
        if type(cells) is not int or cells < 0:
            raise ValueError("nonnegative integer contributor count required")
        if not cells:
            continue
        for key in ("rights", "attribution", "vertical_datum", "offset_note"):
            text(row.get(key), key)
        https_url(row.get("citation"))
        if not re.fullmatch(r"[0-9a-f]{64}", str(row.get("sha256", ""))):
            raise ValueError("source SHA-256 required")
        used.append(dict(row, contributed_cells=cells))
    if any(key not in {str(code) for code in seen} for key in counts):
        raise ValueError("unknown contributor code")
    if not used or sum(row["contributed_cells"] for row in used) != manifest.get("stats", {}).get("valid_cells"):
        raise ValueError("contributor total differs from valid_cells or is empty")
    return used


def shell(title: str, content: str) -> str:
    style = CSS.replace('STOP100', f'{100 / 1700 * 100:.5f}%').replace('STOP500', f'{500 / 1700 * 100:.5f}%')
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
            f'img-src \'self\' data:; style-src \'unsafe-inline\'">'
            f'<title>{escape(title)}</title><style>{style}</style></head>'
            f'<body><header><strong>{WARNING}</strong></header><main>{content}</main></body></html>\n')


def rights_page(manifest: dict, manifest_sha256: str) -> str:
    sources = validate_manifest(manifest)
    if not re.fullmatch(r"[0-9a-f]{64}", manifest_sha256):
        raise ValueError("manifest SHA-256 required")
    parts = ['<h1>Coast data rights and attribution</h1>',
             '<p>Native C1 manifest inventory. Source notices below are verbatim, not independently verified '
             'licences. No CC0/public-domain/commercial clearance is inferred from the publisher.</p>',
             '<p class="pill">CSUMB / third-party for-profit permission question: involvement and '
             'applicable terms are not resolved by this manifest. If CSUMB terms apply, non-profit use '
             'requires acknowledgment and for-profit use requires permission or owner/counsel resolution. '
             'No permission request has been sent. Publication remains held.</p>',
             f'<p>{DATA_CAVEAT}</p><p>Manifest SHA-256: <code>{manifest_sha256}</code></p>',
             f'<p>Sources actually contributing: {len(sources)}. Counts: native C1 contributor_cells; '
             'the preview build separately verifies the contributor raster and its hash. '
             'Zero-contribution inputs are excluded.</p>']
    for row in sources:
        e = {key: escape(str(value), quote=True) for key, value in row.items()}
        parts.append(f'<section data-source="{e["id"]}"><h2>{e["id"]}</h2>'
                     f'<p>Contributor code {e["code"]}; cells {e["contributed_cells"]}</p>'
                     f'<p>Recorded rights / licence notice: {e["rights"]}</p>'
                     f'<p>Attribution: {e["attribution"]}</p>'
                     f'<p><a href="{e["citation"]}">Original source citation</a> '
                     '(link only; no source downloaded)</p>'
                     f'<p>Source SHA-256: <code>{e["sha256"]}</code></p>'
                     f'<p>Vertical datum: {e["vertical_datum"]}; {e["offset_note"]}</p>'
                     '<p>Rights: review_required; commercial permission unresolved.</p></section>')
    parts.append('<h2>Upstream limitations</h2><ul>' + ''.join(
        f'<li>{escape(str(item))}</li>' for item in manifest.get("limitations", [])) + '</ul>')
    return shell("Coast rights — review required", ''.join(parts))


def verify_inputs(root: Path, manifest: dict) -> dict:
    import numpy as np
    import rasterio
    rows = validate_manifest(manifest)
    hashes = {}
    for key in ("elevation", "contributor"):
        declared = manifest["outputs"][key]
        if declared["path"] != f"{key}.tif":
            raise ValueError("only sibling C1 elevation/contributor inputs are allowed")
        path = root / declared["path"]
        if path.resolve().parent != root.resolve():
            raise ValueError("input symlink escapes admitted C1 directory")
        hashes[key] = digest(path)
        if hashes[key] != declared["sha256"]:
            raise ValueError(f"{key} SHA-256 mismatch")
    counts = Counter()
    with rasterio.open(root / "elevation.tif") as elevation, rasterio.open(root / "contributor.tif") as contributor:
        if (elevation.shape != contributor.shape or elevation.crs != contributor.crs
                or elevation.transform != contributor.transform):
            raise ValueError("C1 input grids are not aligned")
        if (elevation.shape != (manifest["height"], manifest["width"])
                or str(elevation.crs) != manifest["crs"]
                or elevation.transform.a != manifest["resolution_m"]
                or elevation.transform.e != -manifest["resolution_m"]
                or elevation.transform.b != 0 or elevation.transform.d != 0
                or list(elevation.bounds) != manifest["bounds_projected"]):
            raise ValueError("manifest grid declaration mismatch")
        for _, window in contributor.block_windows(1):
            codes = contributor.read(1, window=window)
            values, sizes = np.unique(codes, return_counts=True)
            counts.update({int(code): int(size) for code, size in zip(values, sizes) if code != 0})
    expected = {row["code"]: row["contributed_cells"] for row in rows}
    if dict(counts) != expected:
        raise ValueError("actual contributor counts differ from manifest")
    return {"input_sha256": hashes, "verified_contributor_cells": dict(counts)}


def conservative_sample(elevation, contributor, window, max_side=1300):
    """Nearest values, but withhold any block with a hole/mixed contributor.

    No averaging of depths and no interpolation across datum/source boundaries.
    Native reads are bounded to strips; all source pixels in each display block
    must agree on support and contributor before its centre is displayed.
    """
    import numpy as np
    from rasterio.windows import Window
    stride = max(1, math.ceil(max(window.width, window.height) / max_side))
    width, height = int(window.width) // stride, int(window.height) // stride
    if min(width, height) < 3:
        raise ValueError("view has fewer than three display samples")
    values = np.full((height, width), np.nan, dtype=np.float32)
    codes = np.zeros((height, width), dtype=np.uint16)
    for y in range(0, height, 32):
        rows = min(32, height - y)
        block = Window(window.col_off, window.row_off + y * stride, width * stride, rows * stride)
        z = elevation.read(1, window=block)
        c = contributor.read(1, window=block)
        valid = np.isfinite(z) & (z != elevation.nodata) & (c > 0)
        shape = (rows, stride, width, stride)
        supported = valid.reshape(shape).all(axis=(1, 3))
        cmin = c.reshape(shape).min(axis=(1, 3))
        cmax = c.reshape(shape).max(axis=(1, 3))
        supported &= cmin == cmax
        centre = z[stride // 2::stride, stride // 2::stride]
        values[y:y + rows] = np.where(supported, centre, np.nan)
        codes[y:y + rows] = np.where(supported, cmin, 0)
    return values, codes, stride


def hillshade(values, codes, spacing: float):
    import numpy as np
    valid = np.isfinite(values) & (codes > 0)
    if not valid.any():
        raise ValueError("no supported cells in view")
    z = np.where(valid, values, 0.0)
    dx, dy = np.zeros_like(z), np.zeros_like(z)
    horizontal = valid[:, 2:] & valid[:, 1:-1] & valid[:, :-2]
    horizontal &= (codes[:, 2:] == codes[:, 1:-1]) & (codes[:, :-2] == codes[:, 1:-1])
    vertical = valid[2:] & valid[1:-1] & valid[:-2]
    vertical &= (codes[2:] == codes[1:-1]) & (codes[:-2] == codes[1:-1])
    dx[:, 1:-1] = np.where(horizontal, (z[:, 2:] - z[:, :-2]) / (2 * spacing), 0)
    dy[1:-1] = np.where(vertical, (z[2:] - z[:-2]) / (2 * spacing), 0)
    # NW sun at 45 degrees altitude. Physical slope, no vertical exaggeration.
    light = np.clip((-dx * -.5 - dy * -.5 + math.sqrt(.5)) / np.sqrt(1 + dx*dx + dy*dy), 0, 1)
    depth = -z
    stops = [0, 100, 500, 1700]
    palette = np.array([[228, 217, 163], [105, 199, 199], [36, 105, 133], [21, 43, 82]])
    color = np.stack([np.interp(depth, stops, palette[:, channel]) for channel in range(3)], axis=-1)
    color *= (.35 + .85 * light)[..., None]
    rgba = np.zeros((*z.shape, 4), dtype=np.uint8)
    rgba[:, :, :3] = np.clip(color, 0, 255).astype('uint8')
    rgba[:, :, 3] = valid.astype('uint8') * 255
    return rgba


def png(path: Path, rgba) -> None:
    """Write ordinary lossless RGBA PNG without optional plotting dependencies."""
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data) & 0xffffffff)
    height, width, _ = rgba.shape
    scanlines = b''.join(b'\x00' + row.tobytes() for row in rgba)
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', width, height, 8, 6, 0, 0, 0))
                     + chunk(b'IDAT', zlib.compress(scanlines, 6)) + chunk(b'IEND', b''))


VIEWS = (
    ("overview", "Central coast — regional overview", None),
    ("morro-estero", "Morro Bay / Estero — shelf view", (-121.10, 35.20, -120.80, 35.52)),
    ("buchon-close", "Point Buchon — close view", (-120.99, 35.20, -120.85, 35.32)),
)


def build(manifest_path: Path, output: Path) -> dict:
    import numpy as np
    import rasterio
    from rasterio.warp import transform_bounds
    from rasterio.windows import Window, from_bounds
    if output.resolve().is_relative_to(manifest_path.parent.resolve()):
        raise ValueError("output must be outside the read-only C1 input directory")
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    sources = validate_manifest(manifest)
    sha = hashlib.sha256(raw).hexdigest()
    verification = verify_inputs(manifest_path.parent, manifest)
    output.mkdir(parents=True, exist_ok=False)  # never overwrite an earlier evidence run
    receipt = {"status": "review_required", "navigation": WARNING, "mode": "c1_hillshade_fallback",
               "manifest_sha256": sha, "limitations": manifest.get("limitations", []), **verification,
               "views": [], "c2_c3_acceptance": "not performed; no C2 job launched"}
    (output / "rights.html").write_text(rights_page(manifest, sha), encoding="utf-8")
    with rasterio.open(manifest_path.parent / "elevation.tif") as elevation, rasterio.open(manifest_path.parent / "contributor.tif") as contributor:
        full = Window(0, 0, elevation.width, elevation.height)
        for name, title, bbox in VIEWS:
            window = full if bbox is None else from_bounds(*transform_bounds('EPSG:4326', elevation.crs, *bbox), elevation.transform)
            window = window.round_offsets().round_lengths().intersection(full)
            values, codes, stride = conservative_sample(elevation, contributor, window)
            spacing = float(elevation.res[0] * stride)
            rgba = hillshade(values, codes, spacing)
            png(output / f"{name}-hillshade.png", rgba)
            shown = int(np.count_nonzero(codes))
            view = {"id": name, "title": title, "window": list(window.flatten()), "stride": stride,
                    "display_spacing_m": spacing, "display_shape": list(values.shape), "supported_display_samples": shown,
                    "minimum_elevation_m": float(np.nanmin(values)), "maximum_elevation_m": float(np.nanmax(values)),
                    "png_sha256": digest(output / f"{name}-hillshade.png")}
            receipt["views"].append(view)
            source_list = ''.join(f'<li>{escape(row["id"])}: {escape(row["attribution"])}</li>' for row in sources)
            content = (f'<h1>{escape(title)}</h1><nav><a href="rights.html">Rights and full attribution</a>'
                       + ''.join(f'<a href="{key}.html">{escape(label)}</a>' for key, label, _ in VIEWS)
                       + f'</nav><div class="layout"><div class="figure"><div>N ↑ · EPSG:3310 grid north · hillshade only</div>'
                       f'<img src="{name}-hillshade.png" alt="Real C1 bathymetry hillshade; unsupported cells blank">'
                       '<div class="legend"></div><div class="small">Elevation-positive-up colour scale: 0 → −1700 m · '
                       'NW light, 45° altitude · no vertical exaggeration</div></div><aside>'
                       f'<h2>Cached real data</h2><p>Morro Bay segment<br>10 m C1 mosaic<br>{spacing:g} m display sampling</p>'
                       '<p class="pill">Review required · not cleared for publication</p>'
                       f'<p>{CAVEAT}</p><p>Conservative support: any hole or mixed-source display block is withheld. '
                       'Nearest centre values; no smoothing across sources. Edge remainders omitted.</p>'
                       f'<h2>Mosaic source attribution</h2><ul>{source_list}</ul>'
                       f'<p class="small">Input manifest <code>{sha}</code></p></aside></div>'
                       '<footer>Private C1 fallback preview, not the C3 tile viewer. Blank coverage is not evidence of dry land. '
                       'Source rights and per-source datum caveats are on the linked rights page.</footer>')
            (output / f"{name}.html").write_text(shell(title, content), encoding="utf-8")
    receipt["rights_sha256"] = digest(output / "rights.html")
    (output / "receipt.json").write_text(json.dumps(receipt, indent=2, allow_nan=False) + '\n')
    return receipt


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    receipt = build(args.manifest, args.output)
    print(json.dumps(receipt, indent=2, allow_nan=False))


if __name__ == '__main__':
    main()
