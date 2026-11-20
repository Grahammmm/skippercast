"""Malformed normalized metadata must skip one source, not stop R3."""

import numpy as np
import pytest

from tests.gis.test_relief_select import fixture, main, normalized, put, raster, read, registry_row, row_for


@pytest.mark.parametrize(('field', 'value'), [
    pytest.param(None, [], id='sidecar-list'),
    pytest.param(None, None, id='sidecar-null'),
    pytest.param('invalid-json', '{', id='invalid-json'),
    pytest.param('missing-outputs', None, id='missing-outputs'),
    pytest.param('outputs', None, id='outputs-null'),
    pytest.param('outputs', ['grid.tif'], id='outputs-list'),
    pytest.param('outputs', {}, id='missing-grid-digest'),
    pytest.param('outputs.grid.tif', 42, id='non-string-grid-digest'),
    pytest.param('outputs.support.tif', None, id='non-string-support-digest'),
    pytest.param('params', [], id='params-list'),
    pytest.param('params', {'label': []}, id='unhashable-label'),
    pytest.param('vertical_datum', {}, id='unhashable-datum'),
    pytest.param('resolution_m', '1', id='non-numeric-resolution'),
    pytest.param('resolution_m', 10**400, id='overflowing-resolution'),
    pytest.param('crs', [], id='crs-list'),
    pytest.param('shape', {}, id='shape-object'),
    pytest.param('transform', 'affine', id='transform-string'),
])
def test_malformed_twin_skips_only_its_source(tmp_path, field, value):
    # Both raw TIFFs are usable, so falling back from the bad twin would
    # wrongly select it. Put that row first so the good twin proves continuation.
    region, cache, argv = fixture(tmp_path)
    bad_raw = raster(tmp_path / 'a-bad.tif', np.full((2, 2), -5, dtype='float32'))
    good_raw = raster(tmp_path / 'b-good.tif', np.full((2, 2), -6, dtype='float32'))
    values = np.full((2, 2), -7, dtype='float32')
    classes = np.full(values.shape, 3, dtype='uint8')
    sidecar = normalized(cache, bad_raw, values, classes) / 'sidecar.json'
    good_twin = normalized(cache, good_raw, values, classes)

    doc = read(sidecar)
    if field == 'invalid-json':
        sidecar.write_text(value)
    elif field is None:
        doc = value
    elif field == 'missing-outputs':
        del doc['outputs']
    elif field.startswith('outputs.'):
        doc['outputs'][field.removeprefix('outputs.')] = value
    else:
        doc[field] = value
    if field != 'invalid-json':
        put(sidecar, doc)
    put(region / 'census.json', {'summary': {'region': region.name}, 'files': [
        row_for(bad_raw, 'bad-survey'), row_for(good_raw, 'good-survey'),
    ]})
    put(tmp_path / 'registry.json', {'sources': [registry_row('bad-survey'), registry_row('good-survey')]})

    assert main(argv) == 0
    selected = region / 'select'
    reports = {row['source_id']: row for row in read(selected / 'selection.json')['files']}
    assert reports['bad-survey']['decision'] == 'skipped'
    assert reports['bad-survey']['reason'] == 'normalized_sidecar_malformed'
    assert reports['good-survey']['decision'] == 'included'
    sources = read(selected / 'sources.json')['sources']
    assert [(source['source_id'], source['path']) for source in sources] == [
        ('good-survey', str(good_twin / 'grid.tif')),
    ]
