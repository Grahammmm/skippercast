"""Preview asset assembler: only the pinned real-envelope candidate becomes a deployable stage tree."""
from hashlib import sha256
import json

import pytest

from scripts.relief import morro_preview_assets as assets

ENVELOPE = 'e' * 63 + 'f'
RELEASE = 'b' * 63 + 'c'
GENERATION = 'a' * 63 + 'd'
CATALOGUE = 'c' * 63 + 'd'
CREDITS = b'<main>Credits: NOAA topobathy, BlueTopo</main>'
SURVEY = {'decoded': {'bytes': 10, 'sha256': '1' * 63 + '2'}, 'wire': {'bytes': 5, 'sha256': '3' * 63 + '4'}}
GAP = {'decoded': {'bytes': 4, 'sha256': '5' * 63 + '6'}, 'wire': {'bytes': 3, 'sha256': '7' * 63 + '8'}}


def _sha(raw):
    return sha256(raw).hexdigest()


@pytest.fixture
def case(tmp_path, monkeypatch):
    tree = tmp_path / 'candidate'
    pointer = dict(region='morro-bay', status='reviewed', private=False, envelope_sha256=ENVELOPE,
                   release_sha256=RELEASE, generation=GENERATION, survey_detail=SURVEY, survey_gap=GAP)
    docs = {'pointer': pointer, 'catalog_contours': {'type': 'FeatureCollection', 'features': [1]},
            'detail': {'type': 'FeatureCollection', 'features': [2]},
            'overview': {'type': 'FeatureCollection', 'features': [3]}}
    page = tree / 'dist/sources.html'
    page.parent.mkdir(parents=True)
    page.write_bytes(b'<main>stale v1 credits</main>')
    calls = {'render': [], 'build': 0}

    def render(root, pins):
        calls['render'].append(pins)
        return CREDITS, {'html_sha256': _sha(CREDITS), 'shading_sources': ['relief'], 'contour_sources': ['ft-v3']}

    def build(root):
        calls['build'] += 1
        client = root / 'dist/client'
        (client / 'catalog/relief').mkdir(parents=True)
        (client / 'regions/morro-bay').mkdir(parents=True)
        (client / 'precache.json').write_text(json.dumps({'build': '0123456789'}))
        (client / 'sources.0123456789.html').write_bytes(b'<!doctype html>' + (root / 'dist/sources.html').read_bytes())
        (client / 'catalog/relief/morro-bay.json').write_bytes((root / assets.FILES['pointer']).read_bytes())
        for name in ('detail', 'overview'):
            (client / assets.BUILT[name].removeprefix('client/')).write_bytes((root / assets.FILES[name]).read_bytes())
        (root / 'dist/server').mkdir()
        (root / 'dist/server/index.js').write_text('export default {}')

    monkeypatch.setattr(assets.overlay, 'render', render)

    def write(identity_changes=None, **overrides):
        ident = {'schema': assets.IDENTITY_SCHEMA, 'region': 'morro-bay', 'envelope_sha256': ENVELOPE,
                 'release_sha256': RELEASE, 'generation': GENERATION, 'publication_signature': None,
                 'sources_overlay_html_sha256': _sha(CREDITS), 'files': {}}
        for name, rel in assets.FILES.items():
            raw = json.dumps(overrides.get(name, docs[name]), sort_keys=True).encode()
            (tree / rel).parent.mkdir(parents=True, exist_ok=True)
            (tree / rel).write_bytes(raw)
            ident['files'][name] = _sha(raw)
        ident['pointer_sha256'] = ident['files']['pointer']
        ident.update(identity_changes or {})
        path = tmp_path / 'preview-identity.json'
        path.write_text(json.dumps(ident))
        return path

    return dict(tree=tree, out=tmp_path / 'preview-assets', page=page, docs=docs, write=write, build=build, calls=calls)


def _assemble(case, identity):
    return assets.assemble(case['tree'], identity, CATALOGUE, case['out'], build=case['build'])


def test_assembles_pinned_candidate_with_credits_fed_before_fingerprinting(case):
    manifest = _assemble(case, case['write']())
    out = case['out']
    assert manifest['build'] == '0123456789' and manifest['publication_signature'] is None
    assert manifest['envelope_sha256'] == ENVELOPE and manifest['survey_detail'] == SURVEY
    assert manifest['survey_gap'] == GAP
    # The Worker-named shell was made from the rendered credits, not the stale input page.
    shell = (out / manifest['sources_shell']).read_bytes()
    assert CREDITS in shell and b'stale v1' not in shell
    assert case['page'].read_bytes() == b'<main>stale v1 credits</main>'
    assert case['calls']['render'] == [{'pointer': manifest['candidate']['pointer'], 'detail': manifest['candidate']['detail'],
                                        'overview': manifest['candidate']['overview'], 'catalogue': CATALOGUE}]
    for name, rel in assets.BUILT.items():
        assert manifest['files'][rel]['sha256'] == manifest['candidate'][name] == _sha((out / rel).read_bytes())
    assert 'server/index.js' in manifest['files'] and 'manifest.json' not in manifest['files']
    assert assets.verify(out) == json.loads((out / 'manifest.json').read_bytes())
    assert not [p for p in out.parent.iterdir() if p.name.startswith('.preview-assets.')]


def test_cli_reports_and_verifies(case, capsys, monkeypatch):
    identity = case['write']()
    monkeypatch.setattr(assets, 'run_build', case['build'])
    assert assets.main(['assemble', '--tree', str(case['tree']), '--identity', str(identity),
                        '--catalogue-sha256', CATALOGUE, '--out', str(case['out'])]) == 0
    first = json.loads(capsys.readouterr().out)
    assert first['build'] == '0123456789' and first['envelope_sha256'] == ENVELOPE
    assert assets.main(['verify', '--out', str(case['out'])]) == 0
    assert json.loads(capsys.readouterr().out) == first


@pytest.mark.parametrize('problem,message', [
    ('fixture_pointer', 'placeholder fixture pointer'),
    ('placeholder_envelope', 'placeholder digest'),
    ('no_survey_pair', 'no survey-detail pair'),
    ('no_gap_companion', 'no survey-gap companion'),
    ('gap_repeats_detail', 'repeats the survey detail'),
    ('other_envelope', 'envelope_sha256 differs'),
    ('signed', 'publication signature'),
    ('credits', 'rendered /sources page differs'),
    ('edited_contour', 'detail: SHA-256 differs'),
    ('three_pins', 'exactly the four candidate files'),
])
def test_refused_before_build_and_without_output(case, problem, message):
    pointer = dict(case['docs']['pointer'])
    changes, overrides = {}, {}
    if problem == 'fixture_pointer':
        pass  # both pins are rewritten to the fixture pointer below
    elif problem == 'placeholder_envelope':
        pointer['envelope_sha256'] = 'a' * 64
        changes = {'envelope_sha256': 'a' * 64}
    elif problem == 'no_survey_pair':
        del pointer['survey_detail']
    elif problem == 'no_gap_companion':
        del pointer['survey_gap']
    elif problem == 'gap_repeats_detail':
        pointer['survey_gap'] = dict(GAP, wire=SURVEY['wire'])
    elif problem == 'other_envelope':
        pointer['envelope_sha256'] = '9' * 63 + '8'
    elif problem == 'signed':
        changes = {'publication_signature': 'APPROVED'}
    elif problem == 'credits':
        changes = {'sources_overlay_html_sha256': '7' * 63 + '6'}
    overrides['pointer'] = pointer
    identity = case['write'](changes, **overrides)
    if problem == 'edited_contour':
        path = case['tree'] / assets.FILES['detail']
        path.write_bytes(path.read_bytes() + b' ')
    elif problem == 'three_pins':
        ident = json.loads(identity.read_bytes())
        del ident['files']['catalog_contours']
        identity.write_text(json.dumps(ident))
    elif problem == 'fixture_pointer':
        ident = json.loads(identity.read_bytes())
        ident['pointer_sha256'] = ident['files']['pointer'] = next(iter(assets.PLACEHOLDER_POINTERS))
        identity.write_text(json.dumps(ident))
    with pytest.raises(assets.Held, match=message):
        _assemble(case, identity)
    assert case['calls']['build'] == 0
    assert not case['out'].exists()
    assert case['page'].read_bytes() == b'<main>stale v1 credits</main>'


def test_build_that_drops_the_pointer_copy_produces_nothing(case):
    identity = case['write']()
    good = case['build']

    def build(root):
        good(root)
        (root / 'dist/client/catalog/relief/morro-bay.json').unlink()

    with pytest.raises(assets.Held, match='not the pinned pointer'):
        assets.assemble(case['tree'], identity, CATALOGUE, case['out'], build=build)
    assert not case['out'].exists()
    assert case['page'].read_bytes() == b'<main>stale v1 credits</main>'


def test_failed_build_restores_input_page(case):
    identity = case['write']()

    def build(root):
        raise assets.Held('build: pnpm build exited 1')

    with pytest.raises(assets.Held, match='pnpm build exited'):
        assets.assemble(case['tree'], identity, CATALOGUE, case['out'], build=build)
    assert case['page'].read_bytes() == b'<main>stale v1 credits</main>'
    assert not case['out'].exists()


def test_existing_or_nested_output_is_refused(case):
    identity = case['write']()
    with pytest.raises(assets.Held, match='outside'):
        assets.assemble(case['tree'], identity, CATALOGUE, case['tree'] / 'out', build=case['build'])
    case['out'].mkdir()
    with pytest.raises(assets.Held, match='already exists'):
        _assemble(case, identity)
    assert case['calls']['build'] == 0


@pytest.mark.parametrize('tamper', ['edit', 'add', 'remove'])
def test_verify_refuses_changed_output(case, tamper):
    manifest = _assemble(case, case['write']())
    out = case['out']
    if tamper == 'edit':
        (out / assets.BUILT['detail']).write_bytes(b'{}')
    elif tamper == 'add':
        (out / 'client/extra.js').write_text('x')
    else:
        (out / manifest['sources_shell']).unlink()
    with pytest.raises(assets.Held, match='differ from the manifest'):
        assets.verify(out)
    assert assets.main(['verify', '--out', str(out)]) == 2
