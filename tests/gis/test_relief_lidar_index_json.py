"""Reject ambiguous lidar index JSON before attempting any raster I/O."""
import json

import pytest
import rasterio

from skippercast.relief.normalize_archives import normalize_archive
from skippercast.relief.receipts import sha256_file

pytestmark = pytest.mark.gis


@pytest.mark.parametrize(('key', 'earlier_value'), [
    ('path', 'other-elevation.tif'),
    ('count_path', 'other-count.tif'),
    ('sha256', '0' * 64),
    ('count_sha256', '0' * 64),
    ('schema_version', 2),
    ('label', 'same'),
])
def test_duplicate_index_member_refused_before_raster_open(tmp_path, monkeypatch, key, earlier_value):
    # The last values select a pinned pair. A last-wins decoder would silently
    # discard the conflict and try to open it. File contents need only hash here.
    elevation = tmp_path / 'elevation.tif'
    count = tmp_path / 'count.tif'
    elevation.write_bytes(b'elevation fixture')
    count.write_bytes(b'count fixture')
    row = dict(id='fixture', status='gridded', path=elevation.name, count_path=count.name,
               sha256=sha256_file(elevation), count_sha256=sha256_file(count),
               classes=[2], vertical_datum='NAVD88')
    duplicate = f'{json.dumps(key)}: {json.dumps(earlier_value)}, '
    if key == 'schema_version':
        text = '{' + duplicate + json.dumps(dict(schema_version=1, files=[row]))[1:]
    else:
        row_text = json.dumps(row)
        if key == 'label':
            # Even identical repeats in unused nested metadata are ambiguous JSON.
            row_text = f'{{"metadata": [{{{duplicate}"label": "same"}}], ' + row_text[1:]
        else:
            row_text = '{' + duplicate + row_text[1:]
        text = '{"schema_version": 1, "files": [' + row_text + ']}'
    index = tmp_path / 'lidar-index.json'
    index.write_text(text, encoding='utf-8')

    def unexpected_open(*args, **kwargs):
        pytest.fail('rasterio.open called for an ambiguous lidar index')

    monkeypatch.setattr(rasterio, 'open', unexpected_open)
    with pytest.raises(ValueError, match=rf'duplicate lidar index key: {key!r}'):
        normalize_archive(index, tmp_path / 'cache', family='lidar-grid', lidar_id='fixture')
