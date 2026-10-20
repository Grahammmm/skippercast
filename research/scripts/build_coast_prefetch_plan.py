"""Build a review-required prefetch seed from committed evidence, offline.

This is inventory preparation, not discovery and not proof of statewide coverage.
A reviewer must resolve the explicit gaps before the operator runs a full mirror.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from skippercast.coastal.prefetch import SEGMENTS, SHA, atomic_json
from skippercast.paths import repo_root

# Campaign plan rev 5 section 1. Envelopes are scheduling hints, NOT valid-cell masks.
BOUNDS = dict(zip(SEGMENTS, [
    [-121.95,34.95,-120.55,35.85], [-121.95,35.45,-120.95,35.66],
    [-121.25,34.45,-120.35,35.07], [-122,35.66,-121.2,35.9],
    [-122.2,35.9,-121.45,36.3], [-122.35,36.3,-121.65,36.625],
    [-122.75,36.6,-121.6,36.95], [-122.75,36.95,-122,37.183],
    [-120.65,34,-118.95,34.45], [-120.6,33.85,-119.3,34.15],
    [-119,33.65,-118.25,34.05], [-118.35,33.35,-117.5,33.8],
    [-117.6,32.5343,-117.05,33.4], [-119.7,32.75,-118.25,33.6],
    [-123.3,37.183,-122.28,37.95], [-123.7,37.95,-122.7,38.5],
    [-124.2,38.4,-122.85,39], [-124.4,38.958,-123.25,39.45],
    [-124.8,39.45,-123.6,40.167], [-124.8,40.167,-123.9,40.95],
    [-124.6,40.95,-124,41.55], [-124.75,41.55,-124.05,42],
], strict=True))
SECTORS = {
    'humboldt-cape': ['N6'], 'arena-bodega': ['N3'], 'bodega-reyes': ['N2'],
    'reyes-pigeon': ['N1'], 'pigeon-monterey': ['C6', 'C7a', 'C7b'],
    'monterey-sur': ['C6'], 'cambria-morro': ['C1', 'C2'],
    'morro-conception': ['C1', 'C3'], 'conception-ventura': ['S1'],
    'ventura-los-angeles': ['S1', 'S3'],
}
SFML = ('CSUMB SFML: non-profit use with acknowledgement; for-profit use needs '
        'express permission. Raw research cache only; no redistribution or navigation.')
USGS = 'USGS public domain; attribution and original metadata required; not for navigation. '
NOAA = 'US government public domain; attribution requested; not for navigation.'
GAPS = {
    'noaa-nos-statewide': 'Committed BAG inventory is a candidate set, not exhaustive CA enumeration; reconcile official footprints and all regular/VR BAG listings.',
    'bluetopo-ca': 'Enumerate current CA tiles from NOAA tile scheme; catalog/bluetopo-sample.json contains only a sample.',
    'crm': 'Exact file/subset URLs needed for SoCal v2 1 arc-sec, Vol 6 and Vol 7; no global downloads.',
    'gebco-2026': 'Resolve reviewed-host GEBCO 2026 CA subset URL, size, licence and attribution (COAST-HOSTS prerequisite).',
    'gmrt': 'Resolve reviewed-host GMRT CA subset URL, size, licence and attribution (COAST-HOSTS prerequisite).',
    'ncei-footprints': 'Resolve bounded CA footprint metadata query and pagination completeness (COAST-HOSTS prerequisite).',
    'usgs-cascadia': 'Resolve P9C5DBMR bathymetry and provenance files from official release.',
    'usgs-borderland': 'Resolve F7DV1H3W 10 m and 25 m original grids from official release.',
    'nccos-channel-islands': 'Resolve NCEI accession 0304093 native 2 m/4 m grids.',
    'usgs-dds55': 'Resolve Santa Monica and Palos Verdes/San Pedro bathymetry originals.',
    'csmp-missing-blocks': 'Reconcile DS781 Eureka index-link mismatch and campaign San Simeon/Point Sal-to-Arguello leads; no invented 2 m blocks.',
}


def intersects(box, segment):
    w, s, e, n = box
    a, b, c, d = segment
    return w < c and e > a and s < d and n > b


def segments_for(box):
    return [segment for segment, bounds in BOUNDS.items() if intersects(box, bounds)]


def build(root: Path) -> dict:
    def read(name):
        return json.loads((root / name).read_text())

    rows = {}
    gaps = [{'id': k, 'source': k, 'reason': v} for k, v in GAPS.items()]
    surveys = read('catalog/surveys.json')['surveys']
    pins = {}
    for record in surveys:
        if record['kind'] == 'bathymetry':
            pins.setdefault(record['url'], []).append(record)

    def add(url, source, segments, licence, evidence, **extra):
        if not segments:
            return
        if url in rows:
            rows[url]['segments'] = sorted(set(rows[url]['segments'] + segments), key=SEGMENTS.index)
            return
        # Multiple members of one archive must agree before an archive pin is used.
        known = pins.get(url, [])
        sizes = {r['bytes'] for r in known if type(r.get('bytes')) is int and r['bytes'] > 0}
        hashes = {r['sha256'] for r in known if isinstance(r.get('sha256'), str) and SHA.fullmatch(r['sha256'])}
        if len(sizes) > 1 or len(hashes) > 1:
            gaps.append({'id': 'conflicting-pin-' + known[0]['id'], 'source': source, 'url': url,
                         'reason': 'Archive/member inventory pins disagree; review original size and SHA before download.'})
            return
        rows[url] = {'source': source, 'url': url, 'segments': segments,
                     'licence': licence, 'evidence': evidence,
                     'bytes': next(iter(sizes), None), 'sha256': next(iter(hashes), None), **extra}

    for area in read('catalog/usgs-ds781-source-leads.json')['map_areas']:
        segments = sorted({s for sector in area['planning_sector_ids'] for s in SECTORS.get(sector, [])}, key=SEGMENTS.index)
        # Explicit plan C3 priorities override coarse sector tags for these blocks.
        if area['name'] in ('Offshore of Point Conception', 'Offshore of Gaviota'):
            segments = ['C3', 'S1']
        for product in area.get('products', []):
            if product['kind'] == 'bathymetry':
                add(product['archive_url'], 'csmp', segments, USGS + SFML,
                    'catalog/usgs-ds781-source-leads.json: ' + area['name'])

    for series in ('bss', 'scc'):
        name = f'catalog/csumb-{series}-source-leads.json'
        for record in read(name)['surveys']:
            add(record['original_products_url'], 'csumb-sfml', segments_for(record['catalog_envelope']),
                SFML, name + ': ' + record['survey_id'])

    envelopes = {}
    for region in read('research/receipts/noaa-region-bag-envelope-review.json')['regions']:
        for lead in region['leads']:
            envelopes[lead['bag_url']] = lead['bag_bounds']
    for record in surveys:
        if record['kind'] != 'bathymetry':
            continue
        url = record['url']
        if url in rows:
            continue
        box = envelopes.get(url) or record.get('adapter_review', {}).get('requested_bounds_wgs84')
        source = 'noaa-nos' if '.bag' in url else 'csumb-sfml' if '/ships/' in url else 'usgs-other'
        if not box or url.endswith('/'):
            gaps.append({'id': 'association-' + record['id'], 'source': source, 'url': url,
                         'reason': 'No committed campaign segment association or URL is a directory, not a file.'})
            continue
        add(url, source, segments_for(box), SFML if source == 'csumb-sfml' else NOAA if source == 'noaa-nos' else USGS,
            'catalog/surveys.json: ' + record['id'],
            association_basis='Committed bbox or inspected window; scheduling hint only, not native support.')

    caldig = read('research/catalog/usgs-caldig-v2.json')
    for name, archive in caldig['archives'].items():
        # Whole release originals (bathymetry and CMECS); archives stay unopened.
        add(archive['url'], 'usgs-caldig-i', ['C1', 'C2', 'C3', 'C4'], caldig['rights'],
            caldig['release_url'], bytes=archive['bytes'], sha256=archive['sha256'])

    # Deduplicate gaps and discard an early association gap resolved by a later
    # archive member's inspected window. Never silently discard coverage gaps.
    unresolved = {g['id']: g for g in gaps if not (g['id'].startswith('association-') and g.get('url') in rows)}
    return {'schema_version': 1, 'review_required': True,
            'scope': 'Known committed campaign seed; NOT an exhaustive statewide inventory.',
            'segments': BOUNDS, 'files': sorted(rows.values(), key=lambda r: (SEGMENTS.index(r['segments'][0]), r['source'], r['url'])),
            'unresolved': list(unresolved.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = build(repo_root())
    atomic_json(args.output, result)
    print(json.dumps({'files': len(result['files']), 'unresolved': len(result['unresolved']),
                      'known_bytes': sum(r['bytes'] or 0 for r in result['files']),
                      'unknown_size_files': sum(r['bytes'] is None for r in result['files'])}))


if __name__ == '__main__':
    main()
