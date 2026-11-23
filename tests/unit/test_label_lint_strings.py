"""Offline CLI coverage for the opt-in catalogue label scan."""

import json

import pytest

from scripts.relief import label_lint

EN = 'web/strings.en.generated.json'
ES = 'web/strings.es.generated.json'
MAP = 'web/map/spots.ts'
KEY = 'spot.unnamed'


def write(root, path, value):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value) if not isinstance(value, str) else value, encoding='utf-8')


@pytest.fixture
def tree(tmp_path):
    write(tmp_path, 'catalog/sources.json', {'sources': [{'id': 'atlas', 'name': 'Shelf Survey'}]})
    write(tmp_path, 'style/index.json', {'layers': {}})
    write(tmp_path, MAP, '''
import {t} from '../i18n.ts';
const features = rows.map(r => ({type: 'Feature', properties: {
  key: r.key,
  name: r.unnamed ? t( /* fallback */ 'spot.unnamed', lang) : r.name,
  note: t('spot.tooltip', lang),
}}));
const source = {attribution: t('credit', 'en')};
const layer = {layout: {'text-field': ['get', 'name']}};
// const old = {layout: {'text-field': t('obsolete', lang)}};
''')
    write(tmp_path, EN, {KEY: {'en': 'Unnamed spot'}, 'credit': {'en': 'Shelf Survey'}})
    write(tmp_path, ES, {KEY: 'Sin nombre (sHeLf SuRvEy)', 'credit': 'Shelf Survey'})
    return tmp_path


def run(tree, capsys, *args):
    status = label_lint.main(['--root', str(tree), *args])
    out, err = capsys.readouterr()
    return status, out, err


def hit(file, key, lang, text):
    return {'file': file, 'key': key, 'lang': lang, 'text': text, 'source_id': 'atlas'}


def test_c1_feature_translation(tree, capsys):
    """C1: trace the GeoJSON fallback to drawn ink, not credits, UI or dead code."""
    status, out, err = run(tree, capsys, '--strings', '--json')
    assert (status, json.loads(out), err) == (
        1, [hit(ES, KEY, 'es', 'Sin nombre (sHeLf SuRvEy)')], '',
    )


def test_c1_direct_translation_and_both_languages(tree, capsys):
    """C1: add both languages (even with a fixed call language) to existing style hits."""
    write(tree, MAP, '''
import {t} from '../i18n.ts';
const layer = {layout: {"text-field": ['concat', t("spot.unnamed", 'es'), t("spot.unnamed", 'es')]}};
''')
    write(tree, EN, {KEY: {'en': 'Shelf Survey'}})
    write(tree, 'style/probe.json', {'layers': [
        {'id': 'probe', 'layout': {'text-field': 'Shelf Survey'}},
    ]})
    status, out, err = run(tree, capsys, '--style', 'style/probe.json', '--strings', '--json')
    assert (status, json.loads(out), err) == (
        1, [
            {'file': 'style/probe.json', 'layer_id': 'probe', 'property': 'text-field',
             'text': 'Shelf Survey', 'source_id': 'atlas'},
            hit(EN, KEY, 'en', 'Shelf Survey'), hit(ES, KEY, 'es', 'Sin nombre (sHeLf SuRvEy)'),
        ], '',
    )


@pytest.mark.parametrize('source', [
    pytest.param("const label = t('spot.unnamed', lang); const layer = {layout: {'text-field': label}};",
                 id='bound then drawn, same line'),
    pytest.param("let a = t('spot.unnamed', lang)\nconst label = a\nconst layer = {layout: {'text-field': ['concat', label, '!']}}",
                 id='chained bindings, no semicolons'),
    pytest.param("const label = t('spot.unnamed', lang);\nconst layer = {layout: {'text-field': ['get', 'name']}};\n"
                 "const f = {properties: {name: label}};", id='bound fallback in feature properties'),
    pytest.param("const name = t('spot.unnamed', lang);\nconst layer = {layout: {'text-field': ['get', 'name']}};\n"
                 "const f = {properties: {key: 1, name}};", id='shorthand property'),
])
def test_c1_follows_local_binding(tree, capsys, source):
    """C1: a lookup assigned to a local before it is drawn is still selected (else a source name slips through)."""
    write(tree, MAP, source)
    status, out, err = run(tree, capsys, '--strings', '--json')
    assert (status, json.loads(out), err) == (
        1, [hit(ES, KEY, 'es', 'Sin nombre (sHeLf SuRvEy)')], '',
    )


@pytest.mark.parametrize(('source', 'keys'), [
    pytest.param("function credits() { const label = t('credit', lang); return label; }\n"
                 "function map() { const label = 'Harbor'; return {layout: {'text-field': label}}; }",
                 set(), id='same name in another function is not drawn'),
    pytest.param("function credits() { const label = t('credit', lang); return label; }\n"
                 "function map() { const label = t('spot.unnamed', lang); return {layout: {'text-field': label}}; }",
                 {KEY}, id='drawn function binding selected, sibling credit not'),
    pytest.param("const label = t('credit', lang);\n"
                 "function map() { const label = 'Harbor'; return {layout: {'text-field': label}}; }",
                 set(), id='inner binding shadows an outer one'),
    pytest.param("const label = t('spot.unnamed', lang);\n"
                 "function map() { if (ok) { return {layout: {'text-field': label}}; } }",
                 {KEY}, id='outer binding reaches a nested block'),
    pytest.param("function map() { let label; if (ok) { label = t('spot.unnamed', lang); }\n"
                 "return {layout: {'text-field': label}}; }",
                 {KEY}, id='later bare assignment updates the declared local'),
    pytest.param("const label = t('credit', lang);\n"
                 "function map(label) { return {layout: {'text-field': label}}; }\nmap('Harbor');",
                 set(), id='function parameter shadows an outer lookup'),
    pytest.param("const label = t('credit', lang);\n"
                 "const map = (a, label = 'x') => ({layout: {'text-field': label}});",
                 set(), id='arrow parameter with a default shadows an outer lookup'),
    pytest.param("const label = t('credit', lang);\n"
                 "const map = label => { return {layout: {'text-field': label}}; };",
                 set(), id='bare arrow parameter shadows an outer lookup'),
    pytest.param("const label = t('credit', lang);\n"
                 "function map({ label }: Opts): Layer { return {layout: {'text-field': label}}; }",
                 set(), id='destructured typed parameter shadows an outer lookup'),
    pytest.param("const label = t('spot.unnamed', lang);\n"
                 "function map(other) { return {layout: {'text-field': label}}; }",
                 {KEY}, id='an unrelated parameter does not hide the outer lookup'),
    pytest.param("function map(label) { label = t('spot.unnamed', lang); return {layout: {'text-field': label}}; }",
                 {KEY}, id='parameter reassigned to a lookup is drawn'),
    pytest.param("const label = t('spot.unnamed', lang); show(label);\n"
                 "if (label) { draw = {layout: {'text-field': label}}; }",
                 {KEY}, id='call arguments and conditions are not parameters'),
])
def test_c1_bindings_respect_local_scope(source, keys):
    """C1: a same-named local or parameter elsewhere must not leak its lookup (false violation on a credit)."""
    assert label_lint.drawn_string_keys(source) == keys


def test_c1_binding_to_an_undrawn_lookup_is_ignored(tree, capsys):
    """C1: a binding only matters when drawn; an unused or same-named property key adds nothing."""
    write(tree, MAP, "const label = t('spot.unnamed', lang); const layer = {layout: {'text-field': other}};\n"
                     "const f = {label: 1};")
    assert run(tree, capsys, '--strings', '--json') == (0, '[]\n', '')


def test_c2_missing_key_is_not_a_violation(tree, capsys):
    """C2: report a missing Spanish key without fallback or a failing exit."""
    write(tree, ES, {})
    status, out, err = run(tree, capsys, '--strings', '--json')
    assert (status, json.loads(out), err) == (
        0, [{'file': ES, 'key': KEY, 'lang': 'es', 'kind': 'missing-key'}], '',
    )
    assert run(tree, capsys, '--strings') == (0, f"{ES}: es key '{KEY}': missing-key\n", '')


def test_c2_missing_key_does_not_mask_a_violation(tree, capsys):
    """C2: keep scanning later languages after a warning."""
    write(tree, EN, {})
    assert run(tree, capsys, '--strings') == (
        1, f"{EN}: en key '{KEY}': missing-key\n"
        f"{ES}: es key '{KEY}': 'Sin nombre (sHeLf SuRvEy)' matches 'atlas'\n", '',
    )


def test_c2_embedded_source_name_is_clean(tree, capsys):
    """C2: use the inherited word boundaries rather than a substring check."""
    write(tree, ES, {KEY: 'éShelf Survey y Shelf Survey_2'})
    assert run(tree, capsys, '--strings') == (0, 'No source names found in scanned labels.\n', '')


def test_c2_no_drawn_lookups(tree, capsys):
    """C2: a module that only translates attribution needs no catalogue inputs."""
    write(tree, MAP, "const source = {attribution: t('credit', 'en')};")
    write(tree, EN, '!')
    assert run(tree, capsys, '--strings', '--json') == (0, '[]\n', '')


@pytest.mark.parametrize(('path', 'content', 'detail'), [
    pytest.param('web/map/unreadable.ts', None, 'IsADirectoryError', id='C2: unreadable map module'),
    pytest.param(ES, '!', 'JSONDecodeError', id='C2: malformed string catalogue'),
    pytest.param(ES, [], 'expected an object for string catalogue', id='C2: wrong table shape'),
    pytest.param(EN, {KEY: 'flat'}, f'expected an object for {KEY}', id='C2: wrong English entry shape'),
    pytest.param(ES, {KEY: 5}, f'expected translated text for {KEY}', id='C2: non-text translation'),
])
def test_c2_unusable_input_exits_two(tree, capsys, path, content, detail):
    """C2: refuse incomplete scans; errors are not missing-key warnings."""
    if content is None:
        (tree / path).mkdir()
    else:
        write(tree, path, content)
    status, out, err = run(tree, capsys, '--strings', '--json')
    if detail.endswith('Error'):
        assert (status, out, err.split(': ', 3)[:3]) == (2, '', ['label_lint', str(tree / path), detail])
    else:
        assert (status, out, err) == (2, '', f'label_lint: {tree / path}: {detail}\n')


def test_c3_opt_in_only(tree, capsys):
    """C3: no flag means no catalogue read and byte-identical legacy output."""
    write(tree, ES, '!')
    assert run(tree, capsys, '--json') == (0, '[]\n', '')


def test_c3_read_only_with_strings(tree, capsys):
    """C3: the added scan cannot rewrite inputs or leave a generated report."""
    def snapshot():
        return {p.relative_to(tree): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
                for p in (tree, *tree.rglob('*'))}

    before = snapshot()
    assert run(tree, capsys, '--strings') == (
        1, f"{ES}: es key '{KEY}': 'Sin nombre (sHeLf SuRvEy)' matches 'atlas'\n", '',
    )
    assert snapshot() == before
