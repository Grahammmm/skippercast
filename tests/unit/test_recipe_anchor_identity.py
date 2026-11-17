"""RF0410-4: conflicting duplicate local schema anchor identities are refused.

Two distinct schema nodes declaring one anchor name made the verdict depend on
$defs member order. Admission now refuses the ambiguity before instance
evaluation, used or not. Every schema here is a synthetic copy under tmp_path.
"""
import json

import pytest

from tests._support import ROOT
import validate_recipe as recipe

SCHEMA = 'schemas/coast-recipe-v1.schema.json'
SLUGS = ('morro-bay', 'cambria-san-simeon', 'south-big-sur-san-simeon',
         'santa-cruz-monterey-bay')
METADATA = [SCHEMA, 'catalog/sources.json', 'catalog/coastal-sectors.json']
METADATA += ['regions/' + slug + '/region.json' for slug in SLUGS]
DUPLICATE = 'schema reference not admitted: duplicate anchor at '
VALID = {'status': 'REVIEW REQUIRED', 'valid': True, 'semantic_approval': False,
         'execution_allowed': False, 'not_for_navigation': True}


def recipe_doc():
    return json.loads((ROOT / 'regions' / 'morro-bay' / 'coast.json').read_text(encoding='utf-8'))


def stage(root, defs, ref='#collision'):
    """Metadata snapshot whose schema slug is a ref and whose $defs are `defs`."""
    schema = json.loads((ROOT / SCHEMA).read_text(encoding='utf-8'))
    schema['properties']['slug'] = {'$ref': ref}
    schema['$defs'].update(defs)
    for name in METADATA:
        target = root / 'metadata' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    (root / 'metadata' / SCHEMA).write_text(json.dumps(schema), encoding='utf-8')
    (root / 'workspace').mkdir()
    return root / 'metadata', root / 'workspace'


def pair(first_kw, second_kw, reverse=False):
    items = [('first', {first_kw: 'collision', 'const': 'morro-bay'}),
             ('second', {second_kw: 'collision', 'const': 'different-slug'})]
    return dict(reversed(items) if reverse else items)


def outcome(metadata, workspace, document=None):
    try:
        recipe.validate_recipe(recipe_doc() if document is None else document,
                               metadata_root=metadata, workspace_root=workspace)
    except recipe.RecipeError as error:
        return str(error)
    return None


@pytest.mark.parametrize('first_kw,second_kw', [
    ('$anchor', '$anchor'), ('$dynamicAnchor', '$dynamicAnchor'),
    ('$anchor', '$dynamicAnchor'), ('$dynamicAnchor', '$anchor')])
@pytest.mark.parametrize('reverse', [False, True])
def test_duplicate_across_nodes_refused_in_both_orders(first_kw, second_kw, reverse, tmp_path):
    metadata, workspace = stage(tmp_path, pair(first_kw, second_kw, reverse))
    message = outcome(metadata, workspace)
    later, later_kw = ('first', first_kw) if reverse else ('second', second_kw)
    assert message == DUPLICATE + '/$defs/' + later + '/' + later_kw, message
    assert not list(workspace.iterdir())


@pytest.mark.parametrize('ref_kw', ['$ref', '$dynamicRef'])
def test_duplicate_refused_for_ref_and_dynamic_ref(ref_kw, tmp_path):
    metadata, workspace = stage(tmp_path, pair('$dynamicAnchor', '$dynamicAnchor'))
    schema = json.loads((metadata / SCHEMA).read_text(encoding='utf-8'))
    schema['properties']['slug'] = {ref_kw: '#collision'}
    (metadata / SCHEMA).write_text(json.dumps(schema), encoding='utf-8')
    assert outcome(metadata, workspace).startswith(DUPLICATE)


def test_unused_duplicate_refused_before_instance_evaluation(tmp_path):
    metadata, workspace = stage(tmp_path, pair('$anchor', '$anchor'), ref='#/$defs/first')
    # An empty instance would fail 'required' if evaluation started first.
    assert outcome(metadata, workspace, {}) == DUPLICATE + '/$defs/second/$anchor'


def test_same_node_declaring_both_keywords_is_one_identity(tmp_path):
    defs = {'one': {'$anchor': 'collision', '$dynamicAnchor': 'collision', 'const': 'morro-bay'}}
    metadata, workspace = stage(tmp_path, defs)
    assert outcome(metadata, workspace) is None
    document = recipe_doc()
    document['slug'] = 'other'
    assert not outcome(metadata, workspace, document).startswith(DUPLICATE)


def test_distinct_and_case_differing_names_stay_distinct(tmp_path):
    defs = {'a': {'$anchor': 'collision', 'const': 'morro-bay'},
            'b': {'$anchor': 'Collision', 'const': 'different-slug'},
            'c': {'$dynamicAnchor': 'collision2', 'const': 'x'}}
    metadata, workspace = stage(tmp_path, defs)
    assert outcome(metadata, workspace) is None
    document = recipe_doc()
    document['slug'] = 'different-slug'
    message = outcome(metadata, workspace, document)
    assert message is not None and message.startswith('schema slug: '), message


def test_unique_anchor_still_enforces_target(tmp_path):
    metadata, workspace = stage(tmp_path, {'a': {'$anchor': 'collision', 'const': 'morro-bay'}})
    document = recipe_doc()
    document['slug'] = 'different-slug'
    assert outcome(metadata, workspace, document).startswith('schema slug: ')


def test_diagnostic_pointer_escapes_slash_and_tilde(tmp_path):
    defs = {'a/b': {'$anchor': 'collision', 'const': 'morro-bay'},
            'c~d': {'$anchor': 'collision', 'const': 'x'}}
    metadata, workspace = stage(tmp_path, defs)
    assert outcome(metadata, workspace) == DUPLICATE + '/$defs/c~0d/$anchor'
    defs = {'x': {'$anchor': 'collision', 'const': 'morro-bay'},
            'p/q': {'$anchor': 'collision', 'const': 'x'}}
    metadata, workspace = stage(tmp_path / 'b', defs)
    assert outcome(metadata, workspace) == DUPLICATE + '/$defs/p~1q/$anchor'


def test_cli_duplicate_is_structured_invalid_and_inputs_unchanged(tmp_path, capsys):
    metadata, workspace = stage(tmp_path, pair('$anchor', '$anchor'))
    path = tmp_path / 'synthetic-recipe.json'
    path.write_text(json.dumps(recipe_doc()), encoding='utf-8')
    before = {str(p): p.read_bytes() for p in sorted(tmp_path.rglob('*')) if p.is_file()}
    code = recipe.main([str(path), '--workspace-root', str(workspace),
                        '--metadata-root', str(metadata)])
    captured = capsys.readouterr()
    assert code == 1 and captured.err == ''
    results = json.loads(captured.out)
    assert len(results) == 1
    assert results[0]['status'] == 'INVALID' and results[0]['valid'] is False
    assert results[0]['error'] == DUPLICATE + '/$defs/second/$anchor'
    assert results[0]['semantic_approval'] is False and results[0]['execution_allowed'] is False
    assert before == {str(p): p.read_bytes() for p in sorted(tmp_path.rglob('*')) if p.is_file()}
    assert not list(workspace.iterdir())


def test_cli_unique_control_stays_review_required(tmp_path, capsys):
    metadata, workspace = stage(tmp_path, {'a': {'$anchor': 'collision', 'const': 'morro-bay'}})
    path = tmp_path / 'synthetic-recipe.json'
    path.write_text(json.dumps(recipe_doc()), encoding='utf-8')
    code = recipe.main([str(path), '--workspace-root', str(workspace),
                        '--metadata-root', str(metadata)])
    assert code == 0
    assert json.loads(capsys.readouterr().out) == [dict(VALID, slug='morro-bay')]
