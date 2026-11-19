"""F27-07: offline request-bound survey cache controls, not a cache migration.

Run `python -B -m tests.unit.test_f27_07_audit` with survey dependencies to
compare the same cases with the unchanged readers (exit 1 on a gap).
"""
from hashlib import sha256
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import pytest


def _polygon(x):
    return {'rings': [[[x, 0], [x + 1, 0], [x + 1, 1], [x, 1], [x, 0]]]}


REQUEST = {
    'endpoint': 'https://example.invalid/ArcGIS/MapServer/0/query',  # Includes service and layer.
    'geometry': _polygon(0), 'inSR': 4326, 'outFields': 'OBJECTID,SURVEY_ID', 'where': '1=1',
    'spatialRel': 'esriSpatialRelIntersects', 'returnGeometry': False,
}
CASES = (
    ('same-request', {}, True),
    ('disjoint-polygon-same-id', {'geometry': _polygon(3)}, False),
    ('changed-service', {'endpoint': REQUEST['endpoint'].replace('example.invalid', 'other.invalid')}, False),
    ('changed-layer', {'endpoint': REQUEST['endpoint'].replace('/0/', '/1/')}, False),
    ('changed-crs', {'inSR': 3857}, False),
    ('changed-fields', {'outFields': 'OBJECTID'}, False),
    ('changed-filter', {'where': 'OBJECTID=2'}, False),
)


def _fingerprint(request):
    # Canonical serialization of request fields, not a claim of topological
    # equivalence between differently spelled polygons.
    return sha256(json.dumps(request, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _offline(bound_response, request):
    bound_request, response = bound_response
    if _fingerprint(request) != bound_request:
        raise ValueError('cached response does not match request')
    return response


@pytest.mark.parametrize('_name,changes,reusable', CASES, ids=[case[0] for case in CASES])
def test_only_same_request_can_reuse_the_seeded_response(_name, changes, reusable):
    # An ID-only lookup would ignore each change and return stale results.
    cached = (_fingerprint(REQUEST), b'{"features":[]}')
    # Different mapping insertion order must not invalidate an unchanged request.
    request = {**dict(reversed(tuple(REQUEST.items()))), **changes}
    if reusable:
        assert _offline(cached, request) == b'{"features":[]}'
    else:
        with pytest.raises(ValueError, match='does not match request'):
            _offline(cached, request)


def _deny_transport(*_args, **_kwargs):
    raise AssertionError('offline replay must not open a transport')


def _replay():
    from research.scripts import audit_monterey_ncei_trackline_leads as leads
    from research.scripts import audit_monterey_2009_ncei_valid_beams as beams

    def query_leads(root, geometry, kind, endpoint):
        with patch.dict(leads.SERVICES, {kind: endpoint}):
            return leads.query(root, 'synthetic', geometry, kind, fetch=False)

    # Per-file metadata validation still runs with one invented processed ID
    # and one raw row. No GSF lines, companions, or root-level audit are read.
    stem = '20091103_191445'  # Selected by the baseline's fixed priority case.
    prefix = 'ocean/ships/ventresca/CentralMontereyBay/multibeam/data/version2/MB/reson7125_400/'
    file_rows = [{'FILE_ID': 1, 'DATA_TYPE': 'MB PROCESSED', 'DATA_FILE': prefix + beams.file_name(stem),
                  'SURVEY_NAME': 'CentralMontereyBay', 'NGDC_ID': 'NEW2895', 'MBIO_FORMAT_ID': '121'},
                 {'DATA_TYPE': 'MB RAW'}]

    def query_files(root, geometry, endpoint):
        with (patch.object(beams, 'FILE_LAYER', endpoint),
              patch.object(beams, 'PROCESSED', {stem: (1,)})):
            return beams.query_file_layer(root, '023', geometry, fetch=False)

    lead_rows = [{'OBJECTID': 1, 'SURVEY_ID': 'synthetic', 'SURVEY_YEAR': 2000,
                  'DOWNLOAD_URL': 'https://www.ncei.noaa.gov/unused-fixture'}]
    gap = False
    with (TemporaryDirectory() as directory,
          patch.object(leads, 'urlopen', _deny_transport), patch.object(beams, 'urlopen', _deny_transport)):
        root = Path(directory)
        readers = (
            ('footprint', 'ncei-monterey-tracklines/synthetic-footprint.json', lead_rows,
             lambda geometry, endpoint: query_leads(root, geometry, 'footprint', endpoint)),
            ('trackline', 'ncei-monterey-tracklines/synthetic-trackline.json', lead_rows,
             lambda geometry, endpoint: query_leads(root, geometry, 'trackline', endpoint)),
            ('file-layer', 'ncei-centralmontereybay-priority/023-file-layer.json', file_rows,
             lambda geometry, endpoint: query_files(root, geometry, endpoint)),
        )
        for label, leaf, rows, query in readers:
            cache = root / 'var/review' / leaf
            cache.parent.mkdir(parents=True, exist_ok=True)
            raw = json.dumps({'features': [{'attributes': row} for row in rows]}).encode()
            cache.write_bytes(raw)
            before = None
            for name, changes, reusable in CASES[:4]:
                request = {**REQUEST, **changes}
                geometry = {'type': 'Polygon', 'coordinates': request['geometry']['rings']}
                try:
                    actual = query(geometry, request['endpoint'])
                except (ValueError, FileNotFoundError):
                    actual = None
                if reusable:
                    assert actual is not None and actual[0] and actual[1] == sha256(raw).hexdigest()
                    before = actual
                else:
                    assert actual is None or actual == before, 'unexpected result from a single seeded response'
                passed = (actual is not None) == reusable
                gap |= not passed
                observed = 'same cached rows and response hash' if actual is not None else 'refused offline'
                print(f'{label}/{name}: {"PASS" if passed else "GAP"}; {observed}')
            assert cache.read_bytes() == raw
    return int(gap)


if __name__ == '__main__':
    raise SystemExit(_replay())
