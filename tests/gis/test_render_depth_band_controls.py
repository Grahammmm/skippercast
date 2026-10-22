"""Render each admitted discrete ramp; continuous and invalid-style controls."""
import numpy as np
import pytest

from skippercast.coastal.render import terrain_only
from tests.gis.test_render_terrain_bands import normalized_terrain, terrain_colours


@pytest.mark.parametrize('bands', range(2, 33))
def test_every_admitted_band_count_paints_exact_palette(tmp_path, bands):
    _, xx = np.indices((12, 64))
    depth = 10 + 20*xx/63
    built = terrain_only.build_terrain(tmp_path, normalized_terrain(tmp_path, depth, np.ones(depth.shape, bool)))
    style = terrain_only.style_controls(dict(depth_bands=bands, light_intensity=0,
        color_range='locked', locked_depth_range_m=[10, 30], contour_interval_m=1000,
        no_data_overlay=False))
    rendered, pixels = terrain_only.render_terrain(built, None, style)
    # Independent expected RGB set: N evenly spaced colours, not N-1 thresholds.
    expected = set()
    for k in range(bands):
        t = k/(bands-1)
        rgb = np.array([220-190*t, 235-120*t, 160+65*t])
        # Preserve the renderer's exposure/contrast conversion and byte rounding.
        expected.add(tuple((((rgb/255-.5)+.5)*255).astype('uint8')))
    assert len(expected) == bands
    assert terrain_colours(pixels) == expected
    assert rendered['outlier_pixels'] == dict(below=0, above=0)


def test_zero_bands_keeps_a_continuous_ramp_and_absolute_contours(tmp_path):
    _, xx = np.indices((12, 64))
    depth = 10 + 20*xx/63
    built = terrain_only.build_terrain(tmp_path, normalized_terrain(tmp_path, depth, np.ones(depth.shape, bool)))
    base = dict(light_intensity=0, color_range='locked', locked_depth_range_m=[10, 30],
                contour_interval_m=1000, no_data_overlay=False)
    continuous, pixels = terrain_only.render_terrain(built, None, terrain_only.style_controls(base))
    discrete, _ = terrain_only.render_terrain(built, None, terrain_only.style_controls(dict(base, depth_bands=2)))
    assert len(terrain_colours(pixels)) > 32
    assert discrete['color_range_m'] == continuous['color_range_m'] == [10, 30]
    assert discrete['contour_levels_m'] == continuous['contour_levels_m']
    assert discrete['visible_pixels'] == continuous['visible_pixels']


@pytest.mark.parametrize('bands', [1, -1, 33, 2.0, True, None])
def test_invalid_band_count_still_refused(bands):
    with pytest.raises(ValueError, match='^invalid_style_enum$'):
        terrain_only.style_controls(dict(depth_bands=bands))
