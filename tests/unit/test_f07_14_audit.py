"""F07-14: verify a private cache hit before mesh building or rasterization."""
from datetime import datetime, timedelta, timezone
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from skippercast.coastal.handoff.common import ref, validate_derived_geotiff, write
from skippercast.coastal.render import terrain_only as terrain

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
EXPIRY = NOW + timedelta(hours=1)
OUTPUT = 'private-preview'
INPUTS = {
    'terrain': 'coastal-normalized-terrain-v1',
    'mask': 'coastal-native-support-v2',
    'uncertainty': 'coastal-derived-uncertainty-m-v1',
}


@pytest.fixture
def cached_preview(tmp_path, monkeypatch):
    """Real review, binding and disk I/O; only GIS work and encoded payloads are synthetic."""
    for package in ('numpy', 'rasterio'):
        monkeypatch.setitem(sys.modules, package, SimpleNamespace(__version__='fixture-v1'))
    refs = {}
    for name, contract in INPUTS.items():
        path = tmp_path / f'{name}.tif'
        path.write_bytes(b'II*\0' + name.encode())  # TIFF signature; never opened by GDAL.
        refs[name] = ref(tmp_path, path, contract)
    vertical = dict(schema='vertical-v1', sign='positive_down', units='m', datum='MLLW',
                    scale=1, offset=0, scale_offset_applied=True, storage='normalized_depth',
                    evidence=[], lineage={})
    affine = [1, 0, 0, 0, -1, 0, 0, 0, 1]
    document = dict(schema=terrain.INPUT, creator_id='synthetic-creator', segment_id='synthetic-only',
        **refs, uncertainty_kind='producer_uncertainty_m', vertical=vertical, crs='synthetic-grid', affine=affine,
        provenance=dict(source_sha256s=['a' * 64], upstream_receipt_sha256='b' * 64),
        support_kind='derived_valid_sample_support', limitations=['Synthetic fixture only.'],
        synthetic=True, source_accessed=False, imagery_used=False, internal_diagnostic=True,
        publication_prohibited=True, website='held', habitat='unassessed')
    write(tmp_path / 'science.json', dict(schema=terrain.REVIEW, scope='internal-terrain-only-scientific-review',
        facts_digest=terrain.context(document), independent=True, reviewer_id='synthetic-reviewer',
        decision='accept', checked_at=NOW.isoformat(), valid_until=EXPIRY.isoformat(),
        holds_added=[], synthetic=True))
    document['scientific_review'] = ref(tmp_path, 'science.json', terrain.REVIEW)
    write(tmp_path / 'acceptance.json', document)
    acceptance = ref(tmp_path, 'acceptance.json', terrain.INPUT)

    def build(root, accepted):
        # Stand in for the cold builder, which authenticates before opening GDAL.
        for name, contract in INPUTS.items():
            validate_derived_geotiff(root, accepted[name], contract=contract, cap=terrain.MAX_FILE_BYTES)
        return dict(vertical=vertical, affine=affine, crs='synthetic-grid', crs_wkt='synthetic-grid',
                    nodata=None, support=SimpleNamespace(sum=lambda: 4), vertices=range(4), faces=range(2))

    mesh = Mock(side_effect=build)
    raster = Mock(return_value=(dict(camera={}, color_range_m=[1, 2], contour_levels_m=[]), b'synthetic image'))
    for name, operation in dict(build_terrain=mesh, render_terrain=raster,
            save_mesh=lambda path, _: path.write_bytes(b'synthetic mesh'),
            write_png=lambda path, pixels: path.write_bytes(pixels)).items():
        monkeypatch.setattr(terrain, name, operation)
    kwargs = dict(output_dir=OUTPUT, now=NOW, minimum_valid_until=NOW + timedelta(minutes=5), style=None)
    fresh = terrain.preview(tmp_path, acceptance, **kwargs)
    assert fresh['state'] == 'done' and fresh['internal_diagnostic'] and fresh['publication_prohibited']
    assert (mesh.call_count, raster.call_count) == (1, 1)
    mesh.reset_mock()
    raster.reset_mock()
    return acceptance, kwargs, fresh, mesh, raster


HASH_CHANGED = 'artifact bytes/hash changed'
BINDING_CHANGED = 'terrain_only_output_binding_changed'


@pytest.mark.parametrize(('change', 'reason'), [
    ('none', None),
    ('acceptance.json', HASH_CHANGED), ('science.json', HASH_CHANGED),
    ('terrain.tif', HASH_CHANGED), ('mask.tif', HASH_CHANGED), ('uncertainty.tif', HASH_CHANGED),
    ('sidecar', 'unbound derived GeoTIFF sidecar refused before GDAL'),
    ('private-preview/preview.png', HASH_CHANGED), ('private-preview/terrain-mesh.npz', HASH_CHANGED),
    ('private-preview/render-receipt.json', HASH_CHANGED),
    ('completion-schema', BINDING_CHANGED),
    ('expired', 'review_expired_or_future'), ('horizon', 'review_insufficient_validity'),
    ('style', BINDING_CHANGED), ('runtime', BINDING_CHANGED),
])
def test_verified_hit_before_expensive_work(cached_preview, tmp_path, change, reason):
    acceptance, kwargs, fresh, mesh, raster = cached_preview
    if change == 'expired':
        kwargs.update(now=EXPIRY, minimum_valid_until=None)
    elif change == 'horizon':
        kwargs.update(minimum_valid_until=EXPIRY)
    elif change == 'style':
        kwargs.update(style={'depth_bands': 4})
    elif change == 'runtime':
        sys.modules['rasterio'].__version__ = 'fixture-v2'
    elif change == 'sidecar':
        # Matching TIFF bytes alone cannot authorize an unbound GDAL sidecar.
        (tmp_path / 'terrain.TIF.AUX.XML').write_text('<PAMDataset/>')
    elif change == 'completion-schema':
        # A parseable but damaged completion marker must not authorize reuse.
        path = tmp_path / OUTPUT / 'complete.json'
        path.write_bytes(path.read_bytes().replace(b'coastal-terrain-only-complete-v1',
                                                   b'coastal-terrain-only-complete-v0'))
    elif change != 'none':
        path = tmp_path / change
        before = path.read_bytes()
        path.write_bytes(before[:-1] + bytes([before[-1] ^ 1]))  # Keep size so the hash must decide.

    def snapshot():
        return {p.name: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns) for p in (tmp_path / OUTPUT).iterdir()}

    before_hit = snapshot()
    if reason:
        with pytest.raises(ValueError, match=reason):
            terrain.preview(tmp_path, acceptance, **kwargs)
    else:
        assert terrain.preview(tmp_path, acceptance, **kwargs) == fresh
    assert snapshot() == before_hit  # No rewrite, even when a cached artifact is bad.
    counts = (mesh.call_count, raster.call_count)
    print(f'{change}: {reason or "reused"}; mesh builds={counts[0]}, rasterizations={counts[1]}')
    assert counts == (0, 0), 'verification or reuse reached mesh building/rasterization'
