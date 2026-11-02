import json
import sys

import pytest

from research.scripts import merge_usgs_context as mod

SNAPSHOT = '2026-10-01T00:00:00Z'


def _feature(i, layer, key, value):
    props = {'id': f'{layer}-{i}', 'mpa_screened_at': SNAPSHOT, key: value,
             'fishing_target': False, 'exportable': False, 'depth_qualified': False}
    return {'type': 'Feature', 'geometry': None, 'properties': props}


def _layers():
    legacy = {'scope': 'generalized-statewide-usgs-hard-bottom-context', 'failed_blocks': [],
              'features': [_feature(i, 'legacy', 'block_id', f'B{i % 3}') for i in range(600)]}
    doi = {'scope': 'generalized-usgs-doi-hard-bottom-context', 'failed_releases': [], 'held_releases': ['H1'],
           'features': [_feature(i, 'doi', 'release_id', f'R{i % 2}') for i in range(500)]}
    return legacy, doi


def _refused(legacy, doi, message):
    with pytest.raises(ValueError) as error:
        mod.merge(legacy, doi)
    assert str(error.value) == message


def test_valid_layers_merge_unchanged():
    result = mod.merge(*_layers())
    assert set(result) == {'type', 'schema_version', 'scope', 'compiled_at', 'source', 'source_catalog_url',
                           'legacy_block_count', 'doi_release_count', 'held_releases', 'mpa_screened_at',
                           'method', 'limitations', 'features'}
    assert (result['legacy_block_count'], result['doi_release_count']) == (3, 2)
    assert len(result['features']) == 1100 and result['mpa_screened_at'] == SNAPSHOT


@pytest.mark.parametrize('bad', [{'type': 'Feature', 'geometry': None}, ['not', 'an', 'object'], {'properties': 'text'}])
def test_legacy_feature_without_properties_is_named(bad):
    legacy, doi = _layers()
    legacy['features'][3] = bad
    _refused(legacy, doi, 'legacy feature 3: not a feature')


@pytest.mark.parametrize('value', [['a'], '', None, 7])
def test_doi_id_not_text_is_named(value):
    legacy, doi = _layers()
    doi['features'][5]['properties']['id'] = value
    _refused(legacy, doi, 'doi feature 5: id missing or not text')


@pytest.mark.parametrize('layer,i,key,value,message', [
    ('doi', 0, 'mpa_screened_at', None, 'doi feature 0: MPA snapshot missing'),
    ('legacy', 9, 'block_id', None, 'legacy feature 9: block_id missing'),
    ('doi', 2, 'release_id', ['R1'], 'doi feature 2: release_id missing'),
    ('doi', 4, 'release_id', 'drop', 'doi feature 4: release_id missing')])
def test_snapshot_block_and_release_checked_before_output(layer, i, key, value, message):
    layers = dict(zip(('legacy', 'doi'), _layers()))
    props = layers[layer]['features'][i]['properties']
    if value == 'drop':  # a DOI feature carrying a block_id instead is still refused
        props['block_id'] = props.pop(key)
    elif value is None:
        del props[key]
    else:
        props[key] = value
    _refused(layers['legacy'], layers['doi'], message)


@pytest.mark.parametrize('layer,features', [('legacy', {}), ('doi', 'x')])
def test_features_not_a_list_is_named(layer, features):
    layers = dict(zip(('legacy', 'doi'), _layers()))
    layers[layer]['features'] = features
    _refused(layers['legacy'], layers['doi'], f'{layer} features is not a list')


def test_existing_refusals_keep_text_and_order():
    legacy, doi = _layers()
    legacy['scope'], legacy['features'] = 'other', {}
    _refused(legacy, doi, 'Unexpected USGS source layer scope')
    legacy, doi = _layers()
    doi['features'][1]['properties']['id'] = 'legacy-1'
    _refused(legacy, doi, 'USGS source feature IDs collide')
    legacy, doi = _layers()
    legacy['features'] = legacy['features'][:10]
    _refused(legacy, doi, 'Combined USGS context unexpectedly incomplete')


def _cli(monkeypatch, capsys, tmp_path, legacy_text, doi_text):
    for name, text in (('legacy', legacy_text), ('doi', doi_text)):
        if text is not None:
            (tmp_path / f'{name}.json').write_text(text, encoding='utf-8')
    out = tmp_path / 'out' / 'context.geojson'
    monkeypatch.setattr(sys, 'argv', ['merge_usgs_context', '--legacy', str(tmp_path / 'legacy.json'),
                                      '--doi', str(tmp_path / 'doi.json'), '--output', str(out)])
    try:
        mod.main()
        code = 0
    except SystemExit as stop:
        code = stop.code
    return code, capsys.readouterr(), out


def test_cli_missing_legacy_file_exits_1(monkeypatch, capsys, tmp_path):
    code, captured, out = _cli(monkeypatch, capsys, tmp_path, None, json.dumps(_layers()[1]))
    assert (code, captured.err, captured.out) == (1, 'merge_usgs_context: FileNotFoundError\n', '')
    assert not out.exists() and str(tmp_path) not in captured.err


@pytest.mark.parametrize('text', ['{not json', '[]', '\xff'])
def test_cli_unreadable_json_is_one_line(monkeypatch, capsys, tmp_path, text):
    code, captured, out = _cli(monkeypatch, capsys, tmp_path, json.dumps(_layers()[0]), text)
    assert code == 1 and captured.err.startswith('merge_usgs_context: ') and captured.err.count('\n') == 1
    assert not out.exists() and 'Traceback' not in captured.err


def test_cli_shape_error_writes_nothing(monkeypatch, capsys, tmp_path):
    legacy, doi = _layers()
    del legacy['features'][3]['properties']
    code, captured, out = _cli(monkeypatch, capsys, tmp_path, json.dumps(legacy), json.dumps(doi))
    assert (code, captured.err) == (1, 'merge_usgs_context: legacy feature 3: not a feature\n')
    assert not out.parent.exists() or list(out.parent.iterdir()) == []


def test_cli_good_merge_writes_output(monkeypatch, capsys, tmp_path):
    code, captured, out = _cli(monkeypatch, capsys, tmp_path, *(json.dumps(layer) for layer in _layers()))
    assert code == 0 and len(json.loads(out.read_text())['features']) == 1100
    assert [p.name for p in out.parent.iterdir()] == ['context.geojson']
    assert captured.out == '1100 context polygons across 3 legacy blocks and 2 DOI releases\n'
