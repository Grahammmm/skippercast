"""T13 checker against real terrain_only renders of synthetic cores with holes and disjoint regions."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

np = pytest.importorskip('numpy')
rasterio = pytest.importorskip('rasterio')
pytest.importorskip('jsonschema')
from rasterio.transform import from_origin  # noqa: E402

from research.lib.paths import ROOT  # noqa: E402
from research.scripts import check_terrain_acceptance as module  # noqa: E402
from skippercast.coastal import vertical  # noqa: E402
from skippercast.coastal.handoff.common import ref, write  # noqa: E402
from skippercast.coastal.render import terrain_only  # noqa: E402

SIZE = 24


def support_pattern():
    """Two disjoint supported regions; the left one holds an enclosed hole."""
    support = np.zeros((SIZE, SIZE), dtype='uint8')
    support[2:20, 1:11] = 1
    support[8:12, 4:7] = 0          # enclosed hole
    support[4:22, 14:23] = 1        # second region, separated by unsupported columns 11-13
    return support


def build_core(core, *, origin_x, support, now):
    (core / 'inputs').mkdir(parents=True)
    rows, cols = np.indices((SIZE, SIZE))
    data = (20 + cols * 0.15 + rows * 0.1).astype('float32')
    data[support == 0] = np.nan
    transform = from_origin(origin_x, 3819093, 2, 2)
    profile = dict(driver='GTiff', height=SIZE, width=SIZE, count=1, crs='EPSG:26910', transform=transform)
    terrain = core / 'inputs' / 'terrain.tif'
    with rasterio.open(terrain, 'w', dtype='float32', nodata=np.nan, **profile) as ds:
        ds.write(data, 1)
        ds.set_band_unit(1, 'm')
        ds.set_band_description(1, 'depth_m_positive_down')
        ds.update_tags(vertical_sign='positive_down', vertical_datum='MLLW', scale_offset_applied='false')
    with rasterio.open(terrain) as ds:
        observation = vertical.from_raster(ds, source_sha256='a' * 64)
    block = dict(schema='vertical-v1', **observation['facts'], conflicts=[],
                 evidence=[vertical.evidence_from_observation(observation)])
    normalized = vertical.normalized(block)
    with rasterio.open(terrain, 'r+') as ds:
        ds.update_tags(vertical_contract=json.dumps(normalized), source_sha256='a' * 64, scale_offset_applied='true')
    with rasterio.open(core / 'inputs' / 'mask.tif', 'w', dtype='uint8', **profile) as ds:
        ds.write(support, 1)
    uncertainty = np.where(support, 0.1 + cols * 0.01, np.nan).astype('float32')
    with rasterio.open(core / 'inputs' / 'uncertainty.tif', 'w', dtype='float32', nodata=np.nan, **profile) as ds:
        ds.write(uncertainty, 1)
        ds.set_band_unit(1, 'm')
    proposal = dict(schema=terrain_only.INPUT, creator_id='synthetic-builder', segment_id='synthetic-only',
        terrain=ref(core, 'inputs/terrain.tif', 'coastal-normalized-terrain-v1'),
        mask=ref(core, 'inputs/mask.tif', 'coastal-native-support-v2'),
        uncertainty=ref(core, 'inputs/uncertainty.tif', 'coastal-derived-uncertainty-m-v1'),
        uncertainty_kind='producer_uncertainty_m', vertical=normalized, crs='EPSG:26910',
        affine=list(transform), provenance=dict(source_sha256s=['a' * 64], upstream_receipt_sha256='b' * 64),
        support_kind='derived_valid_sample_support', limitations=['Synthetic fixture; no real terrain claim.'],
        synthetic=True, source_accessed=False, imagery_used=False, internal_diagnostic=True,
        publication_prohibited=True, website='held', habitat='unassessed')
    write(core / 'acceptance-proposal.json', proposal)
    write(core / 'preparation-receipt.json', dict(facts_digest=terrain_only.context(proposal)))
    write(core / 'science-review.json', dict(
        schema=terrain_only.REVIEW, scope='internal-terrain-only-scientific-review',
        facts_digest=terrain_only.context(proposal), independent=True, reviewer_id='synthetic-independent-science',
        decision='accept', checked_at=(now - timedelta(hours=1)).isoformat(),
        valid_until=(now + timedelta(hours=2)).isoformat(), holds_added=[], synthetic=True))
    accepted = dict(proposal, scientific_review=ref(core, 'science-review.json', terrain_only.REVIEW))
    write(core / 'acceptance.json', accepted)
    return accepted


STYLE = dict(no_data_overlay=True, contour_interval_m=0.5, depth_bands=8, vertical_exaggeration=2.0)


@pytest.fixture
def prep(tmp_path):
    now = datetime.now(timezone.utc)
    root = tmp_path / 'prep'
    for label, origin in (('A', 729183), ('B', 729183 + 2 * SIZE + 100)):
        core = root / f'core-{label}'
        document = build_core(core, origin_x=origin, support=support_pattern(), now=now)
        terrain_only.preview(core, document, output_dir='render', now=now, style=STYLE)
    return root


def verify(root, *extra):
    return module.main(['verify', '--prep-root', str(root), '--expect-cores', '2', '--overwrite-receipt', *extra])


def load_receipt(root):
    return json.loads((root / 't13-receipt.json').read_text())


def test_rendered_cores_pass_and_report_holes_and_regions(prep, capsys):
    assert verify(prep) == 0
    receipt = load_receipt(prep)
    assert receipt['verdict'] == 'PASS' and receipt['cross_core']['ok']
    assert receipt['cross_core']['pairs'] == [dict(cores=['A', 'B'], relation='disjoint')]
    for core in receipt['cores']:
        assert core['failed'] == [], core['failed']
        topo = core['facts']['topology']
        assert topo['enclosed_holes'] == 1 and topo['enclosed_hole_cells'] == 12
        assert topo['mask_components_8'] == 2 and topo['mesh_components'] == 2
        assert topo['mesh_components_spanning_mask_regions'] == 0
        assert topo['supported_cells'] == int(support_pattern().sum())
        assert core['facts']['preview']['width'] == 640
        assert {o['path'] for o in core['facts']['outputs']} == {
            'render/complete.json', 'render/preview.png', 'render/render-receipt.json', 'render/terrain-mesh.npz'}
    out = json.loads(capsys.readouterr().out)
    assert out['verdict'] == 'PASS' and out['receipt_sha256']


def rewrite_mesh(path, **changes):
    with np.load(path, allow_pickle=False) as archive:
        arrays = {k: archive[k] for k in archive.files}
    arrays.update(changes)
    np.savez(path, **arrays)


def failed(root, label='A'):
    return next(c for c in load_receipt(root)['cores'] if c['label'] == label)['failed']


def test_triangle_bridging_two_regions_fails(prep):
    mesh = prep / 'core-A' / 'render' / 'terrain-mesh.npz'
    with np.load(mesh, allow_pickle=False) as archive:
        faces, grid = archive['faces'], archive['grid_pixels']
    left = int(np.flatnonzero(grid[:, 0] == 10)[0])
    right = np.flatnonzero(grid[:, 0] == 14)[:2]
    rewrite_mesh(mesh, faces=np.vstack([faces, [[left, int(right[0]), int(right[1])]]]).astype('int32'))
    assert verify(prep) == 1
    assert 'triangles_only_inside_supported_quads' in failed(prep)
    assert 'disjoint_regions_stay_disjoint' in failed(prep)
    assert 'artifact_hashes' in failed(prep)


def test_interpolated_hole_fails(prep):
    mesh = prep / 'core-A' / 'render' / 'terrain-mesh.npz'
    with np.load(mesh, allow_pickle=False) as archive:
        depth, support = archive['depth_m'].copy(), archive['support'].copy()
    depth[9, 5] = 21.0
    support[9, 5] = True
    rewrite_mesh(mesh, depth_m=depth, support=support)
    assert verify(prep) == 1
    assert {'holes_not_interpolated', 'mesh_support_equals_mask'} <= set(failed(prep))


def test_preview_inset_that_hides_a_hole_fails(prep):
    png = prep / 'core-A' / 'render' / 'preview.png'
    width, height, rows = module.decode_png(png)
    pixels = np.frombuffer(b''.join(rows), dtype='uint8').reshape(height, width, 3).copy()
    pixels[module.INSET] = module.INSET_SUPPORTED
    from skippercast.coastal.render.mesh import write_png
    write_png(png, pixels)
    assert verify(prep) == 1
    assert 'preview_nodata_inset_matches_mask' in failed(prep)


def test_review_bound_to_other_facts_fails(prep):
    core = prep / 'core-B'
    review = json.loads((core / 'science-review.json').read_text())
    review['facts_digest'] = 'c' * 64
    write(core / 'science-review.json', review)
    assert verify(prep) == 1
    assert 'science_review_bound' in failed(prep, 'B')


def test_held_core_gives_partial_and_is_not_rendered(prep):
    core = prep / 'core-B'
    shutil.rmtree(core / 'render')
    write(core / 'science-review-HOLD.json', dict(reason='synthetic hold'))
    assert verify(prep) == 3
    receipt = load_receipt(prep)
    assert receipt['verdict'] == 'PARTIAL' and receipt['cores_held'] == 1
    assert not (core / 'render').exists()


def test_overlapping_cores_fail_cross_core(tmp_path):
    now = datetime.now(timezone.utc)
    root = tmp_path / 'prep'
    for label, origin in (('A', 729183), ('B', 729183 + 10)):
        core = root / f'core-{label}'
        document = build_core(core, origin_x=origin, support=support_pattern(), now=now)
        terrain_only.preview(core, document, output_dir='render', now=now, style=STYLE)
    assert verify(root) == 1
    assert load_receipt(root)['cross_core']['overlapping_pairs'] == 1


def test_wrong_core_count_or_missing_render_fails(prep):
    assert module.main(['verify', '--prep-root', str(prep), '--expect-cores', '4']) == 1
    shutil.rmtree(prep / 'core-A' / 'render')
    assert verify(prep) == 1
    assert failed(prep) == ['render_outputs_present']


def test_existing_receipt_is_not_overwritten_by_default(prep):
    (prep / 't13-receipt.json').write_text('{}')
    with pytest.raises(SystemExit):
        module.main(['verify', '--prep-root', str(prep), '--expect-cores', '2'])
    assert (prep / 't13-receipt.json').read_text() == '{}'


def test_run_mode_renders_with_the_cli_and_is_idempotent(tmp_path):
    now = datetime.now(timezone.utc)
    root = tmp_path / 'prep'
    for label, origin in (('A', 729183), ('B', 729183 + 2 * SIZE + 100)):
        build_core(root / f'core-{label}', origin_x=origin, support=support_pattern(), now=now)
    style = tmp_path / 'style.json'
    style.write_text(json.dumps(STYLE))
    command = [sys.executable, '-B', str(ROOT / 'research/scripts/check_terrain_acceptance.py'), 'run',
               '--prep-root', str(root), '--expect-cores', '2', '--style', str(style),
               '--python', sys.executable, '--pythonpath', str(ROOT / 'src'), '--overwrite-receipt']
    env = {'PATH': '/usr/bin:/bin', 'PYTHONPATH': f'{ROOT / "src"}:{ROOT}', 'PYTHONDONTWRITEBYTECODE': '1'}
    first = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
    assert first.returncode == 0, first.stdout + first.stderr
    receipt = load_receipt(root)
    assert all(c['render']['exit_code'] == 0 and 'render_exit_zero' in [k['name'] for k in c['checks']]
               for c in receipt['cores'])
    hashes = {o['path']: o['sha256'] for o in receipt['cores'][0]['facts']['outputs']}
    second = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
    assert second.returncode == 0, second.stdout + second.stderr
    again = {o['path']: o['sha256'] for o in load_receipt(root)['cores'][0]['facts']['outputs']}
    assert again == hashes
    assert Path(receipt['prep_root']) == root.resolve()
