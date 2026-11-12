"""RF0421-7: completed contained uncertainty TIFFs keep their role and private-only tags.

Real writer, real TIFFs, real descriptors. Upstream ``_prepare``/``_claims`` are
test fixtures in the assemble case only, not scientific qualification.
"""
import numpy as np
import pytest

pytest.importorskip('affine')
pytest.importorskip('pyproj')
pytest.importorskip('rasterio')
pytest.importorskip('shapely')

import rasterio  # noqa: E402
from affine import Affine  # noqa: E402
from pyproj import CRS  # noqa: E402

from skippercast.coastal import contained_batch as cb  # noqa: E402
from skippercast.coastal import derived_batch as db  # noqa: E402
from skippercast.coastal import vertical  # noqa: E402
from skippercast.coastal.handoff.common import ref, write  # noqa: E402

MSG = 'completed uncertainty physical semantics changed'
EXPECTED = {'schema': cb.BATCH, 'binding': 'synthetic'}


def _item(valid=None):
    valid = np.ones((2, 2), dtype=bool) if valid is None else valid
    raw = dict(schema='vertical-v1', sign='positive_up', units='m', datum='MLLW', scale=1.0, offset=0.0,
               scale_offset_applied=False,
               evidence=[dict(kind='raster_header', source_sha256='a' * 64, header_sha256='b' * 64, facts={})],
               conflicts=[])
    return dict(crs=CRS.from_epsg(26910), transform=Affine(2, 0, 728871, 0, -2, 3819179),
                facts={'support': {'limitations': [], 'support_kind': 'native_grid_node_footprints'}},
                result={'segment_id': 'synthetic', 'source': {'sha256': 'a' * 64}},
                result_ref={'sha256': 'b' * 64}, vertical=vertical.normalized(raw), packet={'synthetic': True},
                depth=np.full((2, 2), 30.0), uncertainty=np.full((2, 2), 0.5), valid=valid)


def _build(tmp_path, item, directory='out/0'):
    root = tmp_path
    refs = db._write_rasters(root, root / directory, item)
    return root, refs


def _receipt(root, item, refs, directory='out/0'):
    path = root / directory / 'acceptance.json'
    write(path, cb._acceptance(item, refs))
    acceptance = ref(root, path, 'coastal-terrain-only-input-v1')
    return dict(EXPECTED, acceptances=[acceptance], artifacts=[acceptance, *refs.values()])


def _mutate(root, refs, description='producer_uncertainty_m', kind='producer_uncertainty_m',
            publication='true', band_kind=None):
    path = root / refs['uncertainty']['path']
    with rasterio.open(path, 'r+') as ds:
        ds.set_band_description(1, description)
        ds.update_tags(uncertainty_kind=kind, publication_prohibited=publication)
        if band_kind is not None:
            ds.update_tags(1, uncertainty_kind=band_kind)
    refs['uncertainty'] = ref(root, path, 'coastal-derived-uncertainty-m-v1')


def _verify(root, item, refs):
    cb._verify(root, _receipt(root, item, refs), EXPECTED, [item])


@pytest.mark.parametrize('valid', [np.ones((2, 2), dtype=bool), np.array([[True, False], [True, True]])])
def test_canonical_uncertainty_roundtrip_verifies(tmp_path, valid):
    item = _item(valid)
    root, refs = _build(tmp_path, item)
    receipt = _receipt(root, item, refs)
    before = {p: p.read_bytes() for p in (root / 'out').rglob('*') if p.is_file()}
    cb._verify(root, receipt, EXPECTED, [item])
    assert before == {p: p.read_bytes() for p in (root / 'out').rglob('*') if p.is_file()}


@pytest.mark.parametrize('fault', [
    dict(description='unrelated_quantity'),
    dict(description=''),
    dict(kind='unrelated_quantity'),
    dict(kind=''),
    dict(kind='Producer_Uncertainty_M'),
    dict(kind='', band_kind='producer_uncertainty_m'),
    dict(publication='false'),
    dict(publication=''),
    dict(publication='True'),
])
def test_each_single_fault_refuses_after_rebinding(tmp_path, fault):
    item = _item()
    root, refs = _build(tmp_path, item)
    _verify(root, item, refs)
    _mutate(root, refs, **fault)
    with rasterio.open(root / refs['uncertainty']['path']) as ds:
        assert np.array_equal(ds.read(1), item['uncertainty'].astype('float32'))
        assert ds.units == ('m',)
    with pytest.raises(ValueError, match=MSG):
        _verify(root, item, refs)


def test_refusal_never_repairs_evidence(tmp_path):
    item = _item()
    root, refs = _build(tmp_path, item)
    _mutate(root, refs, publication='false')
    receipt = _receipt(root, item, refs)
    before = {p: p.read_bytes() for p in (root / 'out').rglob('*') if p.is_file()}
    with pytest.raises(ValueError, match=MSG):
        cb._verify(root, receipt, EXPECTED, [item])
    assert before == {p: p.read_bytes() for p in (root / 'out').rglob('*') if p.is_file()}


def test_prior_value_fence_still_refuses(tmp_path):
    item = _item()
    root, refs = _build(tmp_path, item)
    other = dict(item, uncertainty=np.full((2, 2), 0.75))
    with pytest.raises(ValueError, match='values/support changed'):
        cb._verify(root, _receipt(root, other, refs), EXPECTED, [other])


def _assemble_existing(tmp_path, monkeypatch, **fault):
    item = _item()
    root, refs = _build(tmp_path, item)
    if fault:
        _mutate(root, refs, **fault)
    receipt = _receipt(root, item, refs)
    write(root / 'out' / 'batch.json', receipt)
    batch = ref(root, root / 'out' / 'batch.json', cb.BATCH)
    write(root / 'out' / 'complete.json',
          dict(schema='coastal-contained-derived-completion-v1', receipt=batch))
    monkeypatch.setattr(cb, '_prepare', lambda *a, **k: ([item], [{}]))
    monkeypatch.setattr(cb, '_claims', lambda *a, **k: EXPECTED)
    return lambda: cb.assemble(root, [], side=2, output_dir='out', now='2026-01-01T00:00:00Z', baselines=[])


def test_existing_completed_assemble_reuses_canonical(tmp_path, monkeypatch):
    call = _assemble_existing(tmp_path, monkeypatch)
    assert call()['binding'] == 'synthetic'


@pytest.mark.parametrize('fault', [dict(description='unrelated_quantity'), dict(kind='unrelated_quantity'),
                                   dict(publication='false')])
def test_existing_completed_assemble_refuses_bad_metadata(tmp_path, monkeypatch, fault):
    call = _assemble_existing(tmp_path, monkeypatch, **fault)
    with pytest.raises(ValueError, match=MSG):
        call()
