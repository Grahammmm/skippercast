"""Offline CLI contract for the map label lint."""

import json

import pytest

from scripts.relief import label_lint

STYLE = 'style/generated/test.json'
CONTOURS = 'catalog/depth-contours/test.geojson'


def write(root, path, value):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value), encoding='utf-8')


def style(*labels):
    return {'layers': [{'id': f'layer-{i}', 'layout': {'text-field': label}}
                       for i, label in enumerate(labels)]}


def geojson(*properties):
    return {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'geometry': None, 'properties': row} for row in properties
    ]}


@pytest.fixture
def tree(tmp_path):
    write(tmp_path, 'style/index.json', {'layers': {'test': {'fragment': 'generated/test.json'}}})
    write(tmp_path, STYLE, style('1 m measured'))
    write(tmp_path, 'catalog/sources.json', {'sources': [
        {'id': 'shelf-atlas', 'name': 'Shelf Survey', 'provider': 'Fjord Lab', 'label': 'Shore Scan',
         'rights': {'attribution': 'Credit Collective'}},
        {'id': 'bay', 'name': 'ABC', 'provider': 'D E'},
    ]})
    write(tmp_path, CONTOURS, geojson({'label': 'estimated (10 m grid)', 'credit': 'Fjord Lab'}))
    return tmp_path


def run(tree, capsys, *args):
    status = label_lint.main(['--root', str(tree), *args])
    out, err = capsys.readouterr()
    return status, out, err


def test_c1_clean_default(tree, capsys):
    """C1: clean text exits zero without pulling in unrelated style or feature fields."""
    assert run(tree, capsys) == (0, 'No source names found in scanned labels.\n', '')


@pytest.mark.parametrize(('text', 'source_id'), [
    pytest.param('(shelf-atlas)', 'shelf-atlas', id='C2: catalogue id alone'),
    pytest.param('See shelf-atlas and Shelf Survey', 'shelf-atlas', id='C2: id and alias report once'),
    pytest.param('See (sHeLf SuRvEy)!', 'shelf-atlas', id='C2: case and punctuation boundaries'),
    pytest.param('See Shore Scan', 'shelf-atlas', id='C2: label alias alone'),
    pytest.param('See Credit Collective', 'shelf-atlas', id='C2: rights attribution alone'),
    pytest.param('ABC bay D E', None, id='C2: short source terms are ignored'),
    pytest.param('éShelf Survey / Shelf Survey_2 / Fjord Labyrinth', None,
                 id='C2: no embedded word matches'),
])
def test_c2_literal_matching(tree, capsys, text, source_id):
    """C2: distinguish whole-term hits from substring hits and retain the matching id."""
    write(tree, STYLE, style(text))
    status, out, err = run(tree, capsys, '--json')
    assert (status, json.loads(out), err) == (
        1 if source_id else 0,
        [{'file': STYLE, 'layer_id': 'layer-0', 'property': 'text-field', 'text': text,
          'source_id': source_id}] if source_id else [],
        '',
    )


def test_c1_nested_style_and_get(tree, capsys):
    """C1: find nested strings and get operands without linting operator or property names."""
    write(tree, STYLE, style(['concat', ['get', 'label'], ['get', 'Fjord Lab'],
                              ['to-string', ['get', 'caption']], ' Shelf Survey',
                              ['match', ['get', 'category'], ['Coast Guild', 'bay'], ' yes', ' no']]))
    write(tree, 'catalog/relief/region.json', {'sources': [
        {'id': 'other-survey', 'label': 'Far Bank', 'attribution': 'TIDE'},
        {'id': 'guild', 'label': 'Coast Guild'},
        {'id': 'concat', 'label': 'Expression, not a source name in the label'},
    ]})
    write(tree, CONTOURS, geojson(None, {'label': 'FJORD LAB', 'caption': '(Tide)'}))
    status, out, err = run(tree, capsys, '--json')
    assert (status, json.loads(out), err) == (1, [
        {'file': STYLE, 'layer_id': 'layer-0', 'property': 'text-field',
         'text': ' Shelf Survey', 'source_id': 'shelf-atlas'},
        {'file': STYLE, 'layer_id': 'layer-0', 'property': 'text-field',
         'text': 'Coast Guild', 'source_id': 'guild'},
        {'file': CONTOURS, 'feature_index': 1, 'property': 'caption',
         'text': '(Tide)', 'source_id': 'other-survey'},
        {'file': CONTOURS, 'feature_index': 1, 'property': 'label',
         'text': 'FJORD LAB', 'source_id': 'shelf-atlas'},
    ], '')


def test_c1_default_label(tree, capsys):
    """C1: label is scanned even when no style gets it explicitly."""
    write(tree, CONTOURS, geojson({'label': 'Shelf Survey'}, {'label': 42}))
    status, out, err = run(tree, capsys, '--json')
    assert (status, json.loads(out), err) == (1, [
        {'file': CONTOURS, 'feature_index': 0, 'property': 'label',
         'text': 'Shelf Survey', 'source_id': 'shelf-atlas'},
    ], '')


def test_c1_input_options(tree, capsys):
    """C1: explicit styles replace the index and extra data augments default data."""
    write(tree, STYLE, style('Shelf Survey'))
    write(tree, 'a.json', style(['get', 'caption']))
    write(tree, 'b.json', style('Far Bank'))
    write(tree, 'catalog/relief/region.json', {'sources': [{'id': 'far', 'label': 'Far Bank'}]})
    write(tree, CONTOURS, geojson({'caption': 'Fjord Lab', 'label': 'Shelf Survey'}))
    write(tree, 'first.geojson', geojson({'note': 'Shore Scan'}))
    write(tree, 'second.geojson', geojson({'alt': 'Credit Collective'}))
    assert run(tree, capsys, '--style', 'a.json', 'b.json', '--data', 'first.geojson',
               str(tree / 'second.geojson'), '--field', 'note', 'alt') == (
        1,
        "b.json: layer 'layer-0', 'text-field': 'Far Bank' matches 'far'\n"
        "catalog/depth-contours/test.geojson: feature 0, 'caption': 'Fjord Lab' matches 'shelf-atlas'\n"
        "first.geojson: feature 0, 'note': 'Shore Scan' matches 'shelf-atlas'\n"
        "second.geojson: feature 0, 'alt': 'Credit Collective' matches 'shelf-atlas'\n",
        '',
    )


def test_c3_read_only(tree, capsys):
    """C3: reporting a finding does not normalize source inputs or save a report to disk."""
    write(tree, STYLE, style('Shelf Survey'))

    def snapshot():
        return {p.relative_to(tree): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
                for p in tree.rglob('*')}

    before = snapshot()
    assert run(tree, capsys) == (
        1, f"{STYLE}: layer 'layer-0', 'text-field': 'Shelf Survey' matches 'shelf-atlas'\n", '',
    )
    assert snapshot() == before


@pytest.mark.parametrize(('path', 'args', 'content', 'error'), [
    pytest.param('catalog/sources.json', (), '!', 'JSONDecodeError', id='C3: malformed catalogue'),
    pytest.param('catalog/relief/broken.json', (), '!', 'JSONDecodeError', id='C3: malformed pointer'),
    pytest.param('style/index.json', (), '!', 'JSONDecodeError', id='C3: malformed style index'),
    pytest.param(STYLE, (), '!', 'JSONDecodeError', id='C3: malformed style fragment'),
    pytest.param(CONTOURS, (), '!', 'JSONDecodeError', id='C3: malformed default data'),
    pytest.param('missing.geojson', ('--data', 'missing.geojson'), None, 'FileNotFoundError',
                 id='C3: missing explicit data'),
])
def test_c3_unreadable_input(tree, capsys, path, args, content, error):
    """C3: refuse incomplete scans instead of certifying them clean or reporting partial findings."""
    write(tree, STYLE, style('Shelf Survey'))
    if content is not None:
        target = tree / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')
    status, out, err = run(tree, capsys, *args, '--json')
    assert (status, out, err.split(': ', 3)[:3]) == (2, '', ['label_lint', str(tree / path), error])


@pytest.mark.parametrize(('path', 'document', 'detail'), [
    pytest.param(STYLE, [], 'expected an object for style', id='C3: wrong document shape'),
    pytest.param(CONTOURS, {}, 'expected an array for features', id='C3: missing feature rows'),
    pytest.param('style/index.json', {'layers': {'test': {}}}, 'expected a fragment path for test',
                 id='C3: missing fragment path'),
    pytest.param('catalog/sources.json', {'sources': [{'name': 'Atlas'}]}, 'expected a source id',
                 id='C3: source cannot be identified'),
    pytest.param(STYLE, {'layers': [{'layout': {'text-field': 'Atlas'}}]},
                 'expected a layer id for text-field', id='C3: layer cannot be identified'),
])
def test_c3_invalid_shape(tree, capsys, path, document, detail):
    """C3: valid JSON with missing scan inputs is not a clean result."""
    write(tree, path, document)
    assert run(tree, capsys) == (2, '', f'label_lint: {tree / path}: {detail}\n')


def test_c3_unreadable_directory(tree, capsys):
    """C3: a file in place of the relief directory cannot hide its pointers."""
    path = tree / 'catalog/relief'
    path.touch()
    status, out, err = run(tree, capsys)
    assert (status, out, err.split(': ', 3)[:3]) == (
        2, '', ['label_lint', str(path), 'NotADirectoryError'],
    )
