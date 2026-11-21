"""region.py pointer-branch: an approved release becomes one local data branch, never pushed.

A synthetic OUT (the package test helpers' approved chain) and a disposable Git clone stand in
for real region data. Every refusal is checked before any Git command or write.
"""
import json
import os
import subprocess

import pytest

from scripts.relief import region as cli
from skippercast.platform import depth_contours as dc
from skippercast.relief import envelope, pointer_branch, receipts, rollback
from tests._support import ROOT
from tests.unit.test_relief_package import REGION, SOURCE, LAYERS, approved, assembly, kit_style  # noqa: F401

POINTER = f'catalog/relief/{REGION}.json'
CONTOURS = f'catalog/depth-contours/{REGION}.geojson'
SCHEMA = 'catalog/relief/pointer.schema.json'
OUTPUT = 'layers/contours/contours.geojson'
RIGHTS = {'license': 'public-domain', 'commercial_use': 'allowed', 'attribution_required': False,
          'public_display': 'allowed', 'attribution': 'Synthetic survey', 'terms_url': 'https://example.org/terms'}
CATALOG = {
    'catalog/data-needs.json': {'schema_version': 1, 'needs': [{'id': 'bathymetry'}]},
    'catalog/sources.json': {'schema_version': 1, 'sources': [{
        'id': SOURCE, 'needs': ['bathymetry'], 'documentation_url': 'https://example.org/docs',
        'review_status': 'approved', 'survey_year': 2020, 'rights': RIGHTS}]},
    f'regions/{REGION}/region.json': {'id': REGION, 'bounds': [-122, 34, -120, 36],
                                      'source_bindings': {'bathymetry': [SOURCE]}},
}
DEPTH = 60  # an ft-v2 index depth that first draws at zoom 8


def put(root, path, data):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)


@pytest.fixture
def clone(tmp_path, monkeypatch):
    """A clean repo at main holding the catalogs, the region and the pointer schema."""
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)
    monkeypatch.setenv('LC_ALL', 'C')
    root = tmp_path / 'clone'
    root.mkdir()

    def git(*args):
        return subprocess.check_output(['git', *args], cwd=root).decode().strip()

    git('init', '--initial-branch=main', '--template=')
    git('config', 'user.name', 'Fixture Builder')
    git('config', 'user.email', 'fixture@example.invalid')
    git('config', 'core.autocrlf', 'false')
    for path, doc in CATALOG.items():
        put(root, path, json.dumps(doc, indent=1).encode())
    put(root, SCHEMA, (ROOT / SCHEMA).read_bytes())
    git('add', '--', *CATALOG, SCHEMA)
    git('commit', '-m', 'Base catalog')
    return root, git


def contour_doc(*, survey_date='2020', region_id=REGION):
    common = {'source_id': SOURCE, 'survey_date': survey_date, 'vertical_datum': 'NAVD88'}
    return {
        'type': 'FeatureCollection',
        'features': [{'type': 'Feature', 'id': 'synthetic-line',
                      'properties': {**common, 'kind': 'contour', 'depth_ft': DEPTH, 'index': True,
                                     'estimated': True, 'minzoom': dc.V2_MINZOOM[DEPTH]},
                      'geometry': {'type': 'LineString', 'coordinates': [[-121.2, 35.2], [-121.1, 35.3]]}}],
        'provenance': {'region_id': region_id, 'set': dc.FT_V2, 'units': 'ft',
                       'shelf_limit_ft': dc.V2_SHELF_LIMIT_FT, 'intervals': dc.v2_intervals(),
                       'index_depths_ft': list(dc.V2_INDEX_FT), 'features': 1,
                       'sources': [{**common, 'sha256': 'a' * 64}]},
    }


def stage_contours(region, doc=None):
    """A done contours receipt whose output is the catalog-input bytes."""
    raw = receipts.canonical(contour_doc() if doc is None else doc)

    def build(out):
        (out / 'contours.geojson').write_bytes(raw)

    run = receipts.StageRun(region, 'contours', build, 'c' * 64, target='layers/contours')
    assert receipts.run_stage(run).state == 'ok'
    return raw


def release(root, *, style=None, doc=None):
    region, _, _, review, approval = approved(root, style=style)
    return region, review, approval, stage_contours(region, doc)


def argv(region, review, approval, repo, *extra):
    return ['--region', REGION, '--out', str(region.out_root), '--approval', str(approval),
            '--envelope', str(review), '--repo', str(repo), *extra]


def sha(data):
    return receipts.sha256_bytes(data)


@pytest.fixture
def git_calls(monkeypatch):
    """Every Git argv the command runs through the shared GitCli."""
    calls, real = [], rollback.GitCli.run

    def spy(self, args):
        calls.append(args)
        return real(self, args)

    monkeypatch.setattr(rollback.GitCli, 'run', spy)
    return calls


def invoke(capsys, args):
    capsys.readouterr()  # drop the fixture stages' progress lines
    return pointer_branch.main(args)


def refused(capsys, message):
    out = capsys.readouterr()
    assert (out.out, out.err) == ('', f'region.py pointer-branch: {message}\n')


def untouched(clone, head, branches='main'):
    root, git = clone
    assert git('branch', '--format=%(refname:short)') == branches
    assert git('rev-parse', 'HEAD') == head and git('status', '--porcelain') == ''


# ---------------------------------------------------------------- C1


def test_c1_first_release_has_no_previous(tmp_path, assembly, clone, capsys):
    """C1: A first release must not invent lineage; a wrong previous or serialisation changes the bytes."""
    root, git = clone
    region, review, approval, _ = release(tmp_path / 'out')
    assert invoke(capsys, argv(region, review, approval, root)) == 0
    written = (root / POINTER).read_bytes()
    assert written == receipts.canonical(envelope.build_pointer(approval, review, previous=None))
    assert json.loads(written)['previous'] is None


def test_c1_second_release_takes_previous_from_head(tmp_path, assembly, clone, capsys):
    """C1: previous is the HEAD pointer's lineage; reading another file or none breaks rollback lineage."""
    root, git = clone
    region, review, approval, _ = release(tmp_path / 'first')
    assert invoke(capsys, argv(region, review, approval, root)) == 0
    first = json.loads((root / POINTER).read_bytes())
    git('switch', 'main')
    git('merge', '--ff-only', f'data/{REGION}-{first["generation"][:12]}')

    region2, review2, approval2, _ = release(tmp_path / 'second', style=kit_style() | {'contours': None})
    assert review2.parent.name != review.parent.name
    assert invoke(capsys, argv(region2, review2, approval2, root)) == 0
    second = json.loads((root / POINTER).read_bytes())
    assert second['previous'] == {key: first[key] for key in
                                  ('generation', 'release_sha256', 'envelope_sha256', 'sha256')}
    assert (root / POINTER).read_bytes() == receipts.canonical(
        envelope.build_pointer(approval2, review2, previous=first))


def test_c1_refuses_a_generation_head_already_points_at(tmp_path, assembly, clone, capsys):
    """C1: Re-releasing HEAD's generation would make the pointer its own previous."""
    root, git = clone
    region, review, approval, _ = release(tmp_path / 'out')
    assert invoke(capsys, argv(region, review, approval, root)) == 0
    git('switch', 'main')
    git('merge', '--ff-only', f'data/{REGION}-{review.parent.name[:12]}')
    head = git('rev-parse', 'HEAD')
    branches = git('branch', '--format=%(refname:short)')
    assert invoke(capsys, argv(region, review, approval, root, '--branch', 'again')) == 1
    refused(capsys, f'HEAD already points {REGION} at generation {review.parent.name}')
    untouched(clone, head, branches)


def test_c1_verify_chain_runs_before_anything_else(tmp_path, assembly, clone, git_calls, capsys, monkeypatch):
    """C1: A bad approval must stop the command before the contours, catalog or Git are read."""
    root, git = clone
    head = git('rev-parse', 'HEAD')
    region, review, approval, _ = release(tmp_path / 'out')
    approval.write_text(json.dumps(json.loads(approval.read_bytes()) | {'verdict': 'APPROVED'}))
    seen = []
    monkeypatch.setattr(pointer_branch, 'contour_bytes', lambda *a: seen.append('contours'))
    monkeypatch.setattr(pointer_branch, 'check_catalog_input', lambda *a: seen.append('catalog'))
    assert invoke(capsys, argv(region, review, approval, root)) == 1
    refused(capsys, 'approval lacks the exact release verdict')
    assert (seen, git_calls) == ([], [])
    untouched(clone, head)


def test_c1_layer_byte_changed_after_approval_is_refused(tmp_path, assembly, clone, git_calls, capsys):
    """C1: A layer edited after review must never reach a data branch."""
    root, git = clone
    head = git('rev-parse', 'HEAD')
    region, review, approval, _ = release(tmp_path / 'out')
    layer = sorted(LAYERS)[0]
    (region.dir / layer).write_bytes(LAYERS[layer] + b'!')
    assert invoke(capsys, argv(region, review, approval, root)) == 1
    refused(capsys, f'layer hash or size changed: {layer}')
    assert git_calls == []
    untouched(clone, head)


def test_c1_head_pointer_of_another_region_is_refused(tmp_path, assembly, clone, capsys):
    """C1: Lineage from another region's pointer at this path is refused, not copied."""
    root, git = clone
    region, review, approval, _ = release(tmp_path / 'out')
    alien = envelope.build_pointer(approval, review) | {'region': 'other-bay', 'generation': 'e' * 64}
    put(root, POINTER, receipts.canonical(alien))
    git('add', POINTER)
    git('commit', '-m', 'Alien pointer')
    head = git('rev-parse', 'HEAD')
    assert invoke(capsys, argv(region, review, approval, root)) == 1
    refused(capsys, 'previous pointer belongs to another region')
    untouched(clone, head)


def test_c1_validates_against_the_clone_head_schema(tmp_path, assembly, clone, capsys):
    """C1: The pointer must satisfy the schema of the commit it lands on; a missing schema is refused."""
    root, git = clone
    region, review, approval, _ = release(tmp_path / 'out')
    schema = json.loads((root / SCHEMA).read_bytes())
    schema['required'] = [*schema['required'], 'reviewed_by']
    put(root, SCHEMA, json.dumps(schema).encode())
    git('commit', '-am', 'Stricter schema')
    head = git('rev-parse', 'HEAD')
    assert invoke(capsys, argv(region, review, approval, root)) == 1
    refused(capsys, "invalid relief metadata at document: 'reviewed_by' is a required property")
    untouched(clone, head)

    git('rm', '-q', SCHEMA)
    git('commit', '-m', 'No schema')
    head = git('rev-parse', 'HEAD')
    assert invoke(capsys, argv(region, review, approval, root)) == 1
    refused(capsys, f'HEAD has no {SCHEMA}')
    untouched(clone, head)


# ---------------------------------------------------------------- C2


@pytest.mark.parametrize('state', ['missing', 'held', 'unproved'])
def test_c2_contours_receipt_not_done_is_refused(tmp_path, assembly, clone, git_calls, capsys, state):
    """C2: Only a done contours receipt is a release input; held or edited output stops before Git."""
    root, git = clone
    head = git('rev-parse', 'HEAD')
    region, _, _, review, approval = approved(tmp_path / 'out')
    if state == 'held':
        def held(out):
            raise receipts.Held('synthetic hold')

        receipts.run_stage(receipts.StageRun(region, 'contours', held, 'c' * 64, target='layers/contours'))
    elif state == 'unproved':
        stage_contours(region)
        (region.dir / OUTPUT).write_bytes(b'{}')
    reason = receipts.check(region, 'contours').reason
    assert invoke(capsys, argv(region, review, approval, root)) == 1
    refused(capsys, f'contours receipt is not done: {state}: {reason}')
    assert git_calls == []
    untouched(clone, head)


def test_c2_rehashes_the_bytes_it_commits(tmp_path, assembly, clone, git_calls, capsys, monkeypatch):
    """C2: Bytes changed after the done rule read them must not be committed under the receipt's hash."""
    root, git = clone
    head = git('rev-parse', 'HEAD')
    region, review, approval, raw = release(tmp_path / 'out')
    real = receipts.check

    def late_write(*args, **kwargs):
        verdict = real(*args, **kwargs)
        (region.dir / OUTPUT).write_bytes(raw.replace(b'NAVD88', b'NAVD99'))
        return verdict

    monkeypatch.setattr(receipts, 'check', late_write)
    assert invoke(capsys, argv(region, review, approval, root)) == 1
    refused(capsys, f'{OUTPUT} does not match the contours receipt')
    assert git_calls == []
    untouched(clone, head)


def test_c2_region_mismatch_is_refused(tmp_path, assembly, clone, git_calls, capsys):
    """C2: Another region's contours under this receipt never reach this region's catalog path."""
    root, git = clone
    head = git('rev-parse', 'HEAD')
    region, review, approval, _ = release(tmp_path / 'out', doc=contour_doc(region_id='other-bay'))
    assert invoke(capsys, argv(region, review, approval, root)) == 1
    refused(capsys, f'{OUTPUT} is not region {REGION}')
    assert git_calls == []
    untouched(clone, head)


def test_c2_envelope_generation_not_the_approved_one(tmp_path, assembly, clone, git_calls, capsys):
    """C2: An approval for one generation cannot release another generation's envelope."""
    root, git = clone
    head = git('rev-parse', 'HEAD')
    _, review, approval, _ = release(tmp_path / 'first')
    region2, review2, _, _ = release(tmp_path / 'second', style=kit_style() | {'contours': None})
    assert review.parent.name != review2.parent.name
    assert invoke(capsys, argv(region2, review2, approval, root)) == 1
    refused(capsys, 'envelope sha256 does not match approval')
    assert git_calls == []
    untouched(clone, head)


def test_c2_envelope_from_another_out_is_refused(tmp_path, assembly, clone, git_calls, capsys):
    """C2: The contours and the envelope must come from the same OUT/<id>, not two pipelines."""
    root, git = clone
    head = git('rev-parse', 'HEAD')
    _, review, approval, _ = release(tmp_path / 'first')
    other, _, _, _ = release(tmp_path / 'second')
    assert invoke(capsys, argv(other, review, approval, root)) == 1
    refused(capsys, f'envelope is not a release of OUT/{REGION}')
    assert git_calls == []
    untouched(clone, head)


def test_c2_catalog_validator_refuses_unstated_survey_date(tmp_path, assembly, clone, git_calls, capsys):
    """C2: Done stage bytes the catalog build would reject (an unstated date) are refused unchanged."""
    root, git = clone
    head = git('rev-parse', 'HEAD')
    doc = contour_doc(survey_date=dc.UNSTATED_SURVEY_DATE)
    sources = {SOURCE: CATALOG['catalog/sources.json']['sources'][0]}
    region_doc = CATALOG[f'regions/{REGION}/region.json']
    dc.check_selected_contours(doc, region_doc, sources, {SOURCE})  # the stage's own validator accepts it
    region, review, approval, raw = release(tmp_path / 'out', doc=doc)
    assert invoke(capsys, argv(region, review, approval, root)) == 1
    refused(capsys, f'Depth contour source {SOURCE} lacks its grid hash, survey date or datum')
    assert git_calls == [] and (region.dir / OUTPUT).read_bytes() == raw
    untouched(clone, head)


# ---------------------------------------------------------------- C3


def test_c3_branch_has_exactly_the_two_files_in_one_signed_commit(tmp_path, assembly, clone, capsys):
    """C3: Extra paths, a missing sign-off, a moved main or a wrong receipt line fail here."""
    root, git = clone
    head = git('rev-parse', 'HEAD')
    region, review, approval, raw = release(tmp_path / 'out')
    gen = review.parent.name
    capsys.readouterr()
    assert cli.main(['pointer-branch', *argv(region, review, approval, root)]) == 0
    branch = f'data/{REGION}-{gen[:12]}'
    pointer = receipts.canonical(envelope.build_pointer(approval, review))
    commit = git('rev-parse', 'HEAD')
    out = capsys.readouterr()
    assert (out.out, out.err) == (f'Branch: {branch}\nCommit: {commit}\n{POINTER}: {sha(pointer)}\n'
                                  f'{CONTOURS}: {sha(raw)}\nNot pushed.\n', '')
    assert git('branch', '--show-current') == branch
    assert git('rev-parse', 'HEAD~1', 'main').splitlines() == [head, head]
    assert git('diff', '--name-only', 'HEAD~1').splitlines() == sorted([POINTER, CONTOURS])
    assert git('log', '-1', '--format=%s') == f'Release relief for {REGION} generation {gen}'
    assert git('log', '-1', '--format=%(trailers:key=Signed-off-by,valueonly)') == (
        'Fixture Builder <fixture@example.invalid>')
    assert git('show', f'HEAD:{CONTOURS}').encode() == raw
    assert git('remote') == '' and git('status', '--porcelain') == ''


def test_c3_named_branch_and_dirty_clone(tmp_path, assembly, clone, capsys):
    """C3: --branch names the branch; a dirty clone is refused before the branch is created."""
    root, git = clone
    head = git('rev-parse', 'HEAD')
    region, review, approval, _ = release(tmp_path / 'out')
    put(root, 'scratch.txt', b'local edit\n')
    assert invoke(capsys, argv(region, review, approval, root, '--branch', 'data/named')) == 1
    refused(capsys, 'rollback requires a clean worktree and index')
    assert git('branch', '--format=%(refname:short)') == 'main' and git('rev-parse', 'HEAD') == head
    (root / 'scratch.txt').unlink()
    assert invoke(capsys, argv(region, review, approval, root, '--branch', 'data/named')) == 0
    assert git('branch', '--show-current') == 'data/named'


@pytest.mark.parametrize('bad', [['--region', 'Morro Bay'], ['--approval']], ids=['region', 'missing-approval'])
def test_c3_usage_errors_exit_2(tmp_path, clone, bad, capsys):
    """C3: Usage errors are 2, never mistaken for a refusal or a written branch."""
    root, _ = clone
    args = ['--region', REGION, '--out', str(tmp_path), '--approval', 'a.json', '--envelope', 'e.json',
            '--repo', str(root)]
    if bad == ['--approval']:
        args = args[:4] + args[6:]
    else:
        args[:2] = bad
    with pytest.raises(SystemExit) as exc:
        pointer_branch.main(args)
    assert exc.value.code == 2


# ------------------------------------------------- shared writer amendment


@pytest.mark.parametrize('message', [None, 'Release relief for fixture'], ids=['default', 'supplied'])
def test_a1_write_branch_message(clone, message):
    """A1: The rollback subject stays byte-identical by default; a supplied subject is used verbatim."""
    root, git = clone
    state = {POINTER: b'{"release":1}', CONTOURS: None}
    kwargs = {} if message is None else {'message': message}
    rollback.write_branch(root, REGION, state, branch='local/one', run=rollback.GitCli(root).run, **kwargs)
    expected = f'Roll back relief release for {REGION}' if message is None else message
    assert git('log', '-1', '--format=%B') == f'{expected}\n\nSigned-off-by: Fixture Builder <fixture@example.invalid>'
