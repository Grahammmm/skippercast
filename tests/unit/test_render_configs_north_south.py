"""Runtime contracts for the north coast and southern California render recipes."""
from decimal import Decimal
import json
import re

import pytest

from skippercast.relief import render_config
from tests._support import ROOT


REGIONS = (
    'point-arena-bodega',
    'bodega-point-reyes',
    'point-reyes-pigeon',
    'fort-bragg-point-arena',
    'shelter-cove-north-mendocino',
    'humboldt-bay-cape-mendocino',
    'trinidad-klamath',
    'crescent-city',
    'southern-california',
)
ISLANDS = ('channel-islands-north', 'outer-islands-borderland')


@pytest.fixture(autouse=True)
def checkout(monkeypatch):
    monkeypatch.setattr(render_config, 'repo_root', lambda: ROOT)


@pytest.mark.parametrize('region_id', REGIONS, ids=lambda region: f'C1: {region}')
def test_c1_schema_and_style_pin(region_id):
    # A missing pin can still resolve to today's default and drift when it changes.
    recipe = render_config._config(region_id)
    assert recipe is not None
    version, style = render_config.resolve_style(region_id)
    assert style is not None
    assert (recipe['style'], version, style.version, render_config.piers(region_id)) == (
        'nearshore-v1.0.0', 'nearshore-v1.0.0', 'nearshore-v1.0.0', [],
    )


@pytest.mark.parametrize('region_id', REGIONS, ids=lambda region: f'C2: {region}')
def test_c2_loaded_windows_match_region_metadata(region_id):
    # Copying a nearby camera or dropping an island must fail the whole-list comparison.
    source = ROOT / 'regions' / region_id / 'region.json'
    region = json.loads(source.read_bytes())
    harbor = region['harbor']
    harbor_slug = re.sub(r'[^a-z0-9]+', '-', harbor['name'].lower()).strip('-')
    point = region['forecast_points'][0]
    expected = [
        dict(id=f'{harbor_slug}-z13', center=[harbor['longitude'], harbor['latitude']],
             size_m=4000, zoom=13),
        dict(id=f'{point["id"]}-z15', center=[point['longitude'], point['latitude']],
             size_m=1200, zoom=15),
    ]
    if region_id == 'southern-california':
        for island in ISLANDS:
            source = ROOT / 'regions' / island / 'region.json'
            # Compute from the recorded decimal coordinates before converting to JSON numbers.
            west, south, east, north = json.loads(source.read_bytes(), parse_float=Decimal)['bounds']
            expected.append(dict(id=f'{island}-z13', zoom=13, size_m=4000,
                                 center=[float((west + east) / 2), float((south + north) / 2)]))
    assert render_config.previews(region_id) == expected
