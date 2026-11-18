#!/usr/bin/env python3
"""Measurement check for the relief, contour and 3D byte budgets (MB-12).

This is a measurement script, not a CI gate. Nothing is downloaded or uploaded; it reads local files only.

Budgets (MAP-DESIGN-LOCK section 4):
  * relief bytes per view, worst case at 256 px tiles: desktop 1200x800 <= 1.6 MB, phone 390x844 <= 0.8 MB
  * per-sector relief archive <= 1.5 GB
  * depth contours: overview file <= 300 KB, full file <= 1 MB, per region
  * first load: 0 B added (layer off means zero relief or contour requests; proved by e2e/v2-relief-requests.spec.ts)

Per-view bytes = tiles touched by the viewport x the archive's mean tile size (tile data bytes / addressed tiles,
read from the PMTiles v3 header). z16-17 bytes per region come from Z17-SIZE.md when that file exists; when it does
not, the report says so plainly.

Exit status: 1 only when a budget is exceeded AND the run is a --fixture run or --strict. A plain run on real
files reports OVER rows and still exits 0.

Usage:
  python3 scripts/check_relief_budget.py                       # real Laguna/Morro design archives + repo dist contours
  python3 scripts/check_relief_budget.py --fixture FILE.json   # synthetic measurements (exit 1 if over budget)
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DESIGN = Path.home() / 'agent-work/scratch/sc-map-goal/design/tiles'
Z17_SIZE = Path.home() / 'agent-work/reports/sc-map-goal/Z17-SIZE.md'
TILE_PX = 256
VIEWS = {'desktop 1200x800': (1200, 800, 1_600_000), 'phone 390x844': (390, 844, 800_000)}
ARCHIVE_MAX = 1_500_000_000
CONTOUR_OVERVIEW_MAX = 300_000
CONTOUR_FULL_MAX = 1_000_000
# Design archives measured for the map design lock: the chosen ramp B for each sector.
DESIGN_ARCHIVES = {'laguna': 'laguna-B.pmtiles', 'morro': 'morro-B.pmtiles'}
DESIGN_Z17 = {'laguna': 'laguna-B-z17.pmtiles'}
DESIGN_CONTOURS = {'laguna': 'laguna/contours-ft.geojson', 'morro': 'morro/contours-ft.geojson'}


def tiles_in_view(width: int, height: int, tile_px: int = TILE_PX) -> int:
    """Worst case: an unaligned viewport touches one extra tile column and row."""
    return (math.ceil(width / tile_px) + 1) * (math.ceil(height / tile_px) + 1)


def pmtiles_header(path: Path) -> dict:
    with open(path, 'rb') as f:
        raw = f.read(127)
    if len(raw) < 127 or raw[:7] != b'PMTiles' or raw[7] != 3:
        raise ValueError(f'{path}: not a PMTiles v3 archive')
    data_len, addressed = struct.unpack_from('<QQ', raw, 64)[0], struct.unpack_from('<Q', raw, 72)[0]
    return {'tile_data_bytes': data_len, 'addressed_tiles': addressed, 'min_zoom': raw[100], 'max_zoom': raw[101],
            'file_bytes': path.stat().st_size}


def region_from_archive(path: Path) -> dict:
    h = pmtiles_header(path)
    if not h['addressed_tiles']:
        raise ValueError(f'{path}: archive has no tiles')
    return {'archive_bytes': h['file_bytes'], 'tile_count': h['addressed_tiles'],
            'mean_tile_bytes': h['tile_data_bytes'] / h['addressed_tiles'], 'zooms': [h['min_zoom'], h['max_zoom']]}


def check(name: str, value: float, limit: float, rows: list) -> None:
    rows.append({'check': name, 'value': round(value), 'limit': limit, 'ok': value <= limit})


def evaluate(regions: dict) -> list:
    rows: list = []
    for rid, r in regions.items():
        if 'mean_tile_bytes' in r:
            for view, (w, h, limit) in VIEWS.items():
                n = tiles_in_view(w, h)
                check(f'{rid}: relief per view, {view} ({n} tiles)', n * r['mean_tile_bytes'], limit, rows)
        if 'archive_bytes' in r:
            check(f'{rid}: relief archive', r['archive_bytes'], ARCHIVE_MAX, rows)
        if r.get('contours_overview_bytes') is not None:
            check(f'{rid}: contours overview', r['contours_overview_bytes'], CONTOUR_OVERVIEW_MAX, rows)
        if r.get('contours_full_bytes') is not None:
            check(f'{rid}: contours full', r['contours_full_bytes'], CONTOUR_FULL_MAX, rows)
    return rows


def real_regions(design: Path, repo: Path) -> dict:
    regions: dict = {}
    for rid, name in DESIGN_ARCHIVES.items():
        path = design / name
        if not path.is_file():
            print(f'note: design archive {path} not found; {rid} relief not measured')
            continue
        regions[rid] = region_from_archive(path)
        z = design / DESIGN_Z17.get(rid, '')
        if rid in DESIGN_Z17 and z.is_file():
            regions[rid]['design_z17_box_bytes'] = z.stat().st_size
        c = design.parent / DESIGN_CONTOURS[rid]
        if c.is_file():
            regions[rid]['contours_full_bytes'] = c.stat().st_size
    # Contours already shipped in the repo, per region.
    for d in sorted((repo / 'dist/regions').glob('*/depth-contours.geojson')):
        entry = regions.setdefault(f'dist:{d.parent.name}', {})
        entry['contours_full_bytes'] = d.stat().st_size
        ov = d.with_name('depth-contours-overview.geojson')
        if ov.is_file():
            entry['contours_overview_bytes'] = ov.stat().st_size
    return regions


def z17_report(path: Path) -> list:
    if not path.is_file():
        return [f'z16-17 bytes per region: NOT REPORTED, {path} is absent (MB-07 has not produced Z17-SIZE.md)']
    out = [f'z16-17 bytes per region, from {path}:']
    rows = [ln for ln in path.read_text(encoding='utf-8', errors='replace').splitlines() if ln.lstrip().startswith('|')]
    out += rows[:60] or ['  (no table rows found in the file)']
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--fixture', type=Path, help='JSON {"regions": {id: {mean_tile_bytes, archive_bytes, contours_*_bytes}}}')
    ap.add_argument('--strict', action='store_true', help='exit 1 on an over-budget real measurement')
    ap.add_argument('--design-dir', type=Path, default=DESIGN)
    ap.add_argument('--repo', type=Path, default=ROOT)
    ap.add_argument('--z17-size', type=Path, default=Z17_SIZE)
    a = ap.parse_args(argv)

    if a.fixture:
        regions = json.loads(a.fixture.read_text())['regions']
        print(f'synthetic fixture {a.fixture}')
    else:
        regions = real_regions(a.design_dir, a.repo)
    rows = evaluate(regions)
    print(f'{"check":<58}{"measured":>14}{"budget":>14}  status')
    for r in rows:
        print(f'{r["check"]:<58}{r["value"]:>14,}{r["limit"]:>14,}  {"ok" if r["ok"] else "OVER"}')
    for rid, r in regions.items():
        if 'design_z17_box_bytes' in r:
            print(f'{rid}: design z17 box archive {r["design_z17_box_bytes"]:,} B (design sample, not Z17-SIZE.md)')
        if 'tile_count' in r:
            print(f'{rid}: {r["tile_count"]} tiles, mean {r["mean_tile_bytes"]:,.0f} B/tile, zooms {r["zooms"][0]}-{r["zooms"][1]}')
    print('first load: 0 B added is proved by e2e/v2-relief-requests.spec.ts (layer off: zero relief/contour requests)')
    for ln in z17_report(a.z17_size):
        print(ln)
    over = [r for r in rows if not r['ok']]
    print(f'{len(over)} over budget of {len(rows)} checks')
    return 1 if over and (a.fixture or a.strict) else 0


if __name__ == '__main__':
    sys.exit(main())
