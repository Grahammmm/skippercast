"""F31-02: reconcile requested USGS work before filtering on prerequisite evidence."""

import hashlib
import json
import sys
import zipfile

import pytest

from research.scripts import fetch_hard_footprint_usgs_class as class_fetch


def no_transport(*args, **kwargs):
    pytest.fail('This receipt must be produced without a transport call')


@pytest.mark.parametrize(('selection', 'status', 'verified', 'missing'), [
    ('mixed', 'partial', 1, ['SYNTHETIC-B']),
    ('unmatched', 'partial', 0, ['SYNTHETIC-B']),
    ('matched', 'complete', 2, []),
    ('empty', 'empty', 0, []),
])
def test_class_fetch_counts_inventory_ids(tmp_path, monkeypatch, selection, status, verified, missing):
    # A tile's requested ID must survive the audit join and a duplicate tile ID
    # must not inflate the denominator. The actual cache/hash path stays in use.
    first, second = 'SYNTHETIC-A', 'SYNTHETIC-B'
    wanted = {'mixed': [first, second], 'unmatched': [second],
              'matched': [first, second], 'empty': []}[selection]
    inventory = tmp_path / 'inventory.json'
    inventory.write_text(json.dumps({
        'scope': 'noaa-nbs-tiles-intersecting-displayed-usgs-hard-context',
        'tiles': [{'source_ids': wanted}, {'source_ids': wanted}],
    }))
    options = []
    for prefix, id_key, ident in [('usgs', 'release_id', first), ('map', 'block_id', second)]:
        audit, cache = tmp_path / f'{prefix}.json', tmp_path / prefix
        options.extend((f'--{prefix}-audit', str(audit), f'--{prefix}-cache', str(cache)))
        cache.mkdir()
        if selection == 'empty' or (selection == 'unmatched' and ident == second):
            continue
        archive = cache / 'seed.zip'
        with zipfile.ZipFile(archive, 'w') as bundle:
            bundle.writestr('synthetic.txt', ident)
        data = archive.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        ready = ident == first or selection == 'matched'
        if ready:
            archive.rename(cache / f'{ident}-seafloor_character-{digest[:16]}.zip')
        audit.write_text(json.dumps({'products': [{
            id_key: ident, 'kind': 'seafloor_character', 'status': 'ok' if ready else 'failed',
            'archive_url': f'https://pubs.usgs.gov/{ident}.zip',
            'archive_sha256': digest, 'archive_bytes': len(data),
        }]}))

    output = tmp_path / 'receipt.json'
    monkeypatch.setattr(class_fetch, 'urlopen', no_transport)
    monkeypatch.setattr(sys, 'argv', ['class-fetch', '--inventory', str(inventory),
                                      '--output', str(output), *options])
    if missing:
        with pytest.raises(SystemExit) as exit_info:
            class_fetch.main()
        assert exit_info.value.code == 1
    else:
        class_fetch.main()
    report = json.loads(output.read_text())
    assert (report['status'], report['requested'], report['verified'], report['failed']) == (
        status, len(wanted), verified, len(missing))
    assert {row['release_id'] for row in report['archives']} == set(wanted) - set(missing)
    assert [row['release_id'] for row in report['failures']] == missing
    assert all('audit' in row['error'] for row in report['failures'])


def test_class_fetch_holds_source_when_one_of_its_archives_failed_audit(tmp_path, monkeypatch):
    # Contract: a source is verified only if every audited archive verifies.
    # Bug caught: a successful row for the same source masked its failed row,
    # reporting 'complete: 1 / 1 verified' despite a failed prerequisite.
    ident = 'SYNTHETIC-A'
    inventory = tmp_path / 'inventory.json'
    inventory.write_text(json.dumps({
        'scope': 'noaa-nbs-tiles-intersecting-displayed-usgs-hard-context',
        'tiles': [{'source_ids': [ident]}]}))
    cache = tmp_path / 'usgs'
    cache.mkdir()
    data = b'synthetic archive'
    digest = hashlib.sha256(data).hexdigest()
    (cache / f'{ident}-seafloor_character-{digest[:16]}.zip').write_bytes(data)
    base = {'release_id': ident, 'kind': 'seafloor_character', 'archive_bytes': len(data),
            'archive_url': f'https://pubs.usgs.gov/{ident}.zip', 'archive_sha256': digest}
    (tmp_path / 'usgs.json').write_text(json.dumps({'products': [
        {**base, 'status': 'ok'},
        {**base, 'status': 'failed', 'archive_sha256': '1' * 64}]}))
    output = tmp_path / 'receipt.json'
    monkeypatch.setattr(class_fetch, 'urlopen', no_transport)
    monkeypatch.setattr(sys, 'argv', [
        'class-fetch', '--inventory', str(inventory), '--output', str(output),
        '--usgs-audit', str(tmp_path / 'usgs.json'), '--usgs-cache', str(cache),
        '--map-audit', str(tmp_path / 'absent.json'), '--map-cache', str(tmp_path / 'map')])
    with pytest.raises(SystemExit) as exit_info:
        class_fetch.main()
    assert exit_info.value.code == 1
    report = json.loads(output.read_text())
    assert (report['status'], report['requested'], report['verified'], report['failed']) == ('partial', 1, 0, 1)
    assert [row['archive_sha256'] for row in report['archives']] == [digest]
    assert [(row['release_id'], row['archive_sha256']) for row in report['failures']] == [(ident, '1' * 64)]


def test_class_fetch_holds_source_when_one_of_its_archives_was_omitted(tmp_path, monkeypatch):
    # Contract: the native audit's `omissions` (archives never inspected for
    # missing metadata) hold their source like a failed row does.
    # Bug caught: one inspected archive masked a sibling omission, reporting
    # 'complete: 1 / 1 verified'. A non-seafloor omission must not hold it.
    ident = 'SYNTHETIC-A'
    inventory = tmp_path / 'inventory.json'
    inventory.write_text(json.dumps({
        'scope': 'noaa-nbs-tiles-intersecting-displayed-usgs-hard-context',
        'tiles': [{'source_ids': [ident]}]}))
    cache = tmp_path / 'usgs'
    cache.mkdir()
    data = b'synthetic archive'
    digest = hashlib.sha256(data).hexdigest()
    (cache / f'{ident}-seafloor_character-{digest[:16]}.zip').write_bytes(data)
    base = {'release_id': ident, 'kind': 'seafloor_character', 'archive_bytes': len(data),
            'archive_url': f'https://pubs.usgs.gov/{ident}.zip', 'archive_sha256': digest}
    omission = {'release_id': ident, 'kind': 'seafloor_character',
                'archive_url': f'https://pubs.usgs.gov/{ident}-2.zip',
                'metadata_url': f'https://pubs.usgs.gov/{ident}-2.xml',
                'issue': 'No successful original metadata audit'}
    audit = tmp_path / 'usgs.json'
    audit.write_text(json.dumps({'products': [{**base, 'status': 'ok'}], 'omissions': [
        omission, {**omission, 'kind': 'bathymetry'}]}))
    output = tmp_path / 'receipt.json'
    monkeypatch.setattr(class_fetch, 'urlopen', no_transport)
    monkeypatch.setattr(sys, 'argv', [
        'class-fetch', '--inventory', str(inventory), '--output', str(output),
        '--usgs-audit', str(audit), '--usgs-cache', str(cache),
        '--map-audit', str(tmp_path / 'absent.json'), '--map-cache', str(tmp_path / 'map')])
    with pytest.raises(SystemExit) as exit_info:
        class_fetch.main()
    assert exit_info.value.code == 1
    report = json.loads(output.read_text())
    assert (report['status'], report['requested'], report['verified'], report['failed']) == ('partial', 1, 0, 1)
    assert [row['archive_sha256'] for row in report['archives']] == [digest]
    assert [(row['release_id'], 'omitted' in row['error']) for row in report['failures']] == [(ident, True)]

    # Without the seafloor omission the same source verifies completely.
    audit.write_text(json.dumps({'products': [{**base, 'status': 'ok'}],
                                 'omissions': [{**omission, 'kind': 'bathymetry'}]}))
    class_fetch.main()
    assert json.loads(output.read_text())['status'] == 'complete'


@pytest.fixture
def raster_zip(tmp_path):
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    tif = tmp_path / 'synthetic.tif'
    with rasterio.open(tif, 'w', driver='GTiff', width=2, height=2, count=1,
                       dtype='uint8', crs='EPSG:4326', transform=from_origin(0, 1, 0.5, 0.5)) as raster:
        raster.write(np.full((2, 2), 3, dtype='uint8'), 1)
    archive = tmp_path / 'synthetic.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        bundle.write(tif, tif.name)
    return archive.read_bytes()


@pytest.mark.gis
@pytest.mark.parametrize('family', ['doi', 'map'])
@pytest.mark.parametrize(('selection', 'status', 'count', 'inspected'), [
    ('mixed', 'degraded', 2, 1), ('matched', 'ok', 2, 2), ('non-grid-only', 'empty', 0, 0),
])
def test_native_inspections_reconcile_catalog_products(tmp_path, raster_zip, family, selection,
                                               status, count, inspected):
    # Metadata availability decides whether work can run, not whether a grid
    # was requested. Non-grid products do not become missing prerequisites.
    from research.scripts import inspect_usgs_doi_grids as doi, inspect_usgs_native_grids as native

    ident = 'SYNTHETIC'
    if family == 'doi':
        prefix = f'https://cmgds.marine.usgs.gov/data-releases/media/10.5066-{ident}'
        id_key, scope, inspect = 'release_id', 'doi-', doi.inspect
    else:
        prefix = f'https://pubs.usgs.gov/ds/781/{ident}'
        id_key, scope, inspect = 'block_id', '', native.inspect

    kinds = ['cmecs'] if selection == 'non-grid-only' else ['bathymetry', 'seafloor_character', 'cmecs']
    products, records = [], []
    for kind in kinds:
        archive_url = f'{prefix}/data/{kind}.zip'
        metadata_url = f'{prefix}/metadata/{kind}.xml'
        products.append({'kind': kind, 'archive_url': archive_url, 'metadata_url': metadata_url,
                         'description': kind, 'filename': f'{kind}.zip'})
        if kind == 'cmecs':
            records.append({'status': 'ok', id_key: ident, 'kind': kind, 'metadata_url': metadata_url})
            continue
        if kind == 'seafloor_character' and selection == 'mixed':
            if family == 'map':
                records.append({'status': 'failed', id_key: ident, 'kind': kind, 'metadata_url': metadata_url})
            continue
        records.append({'status': 'ok', id_key: ident, 'kind': kind, 'metadata_url': metadata_url,
                        'xml_sha256': '0' * 64,
                        'bounds': {'westbc': 0, 'eastbc': 1, 'southbc': 0, 'northbc': 1}})
        key = hashlib.sha256(archive_url.encode()).hexdigest()[:16]
        (tmp_path / f'{ident}-{kind}-{key}.zip').write_bytes(raster_zip)
    if family == 'doi':
        inventory = {'scope': 'usgs-state-waters-doi-product-links', 'releases': [{
            id_key: ident, 'status': 'ok', 'study_areas': ['Synthetic'],
            'landing_url': f'{prefix}/index.html', 'products': products,
        }]}
    else:
        inventory = {'scope': 'usgs-state-waters-map-block-links', 'blocks': [{
            'id': ident, 'products': {product['kind']: [product] for product in products},
        }]}
    report = inspect(inventory, {'scope': f'usgs-state-waters-{scope}native-metadata',
                                 'records': records}, tmp_path, fetcher=no_transport)
    assert (report['health']['status'], report['product_count'], report['inspected_count']) == (
        status, count, inspected)
    assert [row['kind'] for row in report['products'] if row['valid_pixels'] == 4] == kinds[:inspected]
    if selection == 'mixed':
        omission, = report['omissions']
        assert (omission[id_key], omission['kind'], omission['archive_url'], omission['metadata_url']) == (
            ident, 'seafloor_character', products[1]['archive_url'], products[1]['metadata_url'])
        assert 'metadata audit' in omission['issue']
        assert report['health']['issues'] == [omission['archive_url']]
    else:
        assert report.get('omissions', []) == report['health']['issues'] == []
