"""F27-07: seed and replay the real survey search caches using only synthetic responses."""
from hashlib import sha256
from io import BytesIO
import json

import pytest

from research.scripts import audit_monterey_ncei_trackline_leads as leads


ENDPOINT = 'https://example.invalid/ArcGIS/MapServer/0/query'
CASES = ('same-request', 'disjoint-polygon-same-id', 'changed-service', 'changed-layer',
         'changed-crs', 'changed-fields', 'changed-filter', 'legacy-response', 'swapped-response')


def _polygon(x):
    return {'type': 'Polygon', 'coordinates': [[[x, 0], [x + 1, 0], [x + 1, 1], [x, 1], [x, 0]]]}


def _deny_transport(*_args, **_kwargs):
    raise AssertionError('offline replay must not open a transport')


def _check_cache(monkeypatch, case, cache, query, module, rows, change_contract):
    # An ID-only lookup returns the previous rows in all six request variants.
    # A request-only receipt also accepts a different, valid response under the same ID.
    geometry = _polygon(0)
    raw = json.dumps({'features': [{'attributes': row} for row in rows]}).encode()
    if case == 'legacy-response':
        cache.parent.mkdir(parents=True)
        cache.write_bytes(raw)
    else:
        monkeypatch.setattr(module, 'urlopen', lambda *_args, **_kwargs: BytesIO(raw))
        expected_rows, digest = query(geometry, fetch=True)
        assert expected_rows and digest == sha256(raw).hexdigest()
        assert cache.read_bytes() == raw
        if case == 'same-request':
            monkeypatch.setattr(module, 'urlopen', _deny_transport)
            # Equivalent JSON object insertion order has no effect on the request.
            assert query(dict(reversed(tuple(geometry.items()))), fetch=False) == (expected_rows, digest)
            return
    monkeypatch.setattr(module, 'urlopen', _deny_transport)
    if case == 'disjoint-polygon-same-id':
        geometry = _polygon(3)
    elif case == 'changed-crs':
        encode = leads.esri_polygon
        monkeypatch.setattr(leads, 'esri_polygon', lambda geometry: {
            **encode(geometry), 'spatialReference': {'wkid': 3857},
        })
    elif case == 'swapped-response':
        # Independently valid JSON and rows, different response bytes.
        cache.write_bytes(raw + b'\n')
    elif case != 'legacy-response':
        change_contract(case)
    before = cache.read_bytes()
    with pytest.raises(ValueError, match='NCEI query cache'):
        query(geometry, fetch=False)
    assert cache.read_bytes() == before


def _changed_endpoint(case):
    if case == 'changed-service':
        return ENDPOINT.replace('example.invalid', 'other.invalid')
    return ENDPOINT.replace('/0/', '/1/')


@pytest.mark.parametrize('case', CASES)
@pytest.mark.parametrize('kind', ('footprint', 'trackline'))
def test_survey_leads_reuse_only_bound_responses(tmp_path, monkeypatch, kind, case):
    monkeypatch.setitem(leads.SERVICES, kind, ENDPOINT)
    rows = [{'OBJECTID': 1, 'SURVEY_ID': 'synthetic', 'SURVEY_YEAR': 2000,
             'DOWNLOAD_URL': 'https://www.ncei.noaa.gov/unused-fixture'}]
    cache = tmp_path / 'var/review/ncei-monterey-tracklines' / f'synthetic-{kind}.json'

    def query(geometry, fetch):
        return leads.query(tmp_path, 'synthetic', geometry, kind, fetch)

    def change_contract(change):
        if change == 'changed-fields':
            monkeypatch.setitem(leads.FIELDS, kind, 'OBJECTID')
        elif change == 'changed-filter':
            monkeypatch.setattr(leads, 'FILTER', 'OBJECTID=2')
        else:
            monkeypatch.setitem(leads.SERVICES, kind, _changed_endpoint(change))

    _check_cache(monkeypatch, case, cache, query, leads, rows, change_contract)


@pytest.mark.gis
@pytest.mark.parametrize('case', CASES)
def test_per_file_lookup_reuses_only_bound_responses(tmp_path, monkeypatch, case):
    from research.scripts import audit_monterey_2009_ncei_valid_beams as beams

    stem = '20091103_191445'  # Existing priority case; no native files are inspected.
    prefix = 'ocean/ships/ventresca/CentralMontereyBay/multibeam/data/version2/MB/reson7125_400/'
    rows = [{'FILE_ID': 1, 'DATA_TYPE': 'MB PROCESSED', 'DATA_FILE': prefix + beams.file_name(stem),
             'SURVEY_NAME': 'CentralMontereyBay', 'NGDC_ID': 'NEW2895', 'MBIO_FORMAT_ID': '121'},
            {'DATA_TYPE': 'MB RAW'}]
    monkeypatch.setattr(beams, 'PROCESSED', {stem: (1,)})
    monkeypatch.setattr(beams, 'FILE_LAYER', ENDPOINT)
    cache = tmp_path / 'var/review/ncei-centralmontereybay-priority/023-file-layer.json'

    def query(geometry, fetch):
        return beams.query_file_layer(tmp_path, '023', geometry, fetch)

    def change_contract(change):
        if change == 'changed-fields':
            monkeypatch.setattr(beams, 'FILE_FIELDS', 'OBJECTID')
        elif change == 'changed-filter':
            monkeypatch.setattr(beams, 'FILE_FILTER', 'OBJECTID=2')
        else:
            monkeypatch.setattr(beams, 'FILE_LAYER', _changed_endpoint(change))

    _check_cache(monkeypatch, case, cache, query, beams, rows, change_contract)
