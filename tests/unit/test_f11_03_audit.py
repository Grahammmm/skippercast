"""F11-03: the requested mode, not the selected surveys, owns reach outputs."""
import pytest

from skippercast.platform.contracts import atomic_json, read_json
from skippercast.seafloor.io import sha256
from tests._support import ROOT

pytestmark = pytest.mark.gis
REACH = 'fixture-r01'


@pytest.fixture
def reach_inputs(tmp_path):
    import numpy as np
    from pyproj import Transformer
    import rasterio
    from rasterio.transform import from_origin

    from skippercast.seafloor.manifest import qualify_row
    from skippercast.seafloor.source_ingest import ingest

    root = tmp_path
    atomic_json(root / 'catalog/survey.schema.json', read_json(ROOT / 'catalog/survey.schema.json'))
    atomic_json(root / 'catalog/habitat-rules.json',
                dict(read_json(ROOT / 'catalog/habitat-rules.json'), substrate_bindings=[]))
    atomic_json(root / 'catalog/reaches.json', {'input_hash': 'grid', 'reaches': [{'id': REACH}]})
    reference = root / 'var/seafloor/reference'
    atomic_json(reference / 'cells.json', {'input_hash': 'grid', 'cells': [
        {'id': '3310:0:0', 'reach': REACH, 'tier': 0, 'band_area_m2': 50000,
         'reference_unknown_area_m2': 0},
    ]})
    atomic_json(reference / 'run.json', {'input_hash': 'grid',
                'output_hashes': {'cells.json': sha256(reference / 'cells.json')}})
    atomic_json(root / 'dist/data/atlas.json', {'areas': [], 'targets': []})
    atomic_json(root / 'dist/data/seafloor-ledger.json', {
        'reaches': [{'id': REACH, 'band_km2': .05}], 'totals': {'band_km2': .05},
    })
    (root / 'requirements-survey.txt').write_text('fixture')
    transform = Transformer.from_crs(3310, 4326, always_xy=True)
    bounds = [*transform.transform(-50, -50), *transform.transform(300, 300)]
    template = next(r for r in read_json(ROOT / 'catalog/surveys.json')['surveys'] if r['status'] == 'usable')
    template.pop('adapter_review')
    sources = {}
    for ident, depth in [('public', -50), ('private', -55)]:
        native = root / f'{ident}.tif'
        with rasterio.open(native, 'w', driver='GTiff', width=160, height=160, count=1, dtype='float32',
                           crs=3310, transform=from_origin(-30, 280, 2, 2), nodata=np.nan) as out:
            out.write(np.full((160, 160), depth, dtype='float32'), 1)
        row = dict(template, id=ident, url=f'https://pubs.usgs.gov/{ident}.tif', archive_member='unknown',
                   sha256=sha256(native), bytes=native.stat().st_size, derived_from=[], status='candidate')
        if ident == 'private':
            row['license'] = 'unknown'
        receipt, _, _ = ingest(row, bounds, root=root, local=native)
        sources[ident] = qualify_row(row, receipt, rights_url=row['url'], physical_only=ident == 'private')
    return root, sources


@pytest.mark.parametrize('selected', [(), ('public',), ('public', 'private')],
                         ids=['no-match', 'public-only', 'mixed'])
def test_physical_only_keeps_ordinary_reach_and_ledger_unchanged(reach_inputs, selected):
    # The old source-status routing overwrites a previously processed ordinary
    # reach when the physical-only run selects no private-status surveys.
    from skippercast.seafloor.run import run

    root, sources = reach_inputs
    manifest = root / 'catalog/surveys.json'
    ledger = root / 'dist/data/seafloor-ledger.json'
    ordinary = root / 'var/seafloor/reaches' / REACH
    private = root / 'var/seafloor/private-reaches' / REACH
    atomic_json(manifest, {'surveys': [sources['public']]})
    normal, cached = run(REACH, root=root)
    assert not cached and normal['publication_prohibited'] is False
    assert normal['inputs']['screen']['reasons'] == ['screen-missing']
    assert read_json(ledger)['reaches'][0]['tier1_km2'] == .05
    assert read_json(ordinary / 'run.json') == normal

    def snapshot():
        return ledger.read_bytes(), {p.relative_to(ordinary): p.read_bytes()
                                     for p in ordinary.rglob('*') if p.is_file()}

    before = snapshot()
    atomic_json(manifest, {'surveys': [sources[ident] for ident in selected]})
    result, cached = run(REACH, root=root, physical_only=True)
    assert snapshot() == before
    assert not cached and result['publication_prohibited'] is True
    assert [row['id'] for row in result['inputs']['sources']] == list(selected)
    assert result['inputs']['screen']['reasons'] == ['screen-deferred']
    assert read_json(private / 'run.json') == result
    assert read_json(private / 'habitat.geojson')['features'] == []

    # A cache hit must not repair or rewrite the ordinary ledger or receipt.
    result_again, cached = run(REACH, root=root, physical_only=True)
    assert cached and result_again == result
    assert snapshot() == before
