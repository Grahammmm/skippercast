#!/usr/bin/env python3
"""Build the California outer-coast seafloor inventory from repository catalogs only.

COAST-INVENTORY-1. Reads committed catalogs, review summaries and receipts; makes no
network request and opens no raster. Writes:

  catalog/coast-seafloor-inventory.json   one row per catalog/coastal-sectors.json sector
  reports/COAST-SEAFLOOR-INVENTORY.md     the same rows, the ranked gap list and a summary

Every figure carries a label:
  MEASURED   copied or summed from pixel/cell counts already recorded in a repo catalog
  ESTIMATED  derived with a stated assumption (for example assigning a raster or reach to a
             sector by its bounding-box latitude)
  UNKNOWN    the repo has no catalog figure for it; never filled by guessing

Run from the repository root:  python3 research/scripts/inventory_coast_seafloor.py
Add --check to fail when the committed outputs differ from a fresh build.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_JSON = ROOT / 'catalog/coast-seafloor-inventory.json'
OUT_MD = ROOT / 'reports/COAST-SEAFLOOR-INVENTORY.md'
FT_300_M = 91.44
TIER_ORDER = ['2 m', '5 m', '10 m', 'coarser', 'none']
# A sector's tier is the finest class with at least this much read shallow area, so one
# harbour survey does not label a whole sector. Judgment threshold: tier labels are ESTIMATED.
MIN_TIER_KM2 = 5.0

INPUTS = {
    'sectors': 'catalog/coastal-sectors.json',
    'readiness': 'dist/data/california-atlas-readiness.json',
    'ledger': 'dist/data/seafloor-ledger.json',
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

# Central seafloor-ledger planning regions (catalog/seafloor-scope.json) and the browse
# sector each one starts in. Used only when a reach has no located CSUMB survey.
REGION_DEFAULT_SECTOR = {
    'santa-cruz-monterey-bay': 'pigeon-monterey',
    'monterey-point-sur': 'monterey-sur',
    'big-sur-coast': 'big-sur',
    'south-big-sur-san-simeon': 'sur-san-simeon',
    'cambria-san-simeon': 'cambria-morro',
    'morro-bay': 'morro-conception',
    'point-arguello-conception': 'morro-conception',
}

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


def sector_for_lat(lat, sectors):
    for s in sectors:
        lo, hi = s['latitude']
        if lo <= lat < hi:
            return s['id']
    return None


def csumb_resolution(src):
    res = src.get('resolution_m', src.get('resolution'))
    if isinstance(res, list) and res:
        return float(res[0])
    if isinstance(res, (int, float)):
        return float(res)
    member = src.get('archive_member') or src.get('bathymetry_grid') or ''
    m = re.search(r'(\d+)m(?:bathy|bthy)', member)
    return float(m.group(1)) if m else None


def csumb_date(src):
    dates = [d for d in (src.get('acquisition_dates') or []) if d]
    if dates:
        return f'{min(dates)[:4]}-{max(dates)[:4]}' if min(dates)[:4] != max(dates)[:4] else min(dates)[:4]
    if src.get('acquisition_year'):
        return str(src['acquisition_year'])
    return None


def csumb_name(src):
    member = src.get('archive_member') or src.get('bathymetry_grid') or ''
    survey = src.get('name') or src.get('survey_id') or src.get('block') or member.split('/')[0]
    return survey


def usgs_name(title, res_m):
    """Short display name for a USGS state-waters bathymetry title."""
    t = re.sub(r'^Bathymetry(?: \[\d+m\])?(?:--| from multibeam echosounder data collected | )', '', title)
    t = re.sub(r'(?i)^offshore of the |^offshore of |^offshore ', '', t)
    t = re.sub(r'(?i)\s*(map )+area|,\s*California$', '', t).strip(' ,')
    return f'USGS state-waters {round(res_m, 1):g} m bathymetry, {t}'


def polygon_centroid(geom):
    ring = geom['coordinates'][0] if geom['type'] == 'Polygon' else geom['coordinates'][0][0]
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def in_bounds(lon, lat, b):
    return b[0] <= lon <= b[2] and b[1] <= lat < b[3]


def build():
    data = {k: load(v) for k, v in INPUTS.items()}
    sectors = data['sectors']['sectors']
    ids = [s['id'] for s in sectors]
    readiness = {s['sector_id']: s for s in data['readiness']['sectors']}
    bounds = {sid: readiness[sid]['bounds'] for sid in ids}
    input_files = sorted([*INPUTS.values(), *glob.glob(CSUMB_GLOB, root_dir=ROOT),
                          *glob.glob(DS3091_GLOB, root_dir=ROOT), *glob.glob(USGS_HARD_GLOB, root_dir=ROOT)])

    rows = {sid: {'shallow_sources': []} for sid in ids}
    survey_year = {}
    for sv in data['surveys']['surveys']:
        y = sv.get('year')
        if isinstance(y, int) or (isinstance(y, str) and y.isdigit()):
            survey_year[sv['id']] = int(y)
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

    # 1. CSUMB native grids recorded with hashes (downloaded) in catalog/csumb-*native-sources.json.
    csumb_lat = {}
    csumb_by_sector = defaultdict(list)
    for rel in sorted(glob.glob(CSUMB_GLOB, root_dir=ROOT)):
        for src in load(rel).get('sources', []):
            res = csumb_resolution(src)
            b = src.get('bounds_wgs84')
            sid = None
            if b:
                lat = (b[1] + b[3]) / 2
                sid = sector_for_lat(lat, sectors)
                if src.get('id'):
                    csumb_lat[src['id']] = lat
            entry = {
                'family': 'CSUMB',
                'name': f'CSUMB {csumb_name(src)} {rnd(res, 0) if res else "?"} m native grid',
                'id': src.get('id'),
                'resolution_m': res,
                'date': csumb_date(src),
                'date_kind': 'acquisition',
                'read': bool(src.get('sha256') or src.get('archive_sha256')),
                'pixels_0_300ft': src.get('nominal_0_300ft_pixels'),
                'depth_max_m': src.get('depth_max_m'),
                'catalog': rel,
                'sector_basis': 'bounding-box centre latitude' if sid else None,
            }
            if sid is None:
                # Grid without bounds: use the readiness catalog-lead mapping of its survey id.
                survey = src.get('survey_id')
                hits = [x for x in ids if survey and survey in (readiness[x].get('csumb_catalog_survey_lead_ids') or [])]
                if hits:
                    sid = hits[0]
                    entry['sector_basis'] = 'readiness CSUMB survey-lead mapping (first listed sector)'
            if sid:
                csumb_by_sector[sid].append(entry)

    # 2. Central seafloor ledger: native coverage against the provisional BlueTopo 0-100 m reference band.
    ledger = data['ledger']
    reach_sector = {}
    by_sector_ledger = defaultdict(lambda: {'band': 0.0, 'tier1': 0.0, 'selected': 0.0, 'tier2': 0.0,
                                            'reaches': 0, 'assessed': 0, 'unassessed': 0, 'held': 0,
                                            'habitat_polygons': 0, 'surveys': set(), 'basis': set()})
    for r in ledger['reaches']:
        lats = [csumb_lat[s] for s in r.get('surveys_used', []) if s in csumb_lat]
        if lats:
            lats.sort()
            sid = sector_for_lat(lats[len(lats) // 2], sectors) or REGION_DEFAULT_SECTOR[r['region']]
            basis = 'median CSUMB survey latitude'
        else:
            sid = REGION_DEFAULT_SECTOR[r['region']]
            basis = 'planning-region start sector'
        reach_sector[r['id']] = sid
        agg = by_sector_ledger[sid]
        agg['band'] += r['band_km2']
        agg['tier1'] += r['tier1_km2']
        agg['tier2'] += r.get('tier2_km2') or 0.0
        agg['selected'] += r.get('selected_valid_km2') or 0.0
        agg['reaches'] += 1
        agg['assessed'] += r['status'] == 'habitat-screened'
        agg['held'] += r['status'] == 'habitat-held-for-screen'
        agg['unassessed'] += r['status'] == 'unassessed'
        agg['habitat_polygons'] += r.get('habitat_count') or 0
        agg['surveys'].update(r.get('surveys_used', []))
        agg['basis'].add(basis)

    # 3. USGS DS 781 / DOI original bathymetry grids opened in the depth-datum ledger.
    pubdate = {r['archive_url']: r.get('publication_date') for r in data['usgs_meta']['records']}
    usgs_sources = data['usgs_bathy']['sources']
    for sid in ids:
        for idx in next(s for s in data['usgs_bathy']['sectors'] if s['sector_id'] == sid)['intersecting_source_indices']:
            src = usgs_sources[idx]
            b = src['raster_bounds_wgs84']
            cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            # One sector per raster, by bbox centre inside the readiness sector box (latitude bands
            # alone misplace the east-west Santa Barbara Channel coast).
            if not in_bounds(cx, cy, bounds[sid]):
                continue
            res = src['native_resolution_m'][0]
            rows[sid]['shallow_sources'].append({
                'family': 'USGS DS781',
                'name': usgs_name(src['title'], res),
                'id': src['id'],
                'resolution_m': res,
                'date': pubdate.get(src['archive_url']),
                'date_kind': 'publication',
                'read': True,
                'pixels_0_300ft': None,
                'valid_pixels_all_depths': src['valid_native_pixels'],
                'slug': src['archive_url'].rsplit('/', 1)[-1].lower().replace('_', '-').replace('.', '-'),
                'catalog': INPUTS['usgs_bathy'],
                'sector_basis': 'raster bbox centre inside the sector box',
            })
    usgs_unavailable = data['usgs_bathy'].get('unavailable_original_grids', [])

    # 4. NOAA original regular BAGs (<=4 m) opened with per-sector measured and 25-200 ft eligible cells.
    noaa_reg = defaultdict(list)
    for f in data['noaa_regular']['files']:
        if f.get('status') != 'ok':
            continue
        res = f['native_resolution_m']
        for sid, c in (f.get('sectors') or {}).items():
            noaa_reg[sid].append({
                'family': 'NOAA BAG',
                'name': f"NOAA {f['survey_id']} {rnd(res[0], 1):g} m BAG",
                'id': f['bag_url'].rsplit('/', 1)[-1],
                'survey_id': f['survey_id'],
                'resolution_m': float(res[0]),
                'date': (f.get('survey_dates') or [None])[-1][:10] if f.get('survey_dates') else None,
                'date_kind': 'survey end',
                'read': True,
                'measured_cells': c['measured_native_cells'],
                'eligible_25_200ft_cells': c['depth_uncertainty_eligible_cells'],
                'eligible_area_km2': c['depth_uncertainty_eligible_cells'] * res[0] * res[1] / 1e6,
                'catalog': INPUTS['noaa_regular'],
            })
    noaa_vr = {s['sector_id']: s for s in data['noaa_vr']['sectors']}
    vr_dates = defaultdict(list)
    for f in data['noaa_vr']['files']:
        for sid in (f.get('sectors') or {}):
            vr_dates[sid].append((f['survey_id'], (f.get('survey_dates') or [None])[-1]))

    # 5. Habitat: USGS character rasters, display hard-context outlines, CDFW ds3091 patches.
    char = {s['sector_id']: s for s in data['usgs_char']['sectors']}
    char_products = data['usgs_char']['products']
    ds3091 = defaultdict(int)
    for rel in sorted(glob.glob(DS3091_GLOB, root_dir=ROOT)):
        for feat in load(rel)['features']:
            lon, lat = polygon_centroid(feat['geometry'])
            for sid in ids:
                if in_bounds(lon, lat, bounds[sid]):
                    ds3091[sid] += 1
                    break
    usgs_hard = defaultdict(int)
    for rel in sorted(glob.glob(USGS_HARD_GLOB, root_dir=ROOT)):
        for feat in load(rel)['features']:
            lon, lat = polygon_centroid(feat['geometry'])
            for sid in ids:
                if in_bounds(lon, lat, bounds[sid]):
                    usgs_hard[sid] += 1
                    break

    # 6. Fishing/dive use proxy: home ports whose match point lies in the sector band.
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

        # --- shallow sources (0-300 ft) ---
        shallow = []
        cs = [e for e in csumb_by_sector[sid] if e['pixels_0_300ft']]
        for e in cs:
            shallow.append(e)
        shallow.extend(rows[sid]['shallow_sources'])
        reg = [e for e in noaa_reg.get(sid, []) if e['eligible_25_200ft_cells'] > 0]
        shallow.extend(reg)
        vr = noaa_vr.get(sid, {})
        vr_eligible = vr.get('depth_uncertainty_eligible_cells', 0)
        agg = by_sector_ledger.get(sid)
        if agg and agg['tier1'] > 0:
            shallow.append({'family': 'Seafloor ledger', 'name': 'Central seafloor ledger native sources '
                            '(CSUMB, USGS, PG&E/CSUMB and NOAA grids)', 'resolution_m': 2.0,
                            'read': True, 'date': None, 'date_kind': None, 'catalog': INPUTS['ledger']})

        finest_res = min((e['resolution_m'] for e in shallow if e.get('resolution_m')), default=None)
        if finest_res is None and vr_eligible > 0:
            finest_res = 4.0
        # Shallow area read per tier (km2). Overlaps are not deduplicated.
        area = defaultdict(float)
        area_basis = defaultdict(list)
        if agg and agg['selected'] > 0:
            # The ledger already joins the sector's CSUMB, USGS and NOAA grids; adding them again would double count.
            area['2 m'] += agg['selected']
            area_basis['2 m'].append(f'seafloor ledger selected native footprint {agg["selected"]:.1f} km2 (M)')
        else:
            for e in cs:
                a = e['pixels_0_300ft'] * e['resolution_m'] ** 2 / 1e6
                area[tier_of(e['resolution_m'])] += a
            for t in TIER_ORDER:
                if area[t]:
                    area_basis[t].append(f'CSUMB nominal 0-300 ft pixels {area[t]:.1f} km2 (M)')
            for e in reg:
                area[tier_of(e['resolution_m'])] += e['eligible_area_km2']
            for t in ('2 m', '5 m'):
                a = sum(e['eligible_area_km2'] for e in reg if tier_of(e['resolution_m']) == t)
                if a:
                    area_basis[t].append(f'NOAA regular BAG 25-200 ft eligible cells {a:.1f} km2 (M)')
            usgs_area = 0.0
            for e in rows[sid]['shallow_sources']:
                a = e['valid_pixels_all_depths'] * e['resolution_m'] ** 2 / 1e6
                usgs_area += a
                area[tier_of(e['resolution_m'])] += a
            if usgs_area:
                area_basis['2 m'].append(f'USGS DS781 valid pixels x cell area {usgs_area:.1f} km2, all depths, whole raster (E)')
            if vr_eligible:
                area['5 m'] += vr_eligible / 1e6
                area_basis['5 m'].append(f'NOAA VR BAG eligible cells x 1 m2 lower bound {vr_eligible / 1e6:.1f} km2 (E)')
        present = [t for t in TIER_ORDER[:-1] if area[t] > 0]
        tier = next((t for t in present if area[t] >= MIN_TIER_KM2), present[0] if present else tier_of(finest_res))
        patch_only = tier not in [t for t in present if area[t] >= MIN_TIER_KM2]
        not_in_ledger = []
        if agg:
            ledger_ids = {x for a in by_sector_ledger.values() for x in a['surveys']}
            for e in rows[sid]['shallow_sources']:
                if not any(x.startswith(e['slug']) for x in ledger_ids):
                    not_in_ledger.append((e['name'], e['valid_pixels_all_depths'] * e['resolution_m'] ** 2 / 1e6))
        tier_res = {'2 m': 2.0, '5 m': 5.0, '10 m': 10.0}.get(tier)
        best_res = min((e['resolution_m'] for e in shallow if e.get('resolution_m') and tier_of(e['resolution_m']) == tier),
                       default=tier_res if tier != 'none' else None)
        vr_only = tier == '5 m' and bool(vr_eligible) and not any(tier_of(e.get('resolution_m')) == '5 m' for e in shallow)
        if vr_only:
            best_res = 4.0
        # Preferred source family when several share the best tier.
        pref = ['Seafloor ledger', 'CSUMB', 'USGS DS781', 'NOAA BAG']
        best_family = None
        for fam in pref:
            if any(e['family'] == fam and tier_of(e.get('resolution_m')) == tier for e in shallow):
                best_family = fam
                break
        fam_entries = [e for e in shallow if e['family'] == best_family and tier_of(e.get('resolution_m')) == tier]
        if best_family == 'Seafloor ledger':
            years = sorted({str(survey_year[x]) for x in agg['surveys'] if survey_year.get(x)})
            best_source = {
                'name': 'CSUMB/USGS California Seafloor Mapping Program native grids (read through the central seafloor ledger)',
                'family': 'CSUMB/CSMP',
                'date': fig(f'{years[0]}-{years[-1]}' if len(years) > 1 else (years[0] if years else None),
                            'MEASURED' if years else 'UNKNOWN',
                            'acquisition years recorded in catalog/surveys.json for the ledger surveys used in this sector '
                            f'({sum(1 for x in agg["surveys"] if survey_year.get(x))} of {len(agg["surveys"])} have a year); '
                            'release dates are not recorded'),
                'surveys_used': sorted(agg['surveys']),
            }
        elif best_family:
            dates = sorted({e['date'] for e in fam_entries if e.get('date')})
            names = sorted({e['name'] for e in fam_entries})
            kind = fam_entries[0]['date_kind']
            best_source = {
                'name': '; '.join(names[:4]) + (f' (+{len(names) - 4} more)' if len(names) > 4 else ''),
                'family': best_family,
                'date': fig(f'{dates[0]}' + (f' to {dates[-1]}' if dates[-1] != dates[0] else '') if dates else None,
                            'MEASURED' if dates else 'UNKNOWN', f'{kind} date recorded in {fam_entries[0]["catalog"]}'),
            }
        elif vr_eligible > 0:
            survs = sorted(set(vr.get('survey_ids_with_eligible_cells', [])))
            best_source = {
                'name': 'NOAA variable-resolution BAGs ' + ', '.join(survs) + ' (1-4 m refinements)',
                'family': 'NOAA VR BAG',
                'date': fig(None, 'UNKNOWN', 'per-sector VR survey dates are listed per file only'),
            }
        else:
            best_source = None

        # Coverage percent of the 0-300 ft area.
        if agg and agg['band'] > 0 and agg['tier1'] > 0:
            pct = 100.0 * agg['selected'] / agg['band']
            coverage = fig(round(pct), 'MEASURED',
                           f'selected native footprint {agg["selected"]:.1f} km2 / provisional BlueTopo 0-100 m reference band '
                           f'{agg["band"]:.1f} km2 from dist/data/seafloor-ledger.json; reach-to-sector assignment by '
                           f'{" and ".join(sorted(agg["basis"]))} (ESTIMATED where a planning region crosses the sector line)')
            tier1_pct = fig(round(100.0 * agg['tier1'] / agg['band']), 'MEASURED',
                            'tier-1 cell share (250 m cells at least 25% covered by one usable original source)')
        else:
            coverage = fig(None, 'UNKNOWN', 'no 0-300 ft reference area for this sector exists in the repo; '
                           'the seafloor ledger covers only Pigeon Point to Point Conception')
            tier1_pct = None

        reg_area_2m = sum(e['eligible_area_km2'] for e in reg if e['resolution_m'] <= 2.0)
        reg_area_all = sum(e['eligible_area_km2'] for e in reg)
        cs_area = sum((e['pixels_0_300ft'] or 0) * (e['resolution_m'] or 0) ** 2 / 1e6 for e in cs
                      if e['resolution_m'] and e['resolution_m'] <= 2.0)
        shallow_block = {
            'best_tier': tier,
            'best_tier_label': 'ESTIMATED',
            'best_tier_basis': f'finest class with at least {MIN_TIER_KM2:g} km2 of read shallow area in the sector',
            'best_resolution_m': fig(rnd(best_res, 2), ('ESTIMATED' if vr_only else 'MEASURED') if best_res else 'UNKNOWN',
                                     'finest native grid spacing among read sources of the best tier'
                                     + ('' if tier != '5 m' or not vr_eligible else
                                        '; VR BAG refinements are recorded only as 1-4 m')),
            'finest_resolution_anywhere_m': fig(rnd(finest_res, 2), 'MEASURED' if finest_res else 'UNKNOWN',
                                                'finest grid with any recorded cells in the sector, however small'),
            'area_read_by_tier_km2': {t: fig(round(area[t], 1), 'ESTIMATED' if any('(E)' in b for b in area_basis[t]) else 'MEASURED',
                                             '; '.join(area_basis[t]))
                                      for t in ('2 m', '5 m') if area[t]},
            'patch_only': patch_only,
            'usgs_ds781_opened_not_in_ledger': fig(
                [n for n, _ in not_in_ledger], 'ESTIMATED',
                f'opened DS781 grids whose archive is not among the seafloor-ledger surveys; about '
                f'{sum(a for _, a in not_in_ledger):.0f} km2 of valid pixels (all depths, whole rasters)') if not_in_ledger else None,
            'best_source': best_source,
            'coverage_pct_of_0_300ft': coverage,
            'tier1_cell_pct': tier1_pct,
            'csumb_2m_0_300ft_km2': fig(round(cs_area, 1), 'MEASURED',
                                       'sum of nominal_0_300ft_pixels x 4 m2 for 2 m CSUMB grids centred in the sector; '
                                       'overlapping blocks are not deduplicated') if cs_area else None,
            'noaa_bag_25_200ft_km2_at_2m_or_finer': fig(round(reg_area_2m, 1), 'MEASURED',
                                                        'sum of 25-200 ft depth/uncertainty-eligible cells x cell area for '
                                                        'regular BAGs <=2 m in dist/data/noaa-regular-native-depth-review.json; '
                                                        'overlapping surveys are not deduplicated') if reg else None,
            'noaa_bag_25_200ft_km2_all_regular': fig(round(reg_area_all, 1), 'MEASURED',
                                                     'same, all regular BAGs <=4 m') if reg else None,
            'noaa_vr_25_200ft_cells': fig(vr_eligible, 'MEASURED',
                                          'depth/uncertainty-eligible VR BAG refinement cells (1-4 m, area not computable '
                                          'without per-cell spacing)') if vr_eligible else None,
            'usgs_ds781_2m_grids_opened': fig(len(rows[sid]['shallow_sources']), 'ESTIMATED',
                                              'DS781 bathymetry rasters opened in dist/data/usgs-depth-datum-ledger.json whose '
                                              'bbox centre lies in this sector box; 0-300 ft pixels not recorded'),
            'sources': [{k: v for k, v in e.items() if k in ('family', 'name', 'resolution_m', 'date', 'date_kind',
                                                              'pixels_0_300ft', 'eligible_25_200ft_cells', 'sector_basis')}
                        for e in sorted(shallow, key=lambda e: (e.get('resolution_m') or 99, e['name']))][:12],
            'source_count': len(shallow),
        }
        row['shallow_0_300ft'] = shallow_block

        # --- deeper than 300 ft ---
        deep = []
        for e in csumb_by_sector[sid]:
            if e.get('depth_max_m') and e['depth_max_m'] > FT_300_M:
                deep.append({'name': e['name'], 'resolution_m': e['resolution_m'], 'date': e['date'],
                             'basis': f'depth_max_m {e["depth_max_m"]:.0f} in {e["catalog"]}', 'label': 'MEASURED'})
        if sid in em300['sector_ids']:
            deep.append({'name': em300['name'], 'resolution_m': float(em300['spatial']['resolution_m']), 'date': '1998',
                         'basis': 'catalog/candidates/usgs-monterey-1998-em300-original.json (canyon/shelf survey; '
                                  'depth band not tabulated)', 'label': 'ESTIMATED'})
        if sid in caldig['sector_ids']:
            deep.append({'name': caldig['name'], 'resolution_m': float(caldig['spatial']['resolution_m']), 'date': None,
                         'basis': 'catalog/candidates/usgs-caldig-v2.json (offshore deep-water release; mapping held '
                                  'in research/receipts/coast-c1-m2-held.json)', 'label': 'ESTIMATED'})
        if sid == 'big-sur':
            deep.append({'name': 'CSUMB BSS_Block13 5 m native grid', 'resolution_m': 5.0, 'date': '2011',
                         'basis': 'catalog/csumb-bss-native-sources.json: no valid cell shallower than 78.32 m NAVD88; '
                                  'deeper extent not tabulated', 'label': 'ESTIMATED'})
        deep.sort(key=lambda d: d['resolution_m'])
        tile = bluetopo.get(bt_tile.get(sid))
        if deep:
            d0 = deep[0]
            deep_block = {
                'best_tier': tier_of(d0['resolution_m']),
                'best_resolution_m': fig(d0['resolution_m'], d0['label'], d0['basis']),
                'best_source': d0['name'],
                'sources': deep,
            }
        else:
            deep_block = {
                'best_tier': 'coarser',
                'best_resolution_m': fig(float(gebco['spatial']['resolution_m']), 'MEASURED',
                                         'GEBCO_2026 grid spacing from catalog/candidates/gebco-2026-grid.json; no native grid '
                                         'with a recorded depth beyond 300 ft is catalogued for this sector (NOAA BAG reviews '
                                         'tabulate only 25-200 ft cells, so finer deep cells in read BAGs are UNKNOWN)'),
                'best_source': f'Statewide fallback only: {gebco["name"]} ({float(gebco["spatial"]["resolution_m"]):.0f} m)',
                'sources': [],
            }
        if tile:
            deep_block['compilation_context'] = (
                f'NOAA BlueTopo tile {tile["tile"]} at {tile["resolution_m"][0]:g} m (compilation; one sampled tile, '
                f'{tile["counts"]["measured_contributor_pixels"]:,} measured-contributor pixels; not a native survey grid)')
        row['deeper_than_300ft'] = deep_block

        # --- review status ---
        n_reg_files = len({e['id'] for e in noaa_reg.get(sid, [])})
        n_vr_files = vr.get('source_files_with_eligible_cells', 0)
        n_cs = len(csumb_by_sector[sid])
        n_usgs = len(rows[sid]['shallow_sources'])
        read_total = n_reg_files + n_vr_files + n_cs + n_usgs
        if agg and agg['tier1'] > 0:
            status = 'reviewed-coverage-measured'
        elif read_total:
            status = 'partly-reviewed'
        else:
            status = 'catalogued-only'
        unread = []
        if rd['original_bag_bbox_leads'] > n_reg_files + n_vr_files:
            unread.append(f'{rd["original_bag_bbox_leads"]} NOAA BAG bbox leads vs {n_reg_files + n_vr_files} BAG files read '
                          'with cells in the sector (bounded <=100 MB audit)')
        ds_links = sum(m['bathymetry_product_links'] for m in rd['usgs_ds781_map_area_leads'])
        if ds_links > n_usgs:
            unread.append(f'{ds_links} USGS DS781 bathymetry product links vs {n_usgs} opened grids assigned here')
        for u in usgs_unavailable:
            if any(k.lower() in u['archive_url'].lower() for k in ('pointconception',)) and sid == 'conception-ventura':
                unread.append('USGS Offshore Point Conception bathymetry archive exceeded the download bound')
        if agg and agg['unassessed']:
            unread.append(f'{agg["unassessed"]} of {agg["reaches"]} seafloor-ledger reaches unassessed (no native source attached)')
        if agg and agg['held']:
            unread.append(f'{agg["held"]} seafloor-ledger reaches held for the spatial screen')
        n_ledger = len(agg['surveys']) if agg else 0
        files_basis = (f'CSUMB grids {n_cs}, USGS DS781 grids {n_usgs} (ESTIMATED assignment), NOAA regular BAGs '
                       f'{n_reg_files}, NOAA VR BAGs {n_vr_files}')
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
        if agg:
            hab['usgs_csumb_classes']['csumb_terrain_habitat'] = {
                'ledger_reaches_habitat_screened': fig(agg['assessed'], 'MEASURED', INPUTS['ledger']),
                'ledger_reaches_total': fig(agg['reaches'], 'MEASURED', INPUTS['ledger']),
                'graded_physical_habitat_polygons': fig(agg['habitat_polygons'], 'MEASURED', INPUTS['ledger']),
                'screened_habitat_km2': fig(round(agg['tier2'], 1), 'MEASURED', 'tier-2 km2 in the seafloor ledger'),
            }
        if hab['usgs_csumb_classes']['usgs_character_rasters_opened']['value'] or (agg and agg['habitat_polygons']):
            hab['summary'] = 'native classes read' + (' (USGS character)' if ch.get('opened_native_rasters') else '') + \
                (' + CSUMB/ledger terrain habitat' if agg and agg['habitat_polygons'] else '') + '; CDFW ds3091 context'
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
        'schema_version': 1,
        'id': 'coast-seafloor-inventory',
        'task': 'COAST-INVENTORY-1',
        'scope': 'California outer-coast browse sectors (catalog/coastal-sectors.json), north to south. Bays and offshore '
                 'islands need their own packages and are not inventoried here.',
        'generator': 'research/scripts/inventory_coast_seafloor.py',
        'labels': {
            'MEASURED': 'copied or summed from pixel/cell counts already recorded in a repo catalog',
            'ESTIMATED': 'derived with a stated assumption, usually assigning a raster or reach to a sector by latitude',
            'UNKNOWN': 'no catalog figure exists in the repo; not filled by guessing',
        },
        'tiers': {
            '2 m': 'native grid spacing <= 2 m', '5 m': '> 2 m and <= 5 m (includes VR BAG 1-4 m refinements recorded only as <= 4 m)',
            '10 m': '> 5 m and <= 10 m', 'coarser': '> 10 m or compilation only', 'none': 'no native grid with recorded cells',
        },
        'limits': [
            'Grid spacing is not sounding accuracy; no source here is qualified as an MLLW fishing depth.',
            'Coverage percentages exist only where dist/data/seafloor-ledger.json supplies a 0-300 ft reference area '
            '(provisional BlueTopo 0-100 m band, about 0-328 ft).',
            'NOAA counts come from bounded audits (files <= 100 MB); larger or failed files are open items, not zeros.',
            'Overlapping surveys are not deduplicated in any km2 sum below.',
            'This inventory changes no map layer, target, score or export.',
        ],
        'inputs': [{'path': p, 'sha256': sha256(p)} for p in input_files],
        'summary': summary,
        'sectors': out_rows,
        'gap_list': gap_list,
    }


def rank_gaps(rows):
    gaps = []
    for r in rows:
        sh = r['shallow_0_300ft']
        cov = sh['coverage_pct_of_0_300ft']
        tier = sh['best_tier']
        extra = ''
        if sh.get('usgs_ds781_opened_not_in_ledger'):
            extra = ('; opened but not yet in the ledger: '
                     + ', '.join(n.split(', ', 1)[-1] for n in sh['usgs_ds781_opened_not_in_ledger']['value']))
        if tier != '2 m':
            severity, why = 3, f'no 2 m shallow grid read beyond small patches (best {tier})'
        elif sh['patch_only']:
            severity, why = 3, f'2 m grids read only in patches under {MIN_TIER_KM2:g} km2'
        elif cov['label'] == 'UNKNOWN':
            severity, why = 2, '2 m grids read in part of the sector; 0-300 ft coverage UNKNOWN'
        elif cov['value'] < 60:
            severity, why = 2, f'2 m coverage {cov["value"]}% of the 0-300 ft reference band{extra}'
        elif cov['value'] < 90:
            severity, why = 1, f'2 m coverage {cov["value"]}% of the 0-300 ft reference band{extra}'
        else:
            continue
        ports = r['use_proxy']['home_ports']['value']
        cands, action = candidates_for(r)
        gaps.append({'sector_id': r['id'], 'name': r['name'], 'severity': severity, 'why': why,
                     'home_ports': ports, 'home_port_names': r['use_proxy']['home_port_names'],
                     'candidate_sources': cands, 'action': action})
    # Severity first, then use proxy (home ports), then north-to-south order.
    order = {r['id']: r['order'] for r in rows}
    gaps.sort(key=lambda g: (-g['severity'], -g['home_ports'], order[g['sector_id']]))
    for i, g in enumerate(gaps, 1):
        g['rank'] = i
        g['rank_label'] = 'ESTIMATED'
    return gaps


def candidates_for(r):
    sid, coast = r['id'], r['coast']
    sh = r['shallow_0_300ft']
    c = []
    if coast == 'central':
        if sid == 'pigeon-monterey':
            c += ['ds781', 'lidar', 'csmp']
            action = ('download: attach the catalogued USGS Offshore Santa Cruz, Scott Creek, Pigeon Point and Aptos 2 m grids '
                      'to the unassessed ledger reaches r01-r10, then rerun the ledger')
        else:
            c += ['csmp', 'noaa', 'opc']
            action = ('download: read remaining catalogued CSUMB/NOAA grids into the ledger; request CSUMB/OPC for any '
                      'block missing from NCEI; survey only where no block exists')
    elif sh['best_tier'] != '2 m' or sh['patch_only']:
        c += ['csmp', 'ds781', 'noaa', 'lidar', 'opc']
        action = ('request: ask CSUMB Seafloor Mapping Lab / OPC whether CSMP state-waters 2 m grids exist for this reach; '
                  'download any NOAA BAG >100 MB not yet read; survey if neither exists')
    else:
        c += ['ds781', 'noaa', 'csmp']
        action = ('download: open the catalogued but unread DS781 bathymetry and NOAA BAG files, then build a 0-300 ft '
                  'reference area (extend the seafloor ledger) so coverage can be MEASURED')
    return [{'family': k, 'name': CANDIDATE_FAMILIES[k][0], 'evidence': CANDIDATE_FAMILIES[k][1]} for k in c], action


def summarize(rows):
    tiers = {t: [r['id'] for r in rows if r['shallow_0_300ft']['best_tier'] == t] for t in TIER_ORDER}
    deep = {t: [r['id'] for r in rows if r['deeper_than_300ft']['best_tier'] == t] for t in TIER_ORDER}
    status = defaultdict(list)
    for r in rows:
        status[r['review']['status']].append(r['id'])
    measured_cov = [r for r in rows if r['shallow_0_300ft']['coverage_pct_of_0_300ft']['label'] == 'MEASURED']
    return {
        'sector_count': fig(len(rows), 'MEASURED', 'catalog/coastal-sectors.json'),
        'shallow_tier_counts': {t: fig(len(v), 'ESTIMATED', f'count of sectors whose best_tier is {t}; best_tier uses the '
                                       f'{MIN_TIER_KM2:g} km2 threshold') for t, v in tiers.items()},
        'shallow_tier_sectors': tiers,
        'deep_tier_counts': {t: fig(len(v), 'ESTIMATED', 'count of sectors by best deeper-than-300 ft tier; several deep '
                                    'sources have no tabulated depth band') for t, v in deep.items()},
        'review_status_counts': {k: fig(len(v), 'MEASURED', 'review.status per sector') for k, v in sorted(status.items())},
        'review_status_sectors': dict(sorted(status.items())),
        'coverage_measured_sectors': fig(len(measured_cov), 'MEASURED', 'sectors with a ledger 0-300 ft reference area'),
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
    if isinstance(v, float):
        v = f'{v:g}'
    elif isinstance(v, int):
        v = f'{v:,}'
    return f'{v}{suffix} ({f["label"][0]})'


def render_md(inv):
    s = inv['summary']
    rows = inv['sectors']
    L = []
    t = s['shallow_tier_counts']
    st = s['review_status_counts']
    patch_n = sum(1 for r in rows if r['shallow_0_300ft']['patch_only'])
    sw = s['statewide_survey_catalog']
    L += ['# California coast seafloor inventory (COAST-INVENTORY-1)', '',
          f'Generated by `{inv["generator"]}` from repository catalogs only (no downloads). '
          'Machine-readable copy: `catalog/coast-seafloor-inventory.json`. Labels: **M** = MEASURED from catalog '
          'pixel/cell counts, **E** = ESTIMATED with a stated assumption, UNKNOWN = no catalog figure.', '',
          '## Summary for G', '',
          f'- **Is the inventory complete?** Yes for the list: all {s["sector_count"]["value"]} outer-coast sectors in '
          '`catalog/coastal-sectors.json` have a row (M). Bays and offshore islands are outside these sectors and are not covered.',
          f'- **Best shallow (0-300 ft) detail by sector:** 2 m: {t["2 m"]["value"]} · 5 m: {t["5 m"]["value"]} · '
          f'10 m: {t["10 m"]["value"]} · coarser: {t["coarser"]["value"]} · none: {t["none"]["value"]} '
          f'(E: a sector\'s tier is the finest grid class with at least {MIN_TIER_KM2:g} km2 read). '
          + (f'Of the 2 m sectors, {patch_n} {"has" if patch_n == 1 else "have"} 2 m only in small patches '
             f'({", ".join(r["name"] for r in rows if r["shallow_0_300ft"]["patch_only"])}). ' if patch_n else '')
          + 'Having a 2 m tier means 2 m grids exist for part of the sector, not that the whole sector is mapped at 2 m.',
          f'- **Has it all been reviewed? No.** {st.get("reviewed-coverage-measured", {"value": 0})["value"]} sectors '
          'have native grids read **and** a measured share of the 0-300 ft seabed; '
          f'{st.get("partly-reviewed", {"value": 0})["value"]} have some native grids read but no way yet to say what share '
          f'they cover; {st.get("catalogued-only", {"value": 0})["value"]} are catalogued only. '
          f'Fully reviewed (every catalogued lead read): {s["fully_reviewed_sectors"]["value"]} (M).',
          f'- **Where we know coverage (M):** ' + '; '.join(
              f'{r["name"]} {r["shallow_0_300ft"]["coverage_pct_of_0_300ft"]["value"]}%' for r in rows
              if r['shallow_0_300ft']['coverage_pct_of_0_300ft']['label'] == 'MEASURED') + '.',
          '- **Elsewhere coverage is UNKNOWN**, not zero: the repo has no 0-300 ft reference area outside Pigeon Point to '
          'Point Conception, so pixel counts there cannot be turned into a percentage.',
          f'- **Deeper than 300 ft:** best native tier by sector (E): ' + ' · '.join(
              f'{k}: {v["value"]}' for k, v in s['deep_tier_counts'].items()) +
          '. "Coarser" means only the statewide GEBCO grid (463 m) is catalogued for deep water there; BlueTopo compilation tiles exist '
          'for every sector but are not native surveys.',
          '- **Habitat classes:** CDFW ds3091 predicted hard/soft is decoded for all 19 sectors (context only). USGS/CSUMB '
          'native classes are read in ' + str(sum(1 for r in rows if r['habitat']['summary'].startswith('native classes read'))) +
          ' sectors (M).',
          f'- **Statewide source catalog (M):** `catalog/surveys.json` lists {sw["entries"]["value"]} survey files; '
          f'{sw["native_inspected"]["value"]} were opened at native resolution, {sw["catalog_or_metadata_only"]["value"]} are '
          f'catalogue or metadata only, {sw["usable_status"]["value"]} are marked usable. It has no sector field, so the '
          'per-sector counts below come from the sector review files.',
          f'- **Top gaps:** ' + '; '.join(f'{g["rank"]}. {g["name"]}' for g in inv['gap_list'][:5]) + ' (rank E).',
          '- Nothing here is a fishing target; grid spacing is not depth accuracy, and no source is yet MLLW-qualified.', '']

    L += ['## Sector table (north to south)', '',
          '| # | Sector | Best 0-300 ft | Source (date) | % of 0-300 ft covered | Deeper than 300 ft | Review status | Habitat classes |',
          '|---|---|---|---|---|---|---|---|']
    for r in rows:
        sh = r['shallow_0_300ft']
        bs = sh['best_source']
        src = '-' if not bs else f'{bs["name"]} ({fmt(bs["date"])})'
        dp = r['deeper_than_300ft']
        deep = f'{dp["best_tier"]}: {fmt(dp["best_resolution_m"], " m")}'
        if not dp['sources']:
            deep += ' GEBCO only; native UNKNOWN'
        rv = r['review']
        hab = r['habitat']
        best = f'{sh["best_tier"]}{" (patches only)" if sh["patch_only"] else ""}, finest {fmt(sh["best_resolution_m"], " m")}'
        L.append(f'| {r["order"]} | {r["name"]} | {best} | {src} | '
                 f'{fmt(sh["coverage_pct_of_0_300ft"], "%")} | {deep} | {rv["status"]}, {fmt(rv["native_files_read"])} files read | '
                 f'{hab["summary"]}; ds3091 patches {fmt(hab["cdfw_ds3091"]["predicted_hard_patches"])} |')
    L += ['', 'Status key: `reviewed-coverage-measured` = native grids read and a 0-300 ft share measured in the seafloor ledger; '
          '`partly-reviewed` = some native grids read, share UNKNOWN; `catalogued-only` = leads listed, nothing read.', '']

    L += ['## Sector detail', '']
    for r in rows:
        sh, dp, rv, hab = r['shallow_0_300ft'], r['deeper_than_300ft'], r['review'], r['habitat']
        L.append(f'### {r["order"]}. {r["name"]} (`{r["id"]}`, lat {r["latitude"][0]}-{r["latitude"][1]})')
        L.append('')
        L.append(f'- 0-300 ft: best **{sh["best_tier"]}**{" (patches only)" if sh["patch_only"] else ""} (E); finest grid '
                 f'anywhere {fmt(sh["finest_resolution_anywhere_m"], " m")}; {sh["source_count"]} read sources with cells in the sector.')
        for t, f in sh['area_read_by_tier_km2'].items():
            L.append(f'  - Read area at {t}: {fmt(f, " km2")} - {f["basis"]}.')
        if sh.get('usgs_ds781_opened_not_in_ledger'):
            f = sh['usgs_ds781_opened_not_in_ledger']
            L.append(f'  - Opened but not yet in the seafloor ledger (E): {", ".join(f["value"])}; {f["basis"]}.')
        if sh['coverage_pct_of_0_300ft']['label'] == 'MEASURED':
            L.append(f'  - Coverage {fmt(sh["coverage_pct_of_0_300ft"], "%")}: {sh["coverage_pct_of_0_300ft"]["basis"]}. '
                     f'Tier-1 cell share {fmt(sh["tier1_cell_pct"], "%")}.')
        else:
            L.append('  - Coverage UNKNOWN: ' + sh['coverage_pct_of_0_300ft']['basis'] + '.')
        for k, label in (('csumb_2m_0_300ft_km2', 'CSUMB 2 m nominal 0-300 ft area'),
                         ('noaa_bag_25_200ft_km2_at_2m_or_finer', 'NOAA BAG <=2 m eligible 25-200 ft area'),
                         ('noaa_bag_25_200ft_km2_all_regular', 'NOAA BAG <=4 m eligible 25-200 ft area'),
                         ('noaa_vr_25_200ft_cells', 'NOAA VR eligible 25-200 ft cells'),
                         ('usgs_ds781_2m_grids_opened', 'USGS DS781 2 m grids opened')):
            if sh.get(k):
                L.append(f'  - {label}: {fmt(sh[k], " km2" if "km2" in k else "")}')
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
          'Ranking (ESTIMATED): severity first (3 = no 2 m shallow grid read; 2 = 2 m read but coverage UNKNOWN or under 60%; '
          '1 = 60-89%), then the number of SkipperCast home ports in the sector (`dist/data/home-ports.json`) as the use proxy, '
          'then north to south. Candidate sources are named from repo evidence; whether each one covers the sector is unverified '
          'until its files are read.', '',
          '| Rank | Sector | Why | Home ports | Candidate sources | What to do |', '|---|---|---|---|---|---|']
    for g in inv['gap_list']:
        cands = '; '.join(c['name'].split(' (')[0] for c in g['candidate_sources'])
        L.append(f'| {g["rank"]} | {g["name"]} | {g["why"]} | {g["home_ports"]} ({", ".join(g["home_port_names"]) or "-"}) | '
                 f'{cands} | {g["action"]} |')
    L += ['', 'Candidate source evidence in the repo:', '']
    for k, (name, ev) in CANDIDATE_FAMILIES.items():
        L.append(f'- {name}: `{ev}`')
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
    print('status', {k: v['value'] for k, v in s['review_status_counts'].items()})
    return 0


if __name__ == '__main__':
    sys.exit(main())
