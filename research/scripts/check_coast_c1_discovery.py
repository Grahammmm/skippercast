"""Offline check of the 2026-10-20 C1 discovery, never a renewed live trial.

Run with PYTHONPATH=src:. and a jsonschema/pyproj-enabled survey runtime.
Raw response evidence stays in the supplied private receipt directory.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

from skippercast.coastal import live_discovery as ld


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(base):
    root = Path(__file__).resolve().parents[2]
    assert Path(ld.__file__).resolve() == root / 'src/skippercast/coastal/live_discovery.py'
    live = base / 'live'
    read = lambda path: json.loads(path.read_text())
    pins = read(base / 'SHA256SUMS.json')
    for name, expected in pins.items():
        assert sha(base / name) == expected, name
    manifest_path = live / 'checkpoint-manifest.json'
    manifest = read(manifest_path)
    receipt = read(live / 'receipt.json')
    catalog = read(live / 'catalog.json')
    assessment = read(live / 'assessment.json')
    summary = read(root / 'research/receipts/coast-c1-discovery.json')
    plan_path = root / 'research/catalog/coast-c1-discovery-plan.json'
    plan = read(plan_path)
    _, decisions = ld.check_plan(plan)
    assert receipt['allowlist'] == decisions
    assert receipt['plan_sha256'] == ld._digest(plan)
    assert summary['plan_sha256'] == sha(plan_path)
    discover, script = ld.load_script(root)
    discover.validate_schema(manifest)
    for candidate in manifest['candidates']:
        discover.validate_candidate(candidate, manifest)
    assert catalog == ld.frozen_catalog(manifest, manifest_path.read_bytes())
    assert read(live / 'catalog-diff.json') == ld.diff(None, catalog)
    assert manifest['status'] == 'FINALIZED' and manifest['bounded_plan_finished']
    assert not manifest['discovery_complete'] and manifest['failed_requests'] == [1]
    assert not manifest['unattempted_queries']
    assert len(manifest['added_queries']) == 1
    assert len(manifest['plan']['catalogs']) == 2
    assert sum(len(c['queries']) for c in manifest['plan']['catalogs']) == 7
    assert receipt['script_plan_sha256'] == manifest['plan_sha256']
    assert receipt['script_sha256'] == sha(script)
    assert receipt['module_sha256'] == sha(Path(ld.__file__))
    requests = manifest['requests']
    assert receipt['requests'] == requests
    assert len(requests) == receipt['network_requests'] == 7
    assert requests[0]['http_status'] == 302
    assert requests[0]['location'] == requests[-1]['url']
    assert all(r['status'] == 'OK' and r['http_status'] == 200 for r in requests[1:])
    assert all(r['purpose'] == 'metadata' for r in requests)
    assert receipt['native_source_downloads'] == 0
    observed = sum(r['observed_body_bytes'] for r in requests)
    assert observed == receipt['observed_body_bytes'] == manifest['observed_body_bytes'] == 71161
    assert observed <= receipt['budget_charged_bytes'] == manifest['budget_charged_bytes'] <= 250000000
    start = discover.timestamp(manifest['start_utc'])
    stop = discover.timestamp(manifest['stopped_at'])
    assert 0 < stop - start <= receipt['elapsed_seconds'] < 1500
    assert discover.timestamp(manifest['deadline_utc']) - start == 1800
    assert discover.timestamp(manifest['discovery_cutoff_utc']) - start == 1500
    assert all(discover.timestamp(r['stop_utc']) < start + 1500 for r in requests)
    for row in requests[1:]:
        assert sha(Path(row['body_path'])) == row['sha256']
    for output in receipt['outputs']:
        assert sha(live / output['path']) == output['sha256']
    assert sha(manifest_path) == receipt['manifest']['sha256'] == summary['manifest_sha256']
    assert sha(live / 'catalog.json') == summary['catalog_sha256'] == assessment['catalog_sha256']
    assert sha(live / 'receipt.json') == summary['receipt_sha256']
    assert receipt['within_caps'] is True
    assert catalog['review_required'] and receipt['review_required'] and summary['review_required']
    assert not catalog['mapping_accepted'] and not catalog['execution_authorized']
    assert not summary['semantic_accepted'] and not summary['publication_accepted']
    assert len(catalog['candidates']) == 9
    primary, = [c for c in catalog['candidates'] if c['catalog_id'] == 'usgs-caldig-i-v2']
    text = Path(requests[1]['body_path']).read_text()
    def field(name):
        match = re.search(r'^\s*' + re.escape(name) + r':\s*(.+)$', text, re.M)
        assert match, name
        return match.group(1).strip()
    metadata = primary['metadata']
    assert field('Geospatial_Data_Presentation_Form') == 'GeoTIFF'
    assert field('Abscissa_Resolution') == field('Ordinate_Resolution') == '10.0'
    assert field('Planar_Distance_Units') == 'Meters'
    assert metadata['resolution'] == dict(x=10.0, y=10.0, units='m', rows=15227, columns=11242)
    assert int(field('Row_Count')) == 15227 and int(field('Column_Count')) == 11242
    assert metadata['vertical_datum'] is None
    assert primary['field_evidence']['stated_vertical_datum'] == 'not stated'
    assert not any(name in text for name in ['Vertical_Datum', 'Altitude_Datum_Name', 'Depth_Datum_Name'])
    assert 'Small voids were filled' in text and 'H1309, H13151' in text
    assert primary['access_url'] in discover.response_links(Path(requests[-1]['body_path']).read_text(), requests[-1]['url'])
    vr = [c for c in catalog['candidates'] if c['metadata']['format'] == 'VR BAG']
    assert len(vr) == 8
    assert {c['field_evidence']['survey_id'] for c in vr} == {'H13089', 'H13151', 'H13152', 'W00479'}
    for c in vr:
        assert '_VR_' in c['publisher_id']
        assert c['field_evidence']['grid_class'] == 'VR'
        assert c['field_evidence']['acquire_hold'] == 'P10'
        assert not c['terrain']['accepted']
        assert c['metadata']['resolution'] is None
    upstream = read(base / 'upstream-scope.json')
    assert sha(Path(upstream['parent_path'])) == upstream['parent_sha256'] == 'd78b6c9d21180ea97aef971392f68c14ef0d982977e4b1cc4c8bd4e16647c248'
    assert assessment['regular_pyramids'] == upstream['regular_transit_holds']
    regular = assessment['regular_pyramids']
    assert {s['survey_id'] for s in regular} == {'W00431', 'W00433', 'W00443', 'W00444', 'W00447'}
    assert all(s['surveyed_cells_in_bbox'] == 'not_established' and not s['bridge_eligible'] and s['resolution_pyramid_m'] for s in regular)
    assert len(assessment['holds']) == 13
    return dict(result='PASS', pinned_files=len(pins), candidates=9, vr_files=8,
                regular_survey_holds=5, network_requests=7, observed_body_bytes=observed,
                within_caps=True, elapsed_seconds=receipt['elapsed_seconds'],
                discovery_complete=False, semantic_accepted=False,
                catalog_sha256=sha(live / 'catalog.json'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receipts', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.receipts.resolve()), indent=2, sort_keys=True))
