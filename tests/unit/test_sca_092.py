"""Offline CLI regression coverage for USGS discovery-bound XML evidence."""
import io
import json
import sys
from datetime import datetime, timedelta, timezone

import pytest

from research.scripts import audit_usgs_doi_metadata as doi
from research.scripts import audit_usgs_map_metadata as maps

XML = b'<metadata><bounding><westbc>1</westbc><eastbc>2</eastbc><southbc>3</southbc><northbc>4</northbc></bounding></metadata>'
MAP = 'https://pubs.usgs.gov/ds/781/OffshoreFixture/'
DOI = 'https://cmgds.marine.usgs.gov/data-releases/'
MEDIA = DOI + 'media/2000/10.5066-P9FIXTURE/'
TIME = datetime(2025, 1, 1, tzinfo=timezone.utc)


@pytest.fixture(params=[maps, doi], ids=['map', 'doi'])
def cli(request, tmp_path, monkeypatch):
    mod = request.param
    is_map = mod is maps
    key = 'blocks' if is_map else 'releases'
    products = [
        {'metadata_url': (MAP + 'metadata/' if is_map else MEDIA) + f'Bathymetry_{n}.xml',
         'archive_url': (MAP + 'data/' if is_map else MEDIA) + f'Bathymetry_{n}.zip',
         'kind': 'bathymetry', 'filename': f'Bathymetry_{n}.zip'}
        for n in range(2)
    ]
    row: dict = {'status': 'ok', 'checked_at': TIME.isoformat()}
    if is_map:
        row.update(id='OffshoreFixture', catalog_url=MAP + 'data_catalog_fixture.html',
                   products={'bathymetry': products})
    else:
        row.update(release_id='P9FIXTURE', doi='https://doi.org/10.5066/P9FIXTURE', study_areas=['Z', 'A'],
                   landing_url=DOI + 'datarelease/10.5066-P9FIXTURE/', products=products)
    discovery = {'scope': f'usgs-state-waters-{"map-block" if is_map else "doi-product"}-links',
                 'health': {'status': 'ok', 'issues': []}, 'collected_at': TIME.isoformat(), key: [row]}
    if is_map:
        discovery.update(block_count=1, catalog_family='ds781', source_url='https://pubs.usgs.gov/ds/781/')
    else:
        discovery.update(index_url='https://pubs.usgs.gov/ds/781/')
    source, previous, out = (tmp_path / name for name in ('input.json', 'previous.json', 'out.json'))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return point

    monkeypatch.setattr(maps, 'datetime', Clock)
    if not is_map:
        monkeypatch.setattr(doi, 'datetime', Clock)

    def run(*, cached=None, when=TIME, calls=None, fail=()):
        nonlocal point
        point = when
        if cached is not None:
            previous.write_bytes(cached)
        out.unlink(missing_ok=True)
        monkeypatch.setattr(sys, 'argv', ['audit', f'--{key}', str(source), '--previous', str(previous), '--output', str(out)])

        class Response(io.BytesIO):
            def __init__(self, url):
                super().__init__(XML)
                self.url = url

        def open_xml(req, *, timeout):
            if calls is None:
                raise AssertionError('unexpected XML request')
            calls.append(req.full_url)
            if req.full_url in fail:
                raise OSError('synthetic source failure')
            return Response(req.full_url)

        monkeypatch.setattr(mod, 'urlopen', open_xml)
        mod.main()
        return out.read_bytes()

    point = TIME
    return is_map, key, discovery, row, products, source, out, run


def write(path, data):
    path.write_text(json.dumps(data), encoding='utf-8')


def seed(cli):
    _, _, discovery, _, products, source, _, run = cli
    write(source, discovery)
    calls = []
    first = json.loads(run(calls=calls))
    assert sorted(calls) == sorted(item['metadata_url'] for item in products)
    assert first['health']['status'] == 'ok'
    assert first['verified_metadata_count'] == 2
    assert first['last_complete_scan_at'] == TIME.isoformat()
    return json.dumps(first, indent=2).encode() + b'\n\n'


def test_same_semantic_inventory_preserves_bytes_without_http(cli):
    cached = seed(cli)
    is_map, _, discovery, row, products, source, _, run = cli
    tomorrow = TIME + timedelta(days=1)
    products.reverse()
    if not is_map:
        row['study_areas'].reverse()
    row['checked_at'] = discovery['collected_at'] = tomorrow.isoformat()
    write(source, discovery)
    assert run(cached=cached, when=tomorrow) == cached


@pytest.mark.parametrize('change', ['add', 'remove', 'archive', 'attribution', 'catalog_or_landing'])
def test_changed_inventory_reconciles_current_products_on_fetch_failure(cli, change):
    cached = seed(cli)
    is_map, _, discovery, row, products, source, _, run = cli
    original_urls = {item['metadata_url'] for item in products}
    if change == 'add':
        products.append({key: value.replace('_1.', '_2.') for key, value in products[-1].items()})
    elif change == 'remove':
        products.pop()
    elif change == 'archive':
        products[-1]['archive_url'] = products[-1]['archive_url'].replace('_1.', '_2.')
    elif change == 'attribution':
        if is_map:
            row['catalog_url'] = MAP + 'data_catalog_revised.html'
        else:
            row['study_areas'] = ['New attribution']
    elif is_map:
        discovery['catalog_family'] = 'csmp'
    else:
        row['landing_url'] += 'revised/'
    write(source, discovery)
    urls = {item['metadata_url'] for item in products}
    retained_urls = (original_urls & urls) if change in ('add', 'remove') else (
        {products[0]['metadata_url']} if change == 'archive' else set())
    calls = []
    result = json.loads(run(cached=cached, when=TIME + timedelta(days=1), calls=calls, fail=urls))
    assert sorted(calls) == sorted(urls)
    assert {row['metadata_url']: row['status'] for row in result['records']} == {
        url: 'retained' if url in retained_urls else 'failed' for url in urls}
    assert result['verified_metadata_count'] == 0
    assert result['health']['status'] == 'degraded'
    assert result['last_complete_scan_at'] == TIME.isoformat()
    assert all(r['checked_at'] == (TIME.isoformat() if r['metadata_url'] in retained_urls else None)
               for r in result['records'])


@pytest.mark.parametrize('invalid', ['missing', 'scope', 'product'])
def test_invalid_current_input_cannot_copy_a_recent_complete_audit(cli, invalid):
    cached = seed(cli)
    _, _, discovery, _, products, source, out, run = cli
    if invalid == 'missing':
        source.unlink()
    elif invalid == 'scope':
        discovery['scope'] = 'wrong-scope'
        write(source, discovery)
    else:
        products[0]['metadata_url'] = 'https://invalid.example/other.xml'
        write(source, discovery)
    with pytest.raises(FileNotFoundError if invalid == 'missing' else ValueError):
        run(cached=cached)
    assert not out.exists()


def test_no_targets_never_start_or_advance_complete_clock(cli):
    cached = seed(cli)
    is_map, key, discovery, _, _, source, _, run = cli
    discovery[key].clear()
    if is_map:
        discovery['block_count'] = 0
    write(source, discovery)
    tomorrow = TIME + timedelta(days=1)
    for previous, expected in ((None, None), (cached, TIME.isoformat())):
        data = json.loads(run(cached=previous, when=tomorrow))
        assert data['health']['status'] == 'degraded'
        assert data['record_count'] == data['verified_metadata_count'] == 0
        assert data['last_complete_scan_at'] == expected


@pytest.mark.parametrize('failure', ['degraded-health', 'retained-source-row'])
def test_upstream_failure_cannot_copy_or_advance_complete_clock(cli, failure):
    cached = seed(cli)
    _, _, discovery, row, products, source, _, run = cli
    if failure == 'degraded-health':
        discovery['health'] = {'status': 'degraded', 'issues': ['upstream error']}
    else:
        row['status'] = 'retained'
    write(source, discovery)
    calls = []
    result = json.loads(run(cached=cached, when=TIME + timedelta(days=1), calls=calls))
    assert sorted(calls) == sorted(item['metadata_url'] for item in products)
    assert result['health']['status'] == 'degraded'
    assert result['last_complete_scan_at'] == TIME.isoformat()


def test_unbound_legacy_audit_rescans_and_binds_on_success(cli):
    cached = json.loads(seed(cli))
    cached.pop('inventory_sha256', None)
    _, _, _, _, products, _, _, run = cli
    calls = []
    tomorrow = TIME + timedelta(days=1)
    result = json.loads(run(cached=json.dumps(cached).encode(), when=tomorrow, calls=calls))
    assert sorted(calls) == sorted(item['metadata_url'] for item in products)
    assert result['last_complete_scan_at'] == tomorrow.isoformat()
    assert result['verified_metadata_count'] == 2
