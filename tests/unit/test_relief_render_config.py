"""Offline tests for region render recipes and content-pinned selection."""
import json
import shutil

import pytest

from skippercast.relief import render_config
from tests._support import ROOT


@pytest.fixture
def recipe(tmp_path, monkeypatch):
    monkeypatch.setattr(render_config, 'repo_root', lambda: tmp_path)
    shutil.copytree(ROOT / 'style', tmp_path / 'style')
    schema = tmp_path / 'schemas/sc-render-v1.schema.json'
    schema.parent.mkdir()
    shutil.copyfile(ROOT / 'schemas' / schema.name, schema)
    region = tmp_path / 'regions/morro-bay'
    region.mkdir(parents=True)
    (region / 'region.json').write_text('{"fishing_bounds": [-122,34,-120,36]}')
    return region


def test_render_recipe_admits_only_window_pier_and_pin_data(recipe):
    # Without closed shapes, a config edit can silently override pixels or request held substrate.
    path = recipe / 'render.json'
    shutil.copyfile(ROOT / 'regions/morro-bay/render.json', path)
    doc = json.loads(path.read_bytes())
    assert render_config.resolve_style('morro-bay')[0] == 'nearshore-v1.0.0'
    assert render_config.previews('morro-bay') == doc['previews']
    assert render_config.piers('morro-bay') == doc['piers']
    for bad in (doc | {'shading': {'gain': 2}}, doc | {'substrate': 'classes.tif'},
                doc | {'style': {}}, doc | {'style': 'missing'}, doc | {'region': 'other'}):
        path.write_text(json.dumps(bad))
        with pytest.raises(ValueError):
            render_config.resolve_style('morro-bay')
    path.write_text(json.dumps(doc | {'style': 'deep-fixed-v1'}))
    assert render_config.resolve_style('morro-bay') == ('deep-fixed-v1', None)
    index = recipe.parents[1] / 'style/index.json'
    values = json.loads(index.read_bytes())
    values['versions']['deep-fixed-v1']['status'] = 'retired'
    index.write_text(json.dumps(values))
    with pytest.raises(ValueError, match='unavailable render style'):
        render_config.resolve_style('morro-bay')


def test_unpinned_config_verifies_bytes_and_uses_deterministic_windows(recipe):
    # A large coarse footprint cannot displace the finest native footprint or create a z15 window.
    windows = render_config.previews('morro-bay')
    assert windows == [dict(id='fishing-z11', center=[-121, 35], size_m=8000, zoom=11)]
    rows = [('b', 2, 90, [-121, 35.1]), ('a', 2, 100, [-121.5, 35.2]), ('coarse', 5, 200, [-121, 35.3])]
    picked = render_config.previews('morro-bay', native_footprints=rows)
    assert picked == render_config.previews('morro-bay', native_footprints=rows[::-1])
    assert [(w['zoom'], w['size_m'], w['center']) for w in picked[1:]] == [
        (13, 4000, [-121.5, 35.2]), (15, 1200, [-121.5, 35.2])]
    assert [w['zoom'] for w in render_config.previews('morro-bay', native_footprints=rows[-1:])] == [11, 13]
    assert render_config.piers('morro-bay') == []
    style_dir = recipe.parents[1] / 'style'
    version, selected = render_config.resolve_style('morro-bay', root=style_dir)
    assert selected is not None and selected.version == version
    path = style_dir / f'{version}.json'
    path.write_bytes(path.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='sha256'):
        render_config.resolve_style('morro-bay', root=style_dir)
