"""Offline synthetic component grid: decoder orientation and provenance rejection."""
import hashlib
import importlib.util

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from tests._support import ROOT

pytestmark = pytest.mark.gis
SPEC = importlib.util.spec_from_file_location(
    'wind_preview', ROOT / 'research/scripts/map_style/build_wind.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def fixture(tmp_path):
    path = tmp_path / 'synthetic.tif'
    with rasterio.open(path, 'w', driver='GTiff', width=2, height=2, count=2,
                       dtype='float32', crs='EPSG:4326',
                       transform=from_origin(-122.125, 36.125, .25, .25)) as ds:
        for band, element in [(1, 'UGRD'), (2, 'VGRD')]:
            ds.write(np.array([[1, 2], [3, 4]], dtype='float32') * band, band)
            ds.update_tags(band, GRIB_ELEMENT=element, GRIB_SHORT_NAME='10-HTGL',
                           GRIB_UNIT='[m/s]', GRIB_REF_TIME='1794052800',
                           GRIB_VALID_TIME='1794074400')
    return path, {'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                  'run_time': '2026-11-07T12:00:00Z', 'data_time': '2026-11-07T18:00:00Z',
                  'source_url': 'https://example.invalid/synthetic'}


def test_component_orientation_and_grid_centres(tmp_path):
    path, receipt = fixture(tmp_path)
    result = MODULE.decode(path, receipt)
    assert (result['west'], result['north']) == (-122, 36)
    assert result['u'] == [[1, 2], [3, 4]]
    assert result['v'] == [[2, 4], [6, 8]]


@pytest.mark.parametrize('change', ['checksum', 'time', 'level', 'pair', 'missing'])
def test_rejects_unverifiable_component_grid(tmp_path, change):
    path, receipt = fixture(tmp_path)
    if change == 'checksum':
        receipt['sha256'] = '0' * 64
    elif change == 'time':
        receipt['data_time'] = '2026-11-07T19:00:00Z'
    else:
        with rasterio.open(path, 'r+') as ds:
            if change == 'level':
                ds.update_tags(2, GRIB_SHORT_NAME='100-HTGL')
            elif change == 'pair':
                ds.update_tags(2, GRIB_ELEMENT='UGRD')
            else:
                ds.write(np.full((2, 2), np.nan, dtype='float32'), 2)
        receipt['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        MODULE.decode(path, receipt)


def fetch_module(monkeypatch, tmp_path, arguments):
    import sys
    monkeypatch.setitem(sys.modules, 'build_wind', MODULE)
    spec = importlib.util.spec_from_file_location(
        'fetch_wind', ROOT / 'research/scripts/map_style/fetch_wind.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['fetch_wind.py', *arguments])
    return module


def test_fetch_stops_at_two_errors_without_replacing_retained_field(monkeypatch, tmp_path):
    import json
    module = fetch_module(monkeypatch, tmp_path, ['--run', '2026110712', '--hour', '6'])
    folder = tmp_path / 'var/maplayer-wind-1'
    folder.mkdir(parents=True)
    (folder / 'wind-preview.json').write_text('retained')
    calls = []

    def unavailable(url, timeout):
        calls.append(url)
        raise OSError('synthetic NOAA unavailable')

    monkeypatch.setattr(module, 'urlopen', unavailable)
    with pytest.raises(SystemExit, match='two NOAA attempts failed'):
        module.main()
    assert len(calls) == 2
    assert (folder / 'wind-preview.json').read_text() == 'retained'
    errors = json.loads((folder / 'fetch-errors.json').read_text())
    assert len(errors['errors']) == 2
    assert 'synthetic NOAA unavailable' in errors['errors'][1]


def test_fetch_rejects_bulk_crop_before_network(monkeypatch, tmp_path):
    module = fetch_module(monkeypatch, tmp_path,
                          ['--run', '2026110712', '--bounds', '-130', '30', '-110', '50'])
    with pytest.raises(SystemExit) as error:
        module.main()
    assert error.value.code == 2
    assert not (tmp_path / 'var').exists()
