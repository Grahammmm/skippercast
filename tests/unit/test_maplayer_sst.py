"""Offline private SST preview: units, support holes, provenance and freshness."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json

import pytest
from tests._support import ROOT

PATH = ROOT / 'research/scripts/map_style/build_sst.py'
spec = importlib.util.spec_from_file_location('build_sst_preview', PATH)
sst = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sst)
NOW = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
TIME = '2026-11-06T12:00:00Z'


def fixture(folder, rows=None, time=TIME):
    folder.mkdir(exist_ok=True)
    tile = {'region_id': 'synthetic', 'layer_id': 'sst-analysis', 'resolution_degrees': [.05, .05],
            'fields': ['latitude', 'longitude', 'temperature_c', 'temperature_gradient_c_per_km'],
            'frames': [{'time': sst.stamp(time).timestamp(), 'cells': rows if rows is not None else [
                [35.025, -121.075, 10, 0], [35.025, -121.025, 15, 1],
                [35.075, -121.075, None, None], [35.075, -121.025, 20, 1]]}]}
    raw = json.dumps(tile).encode()
    sha = hashlib.sha256(raw).hexdigest()
    name = f'habitat-tiles/sst-analysis--242-70-{sha[:16]}.json'
    (folder / 'habitat-tiles').mkdir(exist_ok=True)
    (folder / name).write_bytes(raw)
    layer = {'sample_at': time, 'resolution_degrees': [.05, .05], 'max_age_hours': 72,
             'source_id': 'synthetic', 'source_url': 'https://example.test/sst', 'dataset': 'fixture',
             'license': 'synthetic', 'limitations': 'fixture', 'total_cells': 4,
             'tiles': [{'path': name, 'sha256': sha}]}
    meta = {'region_id': 'synthetic', 'bounds': [-121.1, 35, -121, 35.1],
            'layers': {'sst-analysis': layer}}
    (folder / 'habitat-dynamics.json').write_text(json.dumps(meta))
    return meta, name


def save(folder, meta):
    (folder / 'habitat-dynamics.json').write_text(json.dumps(meta))


def test_native_cells_units_band_edges_and_missing_support(tmp_path):
    fixture(tmp_path)
    result = sst.build(tmp_path, NOW)
    features = result['cells']['features']
    assert result['valid_cells'] == 3
    assert [p['properties']['temperature_f'] for p in features] == [50, 59, 68]
    assert [p['properties']['colour'] for p in features] == [sst.COLOURS[0], sst.COLOURS[7], sst.COLOURS[-1]]
    ring = features[0]['geometry']['coordinates'][0]
    assert ring[1][0] - ring[0][0] == pytest.approx(.05)
    assert ring[2][1] - ring[1][1] == pytest.approx(.05)
    assert result['breaks']['features'] == []  # fourth corner is missing, no bridged front
    assert result['data_time'] == TIME and not result['stale']


def test_strong_break_threshold_converts_celsius_per_km(tmp_path):
    rows = [[35.025, -121.075, 10, 0], [35.025, -121.025, 10, 1],
            [35.075, -121.075, 10, 0], [35.075, -121.025, 10, 1]]
    fixture(tmp_path, rows)
    result = sst.build(tmp_path, NOW)
    line = result['breaks']['features'][0]['geometry']['coordinates']
    assert len(result['breaks']['features']) == 1
    assert [p[0] for p in line] == pytest.approx([-121.075 + .05 * 2 / 3] * 2)


def test_stale_is_retained_but_explicit_and_future_refused(tmp_path):
    fixture(tmp_path, time='2020-01-01T00:00:00Z')
    assert sst.build(tmp_path, NOW)['stale']
    fixture(tmp_path, time='2027-01-01T00:00:00Z')
    with pytest.raises(ValueError, match='future'):
        sst.build(tmp_path, NOW)


def test_checksum_frame_and_resolution_fail_closed(tmp_path):
    meta, name = fixture(tmp_path)
    original = (tmp_path / name).read_bytes()
    (tmp_path / name).write_bytes(original + b' ')
    with pytest.raises(ValueError, match='checksum'):
        sst.build(tmp_path, NOW)
    (tmp_path / name).write_bytes(original)
    meta['layers']['sst-analysis']['sample_at'] = '2026-11-05T12:00:00Z'
    save(tmp_path, meta)
    with pytest.raises(ValueError, match='matching data time'):
        sst.build(tmp_path, NOW)
    meta['layers']['sst-analysis']['sample_at'] = TIME
    meta['layers']['sst-analysis']['resolution_degrees'] = [.01, .01]
    save(tmp_path, meta)
    with pytest.raises(ValueError, match='resolution'):
        sst.build(tmp_path, NOW)


def test_duplicates_deduped_but_conflicting_overlap_refused(tmp_path):
    meta, name = fixture(tmp_path)
    meta['layers']['sst-analysis']['tiles'] *= 2
    save(tmp_path, meta)
    assert sst.build(tmp_path, NOW)['valid_cells'] == 3
    rows = [[35.025, -121.075, 10, 0], [35.025, -121.075, 11, 0]]
    fixture(tmp_path, rows)
    with pytest.raises(ValueError, match='conflicting'):
        sst.build(tmp_path, NOW)


@pytest.mark.parametrize('value', [True, float('nan'), 41, -3])
def test_invalid_temperature_is_not_rendered(tmp_path, value):
    fixture(tmp_path, [[35.025, -121.075, value, 0]])
    with pytest.raises(ValueError, match='numeric'):
        sst.build(tmp_path, NOW)


def test_private_output_and_input_paths(tmp_path):
    with pytest.raises(ValueError, match='checkout var'):
        sst.private_output(tmp_path / 'public.json')
    assert sst.private_output(sst.ROOT / 'var/preview.json')
    meta, _ = fixture(tmp_path)
    meta['layers']['sst-analysis']['tiles'][0]['path'] = '../escape.json'
    save(tmp_path, meta)
    with pytest.raises(ValueError, match='tile path'):
        sst.build(tmp_path, NOW)
