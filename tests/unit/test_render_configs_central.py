"""Runtime contracts for the Central Coast render recipes."""
import json
import re

import pytest

from skippercast.relief import render_config
from tests._support import ROOT


REGIONS = (
    'big-sur-coast',
    'cambria-san-simeon',
    'south-big-sur-san-simeon',
    'monterey-point-sur',
    'point-arguello-conception',
    'santa-cruz-monterey-bay',
)


@pytest.fixture(autouse=True)
def checkout(monkeypatch):
    monkeypatch.setattr(render_config, 'repo_root', lambda: ROOT)


@pytest.mark.parametrize('region_id', REGIONS, ids=lambda region: f'C1: {region}')
def test_c1_style_pin_and_no_piers(region_id):
    # An omitted pin would resolve to today's default, then drift on a style change.
    recipe = render_config._config(region_id)
    assert recipe is not None
    version, style = render_config.resolve_style(region_id)
    assert style is not None
    assert (recipe['style'], version, style.version, render_config.piers(region_id)) == (
        'nearshore-v1.0.0', 'nearshore-v1.0.0', 'nearshore-v1.0.0', [],
    )


@pytest.mark.parametrize('region_id', REGIONS, ids=lambda region: f'C2: {region} (C3)')
def test_c2_c3_loaded_windows_match_region_metadata(region_id):
    # A restored remote departure, copied camera, swapped axis or later forecast
    # point must fail at the loader boundary.
    source = ROOT / 'regions' / region_id / 'region.json'
    region = json.loads(source.read_bytes())
    if region_id in {
        'big-sur-coast', 'cambria-san-simeon', 'south-big-sur-san-simeon',
        'point-arguello-conception',
    }:
        west, south, east, north = region['fishing_bounds']
        camera_slug = f'{region_id}-overview'
        # Allow only floating-point roundoff when comparing decimal midpoints.
        center = pytest.approx([(west + east) / 2, (south + north) / 2], rel=0, abs=1e-12)
    else:
        harbor = region['harbor']
        camera_slug = re.sub(r'[^a-z0-9]+', '-', harbor['name'].lower()).strip('-')
        center = [harbor['longitude'], harbor['latitude']]
    point = region['forecast_points'][0]
    assert render_config.previews(region_id) == [
        dict(id=f'{camera_slug}-z13', center=center, size_m=4000, zoom=13),
        dict(id=f'{point["id"]}-z15', center=[point['longitude'], point['latitude']],
             size_m=1200, zoom=15),
    ]