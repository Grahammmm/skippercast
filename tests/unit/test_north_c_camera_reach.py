"""Read the actual North C JSON files through the offline reporting CLI."""

import json
import shutil
import subprocess
import sys

import pytest

from tests._support import ROOT

CLI = ROOT / 'scripts/relief/north_c_camera_reach.py'


def _run(root):
    return subprocess.run([sys.executable, str(CLI), '--root', str(root)], cwd=root,
                          capture_output=True, text=True, check=False)


def _report(root):
    result = _run(root)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


@pytest.fixture
def configs(tmp_path):
    for path in ('regions/trinidad-klamath/region.json', 'regions/trinidad-klamath/render.json',
                 'regions/crescent-city/region.json', 'regions/crescent-city/render.json',
                 'schemas/sc-render-v1.schema.json'):
        dest = tmp_path / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / path, dest)
    return tmp_path


def test_actual_north_c_configs_distinguish_center_from_release_bounds():
    """Catches using the map center or fishing bounds, or treating a camera as coverage."""
    report = _report(ROOT)
    assert report['release'] == {
        'oregon_anchor_latitude_deg': 42.0,
        'regions': {
            'trinidad-klamath': {
                'name': 'Trinidad to Klamath River', 'bounds_wsen': [-124.6, 40.95, -124.0, 41.55],
            },
            'crescent-city': {
                'name': 'Crescent City & Del Norte', 'bounds_wsen': [-124.75, 41.55, -124.05, 42.0],
            },
        },
    }
    assert report['preview'] == {
        'northernmost_center': {
            'region_id': 'crescent-city', 'preview_id': 'crescent-city-harbor-z13',
            'center_lon_lat': [-124.185, 41.744],
        },
        'latitude_separation_deg': pytest.approx(0.256),
        'latitude_separation_km_approx': pytest.approx(28.47, abs=0.02),
    }
    assert 'not coverage evidence' in report['scope']


@pytest.mark.parametrize('filename', ['region.json', 'render.json'])
def test_swapped_region_configs_are_refused(configs, filename):
    """Catches trusting the directory name over the identity inside either config."""
    trinidad = configs / 'regions/trinidad-klamath' / filename
    crescent = configs / 'regions/crescent-city' / filename
    original = trinidad.read_bytes()
    trinidad.write_bytes(crescent.read_bytes())
    crescent.write_bytes(original)

    result = _run(configs)
    assert result.returncode == 1
    assert f'trinidad-klamath/{filename}: region id mismatch' in result.stderr
    assert not result.stdout


def test_more_southerly_preview_increases_separation_without_moving_release(configs):
    """Catches hard-coded distances, first-preview selection or camera-derived bounds."""
    before = _report(configs)
    path = configs / 'regions/crescent-city/render.json'
    render = json.loads(path.read_text(encoding='utf-8'))
    # The unchanged second preview now wins; the moved center stays within the bounds.
    render['previews'][0]['center'][1] = 41.68
    path.write_text(json.dumps(render), encoding='utf-8')

    after = _report(configs)
    assert after['release'] == before['release']
    assert after['preview'] == {
        'northernmost_center': {
            'region_id': 'crescent-city', 'preview_id': 'crescent-south-z15',
            'center_lon_lat': [-124.26, 41.7],
        },
        'latitude_separation_deg': pytest.approx(0.3),
        'latitude_separation_km_approx': pytest.approx(33.36, abs=0.02),
    }


def test_release_bound_short_of_oregon_is_refused(configs):
    """Catches printing a fixed endpoint while silently accepting a shortened release bound."""
    path = configs / 'regions/crescent-city/region.json'
    region = json.loads(path.read_text(encoding='utf-8'))
    region['bounds'][3] = 41.99
    path.write_text(json.dumps(region), encoding='utf-8')

    result = _run(configs)
    assert result.returncode == 1
    assert 'release bounds must end at the Oregon anchor (42.0 N)' in result.stderr
    assert not result.stdout


@pytest.mark.parametrize(('region_id', 'center', 'eligible'), [
    ('crescent-city', [-124.185, 42.05], False),
    ('trinidad-klamath', [-124.144, 41.6], False),
    ('crescent-city', [-124.75, 42.0], True),
], ids=['beyond-oregon', 'in-neighbor-but-not-own-release', 'inclusive-corner'])
def test_preview_center_must_be_in_its_own_release(configs, region_id, center, eligible):
    """Catches accepting a world-valid center that wins (or hides behind another winner)."""
    path = configs / 'regions' / region_id / 'render.json'
    render = json.loads(path.read_text(encoding='utf-8'))
    recipe = render['previews'][0]
    recipe['center'] = center
    path.write_text(json.dumps(render), encoding='utf-8')

    result = _run(configs)
    if eligible:
        assert result.returncode == 0, result.stderr
        preview = json.loads(result.stdout)['preview']
        assert preview['northernmost_center'] == {
            'region_id': region_id, 'preview_id': recipe['id'], 'center_lon_lat': center,
        }
        assert preview['latitude_separation_deg'] == 0
    else:
        assert result.returncode == 1, result.stdout
        assert f"{region_id}/render.json: preview {recipe['id']} center is outside region bounds" in result.stderr
        assert not result.stdout
