"""Overlay boundary: only reviewed candidate inputs may replace the Morro credit rows."""
from hashlib import sha256
import json

import pytest

from scripts.relief import morro_sources_overlay as overlay


STYLE = 'a' * 64
RELEASE = 'b' * 64


def _contours(ids, *, overview=False):
    provenance: dict = dict(region_id='morro-bay', set='ft-v3', units='ft', contours=STYLE,
                      features=len(ids), sources=[dict(source_id=i, survey_date='unstated',
                                                       attribution=f'Credit & {i}') for i in ids])
    if overview:
        provenance['overview'] = {}
    return dict(type='FeatureCollection', provenance=provenance, features=[{} for _ in ids])


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    root = tmp_path / 'tree'
    root.mkdir()
    output = tmp_path / 'stage-only'
    page = root / 'dist/sources.html'
    page.parent.mkdir()
    page.write_text('<p>Before</p><h2>Current official checks</h2><p>After</p>', encoding='utf-8')
    sources = {i: dict(id=i, name=f'Name {i}', provider='Agency', needs=[],
                       rights=dict(attribution=f'Credit & {i}', public_display='allowed'))
               for i in ('relief', 'coarse-only', 'detail-only', 'v1', 'other')}
    docs = dict(
        pointer=dict(region='morro-bay', private=False, status='reviewed', release_sha256=RELEASE,
                     style={'contours': STYLE}, native_support_by_zoom={},
                     sources=[dict(id='relief', attribution='Credit & relief', survey_dates=['unstated'])]),
        overview=_contours(['coarse-only'], overview=True), detail=_contours(['detail-only']),
        catalogue={'schema_version': 1, 'sources': list(sources.values())},
    )

    # The existing collector has its own contract tests. Exercise real rendering and the CLI
    # without copying the entire repository's unrelated source and region assets into each fixture.
    def collect(_root):
        return dict(sources=sources, needs={}, runtime=[], regions=[
            dict(id='morro-bay', name='Morro Bay', status='active', layers={
                'Depth contours': {'v1': ''}, 'Shoreline': {'other': ''}}),
            dict(id='elsewhere', name='Elsewhere', status='active', layers={'Depth contours': {'v1': ''}}),
        ])

    monkeypatch.setattr(overlay.register, 'collect', collect)
    return root, output, page, docs


def _args(candidate):
    root, output, _, docs = candidate
    args = ['--tree', str(root), '--out', str(output)]
    for name, doc in docs.items():
        path = root / overlay.INPUTS[name]
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(doc).encode()
        path.write_bytes(raw)
        args += [f'--{name}-sha256', sha256(raw).hexdigest()]
    return args


def test_stage_page_replaces_morro_only_and_uses_both_contour_inputs(candidate, capsys):
    _, out, page, _ = candidate
    original = page.read_bytes()
    # Stale one-file overlays lose the overview-only row or leave the v1 row in Morro.
    assert overlay.main(_args(candidate)) == 0
    result = (out / 'sources.html').read_bytes()
    receipt = json.loads(capsys.readouterr().out)
    assert receipt['release_sha256'] == RELEASE
    assert receipt['html_sha256'] == sha256(result).hexdigest()
    morro, elsewhere = result.split(b'id="region-morro-bay"')[1].split(b'id="region-elsewhere"')
    for ident in (b'coarse-only', b'detail-only', b'relief', b'other'):
        assert b'Credit &amp; ' + ident in morro
    assert b'Credit &amp; v1' not in morro
    assert b'Credit &amp; v1' in elsewhere
    assert b'survey date not stated' in morro
    assert b'<p>Before</p>' in result and b'<p>After</p>' in result
    assert page.read_bytes() == original


@pytest.mark.parametrize('name', ['pointer', 'overview', 'detail', 'catalogue'])
def test_edited_inputs_are_refused_without_output(candidate, capsys, name):
    root, out, _, _ = candidate
    args = _args(candidate)
    path = root / overlay.INPUTS[name]
    path.write_bytes(path.read_bytes() + b' ')
    assert overlay.main(args) == 2
    assert f'{name}: SHA-256' in capsys.readouterr().err
    assert not out.exists()


@pytest.mark.parametrize('problem,expected', [
    ('style', 'wrong or held detail'), ('held', 'wrong or held detail'), ('role', 'wrong or held detail'),
    ('rights', 'not a public catalogue credit'), ('year', 'unsupported catalogue survey date'),
])
def test_hash_match_does_not_grant_display_or_science_claim(candidate, capsys, problem, expected):
    _, out, _, docs = candidate
    if problem == 'style':
        docs['detail']['provenance']['contours'] = 'c' * 64
    elif problem == 'held':
        docs['detail']['publication_held'] = False
    elif problem == 'role':
        docs['detail']['provenance']['overview'] = {}
    elif problem == 'rights':
        docs['catalogue']['sources'][0]['rights']['public_display'] = 'private'
    else:
        docs['catalogue']['sources'][0]['survey_year'] = 2022
    assert overlay.main(_args(candidate)) == 2
    assert expected in capsys.readouterr().err
    assert not out.exists()


def test_output_cannot_overwrite_or_be_inside_source_tree(candidate):
    root, out, page, _ = candidate
    original = page.read_bytes()
    args = _args(candidate)
    assert overlay.main([*args, '--out', str(root / 'dist/accidental')]) == 2
    assert not (root / 'dist/accidental').exists()
    out.mkdir()
    (out / 'sources.html').write_bytes(b'previous overlay')
    assert overlay.main(args) == 2
    assert (out / 'sources.html').read_bytes() == b'previous overlay'
    assert page.read_bytes() == original
