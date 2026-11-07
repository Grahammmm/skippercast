#!/usr/bin/env python3
"""Build the California outer-coast seafloor inventory from repository catalogs only.

COAST-INVENTORY-1. Reads committed catalogs, review summaries and receipts; makes no
network request and opens no raster. Writes:

  catalog/coast-seafloor-inventory.json   one row per catalog/coastal-sectors.json sector
  reports/COAST-SEAFLOOR-INVENTORY.md     the same rows, the ranked gap list and a summary

Every figure carries a label:
  MEASURED   copied or summed from pixel/cell counts already recorded in a repo catalog for
             exactly the quantity named
  ESTIMATED  derived with a stated assumption (for example assigning a raster or reach to a
             sector by its bounding box, or using a 0-100 m reference band for 0-300 ft)
  UNKNOWN    the repo has no catalog figure for it; never filled by guessing

Three facts are kept apart for the 0-300 ft band of every sector:
  1. finest grid available at any depth (catalogued or opened, depth band not necessarily known);
  2. best tier with CONFIRMED shallow cells (a catalog records cells in 0-300 ft, 25-200 ft or the
     seafloor ledger's 0-100 m band for that grid in that sector). No area threshold is applied;
  3. extent: km2 of such cells, reported per evidence family and never summed across families.

Run from the repository root:  python3 research/scripts/inventory_coast_seafloor.py
Add --check to fail when the committed outputs differ from a fresh build.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_JSON = ROOT / 'catalog/coast-seafloor-inventory.json'
OUT_MD = ROOT / 'reports/COAST-SEAFLOOR-INVENTORY.md'
FT_300_M = 91.44
TIER_ORDER = ['2 m', '5 m', '10 m', 'coarser', 'none']
TIER_RES = {'2 m': 2.0, '5 m': 5.0, '10 m': 10.0}
# NOAA variable-resolution BAG refinements are recorded only as "1-4 m", per file, not per cell.
VR_RANGE_M = (1.0, 4.0)

INPUTS = {
    'sectors': 'catalog/coastal-sectors.json',
    'readiness': 'dist/data/california-atlas-readiness.json',
    'ledger': 'dist/data/seafloor-ledger.json',
    'reaches': 'catalog/reaches.json',
    'usgs_bathy': 'dist/data/usgs-depth-datum-ledger.json',
    'usgs_meta': 'dist/data/usgs-ds781-metadata-review.json',
    'usgs_char': 'dist/data/usgs-ds781-native-character-review.json',
    'noaa_regular': 'dist/data/noaa-regular-native-depth-review.json',
    'noaa_vr': 'dist/data/noaa-vr-native-depth-expanded-review.json',
    'bluetopo': 'dist/data/bluetopo-statewide-source-review.json',
    'ports': 'dist/data/home-ports.json',
    'em300': 'catalog/candidates/usgs-monterey-1998-em300-original.json',
    'caldig': 'catalog/candidates/usgs-caldig-v2.json',
    'gebco': 'catalog/candidates/gebco-2026-grid.json',
    'surveys': 'catalog/surveys.json',
}
CSUMB_GLOB = 'catalog/csumb-*native-sources.json'
DS3091_GLOB = 'dist/data/cdfw-predicted-hard-*.geojson'
USGS_HARD_GLOB = 'dist/data/usgs-hard-context-*.geojson'

# Candidate sources a better 0-300 ft grid may come from, by family. Named in the gap list.
# Only the cited repo document is evidence; availability for a given sector is unverified.
CANDIDATE_FAMILIES = {
    'csmp': ('CSUMB / USGS California Seafloor Mapping Program (CSMP) state-waters 2 m multibeam',
             'docs/california-seabed-coverage.md'),
    'ds781': ('USGS California State Waters Map Series (DS 781 / DOI releases) 2 m bathymetry and seafloor character',
              'dist/data/usgs-ds781-metadata-review.json'),
    'noaa': ('NOAA NOS hydrographic BAGs (NCEI) and NOAA NBS / BlueTopo contributors',
             'dist/data/noaa-native-sector-review.json'),
    'lidar': ('NOAA/USACE coastal topobathy lidar (2013 California TopoBathy Merge; 2017 Central CoNED 1 m DEM)',
              'docs/archive/central-300ft-source-gap-strategy.md'),
    'opc': ('California Ocean Protection Council (OPC), state funder and custodian contact for CSMP products',
            'docs/coast-rights-coverage.md'),
}


def load(rel):
    return json.loads((ROOT / rel).read_text(encoding='utf-8'))


def sha256(rel):
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def fig(value, label, basis):
    assert label in ('MEASURED', 'ESTIMATED', 'UNKNOWN')
    if label == 'UNKNOWN':
        value = None
    return {'value': value, 'label': label, 'basis': basis}


def rnd(x, n=1):
    return None if x is None else round(float(x), n)


def tier_of(res_m):
    if res_m is None:
        return 'none'
    if res_m <= 2.0:
        return '2 m'
    if res_m <= 5.0:
        return '5 m'
    if res_m <= 10.0:
        return '10 m'
    return 'coarser'


# ---------------------------------------------------------------- geometry helpers

def albers_3310_to_lonlat(x, y):
    """Inverse EPSG:3310 (NAD83 California Albers, GRS80), Snyder 1987 eq. 14-18 and 3-16."""
    a, f = 6378137.0, 1 / 298.257222101
    e2 = 2 * f - f * f
    e = math.sqrt(e2)

    def m(phi):
        return math.cos(phi) / math.sqrt(1 - e2 * math.sin(phi) ** 2)

    def q(phi):
        s = math.sin(phi)
        return (1 - e2) * (s / (1 - e2 * s * s) - (1 / (2 * e)) * math.log((1 - e * s) / (1 + e * s)))

    p1, p2, p0, lon0 = map(math.radians, (34.0, 40.5, 0.0, -120.0))
    n = (m(p1) ** 2 - m(p2) ** 2) / (q(p2) - q(p1))
    c = m(p1) ** 2 + n * q(p1)
    rho0 = a * math.sqrt(c - n * q(p0)) / n
    yy = y + 4000000.0
    rho = math.hypot(x, rho0 - yy)
    theta = math.atan2(x, rho0 - yy)
    qq = (c - (rho * n / a) ** 2) / n
    phi = math.asin(max(-1.0, min(1.0, qq / 2)))
    for _ in range(20):
        s = math.sin(phi)
        d = ((1 - e2 * s * s) ** 2 / (2 * math.cos(phi))) * (
            qq / (1 - e2) - s / (1 - e2 * s * s) + (1 / (2 * e)) * math.log((1 - e * s) / (1 + e * s)))
        phi += d
        if abs(d) < 1e-12:
            break
    return math.degrees(lon0 + theta / n), math.degrees(phi)


def bbox_3310_to_wgs84(b):
    pts = [albers_3310_to_lonlat(x, y) for x in (b[0], b[2]) for y in (b[1], b[3])]
    return [min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)]


def in_bounds(lon, lat, b):
    return b[0] <= lon <= b[2] and b[1] <= lat < b[3]


def sector_of_bbox(bbox, bounds):
    """Sector whose box holds the bbox centre, plus every sector box the bbox overlaps with positive area."""
    cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
    home = next((sid for sid, b in bounds.items() if in_bounds(cx, cy, b)), None)
    touching = [sid for sid, b in bounds.items()
                if bbox[0] < b[2] and bbox[2] > b[0] and bbox[1] < b[3] and bbox[3] > b[1]]
    return home, touching


def polygon_centroid(geom):
    ring = geom['coordinates'][0] if geom['type'] == 'Polygon' else geom['coordinates'][0][0]
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return sum(xs) / len(xs), sum(ys) / len(ys)


# ---------------------------------------------------------------- pure classification rules

def classify_shallow(evidence):
    """Separate best-available resolution, confirmed shallow tier and extent for one sector.

    Each evidence item: {'resolution_m': float | None, 'resolution_range_m': (lo, hi) | None,
    'depth': 'confirmed' | 'unrecorded' | 'none-shallow', 'family': str, ...}.
    - 'confirmed': a catalog records cells of this grid in the 0-300 ft (or 25-200 ft, or ledger
      0-100 m) band inside this sector;
    - 'unrecorded': grid opened/catalogued but its depth band is not recorded in the repo;
    - 'none-shallow': a catalog records zero 0-300 ft cells.
    No area threshold: one confirmed fine cell set makes that tier available; extent is reported apart.
    """
    def finest(items):
        vals = []
        for e in items:
            if e.get('resolution_m'):
                vals.append(float(e['resolution_m']))
            elif e.get('resolution_range_m'):
                vals.append(float(e['resolution_range_m'][0]))
        return min(vals, default=None)

    confirmed = [e for e in evidence if e['depth'] == 'confirmed']
    definite = [e for e in confirmed if e.get('resolution_m')]
    ranged = [e for e in confirmed if not e.get('resolution_m') and e.get('resolution_range_m')]
    best_definite = min((float(e['resolution_m']) for e in definite), default=None)
    tier = tier_of(best_definite)
    uncertain = False
    if ranged:
        hi = min(float(e['resolution_range_m'][1]) for e in ranged)
        lo = min(float(e['resolution_range_m'][0]) for e in ranged)
        ranged_floor = tier_of(hi)  # class the ranged evidence certainly reaches
        if TIER_ORDER.index(ranged_floor) < TIER_ORDER.index(tier):
            tier = ranged_floor
        # Uncertain when the ranged cells could be finer than the tier we can prove.
        if TIER_ORDER.index(tier_of(lo)) < TIER_ORDER.index(tier):
            uncertain = True
    finest_any = finest(evidence)
    finer_unconfirmed = [e for e in evidence if e['depth'] == 'unrecorded' and e.get('resolution_m')
                         and TIER_ORDER.index(tier_of(e['resolution_m'])) < TIER_ORDER.index(tier)]
    tier_sources = [e for e in confirmed if (e.get('resolution_m') and tier_of(e['resolution_m']) == tier)
                    or (not e.get('resolution_m') and e.get('resolution_range_m')
                        and tier_of(e['resolution_range_m'][1]) == tier)]
    return {
        'tier': tier,
        'tier_uncertain': uncertain,
        'best_confirmed_resolution_m': best_definite if tier_of(best_definite) == tier else None,
        'finest_any_depth_m': finest_any,
        'finer_grids_depth_unrecorded': finer_unconfirmed,
        'tier_sources': tier_sources,
    }


def ledger_tier_proxy(reaches, tier_res):
    """Reach-level share of the provisional 0-100 m band covered by grids at tier_res or finer.

    reaches: [{'band_km2', 'selected_km2', 'resolutions_m': [...], 'crosses': bool}]. The ledger
    records one selected footprint per reach, not per grid, so:
      low  = reaches whose every used grid is <= tier_res  (their footprint is entirely at the tier)
      high = reaches with at least one used grid <= tier_res (footprint may include coarser grids)
    Reaches that cross a sector line are left out of both numerator and denominator.
    Returns None when no non-crossing reach band exists.
    """
    kept = [r for r in reaches if not r['crosses']]
    band = sum(r['band_km2'] for r in kept)
    excluded = sum(r['band_km2'] for r in reaches if r['crosses'])
    if band <= 0:
        return None
    low = sum(r['selected_km2'] for r in kept
              if r['resolutions_m'] and all(x <= tier_res for x in r['resolutions_m']))
    high = sum(r['selected_km2'] for r in kept if any(x <= tier_res for x in r['resolutions_m']))
    return {'low_pct': 100.0 * low / band, 'high_pct': 100.0 * high / band, 'low_km2': low, 'high_km2': high,
            'band_km2': band, 'excluded_crossing_band_km2': excluded,
            'reaches_used': len(kept), 'reaches_crossing': len(reaches) - len(kept)}


# ---------------------------------------------------------------- source parsing

def csumb_resolution(src):
    res = src.get('resolution_m', src.get('resolution'))
    if isinstance(res, list) and res:
        return float(res[0])
    if isinstance(res, (int, float)):
        return float(res)
    member = src.get('archive_member') or src.get('bathymetry_grid') or ''
    mm = re.search(r'(\d+)m(?:bathy|bthy)', member)
    return float(mm.group(1)) if mm else None


def csumb_acq(src):
    dates = [d for d in (src.get('acquisition_dates') or []) if d]
    if dates:
        return f'{min(dates)[:4]}-{max(dates)[:4]}' if min(dates)[:4] != max(dates)[:4] else min(dates)[:4]
    if src.get('acquisition_year'):
        return str(src['acquisition_year'])
    return None


def csumb_name(src):
    member = src.get('archive_member') or src.get('bathymetry_grid') or ''
    return src.get('name') or src.get('survey_id') or src.get('block') or member.split('/')[0]


def usgs_name(title, res_m):
    """Short display name for a USGS state-waters bathymetry title."""
    t = re.sub(r'^Bathymetry(?: \[\d+m\])?(?:--| from multibeam echosounder data collected | )', '', title)
    t = re.sub(r'(?i)^offshore of the |^offshore of |^offshore ', '', t)
    t = re.sub(r'(?i)\s*(map )+area|,\s*California$', '', t).strip(' ,')
    return f'USGS state-waters {round(res_m, 1):g} m bathymetry, {t}'


def year_span(values):
    ys = sorted({str(v)[:4] for v in values if v})
    if not ys:
        return None
    return ys[0] if ys[0] == ys[-1] else f'{ys[0]}-{ys[-1]}'


def date_figs(entries, release_basis, acq_basis):
    """Explicit release date (publication) and, separately, acquisition/survey dates."""
    rel = [e.get('release_date') for e in entries]
    known = [r for r in rel if r]
    n = len(entries)
    if not known:
        release = fig(None, 'UNKNOWN', f'no release/publication date recorded for these {n} grid(s); {release_basis}')
    else:
        span = year_span(known)
        release = fig(span if len(known) == n else f'{span} for {len(known)} of {n} grids; rest UNKNOWN', 'MEASURED',
                      f'publication date recorded for {len(known)} of {n} grid(s) in {INPUTS["usgs_meta"]}'
                      + ('' if len(known) == n else '; the others have no recorded release date (UNKNOWN)'))
    acq = [e.get('acquisition') for e in entries if e.get('acquisition')]
    acquisition = fig(year_span(acq), 'MEASURED', acq_basis) if acq else fig(None, 'UNKNOWN', acq_basis)
    return release, acquisition


# ---------------------------------------------------------------- build

def build():
    data = {k: load(v) for k, v in INPUTS.items()}
    sectors = data['sectors']['sectors']
    ids = [s['id'] for s in sectors]
    readiness = {s['sector_id']: s for s in data['readiness']['sectors']}
    bounds = {sid: readiness[sid]['bounds'] for sid in ids}
    input_files = sorted([*INPUTS.values(), *glob.glob(CSUMB_GLOB, root_dir=ROOT),
                          *glob.glob(DS3091_GLOB, root_dir=ROOT), *glob.glob(USGS_HARD_GLOB, root_dir=ROOT)])

    survey_cat = {sv['id']: sv for sv in data['surveys']['surveys']}
    sv_all = data['surveys']['surveys']
    statewide_surveys = {
        'entries': fig(len(sv_all), 'MEASURED', 'catalog/surveys.json surveys[]'),
        'native_inspected': fig(sum(1 for x in sv_all if x.get('inspection_level') == 'native'), 'MEASURED',
                                'inspection_level == native'),
        'catalog_or_metadata_only': fig(sum(1 for x in sv_all if x.get('inspection_level') in ('catalog', 'metadata')),
                                        'MEASURED', 'inspection_level in (catalog, metadata)'),
        'usable_status': fig(sum(1 for x in sv_all if x.get('status') == 'usable'), 'MEASURED', 'status == usable'),
        'note': 'catalog/surveys.json carries no sector or footprint field, so these counts are statewide only.',
    }
    # Publication dates of USGS DS 781 releases, joined by archive URL (dist/data/usgs-ds781-metadata-review.json).
    pubdate = {r['archive_url']: r.get('publication_date') for r in data['usgs_meta']['records'] if r.get('publication_date')}

    evidence = defaultdict(list)

    # 1. CSUMB native grids recorded in catalog/csumb-*native-sources.json.
    csumb_by_sector = defaultdict(list)
    for rel in sorted(glob.glob(CSUMB_GLOB, root_dir=ROOT)):
        for src in load(rel).get('sources', []):
            res = csumb_resolution(src)
            b = src.get('bounds_wgs84')
            sid, touching, basis = None, [], None
            if b:
                sid, touching = sector_of_bbox(b, bounds)
                basis = 'bounding-box centre in the sector box'
            if sid is None:
                survey = src.get('survey_id')
                hits = [x for x in ids if survey and survey in (readiness[x].get('csumb_catalog_survey_lead_ids') or [])]
                if hits:
                    sid, touching = hits[0], hits
                    basis = 'readiness CSUMB survey-lead mapping (first listed sector)'
            if not sid:
                continue
            px = src.get('nominal_0_300ft_pixels')
            depth = 'unrecorded' if px is None else ('confirmed' if px > 0 else 'none-shallow')
            e = {
                'family': 'CSUMB',
                'name': f'CSUMB {csumb_name(src)} {rnd(res, 0) if res else "?"} m native grid',
                'id': src.get('id'),
                'resolution_m': res,
                'depth': depth,
                'release_date': None,
                'acquisition': csumb_acq(src),
                'read': bool(src.get('sha256') or src.get('archive_sha256')),
                'pixels_0_300ft': px,
                'extent_km2': px * res * res / 1e6 if px and res else None,
                'depth_max_m': src.get('depth_max_m'),
                'crosses_sector_line': len(touching) > 1,
                'catalog': rel,
                'sector_basis': basis,
            }
            csumb_by_sector[sid].append(e)
            evidence[sid].append(e)

    # 2. Central seafloor ledger reaches, placed by their EPSG:3310 bounds (catalog/reaches.json).
    reach_geo = {r['id']: r for r in data['reaches']['reaches']}
    ledger_reaches = defaultdict(list)
    ledger_ctx = defaultdict(lambda: {'band': 0.0, 'tier1': 0.0, 'selected': 0.0, 'tier2': 0.0, 'reaches': 0,
                                      'assessed': 0, 'unassessed': 0, 'held': 0, 'habitat_polygons': 0,
                                      'surveys': set(), 'crossing': []})
    for r in data['ledger']['reaches']:
        bb = bbox_3310_to_wgs84(reach_geo[r['id']]['bounds_3310'])
        sid, touching = sector_of_bbox(bb, bounds)
        if sid is None:
            continue
        used = r.get('surveys_used', [])
        res_list = [float(survey_cat[x]['resolution_m']) for x in used
                    if x in survey_cat and isinstance(survey_cat[x].get('resolution_m'), (int, float))]
        crosses = len(touching) > 1
        ledger_reaches[sid].append({'id': r['id'], 'band_km2': r['band_km2'], 'selected_km2': r.get('selected_valid_km2') or 0.0,
                                    'resolutions_m': res_list, 'crosses': crosses, 'touching': touching})
        c = ledger_ctx[sid]
        c['band'] += r['band_km2']
        c['tier1'] += r['tier1_km2']
        c['tier2'] += r.get('tier2_km2') or 0.0
        c['selected'] += r.get('selected_valid_km2') or 0.0
        c['reaches'] += 1
        c['assessed'] += r['status'] == 'habitat-screened'
        c['held'] += r['status'] == 'habitat-held-for-screen'
        c['unassessed'] += r['status'] == 'unassessed'
        c['habitat_polygons'] += r.get('habitat_count') or 0
        c['surveys'].update(used)
        if crosses:
            c['crossing'].append(r['id'])
        if (r.get('selected_valid_km2') or 0) > 0:
            for x in used:
                sv = survey_cat.get(x, {})
                res = sv.get('resolution_m') if isinstance(sv.get('resolution_m'), (int, float)) else None
                evidence[sid].append({
                    'family': 'Seafloor ledger', 'id': x, 'name': sv.get('title') or x,
                    'resolution_m': float(res) if res else None, 'depth': 'confirmed',
                    'release_date': pubdate.get(sv.get('url')),
                    'acquisition': sv.get('year') if isinstance(sv.get('year'), int) else None,
                    'read': True, 'crosses_sector_line': crosses, 'reach': r['id'],
                    'catalog': INPUTS['ledger'], 'sector_basis': 'reach bounds centre in the sector box'})

    # 3. USGS DS 781 / DOI original bathymetry grids opened in the depth-datum ledger. Their 0-300 ft
    # pixels are not recorded, so they are depth-unrecorded evidence unless the seafloor ledger used them.
    ledger_urls = {survey_cat[x].get('url') for c in ledger_ctx.values() for x in c['surveys'] if x in survey_cat}
    usgs_by_sector = defaultdict(list)
    usgs_sources = data['usgs_bathy']['sources']
    seen_usgs = set()
    for sec in data['usgs_bathy']['sectors']:
        for idx in sec['intersecting_source_indices']:
            if idx in seen_usgs:
                continue
            src = usgs_sources[idx]
            sid, touching = sector_of_bbox(src['raster_bounds_wgs84'], bounds)
            if sid is None:
                continue
            seen_usgs.add(idx)
            res = float(src['native_resolution_m'][0])
            e = {
                'family': 'USGS DS781', 'name': usgs_name(src['title'], res), 'id': src['id'],
                'resolution_m': res, 'depth': 'unrecorded',
                'release_date': pubdate.get(src['archive_url']), 'acquisition': None, 'read': True,
                'valid_area_all_depths_km2': src['valid_native_pixels'] * res * float(src['native_resolution_m'][1]) / 1e6,
                'in_seafloor_ledger': src['archive_url'] in ledger_urls,
                'crosses_sector_line': len(touching) > 1,
                'catalog': INPUTS['usgs_bathy'], 'sector_basis': 'raster bbox centre in the sector box',
            }
            usgs_by_sector[sid].append(e)
            evidence[sid].append(e)
    usgs_unavailable = data['usgs_bathy'].get('unavailable_original_grids', [])

    # 4. NOAA original regular BAGs (<=4 m), with per-sector 25-200 ft depth/uncertainty-eligible cells.
    noaa_reg = defaultdict(list)
    for f in data['noaa_regular']['files']:
        if f.get('status') != 'ok':
            continue
        res = f['native_resolution_m']
        for sid, c in (f.get('sectors') or {}).items():
            elig = c['depth_uncertainty_eligible_cells']
            e = {
                'family': 'NOAA BAG', 'name': f"NOAA {f['survey_id']} {rnd(res[0], 1):g} m BAG",
                'id': f['bag_url'].rsplit('/', 1)[-1], 'survey_id': f['survey_id'],
                'resolution_m': float(res[0]),
                'depth': 'confirmed' if elig > 0 else 'unrecorded',
                'release_date': None, 'acquisition': year_span(f.get('survey_dates') or []), 'read': True,
                'measured_cells': c['measured_native_cells'], 'eligible_25_200ft_cells': elig,
                'extent_km2': elig * res[0] * res[1] / 1e6,
                'crosses_sector_line': False, 'catalog': INPUTS['noaa_regular'],
                'sector_basis': 'per-sector cell counts in the review',
            }
            noaa_reg[sid].append(e)
            evidence[sid].append(e)

    # 5. NOAA variable-resolution BAGs: per-sector eligible cells, refinement spacing only "1-4 m".
    noaa_vr = {s['sector_id']: s for s in data['noaa_vr']['sectors']}
    for f in data['noaa_vr']['files']:
        for sid, c in (f.get('sectors') or {}).items():
            if c.get('depth_uncertainty_eligible_cells', 0) > 0:
                evidence[sid].append({
                    'family': 'NOAA VR BAG', 'name': f"NOAA {f['survey_id']} VR BAG (1-4 m refinements)",
                    'id': f['bag_url'].rsplit('/', 1)[-1], 'resolution_m': None, 'resolution_range_m': VR_RANGE_M,
                    'depth': 'confirmed', 'release_date': None, 'acquisition': year_span(f.get('survey_dates') or []),
                    'read': True, 'eligible_25_200ft_cells': c['depth_uncertainty_eligible_cells'],
                    'crosses_sector_line': False, 'catalog': INPUTS['noaa_vr'],
                    'sector_basis': 'per-sector cell counts in the review'})

    # 6. Habitat: USGS character rasters, display hard-context outlines, CDFW ds3091 patches.
    char = {s['sector_id']: s for s in data['usgs_char']['sectors']}
    char_products = data['usgs_char']['products']

    def count_features(pattern):
        out = defaultdict(int)
        for rel in sorted(glob.glob(pattern, root_dir=ROOT)):
            for feat in load(rel)['features']:
                lon, lat = polygon_centroid(feat['geometry'])
                for sid in ids:
                    if in_bounds(lon, lat, bounds[sid]):
                        out[sid] += 1
                        break
        return out
    ds3091 = count_features(DS3091_GLOB)
    usgs_hard = count_features(USGS_HARD_GLOB)

    # 7. Fishing/dive use proxy: home ports whose match point lies in the sector box.
    ports = defaultdict(list)
    for p in data['ports']['ports']:
        lat, lon = p['match']
        for sid in ids:
            if in_bounds(lon, lat, bounds[sid]):
                ports[sid].append(p['name'])
                break

    bluetopo = {t['tile']: t for t in data['bluetopo']['tiles']}
    bt_tile = data['bluetopo']['sector_tile_ids']
    em300, caldig, gebco = data['em300'], data['caldig'], data['gebco']

    out_rows = []
    for order, s in enumerate(sectors, 1):
        sid = s['id']
        rd = readiness[sid]
        row = {'order': order, 'id': sid, 'name': s['name'], 'coast': s['coast'],
               'latitude': [round(x, 4) for x in s['latitude']]}
        ev = evidence[sid]
        cls = classify_shallow(ev)
        tier = cls['tier']
        row['shallow_0_300ft'] = shallow_block(sid, cls, ev, ledger_reaches[sid], ledger_ctx.get(sid))
        row['deeper_than_300ft'] = deep_block(sid, csumb_by_sector[sid], em300, caldig, gebco,
                                              bluetopo.get(bt_tile.get(sid)))

        # --- review status ---
        n_reg = len({e['id'] for e in noaa_reg.get(sid, [])})
        n_vr = noaa_vr.get(sid, {}).get('source_files_with_eligible_cells', 0)
        n_cs = len(csumb_by_sector[sid])
        n_usgs = len(usgs_by_sector[sid])
        read_total = n_reg + n_vr + n_cs + n_usgs
        ctx = ledger_ctx.get(sid)
        if ctx and ctx['tier1'] > 0:
            status = 'ledger-assessed'
        elif read_total:
            status = 'partly-reviewed'
        else:
            status = 'catalogued-only'
        unread = []
        if rd['original_bag_bbox_leads'] > n_reg + n_vr:
            unread.append(f'{rd["original_bag_bbox_leads"]} NOAA BAG bbox leads vs {n_reg + n_vr} BAG files read '
                          'with cells in the sector (bounded <=100 MB audit)')
        ds_links = sum(m['bathymetry_product_links'] for m in rd['usgs_ds781_map_area_leads'])
        if ds_links > n_usgs:
            unread.append(f'{ds_links} USGS DS781 bathymetry product links vs {n_usgs} opened grids assigned here')
        unrec = [e for e in usgs_by_sector[sid] if not e['in_seafloor_ledger']]
        if unrec:
            unread.append(f'{len(unrec)} opened USGS DS781 grid(s) without a recorded 0-300 ft pixel count')
        for u in usgs_unavailable:
            if 'pointconception' in u['archive_url'].lower() and sid == 'conception-ventura':
                unread.append('USGS Offshore Point Conception bathymetry archive exceeded the download bound')
        if ctx and ctx['unassessed']:
            unread.append(f'{ctx["unassessed"]} of {ctx["reaches"]} seafloor-ledger reaches unassessed (no native source attached)')
        if ctx and ctx['held']:
            unread.append(f'{ctx["held"]} seafloor-ledger reaches held for the spatial screen')
        n_ledger = len(ctx['surveys']) if ctx else 0
        files_basis = (f'CSUMB grids {n_cs}, USGS DS781 grids {n_usgs} (bbox-centre assignment), NOAA regular BAGs '
                       f'{n_reg}, NOAA VR BAGs {n_vr}')
        if n_ledger:
            files_basis += (f'; seafloor-ledger surveys used {n_ledger}. Value is the larger of the two counts because '
                            'the catalogs use different ids for the same file')
        row['review'] = {
            'status': status,
            'native_files_read': fig(max(read_total, n_ledger), 'ESTIMATED' if n_ledger else 'MEASURED', files_basis),
            'catalogued_noaa_bag_leads': fig(rd['original_bag_bbox_leads'], 'MEASURED', INPUTS['readiness']),
            'unread_or_open_items': unread,
        }

        # --- habitat ---
        ch = char.get(sid, {})
        prods = [p for p in char_products if sid in (p.get('planning_sector_ids') or [])]
        hab = {
            'usgs_csumb_classes': {
                'usgs_character_archives_catalogued': fig(ch.get('catalog_archive_leads', 0), 'MEASURED', INPUTS['usgs_char']),
                'usgs_character_rasters_opened': fig(ch.get('opened_native_rasters', 0), 'MEASURED', INPUTS['usgs_char']),
                'usgs_class_tables_verified': fig(ch.get('verified_original_class_tables', 0), 'MEASURED', INPUTS['usgs_char']),
                'usgs_hard_context_outlines': fig(usgs_hard[sid], 'MEASURED',
                                                  'class-3 display outlines in dist/data/usgs-hard-context-*.geojson whose centroid '
                                                  'lies in the sector bounds (assignment ESTIMATED)'),
                'csumb_terrain_habitat': None,
            },
            'cdfw_ds3091': {
                'status': 'decoded (40 m predicted hard/soft, rugosity proxy); docs/california-seabed-coverage.md records all 2,870 '
                          'tiles intersecting the 19 sectors decoded with zero failures',
                'predicted_hard_patches': fig(ds3091[sid], 'MEASURED',
                                              'patches in dist/data/cdfw-predicted-hard-*.geojson whose centroid lies in the '
                                              'sector bounds (assignment ESTIMATED; bands may include offshore islands)'),
            },
        }
        if ctx:
            hab['usgs_csumb_classes']['csumb_terrain_habitat'] = {
                'ledger_reaches_habitat_screened': fig(ctx['assessed'], 'MEASURED', INPUTS['ledger']),
                'ledger_reaches_total': fig(ctx['reaches'], 'MEASURED', INPUTS['ledger']),
                'graded_physical_habitat_polygons': fig(ctx['habitat_polygons'], 'MEASURED', INPUTS['ledger']),
                'screened_habitat_km2': fig(round(ctx['tier2'], 1), 'MEASURED', 'tier-2 km2 in the seafloor ledger'),
            }
        if hab['usgs_csumb_classes']['usgs_character_rasters_opened']['value'] or (ctx and ctx['habitat_polygons']):
            hab['summary'] = 'native classes read' + (' (USGS character)' if ch.get('opened_native_rasters') else '') + \
                (' + CSUMB/ledger terrain habitat' if ctx and ctx['habitat_polygons'] else '') + '; CDFW ds3091 context'
        elif prods:
            hab['summary'] = 'USGS character catalogued, not opened; CDFW ds3091 context only'
        else:
            hab['summary'] = 'no USGS/CSUMB class raster read; CDFW ds3091 predicted context only'
        row['habitat'] = hab
        row['use_proxy'] = {'home_ports': fig(len(ports[sid]), 'MEASURED', 'dist/data/home-ports.json match points in sector bounds'),
                            'home_port_names': ports[sid],
                            'published_candidate_points': fig(rd['published_candidate_points_in_band'], 'MEASURED', INPUTS['readiness'])}
        row['next_source_step'] = rd.get('next_source_step')
        out_rows.append(row)

    gap_list = rank_gaps(out_rows)
    summary = summarize(out_rows)
    summary['statewide_survey_catalog'] = statewide_surveys
    return {
        'schema_version': 2,
        'id': 'coast-seafloor-inventory',
        'task': 'COAST-INVENTORY-1',
        'scope': 'California outer-coast browse sectors (catalog/coastal-sectors.json), north to south. Bays and offshore '
                 'islands need their own packages and are not inventoried here.',
        'generator': 'research/scripts/inventory_coast_seafloor.py',
        'labels': {
            'MEASURED': 'copied or summed from pixel/cell counts already recorded in a repo catalog for exactly the quantity named',
            'ESTIMATED': 'derived with a stated assumption (sector assignment by bounding box, 0-100 m band standing in for '
                         '0-300 ft, reach-level rather than grid-level footprints)',
            'UNKNOWN': 'no catalog figure exists in the repo; not filled by guessing',
        },
        'tiers': {
            '2 m': 'native grid spacing <= 2 m', '5 m': '> 2 m and <= 5 m (also NOAA VR BAG refinements, recorded only as 1-4 m)',
            '10 m': '> 5 m and <= 10 m', 'coarser': '> 10 m or compilation only', 'none': 'no grid with confirmed 0-300 ft cells',
        },
        'definitions': {
            'best_tier': 'finest tier among grids with CONFIRMED shallow cells in the sector: CSUMB nominal_0_300ft_pixels > 0, '
                         'NOAA BAG 25-200 ft eligible cells > 0, or a seafloor-ledger reach with a selected native footprint '
                         'in the 0-100 m band. No minimum area. Grids whose depth band is not recorded (most opened USGS DS781 '
                         'rasters) do not set the tier; they are listed as finer_grids_depth_unrecorded.',
            'tier_uncertain': 'true when the tier rests on NOAA VR BAG cells whose spacing is recorded only as 1-4 m, so the '
                              'true class may be 2 m',
            'coverage_pct_at_best_tier': 'ESTIMATED reach-level range from the seafloor ledger (low = reaches using only grids at '
                                         'the tier or finer; high = reaches using any such grid) over the provisional '
                                         'BlueTopo 0-100 m band of reaches wholly inside the sector; UNKNOWN elsewhere',
            'release_date': 'publication/release date of the grid; acquisition_dates is a separate field',
        },
        'limits': [
            'Grid spacing is not sounding accuracy; no source here is qualified as an MLLW fishing depth.',
            'No repo catalog records a 0-300 ft reference area outside the seafloor ledger (Pigeon Point to Point Conception), '
            'and the ledger band is 0-100 m (about 0-328 ft), so every coverage share is ESTIMATED or UNKNOWN, never MEASURED.',
            'The seafloor ledger records one selected native footprint per reach, not per grid, so coverage at a given resolution '
            'is a low-high range.',
            'NOAA counts come from bounded audits (files <= 100 MB); larger or failed files are open items, not zeros.',
            'Extent figures are per evidence family and are never summed across families; overlapping surveys within a '
            'family are not deduplicated.',
            'This inventory changes no map layer, target, score or export.',
        ],
        'inputs': [{'path': p, 'sha256': sha256(p)} for p in input_files],
        'summary': summary,
        'sectors': out_rows,
        'gap_list': gap_list,
    }


def shallow_block(sid, cls, ev, reaches, ctx):
    tier = cls['tier']
    ts = cls['tier_sources']
    # Best source: preferred family among confirmed sources of the best tier.
    best_source = None
    for fam in ('Seafloor ledger', 'CSUMB', 'NOAA BAG', 'NOAA VR BAG'):
        ents = [e for e in ts if e['family'] == fam]
        if not ents:
            continue
        uniq = {e['id']: e for e in ents}.values()
        uniq = sorted(uniq, key=lambda e: (e.get('resolution_m') or 9, e['name']))
        names = list(dict.fromkeys(e['name'] for e in uniq))
        if fam == 'Seafloor ledger':
            fams = defaultdict(int)
            for e in uniq:
                i = e['id']
                fams['NOAA BAG' if i.startswith('h1') else 'USGS DS781' if i.startswith('bathymetry-') else
                     'USGS 1998' if i.startswith('usgs-') else 'CSUMB/CSMP'] += 1
            label = (f'Seafloor-ledger native grids at {tier} or finer: '
                     + ', '.join(f'{k} {v}' for k, v in sorted(fams.items())))
        else:
            label = '; '.join(names[:4]) + (f' (+{len(names) - 4} more)' if len(names) > 4 else '')
        release, acq = date_figs(
            list(uniq),
            'CSUMB and NOAA catalogs record acquisition/survey dates only' if fam != 'Seafloor ledger'
            else 'catalog/surveys.json records acquisition years only; DS781 publication dates joined by archive URL',
            {'Seafloor ledger': 'acquisition year in catalog/surveys.json', 'CSUMB': 'acquisition_dates in the CSUMB catalog',
             'NOAA BAG': 'survey_dates in ' + INPUTS['noaa_regular'],
             'NOAA VR BAG': 'survey_dates in ' + INPUTS['noaa_vr']}[fam])
        best_source = {'name': label, 'family': fam, 'grids': len(uniq), 'grid_ids': sorted(e['id'] for e in uniq),
                       'release_date': release, 'acquisition_dates': acq}
        break

    # Coverage at the best tier: ledger reach-level range only.
    proxy = ledger_tier_proxy(reaches, TIER_RES[tier]) if reaches and tier in TIER_RES else None
    if proxy and proxy['high_km2'] > 0:
        lo, hi = round(proxy['low_pct']), round(proxy['high_pct'])
        coverage = fig({'low': lo, 'high': hi}, 'ESTIMATED',
                       f'seafloor-ledger selected native footprint in {proxy["reaches_used"]} reach(es) wholly inside the sector: '
                       f'{proxy["low_km2"]:.1f} km2 from reaches using only grids <= {TIER_RES[tier]:g} m, '
                       f'{proxy["high_km2"]:.1f} km2 from reaches using any such grid, over the provisional BlueTopo 0-100 m '
                       f'band {proxy["band_km2"]:.1f} km2 (0-100 m is about 0-328 ft, not 0-300 ft)'
                       + (f'; {proxy["reaches_crossing"]} reach(es) crossing a sector line left out '
                          f'({proxy["excluded_crossing_band_km2"]:.1f} km2 of band)' if proxy['reaches_crossing'] else ''))
    elif reaches and tier in TIER_RES:
        coverage = fig(None, 'UNKNOWN', 'every seafloor-ledger reach placed in this sector crosses a sector line or has no '
                       f'selected footprint at {tier}; no compatible reference area')
    else:
        coverage = fig(None, 'UNKNOWN', 'no 0-300 ft reference area for this sector exists in the repo (the seafloor ledger '
                       'covers only Pigeon Point to Point Conception); pixel counts cannot be turned into a share')

    ledger_context = None
    if ctx and ctx['band'] > 0:
        ledger_context = {
            'all_resolution_footprint_pct_of_0_100m_band': fig(
                round(100.0 * ctx['selected'] / ctx['band']), 'ESTIMATED',
                f'selected native footprint of ALL resolutions {ctx["selected"]:.1f} km2 / provisional BlueTopo 0-100 m band '
                f'{ctx["band"]:.1f} km2 for the {ctx["reaches"]} reach(es) whose bounds centre is in the sector box '
                f'({len(ctx["crossing"])} of them cross a sector line); context only, not coverage at the best tier'),
            'tier1_cell_pct_of_0_100m_band': fig(round(100.0 * ctx['tier1'] / ctx['band']), 'ESTIMATED',
                                                 'tier-1 250 m cells at least 25% covered by one usable original source, same reaches'),
            'reaches_crossing_sector_line': ctx['crossing'],
        }

    conf = [e for e in ev if e['depth'] == 'confirmed']

    def ext(fam, pred, basis):
        items = {e['id']: e for e in conf if e['family'] == fam and pred(e) and e.get('extent_km2')}.values()
        if not items:
            return None
        total = sum(e['extent_km2'] for e in items)
        crossing = sum(1 for e in items if e.get('crosses_sector_line'))
        return fig(round(total, 1 if total >= 1 else 2), 'ESTIMATED' if crossing else 'MEASURED',
                   basis + (f'; {crossing} grid(s) cross a sector line and are counted whole in their centre sector'
                            if crossing else '') + '; overlaps within the family are not deduplicated')

    extent = {
        'csumb_2m_0_300ft_km2': ext('CSUMB', lambda e: e['resolution_m'] and e['resolution_m'] <= 2,
                                    'CSUMB nominal_0_300ft_pixels x cell area, grids <= 2 m centred in the sector'),
        'csumb_5m_0_300ft_km2': ext('CSUMB', lambda e: e['resolution_m'] and 2 < e['resolution_m'] <= 5,
                                    'CSUMB nominal_0_300ft_pixels x cell area, grids > 2 m and <= 5 m centred in the sector'),
        'noaa_bag_2m_25_200ft_km2': ext('NOAA BAG', lambda e: e['resolution_m'] <= 2,
                                        'NOAA regular BAG 25-200 ft depth/uncertainty-eligible cells x cell area, grids <= 2 m '
                                        '(a lower bound for 0-300 ft)'),
        'noaa_bag_5m_25_200ft_km2': ext('NOAA BAG', lambda e: 2 < e['resolution_m'] <= 5,
                                        'same, regular BAGs > 2 m and <= 4 m'),
        'ledger_tier_footprint_km2': (fig({'low': round(proxy['low_km2'], 1), 'high': round(proxy['high_km2'], 1)}, 'ESTIMATED',
                                          f'seafloor-ledger reach footprints at <= {TIER_RES[tier]:g} m (0-100 m band, reaches '
                                          'wholly inside the sector)') if proxy and proxy['high_km2'] > 0 else None),
        'noaa_vr_25_200ft_cells': (fig(sum(e['eligible_25_200ft_cells'] for e in conf if e['family'] == 'NOAA VR BAG'),
                                       'MEASURED', 'NOAA VR BAG 25-200 ft eligible refinement cells; area UNKNOWN because '
                                       'cell spacing is recorded only as 1-4 m')
                                   if any(e['family'] == 'NOAA VR BAG' for e in conf) else None),
    }
    extent = {k: v for k, v in extent.items() if v is not None}

    unrec = cls['finer_grids_depth_unrecorded']
    usgs_open = [e for e in ev if e['family'] == 'USGS DS781']
    finest_any = cls['finest_any_depth_m']
    tier_basis_fams = sorted({e['family'] for e in ts})
    return {
        'best_tier': tier,
        'best_tier_label': 'ESTIMATED',
        'best_tier_basis': ('finest tier with confirmed shallow cells; no area threshold; evidence: '
                            + (', '.join(tier_basis_fams) if tier_basis_fams else 'none')
                            + ('; sector assignment by bounding box' if any(e.get('crosses_sector_line') for e in ts) else '')),
        'tier_uncertain': cls['tier_uncertain'],
        'best_confirmed_resolution_m': (fig(rnd(cls['best_confirmed_resolution_m'], 2), 'MEASURED',
                                            'finest native spacing among confirmed-shallow grids of the best tier')
                                        if cls['best_confirmed_resolution_m'] else
                                        fig(None, 'UNKNOWN', 'best tier rests on NOAA VR BAG refinements recorded only as 1-4 m'
                                            if cls['tier_uncertain'] or tier == '5 m' else 'no confirmed-shallow grid')),
        'finest_grid_any_depth_m': (fig(rnd(finest_any, 2), 'MEASURED', 'finest native spacing of any catalogued or opened grid '
                                        'placed in the sector, whatever its depth band (VR BAGs counted at their 1 m lower end)')
                                    if finest_any else fig(None, 'UNKNOWN', 'no native grid placed in the sector')),
        'finer_grids_depth_unrecorded': [
            {'name': e['name'], 'family': e['family'], 'resolution_m': e['resolution_m'],
             'valid_area_all_depths_km2': fig(round(e['valid_area_all_depths_km2'], 1), 'MEASURED' if not e['crosses_sector_line']
                                              else 'ESTIMATED', 'valid pixels x cell area over the WHOLE raster, all depths; '
                                              'not a shallow area') if e.get('valid_area_all_depths_km2') else None}
            for e in sorted(unrec, key=lambda e: e['name'])],
        'best_source': best_source,
        'coverage_pct_at_best_tier': coverage,
        'extent_confirmed_shallow': extent,
        'seafloor_ledger_context': ledger_context,
        'usgs_ds781_grids_opened': fig(len(usgs_open), 'ESTIMATED',
                                       'DS781 rasters opened in dist/data/usgs-depth-datum-ledger.json whose bbox centre lies in '
                                       'this sector box; 0-300 ft pixels not recorded') if usgs_open else None,
        'sources': [{k: v for k, v in e.items() if k in ('family', 'name', 'resolution_m', 'resolution_range_m', 'depth',
                                                          'release_date', 'acquisition', 'pixels_0_300ft',
                                                          'eligible_25_200ft_cells', 'crosses_sector_line')}
                    for e in sorted({(e['family'], e['id']): e for e in ev}.values(),
                                    key=lambda e: (e.get('resolution_m') or (e.get('resolution_range_m') or (99,))[0],
                                                   e['name']))][:15],
        'source_count': len({(e['family'], e['id']) for e in ev}),
    }


def deep_block(sid, csumb, em300, caldig, gebco, tile):
    deep = []
    for e in csumb:
        if e.get('depth_max_m') and e['depth_max_m'] > FT_300_M:
            deep.append({'name': e['name'], 'resolution_m': e['resolution_m'], 'acquisition': e['acquisition'],
                         'basis': f'depth_max_m {e["depth_max_m"]:.0f} in {e["catalog"]}', 'label': 'MEASURED'})
    if sid in em300['sector_ids']:
        deep.append({'name': em300['name'], 'resolution_m': float(em300['spatial']['resolution_m']), 'acquisition': '1998',
                     'basis': 'catalog/candidates/usgs-monterey-1998-em300-original.json (canyon/shelf survey; '
                              'depth band not tabulated)', 'label': 'ESTIMATED'})
    if sid in caldig['sector_ids']:
        deep.append({'name': caldig['name'], 'resolution_m': float(caldig['spatial']['resolution_m']), 'acquisition': None,
                     'basis': 'catalog/candidates/usgs-caldig-v2.json (offshore deep-water release; mapping held '
                              'in research/receipts/coast-c1-m2-held.json)', 'label': 'ESTIMATED'})
    if sid == 'big-sur':
        deep.append({'name': 'CSUMB BSS_Block13 5 m native grid', 'resolution_m': 5.0, 'acquisition': '2011',
                     'basis': 'catalog/csumb-bss-native-sources.json: no valid cell shallower than 78.32 m NAVD88; '
                              'deeper extent not tabulated', 'label': 'ESTIMATED'})
    deep.sort(key=lambda d: d['resolution_m'])
    if deep:
        d0 = deep[0]
        block = {'best_tier': tier_of(d0['resolution_m']),
                 'best_resolution_m': fig(d0['resolution_m'], d0['label'], d0['basis']),
                 'best_source': d0['name'], 'sources': deep}
    else:
        block = {
            'best_tier': 'coarser',
            'best_resolution_m': fig(float(gebco['spatial']['resolution_m']), 'MEASURED',
                                     'GEBCO_2026 grid spacing from catalog/candidates/gebco-2026-grid.json; no native grid '
                                     'with a recorded depth beyond 300 ft is catalogued for this sector (NOAA BAG reviews '
                                     'tabulate only 25-200 ft cells, so finer deep cells in read BAGs are UNKNOWN)'),
            'best_source': f'Statewide fallback only: {gebco["name"]} ({float(gebco["spatial"]["resolution_m"]):.0f} m)',
            'sources': []}
    if tile:
        block['compilation_context'] = (
            f'NOAA BlueTopo tile {tile["tile"]} at {tile["resolution_m"][0]:g} m (compilation; one sampled tile, '
            f'{tile["counts"]["measured_contributor_pixels"]:,} measured-contributor pixels; not a native survey grid)')
    return block


def rank_gaps(rows):
    gaps = []
    for r in rows:
        sh = r['shallow_0_300ft']
        cov = sh['coverage_pct_at_best_tier']
        tier = sh['best_tier']
        ext2 = sum((sh['extent_confirmed_shallow'].get(k) or {}).get('value') or 0
                   for k in ('csumb_2m_0_300ft_km2', 'noaa_bag_2m_25_200ft_km2'))
        unrec = [g for g in sh['finer_grids_depth_unrecorded'] if g['resolution_m'] and g['resolution_m'] <= 2]
        unrec_note = f'; {len(unrec)} opened 2 m grid(s) with unrecorded depth band' if unrec else ''
        if tier != '2 m':
            severity = 3
            why = f'no confirmed 2 m shallow grid (best confirmed {tier}{", true class may be 2 m" if sh["tier_uncertain"] else ""})' + unrec_note
        elif cov['label'] == 'UNKNOWN':
            severity = 2
            why = ('2 m confirmed in part of the sector; coverage UNKNOWN; confirmed 2 m extent '
                   f'{ext2:.{1 if ext2 >= 1 else 2}f} km2 (CSUMB + NOAA BAG, not deduplicated)') + unrec_note
        elif cov['value']['low'] < 60:
            severity = 2
            why = f'2 m coverage {cov["value"]["low"]}-{cov["value"]["high"]}% of the 0-100 m reference band (E)'
        elif cov['value']['low'] < 90:
            severity = 1
            why = f'2 m coverage {cov["value"]["low"]}-{cov["value"]["high"]}% of the 0-100 m reference band (E)'
        else:
            continue
        cands, action = candidates_for(r)
        gaps.append({'sector_id': r['id'], 'name': r['name'], 'severity': severity, 'why': why,
                     'home_ports': r['use_proxy']['home_ports']['value'], 'home_port_names': r['use_proxy']['home_port_names'],
                     'confirmed_2m_extent_km2': round(ext2, 1 if ext2 >= 1 else 2), 'candidate_sources': cands, 'action': action})
    # Severity, then use proxy (home ports), then smaller confirmed 2 m extent, then north to south.
    order = {r['id']: r['order'] for r in rows}
    gaps.sort(key=lambda g: (-g['severity'], -g['home_ports'], g['confirmed_2m_extent_km2'], order[g['sector_id']]))
    for i, g in enumerate(gaps, 1):
        g['rank'] = i
        g['rank_label'] = 'ESTIMATED'
    return gaps


def candidates_for(r):
    sid, coast = r['id'], r['coast']
    sh = r['shallow_0_300ft']
    unrec = any(g['resolution_m'] and g['resolution_m'] <= 2 for g in sh['finer_grids_depth_unrecorded'])
    pre = ('measure first: count 0-300 ft pixels in the already-opened DS781 2 m grids (no download); ' if unrec else '')
    if coast == 'central':
        if sid == 'pigeon-monterey':
            c = ['ds781', 'lidar', 'csmp']
            action = pre + ('download: attach the catalogued USGS Offshore Santa Cruz, Scott Creek, Pigeon Point and Aptos 2 m '
                            'grids to the unassessed ledger reaches r01-r10, then rerun the ledger')
        else:
            c = ['csmp', 'noaa', 'opc']
            action = pre + ('download: read remaining catalogued CSUMB/NOAA grids into the ledger; request CSUMB/OPC for any '
                            'block missing from NCEI; survey only where no block exists')
    elif sh['best_tier'] != '2 m':
        c = ['csmp', 'ds781', 'noaa', 'lidar', 'opc']
        action = pre + ('request: ask CSUMB Seafloor Mapping Lab / OPC whether CSMP state-waters 2 m grids exist for this '
                        'reach; download any NOAA BAG >100 MB not yet read; survey if neither exists')
    else:
        c = ['ds781', 'noaa', 'csmp']
        action = pre + ('download: open the catalogued but unread DS781 bathymetry and NOAA BAG files, then build a 0-300 ft '
                        'reference area (extend the seafloor ledger) so coverage can be estimated')
    return [{'family': k, 'name': CANDIDATE_FAMILIES[k][0], 'evidence': CANDIDATE_FAMILIES[k][1]} for k in c], action


def summarize(rows):
    tiers = {t: [r['id'] for r in rows if r['shallow_0_300ft']['best_tier'] == t] for t in TIER_ORDER}
    any_depth = {t: [r['id'] for r in rows if tier_of(r['shallow_0_300ft']['finest_grid_any_depth_m']['value']) == t]
                 for t in TIER_ORDER}
    deep = {t: [r['id'] for r in rows if r['deeper_than_300ft']['best_tier'] == t] for t in TIER_ORDER}
    status = defaultdict(list)
    for r in rows:
        status[r['review']['status']].append(r['id'])
    est_cov = [r for r in rows if r['shallow_0_300ft']['coverage_pct_at_best_tier']['label'] == 'ESTIMATED']
    return {
        'sector_count': fig(len(rows), 'MEASURED', 'catalog/coastal-sectors.json'),
        'shallow_tier_counts': {t: fig(len(v), 'ESTIMATED', f'sectors whose best confirmed-shallow tier is {t} (no area '
                                       'threshold; sector assignment by bounding box)') for t, v in tiers.items()},
        'shallow_tier_sectors': tiers,
        'tier_uncertain_sectors': [r['id'] for r in rows if r['shallow_0_300ft']['tier_uncertain']],
        'finest_grid_any_depth_counts': {t: fig(len(v), 'ESTIMATED', 'sectors by finest catalogued/opened grid at any depth')
                                         for t, v in any_depth.items()},
        'deep_tier_counts': {t: fig(len(v), 'ESTIMATED', 'count of sectors by best deeper-than-300 ft tier; several deep '
                                    'sources have no tabulated depth band') for t, v in deep.items()},
        'review_status_counts': {k: fig(len(v), 'MEASURED', 'review.status per sector') for k, v in sorted(status.items())},
        'review_status_sectors': dict(sorted(status.items())),
        'coverage_estimated_sectors': fig(len(est_cov), 'MEASURED', 'sectors with an ESTIMATED ledger coverage range'),
        'coverage_measured_sectors': fig(0, 'MEASURED', 'no sector has a measured 0-300 ft reference area in the repo'),
        'fully_reviewed_sectors': fig(0, 'MEASURED', 'every sector still lists unread catalogued leads or unassessed reaches '
                                      'in review.unread_or_open_items'),
    }


# ---------------------------------------------------------------- markdown

def fmt(f, suffix=''):
    if f is None:
        return '-'
    if f['label'] == 'UNKNOWN':
        return 'UNKNOWN'
    v = f['value']
    if isinstance(v, dict) and 'low' in v:
        v = f'{v["low"]:g}' if v['low'] == v['high'] else f'{v["low"]:g}-{v["high"]:g}'
    elif isinstance(v, float):
        v = f'{v:g}'
    elif isinstance(v, int):
        v = f'{v:,}'
    return f'{v}{suffix} ({f["label"][0]})'


def tier_text(sh):
    return sh['best_tier'] + (' (VR 1-4 m; may be 2 m)' if sh['tier_uncertain'] else '')


def render_md(inv):
    s = inv['summary']
    rows = inv['sectors']
    L = []
    t = s['shallow_tier_counts']
    a = s['finest_grid_any_depth_counts']
    st = s['review_status_counts']
    sw = s['statewide_survey_catalog']
    unc = s['tier_uncertain_sectors']
    names = {r['id']: r['name'] for r in rows}

    def n(k):
        return st.get(k, {'value': 0})['value']

    unknown_ext = []
    for r in rows:
        sh = r['shallow_0_300ft']
        if sh['coverage_pct_at_best_tier']['label'] != 'UNKNOWN':
            continue
        figs = [sh['extent_confirmed_shallow'][k] for k in ('csumb_2m_0_300ft_km2', 'noaa_bag_2m_25_200ft_km2')
                if k in sh['extent_confirmed_shallow']]
        total = sum(f['value'] for f in figs)
        unknown_ext.append((r['name'], round(total, 1 if total >= 1 else 2),
                            'E' if len(figs) > 1 or any(f['label'] == 'ESTIMATED' for f in figs) else 'M'))
    unknown_ext.sort(key=lambda x: x[1])
    L += ['# California coast seafloor inventory (COAST-INVENTORY-1)', '',
          f'Generated by `{inv["generator"]}` from repository catalogs only (no downloads). '
          'Machine-readable copy: `catalog/coast-seafloor-inventory.json`. Labels: **M** = MEASURED from catalog '
          'pixel/cell counts, **E** = ESTIMATED with a stated assumption, UNKNOWN = no catalog figure.', '',
          '## Summary for G', '',
          f'- **Is the inventory complete?** Yes for the list: all {s["sector_count"]["value"]} outer-coast sectors in '
          '`catalog/coastal-sectors.json` have a row (M). Bays and offshore islands are outside these sectors and are not covered.',
          f'- **Best shallow (0-300 ft) detail we can confirm, by sector (E):** 2 m: {t["2 m"]["value"]} · 5 m: {t["5 m"]["value"]} · '
          f'10 m: {t["10 m"]["value"]} · coarser: {t["coarser"]["value"]} · none: {t["none"]["value"]}. '
          '"Confirm" means a catalog records cells of that grid in shallow water in that sector; any amount counts. '
          + (f'For {", ".join(names[x] for x in unc)} the tier rests on NOAA grids recorded only as 1-4 m, so it may really be 2 m. '
             if unc else '')
          + 'A 2 m tier means 2 m grids exist for part of the sector, not that the whole sector is mapped at 2 m.',
          f'- **Counting every grid we hold, whatever its depth (E):** 2 m: {a["2 m"]["value"]} · 5 m: {a["5 m"]["value"]} · '
          f'10 m: {a["10 m"]["value"]} · coarser: {a["coarser"]["value"]} · none: {a["none"]["value"]}. '
          + ('The difference is opened grids (mostly USGS state-waters 2 m) whose shallow pixels were never counted.'
             if any(a[k]['value'] != t[k]['value'] for k in TIER_ORDER) else
             'Same counts as above: the opened USGS state-waters 2 m grids whose shallow pixels were never counted do not '
             'change any sector\'s tier.'),
          f'- **Has it all been reviewed? No.** {n("ledger-assessed")} sectors have native grids read **and** assessed reach by '
          f'reach in the seafloor ledger; {n("partly-reviewed")} have some native grids read but no reference area to say what '
          f'share they cover; {n("catalogued-only")} are catalogued only. Fully reviewed (every catalogued lead read): '
          f'{s["fully_reviewed_sectors"]["value"]} (M).',
          '- **How much of the shallow seabed is covered at the best tier (E, low-high):** ' + '; '.join(
              f'{r["name"]} {fmt(r["shallow_0_300ft"]["coverage_pct_at_best_tier"], "%")}' for r in rows
              if r['shallow_0_300ft']['coverage_pct_at_best_tier']['label'] == 'ESTIMATED') + '. '
          'Ranges, not exact figures: the ledger records one footprint per 10 km reach, not per grid, and its reference band is '
          '0-100 m (about 0-328 ft). No sector has a MEASURED 0-300 ft share.',
          '- **Elsewhere coverage is UNKNOWN**, not zero: the repo has no shallow reference area outside Pigeon Point to '
          'Point Conception, so pixel counts there cannot be turned into a percentage. What we can say is how much confirmed '
          '2 m shallow grid exists there (km2, lower bound from NOAA 25-200 ft cells, overlaps not removed): '
          + '; '.join(f'{nm} {v:g} ({lab})' for nm, v, lab in unknown_ext) + '.',
          f'- **Deeper than 300 ft:** best native tier by sector (E): ' + ' · '.join(
              f'{k}: {v["value"]}' for k, v in s['deep_tier_counts'].items()) +
          '. "Coarser" means only the statewide GEBCO grid (463 m) is catalogued for deep water there; BlueTopo compilation tiles exist '
          'for every sector but are not native surveys.',
          '- **Habitat classes:** CDFW ds3091 predicted hard/soft is decoded for all 19 sectors (context only). USGS/CSUMB '
          'native classes are read in ' + str(sum(1 for r in rows if r['habitat']['summary'].startswith('native classes read'))) +
          ' sectors (M).',
          '- **Release dates:** USGS state-waters releases carry publication dates; CSUMB and NOAA catalogs record only '
          'acquisition or survey dates, so their release dates are UNKNOWN and shown apart from acquisition dates.',
          f'- **Statewide source catalog (M):** `catalog/surveys.json` lists {sw["entries"]["value"]} survey files; '
          f'{sw["native_inspected"]["value"]} were opened at native resolution, {sw["catalog_or_metadata_only"]["value"]} are '
          f'catalogue or metadata only, {sw["usable_status"]["value"]} are marked usable. It has no sector field, so the '
          'per-sector counts below come from the sector review files.',
          f'- **Top gaps:** ' + '; '.join(f'{g["rank"]}. {g["name"]}' for g in inv['gap_list'][:5]) + ' (rank E).',
          '- Nothing here is a fishing target; grid spacing is not depth accuracy, and no source is yet MLLW-qualified.', '']

    L += ['## Sector table (north to south)', '',
          '| # | Sector | Best confirmed 0-300 ft | Finest grid, any depth | Best source | Release date | Acquired | '
          '% of shallow band at best tier | Deeper than 300 ft | Review status | Habitat classes |',
          '|---|---|---|---|---|---|---|---|---|---|---|']
    for r in rows:
        sh = r['shallow_0_300ft']
        bs = sh['best_source']
        dp = r['deeper_than_300ft']
        deep = f'{dp["best_tier"]}: {fmt(dp["best_resolution_m"], " m")}'
        if not dp['sources']:
            deep += ' GEBCO only; native UNKNOWN'
        rv = r['review']
        hab = r['habitat']
        best = f'{tier_text(sh)}, finest {fmt(sh["best_confirmed_resolution_m"], " m")}'
        L.append(f'| {r["order"]} | {r["name"]} | {best} | {fmt(sh["finest_grid_any_depth_m"], " m")} | '
                 f'{bs["name"] if bs else "-"} | {fmt(bs["release_date"]) if bs else "-"} | '
                 f'{fmt(bs["acquisition_dates"]) if bs else "-"} | {fmt(sh["coverage_pct_at_best_tier"], "%")} | {deep} | '
                 f'{rv["status"]}, {fmt(rv["native_files_read"])} files read | '
                 f'{hab["summary"]}; ds3091 patches {fmt(hab["cdfw_ds3091"]["predicted_hard_patches"])} |')
    L += ['', 'Status key: `ledger-assessed` = native grids read and assessed reach by reach against the seafloor ledger\'s '
          'provisional 0-100 m band (share ESTIMATED); `partly-reviewed` = some native grids read, share UNKNOWN; '
          '`catalogued-only` = leads listed, nothing read.', '']

    L += ['## Sector detail', '']
    for r in rows:
        sh, dp, rv, hab = r['shallow_0_300ft'], r['deeper_than_300ft'], r['review'], r['habitat']
        L.append(f'### {r["order"]}. {r["name"]} (`{r["id"]}`, lat {r["latitude"][0]}-{r["latitude"][1]})')
        L.append('')
        L.append(f'- 0-300 ft: best confirmed **{tier_text(sh)}** (E; {sh["best_tier_basis"]}); finest grid at any depth '
                 f'{fmt(sh["finest_grid_any_depth_m"], " m")}; {sh["source_count"]} grids placed in the sector.')
        bs = sh['best_source']
        if bs:
            L.append(f'  - Best source: {bs["name"]}; release date {fmt(bs["release_date"])} ({bs["release_date"]["basis"]}); '
                     f'acquired {fmt(bs["acquisition_dates"])} ({bs["acquisition_dates"]["basis"]}).')
        for g in sh['finer_grids_depth_unrecorded']:
            va = g['valid_area_all_depths_km2']
            L.append(f'  - Finer grid, depth band not recorded: {g["name"]}'
                     + (f' ({fmt(va, " km2")} valid area over the whole raster, all depths)' if va else '') + '.')
        for k, f in sh['extent_confirmed_shallow'].items():
            L.append(f'  - Extent `{k}`: {fmt(f)} - {f["basis"]}.')
        cov = sh['coverage_pct_at_best_tier']
        L.append(f'  - Coverage at best tier {fmt(cov, "%")}: {cov["basis"]}.')
        lc = sh['seafloor_ledger_context']
        if lc:
            L.append(f'  - Ledger context (all resolutions): footprint {fmt(lc["all_resolution_footprint_pct_of_0_100m_band"], "%")} '
                     f'of the 0-100 m band; tier-1 cells {fmt(lc["tier1_cell_pct_of_0_100m_band"], "%")}; '
                     f'{lc["all_resolution_footprint_pct_of_0_100m_band"]["basis"]}.')
        L.append(f'- Deeper than 300 ft: **{dp["best_tier"]}** - {dp["best_source"]}'
                 + (f'; {dp["compilation_context"]}' if dp.get('compilation_context') else '') + '.')
        L.append(f'- Review: `{rv["status"]}`; {rv["native_files_read"]["basis"]}.')
        for u in rv['unread_or_open_items']:
            L.append(f'  - open: {u}')
        uc = hab['usgs_csumb_classes']
        L.append(f'- Habitat: USGS character archives {fmt(uc["usgs_character_archives_catalogued"])}, opened '
                 f'{fmt(uc["usgs_character_rasters_opened"])}, class tables verified {fmt(uc["usgs_class_tables_verified"])}, '
                 f'hard outlines {fmt(uc["usgs_hard_context_outlines"])}; CDFW ds3091 predicted-hard patches '
                 f'{fmt(hab["cdfw_ds3091"]["predicted_hard_patches"])}.')
        if uc.get('csumb_terrain_habitat'):
            ct = uc['csumb_terrain_habitat']
            L.append(f'  - Seafloor ledger: {fmt(ct["ledger_reaches_habitat_screened"])} of {fmt(ct["ledger_reaches_total"])} '
                     f'reaches habitat-screened, {fmt(ct["graded_physical_habitat_polygons"])} graded physical habitat polygons, '
                     f'{fmt(ct["screened_habitat_km2"], " km2")} screened habitat.')
        L.append('')

    L += ['## Gap list, ranked by value for fishing and dive use', '',
          'Ranking (ESTIMATED): severity first (3 = no confirmed 2 m shallow grid; 2 = 2 m confirmed but coverage UNKNOWN or '
          'its low estimate under 60%; 1 = low estimate 60-89%), then the number of SkipperCast home ports in the sector '
          '(`dist/data/home-ports.json`) as the use proxy, then the smaller confirmed 2 m extent, then north to south. '
          'Candidate sources are named from repo evidence; whether each one covers the sector is unverified until its files '
          'are read.', '',
          '| Rank | Sector | Why | Home ports | Candidate sources | What to do |', '|---|---|---|---|---|---|']
    for g in inv['gap_list']:
        cands = '; '.join(c['name'].split(' (')[0] for c in g['candidate_sources'])
        L.append(f'| {g["rank"]} | {g["name"]} | {g["why"]} | {g["home_ports"]} ({", ".join(g["home_port_names"]) or "-"}) | '
                 f'{cands} | {g["action"]} |')
    L += ['', 'Candidate source evidence in the repo:', '']
    for k, (name, ev) in CANDIDATE_FAMILIES.items():
        L.append(f'- {name}: `{ev}`')
    L += ['', '## Definitions', '']
    L += [f'- `{k}`: {v}' for k, v in inv['definitions'].items()]
    L += ['', '## Limits', '']
    L += [f'- {x}' for x in inv['limits']]
    L += ['', '## Inputs', '', 'Every input file and its SHA-256 is listed in `catalog/coast-seafloor-inventory.json` (`inputs`). '
          'Rerun `python3 research/scripts/inventory_coast_seafloor.py` after any of them changes; `--check` reports drift.', '']
    return '\n'.join(L)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--check', action='store_true', help='fail if committed outputs differ from a fresh build')
    args = ap.parse_args(argv)
    inv = build()
    js = json.dumps(inv, indent=2, ensure_ascii=False) + '\n'
    md = render_md(inv)
    if args.check:
        stale = [p for p, body in ((OUT_JSON, js), (OUT_MD, md)) if not p.exists() or p.read_text(encoding='utf-8') != body]
        if stale:
            print('stale: ' + ', '.join(str(p.relative_to(ROOT)) for p in stale))
            return 1
        print('ok')
        return 0
    OUT_JSON.write_text(js, encoding='utf-8')
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    OUT_MD.write_text(md, encoding='utf-8')
    s = inv['summary']
    print('tiers', {k: v['value'] for k, v in s['shallow_tier_counts'].items()})
    print('any-depth', {k: v['value'] for k, v in s['finest_grid_any_depth_counts'].items()})
    print('uncertain', s['tier_uncertain_sectors'])
    print('status', {k: v['value'] for k, v in s['review_status_counts'].items()})
    return 0


if __name__ == '__main__':
    sys.exit(main())
