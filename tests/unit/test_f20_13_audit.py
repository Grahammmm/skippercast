"""F20-13: the additive offline rebuild must not attach an unrelated access receipt."""
import hashlib
import json
from unittest import mock

import pytest

from tests.contract.test_shore_habitat import importer, synthetic_bodies


@pytest.mark.parametrize('change', [None, 'subset name', 'parent receipt', 'parent bytes', 'substituted parent'])
def test_added_access_is_bound_to_the_dossier(tmp_path, capsys, change):
    region = 'morro-bay'
    site = importer.ADDED_SITE
    bodies, receipts = synthetic_bodies('2000-01-01T00:00:00Z')
    baseline = importer.build_asset(region, bodies, receipts)
    baseline['features'].pop()
    legacy_pins = {f['id']: hashlib.sha256(importer.feature_bytes(f)).hexdigest() for f in baseline['features']}
    output = tmp_path / 'package.geojson'
    previous = json.dumps(baseline).encode()
    output.write_bytes(previous)
    inode = output.stat().st_ino

    parent = json.loads(bodies['access'])
    site_ids = set(next(s['access'] for s in importer.SITES[region]['sites'] if s['id'] == site))
    subset = {'type': 'FeatureCollection', 'features': [
        {**f, 'properties': {k: f['properties'][k] for k in importer.ACCESS_FIELDS.split(',')}}
        for f in reversed(parent['features']) if f['properties']['OBJECTID'] in site_ids
    ]}

    parent_path = tmp_path / importer.SOURCE_FILES['access']
    parent_path.write_bytes(bodies['access'])
    noaa_url = importer.query_url(importer.NOAA + '/3/query', importer.WINDOWS[site])
    receipts['noaa'] = importer.receipt(noaa_url, bodies['noaa'], receipts['noaa']['fetchedAt'])
    trusted_parent = {k: v for k, v in receipts['access'].items() if k != 'url'}
    if change == 'subset name':
        # This is still a valid public approach; only its binding should fail.
        subset['features'][0]['properties']['Name'] = 'Different synthetic approach'
    elif change == 'parent receipt':
        receipts['access']['fetchedAt'] = '2000-01-02T00:00:00Z'
    elif change in ('parent bytes', 'substituted parent'):
        # Even matching forged metadata must not authorize different parent bytes.
        parent['features'][0]['properties']['Name'] = 'Unrelated synthetic parent change'
        raw = json.dumps(parent).encode()
        parent_path.write_bytes(raw)
        if change == 'substituted parent':
            r = receipts['access']
            receipts['access'] = importer.receipt(r['url'], raw, r['fetchedAt'])
    (tmp_path / importer.RECEIPT_FILE).write_text(json.dumps(receipts), encoding='utf-8')
    (tmp_path / importer.ADD_FILES['noaa']).write_bytes(bodies['noaa'])
    (tmp_path / importer.ADD_FILES['access']).write_text(json.dumps(subset), encoding='utf-8')

    with (mock.patch.object(importer, 'ADDED_ACCESS_PARENT', trusted_parent, create=True),
          mock.patch.object(importer, 'LEGACY_FEATURE_SHA256', legacy_pins),
          mock.patch.object(importer, 'download', side_effect=AssertionError('offline rebuild attempted a download'))):
        status = importer.main(['--sources', str(tmp_path), '--add-site', site, '--output', str(output)])
    if change:
        assert status == 1, f'{change} was accepted'
        assert 'access' in capsys.readouterr().err
        assert output.read_bytes() == previous
        assert output.stat().st_ino == inode
    else:
        assert status == 0, capsys.readouterr().err
        rebuilt = json.loads(output.read_bytes())
        assert rebuilt['features'][:-1] == baseline['features']
        assert rebuilt['reviews'] == baseline['reviews']
        added = rebuilt['features'][-1]['properties']
        assert added['sourceAcquisitions']['access'] == trusted_parent | {'url': receipts['access']['url']}
        assert added['checkedAt'] is added['accessReviewedAt'] is added['legalReviewedAt'] is None
        assert {int(p['id'].removeprefix('ccc-')) for p in added['access']} == site_ids
        for point in added['access']:
            assert point['name'] == f"Synthetic approach {point['id'].removeprefix('ccc-')}"
            assert point['checkedAt'] is None
