"""Zone labels must come from the exact JSON bytes attested by select."""
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from skippercast.relief import mosaic, receipts, zone


@pytest.fixture
def zone_inputs(tmp_path, monkeypatch):
    return lambda **kwargs: _zone_inputs(tmp_path, monkeypatch, **kwargs)


def _zone_inputs(tmp_path, monkeypatch, *, second_id=None, unknown=False, duplicate=False):
    region = receipts.Region(tmp_path, 'tiny-bay')
    args = SimpleNamespace(region_config=tmp_path / 'region.json', coarse=tmp_path / 'coarse.tif',
                           water=tmp_path / 'water.geojson', coarse_source='tiny-coarse', coarse_date=None)
    selected = region.dir / 'select'
    selected.mkdir(parents=True)
    docs = {
        'selection.json': {'region': region.id, 'scope': 'public', 'files': [
            {'id': 'tiny-grid', 'decision': 'included', 'rights_class': 'public'},
            {'id': 'tiny-fine', 'decision': 'included', 'rights_class': 'public'},
            {'id': 'tiny-withheld', 'decision': 'excluded', 'rights_class': 'private'},
        ]},
        'sources.json': {'scope': 'public', 'sources': [
            {'id': 'tiny-grid', 'rights_class': 'public', 'label': 'Tiny grid',
             'priority_class': 'compiled', 'provenance': 'producer', 'path': 'cache/grid.tif',
             'source_id': 'tiny-catalog'},
            {'id': 'tiny-fine', 'rights_class': 'public', 'label': 'measured', 'source_id': second_id},
        ]},
    }
    if duplicate:
        docs['sources.json']['sources'].append(dict(docs['sources.json']['sources'][0], source_id='tiny-other'))
    outputs = []
    for name, doc in docs.items():
        path = selected / name
        data = receipts.canonical(doc)
        path.write_bytes(data)
        outputs.append({'path': region.record(path), 'sha256': receipts.sha256_bytes(data), 'bytes': len(data)})
    ctx = receipts.StageContext(region, 'public', args, {
        'select': {'outputs': outputs},
        'mosaic.public': {'outputs': [{'path': f'mosaic/public/{name}'}
                                      for name in ('elevation.tif', 'contributor.tif', 'manifest.json')]},
    })
    out = tmp_path / 'zone-out'
    out.mkdir()
    tool_inputs = []

    # Stand in for polygonization, not the release ID join: these features use raster contributor IDs.
    properties = [
        {'sources': ['tiny-withheld' if unknown else 'tiny-grid'], 'source': 'Tiny grid',
         'tier': 'estimated', 'grid_m': 8, 'grid_tier': '4-16m-compiled', 'date': '2025-01-01'},
        {'sources': ['tiny-fine'], 'source': 'Tiny fine', 'tier': '1m-measured', 'grid_m': 1, 'date': None},
        {'sources': [], 'tier': 'none', 'date': None},
    ]
    detail = {'type': 'FeatureCollection', 'region': region.id, 'navigation': 'NOT FOR NAVIGATION', 'features': [
        {'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': [
            [[x, 0], [x + 1, 0], [x + 1, 1], [x, 1], [x, 0]],
        ]}, 'properties': props} for x, props in enumerate(properties)
    ]}

    def run_tool(script, *flags):
        tool_inputs.append(json.loads(flags[flags.index('--selection') + 1].read_bytes()))
        output = flags[flags.index('--output') + 1]
        (output / 'zone.geojson').write_bytes(b'{"type":"FeatureCollection","features":[]}\n')
        (output / 'detail.geojson').write_bytes(receipts.canonical(detail))

    monkeypatch.setattr(mosaic, 'run_tool', run_tool)
    zone.plan(ctx)
    return ctx, out, selected, tool_inputs, detail


@pytest.mark.parametrize(('name', 'old', 'new'), [
    ('selection.json', b'"region":', b'"region" :'),
    ('sources.json', b'tiny-catalog', b'fake-catalog'),
])
def test_zone_refuses_changed_selector_output(zone_inputs, name, old, new):
    # The verified paths and JSON shapes still match after planning, but the bytes do not.
    ctx, out, selected, tool_inputs, _ = zone_inputs()
    path = selected / name
    original = path.read_bytes()
    assert old in original
    path.write_bytes(original.replace(old, new, 1))

    with pytest.raises(receipts.ReceiptError, match=r'hash changed.*' + name.replace('.', r'\.')):
        zone.build(ctx, out)
    assert tool_inputs == []


@pytest.mark.parametrize('second_id', [None, 'tiny-catalog'])
def test_zone_binds_detail_to_public_catalog_without_changing_raster_labels(zone_inputs, second_id):
    ctx, out, _, tool_inputs, raw_detail = zone_inputs(second_id=second_id)
    zone.build(ctx, out)

    assert tool_inputs == [{'region': 'tiny-bay', 'sources': [
        {'id': 'tiny-grid', 'rights_class': 'public', 'label': 'Tiny grid', 'provenance': 'compiled'},
        {'id': 'tiny-fine', 'rights_class': 'public', 'label': 'measured'},
    ]}]
    # Leaking the file ID here makes Chart reject even the valid gap in this collection.
    expected = deepcopy(raw_detail)
    expected['features'][0]['properties']['sources'] = ['tiny-catalog']
    expected['features'][1]['properties']['sources'] = [second_id or 'tiny-fine']
    assert json.loads((out / 'detail.geojson').read_bytes()) == expected


@pytest.mark.parametrize(('invalid', 'message'), [
    ('unknown', 'no public selection binding for tiny-withheld'),
    ('duplicate', 'duplicate public selection binding for tiny-grid'),
])
def test_zone_refuses_unbound_or_ambiguous_detail_before_adoption(zone_inputs, invalid, message):
    # An unselected feature must not leak and duplicate rows must not silently pick a catalog ID.
    ctx, out, _, _, _ = zone_inputs(**{invalid: True})
    with pytest.raises(receipts.ReceiptError, match=message):
        zone.build(ctx, out)
    assert list(out.iterdir()) == []
