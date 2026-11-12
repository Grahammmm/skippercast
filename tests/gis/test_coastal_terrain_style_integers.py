"""Oversized JSON integers in terrain style controls are ordinary refusals, not OverflowError."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
from contextlib import redirect_stdout
from unittest.mock import patch

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

from skippercast.coastal import vertical
from skippercast.coastal.handoff.common import ref, write
from skippercast.coastal.render import terrain_only

NOW = datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc)
HUGE = 10 ** 400
SCALARS = ['vertical_exaggeration', 'light_azimuth_degrees', 'light_elevation_degrees',
           'light_intensity', 'exposure', 'contrast', 'contour_interval_m',
           'slope_overlay', 'uncertainty_overlay']


class FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


@pytest.fixture
def packet(tmp_path):
    root = tmp_path / 'root'
    (root / 'inputs').mkdir(parents=True)
    size = 8
    rows, cols = np.indices((size, size))
    transform = from_origin(729183, 3819093, 2, 2)
    profile = dict(driver='GTiff', height=size, width=size, count=1, crs='EPSG:26910', transform=transform)
    terrain = root / 'inputs' / 'terrain.tif'
    with rasterio.open(terrain, 'w', dtype='float32', nodata=np.nan, **profile) as ds:
        ds.write((20 + cols * 0.15 + rows * 0.1).astype('float32'), 1)
        ds.set_band_unit(1, 'm')
        ds.set_band_description(1, 'depth_m_positive_down')
        ds.update_tags(vertical_sign='positive_down', vertical_datum='MLLW', scale_offset_applied='false')
    with rasterio.open(terrain) as ds:
        observation = vertical.from_raster(ds, source_sha256='a' * 64)
    block = dict(schema='vertical-v1', **observation['facts'], conflicts=[],
                 evidence=[vertical.evidence_from_observation(observation)])
    normalized = vertical.normalized(block)
    with rasterio.open(terrain, 'r+') as ds:
        ds.update_tags(vertical_contract=json.dumps(normalized), source_sha256='a' * 64,
                       scale_offset_applied='true')
    with rasterio.open(root / 'inputs' / 'mask.tif', 'w', dtype='uint8', **profile) as ds:
        ds.write(np.ones((size, size), 'uint8'), 1)
    with rasterio.open(root / 'inputs' / 'uncertainty.tif', 'w', dtype='float32', nodata=np.nan, **profile) as ds:
        ds.write((0.1 + cols * 0.01).astype('float32'), 1)
        ds.set_band_unit(1, 'm')
    doc = dict(schema=terrain_only.INPUT, creator_id='synthetic-builder', segment_id='synthetic-only',
               terrain=ref(root, 'inputs/terrain.tif', 'coastal-normalized-terrain-v1'),
               mask=ref(root, 'inputs/mask.tif', 'coastal-native-support-v2'),
               uncertainty=ref(root, 'inputs/uncertainty.tif', 'coastal-derived-uncertainty-m-v1'),
               uncertainty_kind='producer_uncertainty_m', vertical=normalized, crs='EPSG:26910',
               affine=list(transform), provenance=dict(source_sha256s=['a' * 64], upstream_receipt_sha256='b' * 64),
               support_kind='derived_valid_sample_support', limitations=['Synthetic fixture; no real terrain claim.'],
               synthetic=True, source_accessed=False, imagery_used=False, internal_diagnostic=True,
               publication_prohibited=True, website='held', habitat='unassessed')
    write(root / 'science-review.json', dict(
        schema=terrain_only.REVIEW, scope='internal-terrain-only-scientific-review',
        facts_digest=terrain_only.context(doc), independent=True, reviewer_id='synthetic-independent-science',
        decision='accept', checked_at=(NOW - timedelta(hours=1)).isoformat(),
        valid_until=(NOW + timedelta(hours=2)).isoformat(), holds_added=[], synthetic=True))
    doc['scientific_review'] = ref(root, 'science-review.json', terrain_only.REVIEW)
    return root, doc


def refusal(style):
    with pytest.raises(ValueError) as caught:
        terrain_only.style_controls(style)
    return str(caught.value)


@pytest.mark.parametrize('name', SCALARS)
@pytest.mark.parametrize('sign', [1, -1])
def test_oversized_scalar_controls_refuse_normally(name, sign):
    style = {name: sign * HUGE}
    original = deepcopy(style)
    assert refusal(style) == 'invalid_style_' + name
    assert style == original


@pytest.mark.parametrize('locked', [[0, HUGE], [-HUGE, 0], [-HUGE, HUGE], [0.0, HUGE], [HUGE, HUGE + 1]])
def test_oversized_locked_endpoints_refuse_normally(locked):
    assert refusal(dict(color_range='locked', locked_depth_range_m=locked)) == 'locked_depth_range_required'


def test_valid_styles_and_error_precedence_unchanged():
    assert terrain_only.style_controls() == terrain_only.DEFAULT_STYLE
    style = terrain_only.style_controls(dict(vertical_exaggeration=10, light_intensity=0, exposure=0.25,
                                             color_range='locked', locked_depth_range_m=[-5, 10 ** 30]))
    assert style['vertical_exaggeration'] == 10 and type(style['vertical_exaggeration']) is int
    assert style['locked_depth_range_m'] == [-5, 10 ** 30]
    assert refusal(dict(exposure=True)) == 'invalid_style_exposure'
    assert refusal(dict(exposure=float('inf'))) == 'invalid_style_exposure'
    assert refusal(dict(exposure=None)) == 'invalid_style_exposure'
    assert refusal(dict(nope=1)) == 'unknown_style_control'
    assert refusal(dict(color_range='bad')) == 'invalid_style_enum'
    assert refusal(dict(color_range='locked', locked_depth_range_m=[1, 1])) == 'locked_depth_range_required'
    assert refusal(dict(color_range='locked', locked_depth_range_m=[0])) == 'locked_depth_range_required'
    assert refusal(dict(locked_depth_range_m=[0, 1])) == 'locked_depth_range_requires_locked_mode'


@pytest.mark.parametrize('style', [dict(vertical_exaggeration=HUGE),
                                   dict(color_range='locked', locked_depth_range_m=[0, HUGE])])
def test_real_cli_reports_one_held_document(packet, tmp_path, style):
    root, doc = packet
    acceptance, style_path = tmp_path / 'acceptance.json', tmp_path / 'style.json'
    acceptance.write_text(json.dumps(doc))
    style_path.write_text(json.dumps(style))
    out = io.StringIO()
    with patch.object(terrain_only, 'datetime', FixedClock), redirect_stdout(out), \
            patch.object(terrain_only, 'build_terrain', side_effect=AssertionError('built mesh')):
        code = terrain_only.main(['--root', str(root), '--acceptance', str(acceptance),
                                  '--output-dir', 'render', '--style', str(style_path)])
    held = json.loads(out.getvalue())
    assert code == 2 and held['state'] == 'held'
    assert held['holds'] == ['invalid_style_vertical_exaggeration' if 'vertical_exaggeration' in style
                             else 'locked_depth_range_required']
    assert held['publication_prohibited'] is True and held['website'] == 'held'
    assert held['habitat'] == 'unassessed'


def test_preview_refuses_before_derived_reads_and_output(packet):
    root, doc = packet
    with patch.object(terrain_only, 'build_terrain', side_effect=AssertionError('built mesh')) as seam:
        with pytest.raises(ValueError, match='invalid_style_contrast'):
            terrain_only.preview(root, doc, output_dir='render', now=NOW, style=dict(contrast=HUGE))
    seam.assert_not_called()
    assert not (root / 'render').exists()


def test_healthy_preview_still_done(packet):
    root, doc = packet
    result = terrain_only.preview(root, doc, output_dir='render', now=NOW,
                                  style=dict(vertical_exaggeration=2))
    assert result['state'] == 'done' and result['triangles'] > 0
    assert result['style']['vertical_exaggeration'] == 2
