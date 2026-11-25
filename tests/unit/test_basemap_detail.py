"""Offline extraction coverage guard, including the Trinidad–Klamath gap."""
import copy
import json
import subprocess
import sys

import pytest

from scripts.basemap import check_detail, regions
from tests._support import ROOT
from tests.unit.test_basemap_regions import LISTING


def settings():
    planned = regions.plan('20261008', LISTING)
    return planned, regions.detail_region(planned['regions'])


def test_all_22_regions_include_trinidad_at_detail_zooms():
    planned, detail = settings()
    boxes = check_detail.check_detail(planned, detail)
    assert len(boxes) == 22
    assert next(b['bbox'] for b in boxes if b['id'] == 'trinidad-klamath') == [-124.6, 40.95, -124.0, 41.55]


@pytest.mark.parametrize('fault', ['missing', 'bounds', 'duplicate', 'zoom-min', 'zoom-max', 'overview', 'geometry'])
def test_refuses_incomplete_or_inconsistent_settings(fault):
    planned, detail = settings()
    target = next(b for b in planned['regions'] if b['id'] == 'trinidad-klamath')
    if fault == 'missing':
        planned['regions'].remove(target)
        detail = regions.detail_region(planned['regions'])
    elif fault == 'bounds':
        target['bbox'][3] -= 0.1
        detail = regions.detail_region(planned['regions'])
    elif fault == 'duplicate':
        planned['regions'].append(copy.deepcopy(target))
    elif fault == 'zoom-min':
        planned['detail']['minzoom'] = 12
    elif fault == 'zoom-max':
        planned['detail']['maxzoom'] = 13
    elif fault == 'overview':
        planned['overview']['maxzoom'] = 11
    else:
        detail['geometry']['coordinates'].pop()
    with pytest.raises(ValueError):
        check_detail.check_detail(planned, detail)


def test_draft_subregions_use_containment_not_status_promotion(tmp_path):
    planned, detail = settings()
    coverage = check_detail.check_detail(planned, detail)
    assert next(b['containers'] for b in coverage if b['id'] == 'san-diego') == ['southern-california']
    # Keep the real extraction regions, then add a draft beyond every box.
    for path in (ROOT / 'regions').glob('*/region.json'):
        target = tmp_path / 'regions' / path.parent.name / 'region.json'
        target.parent.mkdir(parents=True)
        target.write_text(path.read_text())
    target = tmp_path / 'regions' / 'outside' / 'region.json'
    target.parent.mkdir()
    target.write_text(json.dumps({'id': 'outside', 'status': 'draft', 'bounds': [-125, 42, -124, 43]}))
    with pytest.raises(ValueError, match='No detail box contains region outside'):
        check_detail.check_detail(planned, detail, root=tmp_path)


def test_cli_checks_defaults_and_saved_settings_offline(tmp_path):
    command = [sys.executable, str(ROOT / 'scripts/basemap/check_detail.py')]
    default = subprocess.run(command, capture_output=True, text=True, check=True)
    assert 'PASS trinidad-klamath: zooms 11–14' in default.stdout
    assert '22 of 22 regions inside a detail box' in default.stdout
    planned, detail = settings()
    (tmp_path / 'plan.json').write_text(json.dumps(planned))
    (tmp_path / 'detail.geojson').write_text(json.dumps(detail))
    saved = subprocess.run([*command, '--dir', str(tmp_path)], capture_output=True, text=True, check=True)
    assert saved.stdout == default.stdout
    (tmp_path / 'detail.geojson').write_text('{}')
    bad = subprocess.run([*command, '--dir', str(tmp_path)], capture_output=True, text=True)
    assert bad.returncode == 1
    assert 'FAIL:' in bad.stderr


def test_cli_refuses_unreadable_saved_settings(tmp_path):
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/basemap/check_detail.py'), '--dir', str(tmp_path)],
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert 'FAIL:' in result.stderr


def _run_dir(tmp_path, plan, detail=None):
    planned, good = settings()
    plan = plan(planned) if callable(plan) else plan
    (tmp_path / 'plan.json').write_text(plan if isinstance(plan, str) else json.dumps(plan))
    (tmp_path / 'detail.geojson').write_text(json.dumps(good if detail is None else detail))
    return subprocess.run([sys.executable, str(ROOT / 'scripts/basemap/check_detail.py'), '--dir', str(tmp_path)],
                          capture_output=True, text=True)


def _drop(key):
    return lambda p: {**p, 'regions': [{k: v for k, v in p['regions'][0].items() if k != key}]}


@pytest.mark.parametrize('plan,message', [
    (_drop('id'), 'plan.json: regions[0] must be an object with a string "id" and a 4-number "bbox"'),
    (_drop('bbox'), 'plan.json: regions[0] must be an object with a string "id" and a 4-number "bbox"'),
    (lambda p: {**p, 'regions': 'x'}, 'plan.json: "regions" must be a list'),
    ([], 'plan.json: not a JSON object'),
    (lambda p: {**p, 'overview': None}, 'plan.json: "overview" must be an object'),
    (lambda p: {**p, 'detail': 3}, 'plan.json: "detail" must be an object'),
    ('{"regions": ', 'plan.json: not valid JSON (line 1 column 13)'),
    (lambda p: {**p, 'regions': [{'id': 'a', 'bbox': [1, 2, 3]}]}, 'regions[0] must be an object'),
    (lambda p: {**p, 'regions': [{'id': 'a', 'bbox': [1, 2, 3, 'x']}]}, 'regions[0] must be an object'),
    ('{"overview": {}, "detail": {}, "regions": [{"id": "a", "bbox": [1, 2, 3, NaN]}]}', 'regions[0] must be an object'),
])
def test_cli_names_file_and_field_of_misshaped_plan(tmp_path, plan, message):
    result = _run_dir(tmp_path, plan)
    assert result.returncode == 1 and result.stdout == ''
    assert result.stderr.startswith('FAIL: ') and message in result.stderr


def test_cli_names_detail_file_and_missing_dir(tmp_path):
    result = _run_dir(tmp_path, lambda p: p, detail=[])
    assert result.returncode == 1 and result.stdout == ''
    assert 'FAIL: detail.geojson: not a JSON object' in result.stderr
    missing = subprocess.run([sys.executable, str(ROOT / 'scripts/basemap/check_detail.py'), '--dir', str(tmp_path / 'no')],
                             capture_output=True, text=True)
    assert 'FAIL: plan.json: cannot read: No such file or directory' in missing.stderr


def _detail_cli(*args):
    return subprocess.run([sys.executable, str(ROOT / 'scripts/basemap/check_detail.py'), *args],
                          capture_output=True)


@pytest.fixture
def saved_manifest(tmp_path):
    boxes = regions.region_boxes()
    return tmp_path / 'pointer.json', {
        'key': 'tiles/basemap/fixture.pmtiles', 'bytes': 1024,
        'built_at': '2026-10-08T00:00:00Z', 'source': {'build': '20261008'},
        'overview': {'bbox': regions.overview_box(boxes), 'minzoom': 0, 'maxzoom': 10},
        'detail': {'minzoom': 11, 'maxzoom': 14},
        'regions': [{'id': box['id'], 'bbox': box['bbox']} for box in boxes],
    }


def _manifest_summary(count):
    return (f"{count} of {count} indexed regions inside the manifest's detail boxes "
            "(footprint only; tile bytes not inspected)\n")


def test_c2_c5_manifest_passes_names_missing_preview_and_passes_after_restore(saved_manifest):
    """C2: Report every indexed region. C5: Name the stale preview gap, then recover."""
    path, document = saved_manifest
    boxes = document['regions']
    # The committed Cambria box is also contained by Morro Bay. No draft is indexed.
    expected = ''.join(f"PASS {box['id']}: inside manifest detail box {box['id']}"
                       + (', morro-bay' if box['id'] == 'cambria-san-simeon' else '') + '\n'
                       for box in boxes) + _manifest_summary(len(boxes))
    path.write_text(json.dumps(document))
    passed = _detail_cli('--manifest', path)
    assert (passed.returncode, passed.stdout, passed.stderr) == (0, expected.encode(), b'')

    document['regions'] = [box for box in boxes if box['id'] != 'trinidad-klamath']
    path.write_text(json.dumps(document))
    failed = _detail_cli('--manifest', path)
    assert (failed.returncode, failed.stdout, failed.stderr) == (
        1, b'', b'FAIL: manifest detail boxes miss indexed region(s): trinidad-klamath\n',
    )

    document['regions'] = boxes
    path.write_text(json.dumps(document))
    restored = _detail_cli('--manifest', path)
    assert (restored.returncode, restored.stdout, restored.stderr) == (0, expected.encode(), b'')


def test_c1_containment_does_not_require_matching_ids_or_equal_bounds(saved_manifest):
    """C1: One larger box can cover all regions, even with a different ID."""
    path, document = saved_manifest
    ids = [box['id'] for box in document['regions']]
    document['regions'] = [{'id': 'whole-coast', 'bbox': document['overview']['bbox']}]
    path.write_text(json.dumps(document))
    result = _detail_cli('--manifest', path)
    expected = ''.join(f'PASS {region_id}: inside manifest detail box whole-coast\n' for region_id in ids)
    assert (result.returncode, result.stdout, result.stderr) == (
        0, (expected + _manifest_summary(len(ids))).encode(), b'',
    )


def test_c3_empty_box_list_names_all_missed_regions_sorted(saved_manifest):
    """C3: An empty footprint misses every region; no misleading PASS is printed."""
    path, document = saved_manifest
    ids = ', '.join(sorted(box['id'] for box in document['regions']))
    document['regions'] = []
    path.write_text(json.dumps(document))
    result = _detail_cli('--manifest', path)
    assert (result.returncode, result.stdout, result.stderr) == (
        1, b'', f'FAIL: manifest detail boxes miss indexed region(s): {ids}\n'.encode(),
    )


@pytest.mark.parametrize('mutate,message', [
    pytest.param(lambda doc: [], 'manifest must be a JSON object', id='C3: non-object manifest'),
    pytest.param(lambda doc: {k: v for k, v in doc.items() if k != 'detail'},
                 'detail must be {"minzoom": 11, "maxzoom": 14}', id='C3: missing detail'),
    pytest.param(lambda doc: {**doc, 'detail': []},
                 'detail must be {"minzoom": 11, "maxzoom": 14}', id='C3: detail not an object'),
    pytest.param(lambda doc: {**doc, 'detail': {'minzoom': 12, 'maxzoom': 14}},
                 'detail must be {"minzoom": 11, "maxzoom": 14}', id='C1: wrong detail minimum'),
    pytest.param(lambda doc: {**doc, 'detail': {'minzoom': 11, 'maxzoom': 15}},
                 'detail must be {"minzoom": 11, "maxzoom": 14}', id='C1: wrong detail maximum'),
    pytest.param(lambda doc: {**doc, 'detail': {**doc['detail'], 'extra': 1}},
                 'detail must be {"minzoom": 11, "maxzoom": 14}', id='C1: extra detail field'),
    pytest.param(lambda doc: {k: v for k, v in doc.items() if k != 'overview'},
                 'overview must be an object', id='C3: missing overview'),
    pytest.param(lambda doc: {**doc, 'overview': None},
                 'overview must be an object', id='C3: overview not an object'),
    pytest.param(lambda doc: {**doc, 'overview': {}},
                 'overview.maxzoom must be 10', id='C3: missing overview maximum'),
    pytest.param(lambda doc: {**doc, 'overview': {**doc['overview'], 'maxzoom': 11}},
                 'overview.maxzoom must be 10', id='C1: wrong overview maximum'),
    pytest.param(lambda doc: {**doc, 'overview': {'maxzoom': 10}},
                 'overview.bbox must be an array of four finite, ordered numbers', id='C3: missing overview bbox'),
    pytest.param(lambda doc: {k: v for k, v in doc.items() if k != 'regions'},
                 'regions must be a list', id='C3: missing regions'),
    pytest.param(lambda doc: {**doc, 'regions': {}}, 'regions must be a list', id='C3: regions not a list'),
    pytest.param(lambda doc: {**doc, 'regions': [None]},
                 'regions[0] must be an object', id='C3: invalid region entry'),
    pytest.param(lambda doc: {**doc, 'regions': [{'bbox': [0, 0, 1, 1]}]},
                 'regions[0].id must be a nonempty string', id='C3: missing region id'),
])
def test_c1_c3_misshaped_manifest_names_file_and_field(saved_manifest, mutate, message):
    """C1: Refuse a wrong zoom split. C3: A malformed field never causes a traceback."""
    path, document = saved_manifest
    path.write_text(json.dumps(mutate(document)))
    result = _detail_cli('--manifest', path)
    assert (result.returncode, result.stdout, result.stderr) == (1, b'', f'FAIL: pointer.json: {message}\n'.encode())


@pytest.mark.parametrize('box', [
    pytest.param({'id': 'a'}, id='C3: missing detail bbox'),
    pytest.param({'id': 'a', 'bbox': '0,0,1,1'}, id='C3: bbox not an array'),
    pytest.param({'id': 'a', 'bbox': [0, 0, 1]}, id='C3: short bbox'),
    pytest.param({'id': 'a', 'bbox': [0, 0, '1', 1]}, id='C3: string coordinate'),
    pytest.param({'id': 'a', 'bbox': [0, 0, True, 1]}, id='C3: boolean coordinate'),
    pytest.param({'id': 'a', 'bbox': [0, 0, float('nan'), 1]}, id='C3: NaN coordinate'),
    pytest.param({'id': 'a', 'bbox': [0, 0, float('inf'), 1]}, id='C3: infinite coordinate'),
    pytest.param({'id': 'a', 'bbox': [1, 0, 0, 1]}, id='C3: reversed longitude'),
    pytest.param({'id': 'a', 'bbox': [0, 1, 1, 1]}, id='C3: zero latitude span'),
])
def test_c3_rejects_unusable_detail_boxes(saved_manifest, box):
    """C3: Reject a bad declared bbox even when the other boxes cover all regions."""
    path, document = saved_manifest
    document['regions'].insert(0, box)
    path.write_text(json.dumps(document))
    result = _detail_cli('--manifest', path)
    assert (result.returncode, result.stdout, result.stderr) == (
        1, b'', b'FAIL: pointer.json: regions[0].bbox must be an array of four finite, ordered numbers\n',
    )


@pytest.mark.parametrize('data,message', [
    pytest.param(None, 'cannot read: No such file or directory', id='C3: missing file'),
    pytest.param(b'{"regions": ', 'not valid JSON (line 1 column 13)', id='C3: bad JSON'),
    pytest.param(b'\xff', 'not valid JSON (invalid text encoding)', id='C3: bad text encoding'),
])
def test_c3_reports_manifest_load_failures(tmp_path, data, message):
    """C3: File and parser failures keep the pointer basename and whole diagnostic."""
    path = tmp_path / 'pointer.json'
    if data is not None:
        path.write_bytes(data)
    result = _detail_cli('--manifest', path)
    assert (result.returncode, result.stdout, result.stderr) == (1, b'', f'FAIL: pointer.json: {message}\n'.encode())


def test_c4_manifest_and_dir_are_mutually_exclusive(tmp_path, monkeypatch):
    """C4: Neither option can silently take precedence over the other."""
    monkeypatch.setenv('COLUMNS', '80')
    result = _detail_cli('--dir', tmp_path, '--manifest', tmp_path / 'pointer.json')
    assert (result.returncode, result.stdout, result.stderr) == (
        2, b'', b'usage: check_detail.py [-h] [--dir DIR | --manifest PATH]\n'
        b'check_detail.py: error: argument --manifest: not allowed with argument --dir\n',
    )


def test_c4_default_and_saved_plan_keep_legacy_bytes(tmp_path):
    """C4: Do not replace extraction output with the indexed-only manifest report."""
    legacy_rows = """\
big-sur-coast|big-sur-coast [-122.2, 35.9, -121.45, 36.3]
bodega-point-reyes|bodega-point-reyes [-123.7, 37.95, -122.7, 38.5]
cambria-san-simeon|cambria-san-simeon, morro-bay [-121.95, 35.45, -120.95, 35.66]
channel-islands-north|southern-california [-120.6, 33.85, -119.3, 34.15]
crescent-city|crescent-city [-124.75, 41.55, -124.05, 42.0]
fort-bragg-point-arena|fort-bragg-point-arena [-124.4, 38.958333333333336, -123.25, 39.45]
humboldt-bay-cape-mendocino|humboldt-bay-cape-mendocino [-124.8, 40.166666666666664, -123.9, 40.95]
monterey-point-sur|monterey-point-sur [-122.35, 36.3, -121.65, 36.625]
morro-bay|morro-bay [-121.95, 34.95, -120.55, 35.85]
outer-islands-borderland|southern-california [-119.7, 32.75, -118.25, 33.6]
point-arena-bodega|point-arena-bodega [-124.2, 38.4, -122.85, 39.0]
point-arguello-conception|point-arguello-conception [-121.25, 34.45, -120.35, 35.07]
point-reyes-pigeon|point-reyes-pigeon [-123.3, 37.18333333333333, -122.28, 37.95]
san-diego|southern-california [-117.6, 32.5343, -117.05, 33.4]
san-pedro-orange-county|southern-california [-118.35, 33.35, -117.5, 33.8]
santa-barbara-channel|southern-california [-120.65, 34.0, -118.95, 34.45]
santa-cruz-monterey-bay|santa-cruz-monterey-bay [-122.75, 36.6, -121.6, 37.18333333333333]
santa-monica-palos-verdes|southern-california [-119.0, 33.65, -118.25, 34.05]
shelter-cove-north-mendocino|shelter-cove-north-mendocino [-124.8, 39.45, -123.6, 40.166666666666664]
south-big-sur-san-simeon|south-big-sur-san-simeon [-122.0, 35.66, -121.2, 35.9]
southern-california|southern-california [-121.0, 32.5, -117.05, 34.45]
trinidad-klamath|trinidad-klamath [-124.6, 40.95, -124.0, 41.55]
"""
    expected = ''.join(f'PASS {region_id}: zooms 11–14 inside detail box {box}\n'
                       for region_id, box in (row.split('|') for row in legacy_rows.splitlines()))
    expected += '22 of 22 regions inside a detail box (extract settings only; not archive coverage)\n'
    planned, detail = settings()
    (tmp_path / 'plan.json').write_text(json.dumps(planned))
    (tmp_path / 'detail.geojson').write_text(json.dumps(detail))
    for args in ((), ('--dir', tmp_path)):
        result = _detail_cli(*args)
        assert (result.returncode, result.stdout, result.stderr) == (0, expected.encode(), b'')
