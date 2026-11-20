"""Failed refresh must not promote incomplete or misidentified exclusion evidence."""

import json
import sys

import pytest

from scripts import collect_noaa_groundfish_areas as noaa
from tests.unit.test_f20_01_audit import COLLINEAR, polygon
from tests.unit.test_noaa_groundfish_shapes import fake


@pytest.mark.parametrize('damage', [
    'empty', 'wrong-service', 'wrong-schema', 'missing-time', 'unknown-status',
    'missing-layer', 'duplicate-layer', 'wrong-layer-category', 'invalid-layer-count',
    'counts-swapped', 'wrong-feature-layer', 'duplicate-feature', 'collapsed-gea',
    'false-exclusion', 'grants-permission', 'exportable',
])
def test_invalid_previous_leaves_destination_untouched(tmp_path, monkeypatch, damage):
    # Every case used to pass the top-level count/type check and replace the output.
    data = noaa.collect(getter=fake())
    layer = data['source_layers'][0]
    feature = data['features'][0]
    props = feature['properties']
    if damage == 'empty':
        data.update(source_layers=[], features=[], feature_count=0)
    elif damage == 'wrong-service':
        data['service_url'] = 'https://example.invalid/MapServer'
    elif damage == 'wrong-schema':
        data['schema_version'] = True
    elif damage == 'missing-time':
        del data['retrieved_at']
    elif damage == 'unknown-status':
        data['status'] = 'failed'
    elif damage == 'missing-layer':
        del data['source_layers'][0], data['features'][0]
        data['feature_count'] -= 1
    elif damage == 'duplicate-layer':
        data['source_layers'].append(layer)
    elif damage == 'wrong-layer-category':
        layer['area_type'] = 'CCA'
    elif damage == 'invalid-layer-count':
        layer['feature_count'] = True
    elif damage == 'counts-swapped':
        layer['feature_count'] = 2
        data['source_layers'][1]['feature_count'] = 3
        data['features'].extend([
            dict(feature, properties=dict(props, id=f'noaa-gca-0-{oid}')) for oid in (2, 3, 4)
        ])  # Actual 4 + 1, claimed 2 + 3: both positive and same aggregate.
        data['feature_count'] += 3
    elif damage == 'wrong-feature-layer':
        props['source_layer_id'] = data['source_layers'][1]['layer_id']
    elif damage == 'duplicate-feature':
        data['features'].append(feature)
        data['feature_count'] += 1
        layer['feature_count'] += 1
    elif damage == 'collapsed-gea':
        feature['geometry'] = polygon(COLLINEAR)
    elif damage == 'false-exclusion':
        props['groundfish_candidate_exclusion'] = False
    elif damage == 'grants-permission':
        props['fishing_permission'] = True
    elif damage == 'exportable':
        props['exportable_as_fishing_spot'] = True

    previous, output = tmp_path / 'previous.json', tmp_path / 'areas.json'
    previous.write_text(json.dumps(data))
    output.write_bytes(b'{"keep": "original destination"}\n')

    def failed_refresh():
        raise TimeoutError('synthetic refresh failure')

    monkeypatch.setattr(noaa, 'collect', failed_refresh)
    monkeypatch.setattr(sys, 'argv', ['collect', '--output', str(output), '--previous', str(previous)])
    with pytest.raises(SystemExit) as stopped:
        noaa.main()
    assert output.read_bytes() == b'{"keep": "original destination"}\n'
    assert 'previous snapshot unusable:' in str(stopped.value)
