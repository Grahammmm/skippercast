import json
from hashlib import sha256
from shutil import copyfile

import pytest

from scripts.relief import central_camera_bounds, central_camera_evidence
from tests._support import ROOT


REGION = 'big-sur-coast'
STYLE = 'nearshore-v1.0.0'


@pytest.fixture
def config_tree(tmp_path, monkeypatch):
    monkeypatch.setenv('SKIPPERCAST_ROOT', str(tmp_path))
    for relative in ('schemas/sc-render-v1.schema.json', 'style/index.json',
                     'style/groups.json', f'style/{STYLE}.json'):
        dest = tmp_path / relative
        dest.parent.mkdir(exist_ok=True)
        copyfile(ROOT / relative, dest)

    # Use the real style index with a different default so a default-only
    # implementation cannot accidentally report the configured selection.
    index = tmp_path / 'style/index.json'
    styles = json.loads(index.read_text())
    styles['default'] = 'deep-fixed-v1'
    index.write_text(json.dumps(styles), encoding='utf-8')

    recipe = tmp_path / 'regions' / REGION / 'render.json'
    recipe.parent.mkdir(parents=True)
    doc = {
        'schema': 'sc-render/1', 'region': REGION, 'style': STYLE, 'piers': [],
        'previews': [
            {'id': 'offshore', 'center': [-121.4, 35.4], 'size_m': 1200, 'zoom': 15},
            {'id': 'harbor', 'center': [-121.2, 35.1], 'size_m': 4000, 'zoom': 13},
        ],
    }
    recipe.write_text(json.dumps(doc), encoding='utf-8')
    (recipe.parent / 'region.json').write_text(
        '{"bounds":[-122,35,-121,36],"fishing_bounds":[-122,35,-121,36]}', encoding='utf-8',
    )
    return recipe, doc


def _report(capsys, region=REGION):
    assert central_camera_evidence.main([region]) == 0
    return json.loads(capsys.readouterr().out)


def test_report_binds_exact_loaded_recipe(config_tree, capsys):
    # A digest over only centers, or using the index default instead of the
    # selected style, cannot identify what the reviewer is looking at.
    report = _report(capsys)
    digest = report.pop('sha256')
    assert report == {
        'region': REGION, 'style_version': STYLE,
        'cameras': [['offshore', -121.4, 35.4, 1200, 15], ['harbor', -121.2, 35.1, 4000, 13]],
    }
    assert digest == sha256(json.dumps(report, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def test_formatting_only_preserves_identity(config_tree, capsys):
    # Hashing the render.json bytes would invalidate review on reformatting.
    recipe, doc = config_tree
    before = _report(capsys)
    doc['previews'][0]['size_m'] = 1200.0
    recipe.write_text(json.dumps(doc, indent=4, sort_keys=True) + '\n', encoding='utf-8')
    assert _report(capsys) == before


@pytest.mark.parametrize('change', ['crop-size', 'order'])
def test_in_bounds_recipe_change_alters_identity(config_tree, monkeypatch, capsys, change):
    # A bounds-pass bit, a centers-only digest, or sorting the cameras would
    # let genuinely different recipes share an identity.
    recipe, doc = config_tree
    monkeypatch.setattr(central_camera_bounds, 'REGIONS', (REGION,))
    assert central_camera_bounds.main([]) == 0
    capsys.readouterr()
    before = _report(capsys)
    if change == 'crop-size':
        doc['previews'][0]['size_m'] = 1201
    else:
        doc['previews'].reverse()
    recipe.write_text(json.dumps(doc), encoding='utf-8')
    assert central_camera_bounds.main([]) == 0
    capsys.readouterr()
    assert _report(capsys)['sha256'] != before['sha256']


def test_missing_recipe_does_not_attest_fallback(config_tree, capsys):
    # The real loader can synthesize a fishing window; it is not a review recipe.
    recipe, _ = config_tree
    recipe.unlink()
    with pytest.raises(SystemExit) as exc:
        central_camera_evidence.main([REGION])
    assert exc.value.code == 2
    out, err = capsys.readouterr()
    assert not out
    assert 'missing render.json' in err
