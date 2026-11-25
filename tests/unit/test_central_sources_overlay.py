"""Central overlay boundary: only reviewed, pinned candidate inputs may replace the Central credit rows."""
from hashlib import sha256
import json

import pytest

from scripts.relief import central_sources_overlay as overlay


STYLE = 'a' * 64
RELEASE = 'b' * 64
CONTOUR_REGION = 'cambria-san-simeon'
TERRAIN_REGION = 'monterey-point-sur'


def _contours(region, ids, *, overview=False):
    provenance: dict = dict(region_id=region, set='ft-v3', units='ft', contours=STYLE,
                            features=len(ids), sources=[dict(source_id=i, survey_date='unstated',
                                                             attribution=f'Credit & {i}') for i in ids])
    if overview:
        provenance['overview'] = {}
    return dict(type='FeatureCollection', provenance=provenance, features=[{} for _ in ids])


def _pointer(region, ids, *, style=True):
    doc = dict(region=region, private=False, status='reviewed', release_sha256=RELEASE, native_support_by_zoom={},
               sources=[dict(id=i, attribution=f'Credit & {i}', survey_dates=['unstated']) for i in ids])
    if style:
        doc['style'] = {'contours': STYLE}
    return doc


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    root = tmp_path / 'tree'
    root.mkdir()
    page = root / 'dist/sources.html'
    page.parent.mkdir()
    page.write_text('<p>Before</p><h2>Current official checks</h2><p>After</p>', encoding='utf-8')
    sources = {i: dict(id=i, name=f'Name {i}', provider='Agency', needs=[],
                       rights=dict(attribution=f'Credit & {i}', public_display='allowed'))
               for i in ('relief', 'coarse-only', 'detail-only', 'terrain', 'v1', 'other')}
    docs = {
        'catalogue': {'schema_version': 1, 'sources': list(sources.values())},
        f'pointer:{CONTOUR_REGION}': _pointer(CONTOUR_REGION, ['relief']),
        f'overview:{CONTOUR_REGION}': _contours(CONTOUR_REGION, ['coarse-only'], overview=True),
        f'detail:{CONTOUR_REGION}': _contours(CONTOUR_REGION, ['detail-only']),
        f'pointer:{TERRAIN_REGION}': _pointer(TERRAIN_REGION, ['terrain'], style=False),
    }

    # The register collector has its own contract tests; exercise real rendering and the CLI without copying
    # the repository's unrelated source and region assets into each fixture.
    def collect(_root):
        return dict(sources=sources, needs={}, runtime=[], regions=[
            dict(id=CONTOUR_REGION, name='Cambria', status='active', layers={
                'Depth contours': {'v1': ''}, 'Shoreline': {'other': ''}}),
            dict(id=TERRAIN_REGION, name='Monterey', status='active', layers={
                'Depth contours': {'v1': ''}, 'Shoreline': {'other': ''}}),
            dict(id='elsewhere', name='Elsewhere', status='active', layers={'Depth contours': {'v1': ''}}),
        ])

    monkeypatch.setattr(overlay.register, 'collect', collect)
    return root, tmp_path / 'stage-only', page, docs


def _write(root, docs):
    """Write every doc, return the pin document for the whole set."""
    pins = {'catalogue': None, 'regions': {}}
    for key, doc in docs.items():
        name, _, region = key.partition(':')
        path = root / (overlay.CATALOGUE if name == 'catalogue' else overlay._path(region, name))
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(doc).encode()
        path.write_bytes(raw)
        if name == 'catalogue':
            pins['catalogue'] = sha256(raw).hexdigest()
        else:
            pins['regions'].setdefault(region, {})[name] = sha256(raw).hexdigest()
    pins['tree'] = overlay.tree_digest(root)  # the page, region configs and every file the collector may read
    return pins


def _args(candidate, pins_edit=None):
    root, output, _, docs = candidate
    pins = _write(root, docs)
    if pins_edit:
        pins_edit(pins)
    pin_file = root.parent / 'pins.json'
    pin_file.write_text(json.dumps(pins))
    return ['--tree', str(root), '--out', str(output), '--pins', str(pin_file)]


def _repin_tree(root):
    """Re-pin the whole tree after a deliberate edit, so only the per-input pins can still refuse."""
    pin_file = root.parent / 'pins.json'
    pins = json.loads(pin_file.read_text())
    pins['tree'] = overlay.tree_digest(root)
    pin_file.write_text(json.dumps(pins))


def test_stage_page_replaces_only_pinned_central_regions(candidate, capsys):
    _, out, page, _ = candidate
    original = page.read_bytes()
    assert overlay.main(_args(candidate)) == 0
    result = (out / 'sources.html').read_bytes()
    receipt = json.loads(capsys.readouterr().out)
    assert receipt['html_sha256'] == sha256(result).hexdigest()
    assert sorted(receipt['regions'][CONTOUR_REGION]['contour_sources']) == ['coarse-only', 'detail-only']
    assert receipt['regions'][TERRAIN_REGION]['contour_sources'] == []
    cambria, rest = result.split(b'id="region-cambria-san-simeon"')[1].split(b'id="region-monterey-point-sur"')
    monterey, elsewhere = rest.split(b'id="region-elsewhere"')
    for ident in (b'coarse-only', b'detail-only', b'relief', b'other'):
        assert b'Credit &amp; ' + ident in cambria
    assert b'Credit &amp; v1' not in cambria
    # Terrain only: shading credit, and no contour row at all (not the stale v1 row).
    assert b'Credit &amp; terrain' in monterey
    assert b'Credit &amp; v1' not in monterey and b'Depth contours' not in monterey
    assert b'Credit &amp; v1' in elsewhere
    assert b'survey date not stated' in cambria
    assert b'<p>Before</p>' in result and b'<p>After</p>' in result
    assert page.read_bytes() == original


@pytest.mark.parametrize('key', ['catalogue', f'pointer:{CONTOUR_REGION}', f'overview:{CONTOUR_REGION}',
                                 f'detail:{CONTOUR_REGION}', f'pointer:{TERRAIN_REGION}'])
def test_edited_inputs_are_refused_without_output(candidate, capsys, key):
    root, out, _, _ = candidate
    args = _args(candidate)
    name, _, region = key.partition(':')
    path = root / (overlay.CATALOGUE if name == 'catalogue' else overlay._path(region, name))
    path.write_bytes(path.read_bytes() + b' ')
    _repin_tree(root)
    assert overlay.main(args) == 2
    assert 'SHA-256 differs' in capsys.readouterr().err
    assert not out.exists()


# Contract: every file that can change the output is bound by the reviewed pins, not only the five named inputs.
# Bug caught: the page (spliced verbatim outside the generated block) or a collector-read file (region config, other
# pointer, asset) is edited, every per-input pin still matches, and an altered page is produced instead of a refusal.
@pytest.mark.parametrize('edit', ['page_before_register', 'region_config', 'other_pointer', 'new_file', 'symlink'])
def test_edit_outside_the_named_inputs_is_refused_without_output(candidate, capsys, edit):
    root, out, page, _ = candidate
    args = _args(candidate)
    if edit == 'page_before_register':
        page.write_text('<p>Injected</p>' + page.read_text(encoding='utf-8'), encoding='utf-8')
    elif edit == 'region_config':
        (root / 'regions/elsewhere').mkdir(parents=True)
        (root / 'regions/elsewhere/region.json').write_text('{"status": "active"}')
    elif edit == 'other_pointer':
        (root / 'catalog/relief/big-sur-coast.json').write_text('{}')
    elif edit == 'new_file':
        (root / 'dist/extra.js').write_text('fetch("https://example.invalid")')
    else:
        (root / 'dist/link').symlink_to('sources.html')
    assert overlay.main(args) == 2
    assert 'tree: SHA-256 differs from the reviewed pin' in capsys.readouterr().err
    assert not out.exists()


def test_tree_changed_while_rendering_is_refused(candidate, capsys, monkeypatch):
    # Bug caught: an input rewritten between the pin check and the splice still reaches the output.
    root, out, page, _ = candidate
    args = _args(candidate)
    collect = overlay.register.collect

    def edit_then_collect(tree):
        page.write_text('<p>Late</p>' + page.read_text(encoding='utf-8'), encoding='utf-8')
        return collect(tree)

    monkeypatch.setattr(overlay.register, 'collect', edit_then_collect)
    assert overlay.main(args) == 2
    assert 'changed while the overlay was rendered' in capsys.readouterr().err
    assert not out.exists()


def test_reviewed_tree_digest_is_printed_for_release_preparation(candidate, capsys):
    # Bug caught: no way to record the tree pin from the reviewed tree, so it would be calculated from the render input.
    root, _, _, docs = candidate
    pins = _write(root, docs)
    assert overlay.main(['--tree', str(root), '--print-tree-digest']) == 0
    assert capsys.readouterr().out.strip() == pins['tree']


@pytest.mark.parametrize('problem,expected', [
    ('style', 'wrong or held detail'), ('held', 'wrong or held detail'), ('role', 'wrong or held detail'),
    ('region', 'wrong or held detail'), ('rights', 'not a public catalogue credit'),
    ('year', 'unsupported catalogue survey date'), ('private', 'expected a reviewed public pointer'),
])
def test_hash_match_does_not_grant_display_or_science_claim(candidate, capsys, problem, expected):
    _, out, _, docs = candidate
    if problem == 'style':
        docs[f'detail:{CONTOUR_REGION}']['provenance']['contours'] = 'c' * 64
    elif problem == 'held':
        docs[f'detail:{CONTOUR_REGION}']['publication_held'] = False
    elif problem == 'role':
        docs[f'detail:{CONTOUR_REGION}']['provenance']['overview'] = {}
    elif problem == 'region':
        docs[f'detail:{CONTOUR_REGION}']['provenance']['region_id'] = 'big-sur-coast'
    elif problem == 'rights':
        docs['catalogue']['sources'][0]['rights']['public_display'] = 'private'
    elif problem == 'private':
        docs[f'pointer:{TERRAIN_REGION}']['private'] = True
    else:
        docs['catalogue']['sources'][0]['survey_year'] = 2022
    assert overlay.main(_args(candidate)) == 2
    assert expected in capsys.readouterr().err
    assert not out.exists()


def test_only_central_regions_with_whole_pins_are_accepted(candidate, capsys):
    _, out, _, docs = candidate

    def foreign(pins):
        pins['regions']['morro-bay'] = pins['regions'].pop(CONTOUR_REGION)

    assert overlay.main(_args(candidate, foreign)) == 2
    assert 'Central Coast regions only' in capsys.readouterr().err

    def half(pins):
        del pins['regions'][CONTOUR_REGION]['overview']

    assert overlay.main(_args(candidate, half)) == 2
    assert 'optionally with both overview and detail' in capsys.readouterr().err

    def no_pointer(pins):
        del pins['regions'][TERRAIN_REGION]['pointer']

    assert overlay.main(_args(candidate, no_pointer)) == 2
    assert not out.exists()

    def no_tree(pins):
        del pins['tree']

    assert overlay.main(_args(candidate, no_tree)) == 2
    assert 'no tree pin was given' in capsys.readouterr().err
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
