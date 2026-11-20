"""Zone labels must come from the exact JSON bytes attested by select."""
import json
from types import SimpleNamespace

import pytest

from skippercast.relief import mosaic, receipts, zone


@pytest.fixture
def zone_inputs(tmp_path, monkeypatch):
    region = receipts.Region(tmp_path, 'tiny-bay')
    args = SimpleNamespace(region_config=tmp_path / 'region.json', coarse=tmp_path / 'coarse.tif',
                           water=tmp_path / 'water.geojson', coarse_source='tiny-coarse', coarse_date=None)
    selected = region.dir / 'select'
    selected.mkdir(parents=True)
    docs = {
        'selection.json': {'region': region.id, 'scope': 'public', 'files': [
            {'id': 'tiny-grid', 'decision': 'included', 'rights_class': 'public'},
        ]},
        'sources.json': {'scope': 'public', 'sources': [
            {'id': 'tiny-grid', 'rights_class': 'public', 'label': 'Tiny grid',
             'priority_class': 'compiled', 'provenance': 'producer', 'path': 'cache/grid.tif'},
        ]},
    }
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

    def run_tool(script, *flags):
        tool_inputs.append(json.loads(flags[flags.index('--selection') + 1].read_bytes()))
        for name in ('zone.geojson', 'detail.geojson'):
            (out / name).touch()

    monkeypatch.setattr(mosaic, 'run_tool', run_tool)
    zone.plan(ctx)
    return ctx, out, selected, tool_inputs


@pytest.mark.parametrize(('name', 'old', 'new'), [
    ('selection.json', b'"region":', b'"region" :'),
    ('sources.json', b'Tiny grid', b'Fake grid'),
])
def test_zone_refuses_changed_selector_output(zone_inputs, name, old, new):
    # The verified paths and JSON shapes still match after planning, but the bytes do not.
    ctx, out, selected, tool_inputs = zone_inputs
    path = selected / name
    original = path.read_bytes()
    assert old in original
    path.write_bytes(original.replace(old, new, 1))

    with pytest.raises(receipts.ReceiptError, match=r'hash changed.*' + name.replace('.', r'\.')):
        zone.build(ctx, out)
    assert tool_inputs == []


def test_zone_keeps_public_compiled_label_from_matching_outputs(zone_inputs):
    ctx, out, _, tool_inputs = zone_inputs
    zone.build(ctx, out)

    assert tool_inputs == [{'region': 'tiny-bay', 'sources': [
        {'id': 'tiny-grid', 'rights_class': 'public', 'label': 'Tiny grid', 'provenance': 'compiled'},
    ]}]
