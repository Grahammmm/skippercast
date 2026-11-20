"""Incremental shore builds remove only the withdrawn region's managed layer."""

import json

from skippercast.platform.build import compile_shore_habitat


def shore_source(region_id):
    stamp = '2026-01-01T00:00:00Z'
    expires = '2027-01-01T00:00:00Z'
    url = 'https://example.org/fixture'
    receipt = {'url': url, 'fetchedAt': stamp, 'responseSha256': '0' * 64, 'bytes': 1}
    return json.dumps({
        'type': 'FeatureCollection', 'schemaVersion': 1, 'countyId': 'fictional',
        'regionId': region_id, 'builtAt': stamp, 'sourceYear': 2006,
        'sourceChecks': {
            'noaaUrl': url, 'accessUrl': url, 'accessTermsUrl': url, 'accessTerms': 'Synthetic fixture',
            'acquisitions': dict.fromkeys(('noaa', 'access', 'terms'), receipt),
        },
        'reviews': dict.fromkeys(('source', 'access', 'legal'), {'reviewedAt': stamp, 'expiresAt': expires}),
        'limitations': ['Synthetic fixture'],
        'features': [{
            'type': 'Feature', 'id': 'fictional-shore',
            'geometry': {'type': 'MultiLineString', 'coordinates': [[[0, 0], [0, 1]]]},
            'properties': {
                'id': 'fictional-shore', 'name': 'Fictional shore', 'areaId': 'central', 'region': region_id,
                'substrate': 'sand', 'shoreClass': '3A', 'sourceYear': 2006,
                'sourceUrl': url, 'sourceObjectIds': [1], 'geometryMethod': 'Synthetic line',
                'horizontalAccuracyM': None, 'accessUrl': url, 'checkedAt': stamp, 'reviewExpiresAt': expires,
                'accessReviewedAt': stamp, 'accessReviewExpiresAt': expires,
                'legalReviewedAt': stamp, 'legalReviewExpiresAt': expires, 'legalSourceUrl': url,
                'license': 'Synthetic fixture', 'attribution': 'Synthetic fixture',
                'access': [{'id': 'ccc-1', 'name': 'Fictional point', 'coordinates': [0, 0],
                            'sourceUrl': url, 'publicAccess': True, 'checkedAt': stamp, 'note': 'Synthetic fixture'}],
            },
        }],
    }).encode()


def test_shore_rebuild_removes_only_withdrawn_layer(tmp_path):
    catalog = tmp_path / 'catalog/shore-habitat'
    catalog.mkdir(parents=True)
    staging = tmp_path / 'dist/regions'
    regions = [{'id': ident, 'bounds': [-1, -1, 2, 2]} for ident in ('withdrawn', 'retained')]
    for region in regions:
        ident = region['id']
        (staging / ident).mkdir(parents=True)
        (catalog / f'{ident}.geojson').write_bytes(shore_source(ident))

    # Preserve a sibling chart asset, a similarly named file, and a same-name
    # file in a directory not managed by this build.
    controls = {
        staging / 'withdrawn/shoreline.geojson': b'other chart layer',
        staging / 'withdrawn/shore-habitat-extra.geojson': b'other shore file',
        staging / 'unmanaged/shore-habitat.geojson': b'unmanaged region',
    }
    (staging / 'unmanaged').mkdir()
    for path, content in controls.items():
        path.write_bytes(content)

    compile_shore_habitat(tmp_path, regions)
    withdrawn = staging / 'withdrawn/shore-habitat.geojson'
    retained = staging / 'retained/shore-habitat.geojson'
    assert withdrawn.read_bytes() == shore_source('withdrawn')
    assert retained.read_bytes() == shore_source('retained')

    (catalog / 'withdrawn.geojson').unlink()
    compile_shore_habitat(tmp_path, regions)

    assert not withdrawn.exists()
    assert retained.read_bytes() == (catalog / 'retained.geojson').read_bytes() == shore_source('retained')
    assert {path: path.read_bytes() for path in controls} == controls
