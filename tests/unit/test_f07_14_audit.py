"""F07-14: verify a private cache hit before mesh building or rasterization.

Default pytest runs the reference hit (not a production repair). Opt in to the
same oracle against unchanged production with:
    python tests/unit/test_f07_14_audit.py
"""
from datetime import datetime, timedelta, timezone
from importlib.resources import files
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from skippercast.coastal.handoff.common import digest, load, ref, resolve, validate_derived_geotiff, write
from skippercast.coastal.render import terrain_only as terrain

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
EXPIRY = NOW + timedelta(hours=1)
OUTPUT = 'private-preview'
INPUTS = {
    'terrain': 'coastal-normalized-terrain-v1',
    'mask': 'coastal-native-support-v2',
    'uncertainty': 'coastal-derived-uncertainty-m-v1',
}


def authenticate_inputs(root, document):
    for name, contract in INPUTS.items():
        validate_derived_geotiff(root, document[name], contract=contract, cap=terrain.MAX_FILE_BYTES)


def verified_hit(root, acceptance, *, output_dir, now, minimum_valid_until, style):
    """Fixture-only reference for the hit path; no rendering or repair path."""
    document = terrain.verify(root, acceptance, now=now, minimum_valid_until=minimum_valid_until)
    authenticate_inputs(root, document)
    render_dir = Path(terrain.__file__).parent
    sources = [render_dir / name for name in ('terrain_only.py', 'align.py', 'mesh.py', 'preview.py')]
    sources += [Path(terrain.vertical.__file__), render_dir.parent / 'handoff' / 'common.py']
    resources = files('skippercast.coastal.resources')
    binding = digest(dict(acceptance=document, style=terrain.style_controls(style),
        code={p.name: ref(p.parent, p.name, 'python')['sha256'] for p in sources},
        schemas={name: digest(json.loads(resources.joinpath(name + '.schema.json').read_text()))
                 for name in (terrain.INPUT, terrain.REVIEW, terrain.RESULT)},
        numpy=sys.modules['numpy'].__version__, rasterio=sys.modules['rasterio'].__version__))
    base, out = terrain.output_path(root, output_dir)
    complete = load(base, ref(base, out / 'complete.json', 'coastal-terrain-only-complete-v1'))
    receipt = load(base, complete['receipt'], contract=terrain.RESULT)
    if complete['binding'] != binding or receipt['render_binding'] != binding:
        raise ValueError('terrain_only_output_binding_changed')
    if {a['path'] for a in receipt['artifacts']} != {f'{output_dir}/terrain-mesh.npz', f'{output_dir}/preview.png'}:
        raise ValueError('terrain_only_output_artifacts_changed')
    for artifact in receipt['artifacts']:
        resolve(base, artifact, cap=terrain.MAX_FILE_BYTES)
    return receipt


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
        authenticate_inputs(root, accepted)  # The existing builder authenticates before loading rasters.
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
    ('private-preview/preview.png', HASH_CHANGED), ('private-preview/terrain-mesh.npz', HASH_CHANGED),
    ('private-preview/render-receipt.json', HASH_CHANGED),
    ('expired', 'review_expired_or_future'), ('horizon', 'review_insufficient_validity'),
    ('style', BINDING_CHANGED), ('runtime', BINDING_CHANGED),
])
def test_verified_hit_before_expensive_work(cached_preview, tmp_path, request, change, reason):
    acceptance, kwargs, fresh, mesh, raster = cached_preview
    if change == 'expired':
        kwargs.update(now=EXPIRY, minimum_valid_until=None)
    elif change == 'horizon':
        kwargs.update(minimum_valid_until=EXPIRY)
    elif change == 'style':
        kwargs.update(style={'depth_bands': 4})
    elif change == 'runtime':
        sys.modules['rasterio'].__version__ = 'fixture-v2'
    elif change != 'none':
        path = tmp_path / change
        before = path.read_bytes()
        path.write_bytes(before[:-1] + bytes([before[-1] ^ 1]))  # Keep size so the hash must decide.

    def snapshot():
        return {p.name: (p.read_bytes(), p.stat().st_ino, p.stat().st_mtime_ns) for p in (tmp_path / OUTPUT).iterdir()}

    before_hit = snapshot()
    preview = terrain.preview if request.config.getoption('f07_14_baseline', False) else verified_hit
    if reason:
        with pytest.raises(ValueError, match=reason):
            preview(tmp_path, acceptance, **kwargs)
    else:
        assert preview(tmp_path, acceptance, **kwargs) == fresh
    assert snapshot() == before_hit  # No rewrite, even when a cached artifact is bad.
    counts = (mesh.call_count, raster.call_count)
    print(f'{change}: {reason or "reused"}; mesh builds={counts[0]}, rasterizations={counts[1]}')
    assert counts == (0, 0), 'verification or reuse reached mesh building/rasterization'


if __name__ == '__main__':
    class BaselineReplay:
        def pytest_addoption(self, parser):
            parser.addoption('--f07-14-baseline', dest='f07_14_baseline', action='store_true')

    raise SystemExit(pytest.main(['-q', '-s', '--tb=short', __file__, '--f07-14-baseline'], plugins=[BaselineReplay()]))
