"""The manual Morro stage preview: workflow guards and the controller steps it runs.

Offline only: no Cloudflare, GitHub or R2 call is made. A hosted run needs G's explicit
preview approval and the stage-only credentials (see the workflow header).
"""
import hashlib
import io
import json
import os
import re
import subprocess

from botocore.exceptions import ClientError
import pytest
import yaml

from scripts.relief import morro_stage_controller as controller
from scripts.relief import morro_stage_preview as preview
from tests._support import ROOT

WORKFLOW_PATH = ROOT / '.github/workflows/stage-preview.yml'
WORKFLOW_TEXT = WORKFLOW_PATH.read_text()
WORKFLOW = yaml.safe_load(WORKFLOW_TEXT)
STEPS = WORKFLOW['jobs']['preview']['steps']
POINTER = {'schema': 'sc-relief-pointer/1', 'region': 'morro-bay', 'generation': 'a' * 64}
ORIGIN = 'https://skippercast-morro-stage.fixture-account.workers.dev'


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                           '-c', 'commit.gpgsign=false', *args], check=True, capture_output=True, text=True).stdout.strip()


def write(repo, path, data):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data if isinstance(data, bytes) else data.encode())


def commit(repo, files, message):
    for path, data in files.items():
        write(repo, path, data)
    git(repo, 'add', '-A')
    git(repo, 'commit', '-q', '-m', message)
    return git(repo, 'rev-parse', 'HEAD')


def pointer_bytes(doc=POINTER):
    return (json.dumps(doc, sort_keys=True) + '\n').encode()


@pytest.fixture
def repo(tmp_path):
    repo = tmp_path / 'candidate'
    repo.mkdir()
    git(repo, 'init', '-q')
    return repo


@pytest.fixture
def base(repo):
    return commit(repo, {'server/index.ts': 'export {}\n', preview.POINTER: pointer_bytes(dict(POINTER, generation='0' * 64))},
                  'reviewed main')


def step(name_prefix):
    matches = [i for i, s in enumerate(STEPS) if s.get('name', '').startswith(name_prefix)]
    assert len(matches) == 1, name_prefix
    return matches[0]


# --- workflow -------------------------------------------------------------------------------------

def test_workflow_runs_only_on_manual_dispatch_from_protected_main():
    triggers = WORKFLOW[True]  # YAML 1.1 reads the `on:` key as a boolean
    assert list(triggers) == ['workflow_dispatch']
    assert set(triggers['workflow_dispatch']['inputs']) == {'candidate', 'pointer_sha256'}
    assert WORKFLOW['permissions'] == {'contents': 'read'}
    job = WORKFLOW['jobs']['preview']
    assert list(WORKFLOW['jobs']) == ['preview']
    for clause in ("github.event_name == 'workflow_dispatch'", "github.repository == 'Grahammmm/skippercast'",
                   "github.ref == 'refs/heads/main'", 'github.ref_protected'):
        assert clause in job['if']
    assert job['environment'] == 'morro-stage-preview'
    assert WORKFLOW['env']['STAGE_WORKER'].endswith('-stage') and WORKFLOW['env']['STAGE_BUCKET'].endswith('-stage')


def test_workflow_reads_only_stage_secrets_and_never_names_production_stores():
    secrets = set(re.findall(r'secrets\.([A-Z0-9_]+)', WORKFLOW_TEXT))
    assert secrets == {'STAGE_CLOUDFLARE_API_TOKEN', 'STAGE_CLOUDFLARE_ACCOUNT_ID', 'STAGE_R2_PUBLISH_TOKEN'}
    body = '\n'.join(line for line in WORKFLOW_TEXT.splitlines() if not line.lstrip().startswith('#'))
    for production in ("'skippercast-feeds'", 'skippercast-feeds ', 'skippercast-backups', 'skippercast-advisor-media',
                       'cloudflare_deploy.sh', 'd1 ', 'CUSTOM_DOMAINS', 'pull_request_target'):
        assert production not in body
    deploy = STEPS[step('Deploy the stage Worker only')]
    assert deploy['run'].startswith('$WRANGLER deploy --config wrangler.stage.json ')
    assert set(deploy['env']) == {'CLOUDFLARE_API_TOKEN', 'CLOUDFLARE_ACCOUNT_ID'}
    assert all('secrets.STAGE_' in value for value in deploy['env'].values())


def test_guards_run_from_the_controller_before_dependencies_build_or_any_credential():
    controller_checkout, candidate_checkout = [s for s in STEPS if str(s.get('uses', '')).startswith('actions/checkout@')]
    assert controller_checkout['with']['ref'] == '${{ github.workflow_sha }}'
    assert candidate_checkout['with']['ref'] == '${{ inputs.candidate }}'
    for checkout in (controller_checkout, candidate_checkout):
        assert checkout['with']['persist-credentials'] is False
    sparse = controller_checkout['with']['sparse-checkout'].split()
    assert 'scripts/relief/morro_stage_preview.py' in sparse and 'scripts/relief/morro_stage_controller.py' in sparse
    order = [step('Reject a non-main dispatch'), STEPS.index(controller_checkout), step('Move the controller'),
             STEPS.index(candidate_checkout), step('Require the candidate to change only Morro data'),
             step('Plan the isolated stage config'), step('Install locked web dependencies'),
             step('Build Worker and fingerprinted site'), step('Re-plan after the build'),
             step('Copy the candidate'), step('Place the checked stage config'), step('Deploy the stage Worker only'),
             step('Require the preview to serve exactly')]
    assert order == sorted(order)
    # Controller copies, never the candidate's, run every guard.
    for name in ('Require the candidate', 'Plan the isolated', 'Re-plan after', 'Copy the candidate', 'Place the checked'):
        assert '"$CONTROLLER/scripts/relief/' in STEPS[step(name)]['run']
    assert '--worker "$STAGE_WORKER" --bucket "$STAGE_BUCKET"' in STEPS[step('Plan the isolated')]['run']
    assert 'cmp "$PLAN_DIR/plan.json" "$PLAN_DIR.rebuilt/plan.json"' in STEPS[step('Re-plan after')]['run']
    # No credential reaches the candidate's own dependency install or build scripts.
    for name in ('Install locked web dependencies', 'Build Worker and fingerprinted site'):
        assert 'env' not in STEPS[step(name)]
    assert 'secrets.' not in json.dumps(WORKFLOW['jobs']['preview']['env'])


def test_every_action_is_pinned_to_a_full_commit():
    for s in STEPS:
        if 'uses' in s:
            ref = s['uses'].split('@', 1)[1]
            assert len(ref) == 40 and all(c in '0123456789abcdef' for c in ref), s['uses']


@pytest.mark.parametrize(('change', 'held'), [
    ({}, None),
    ({'GITHUB_REF': 'refs/heads/feature'}, 'protected main'),
    ({'GITHUB_REF_PROTECTED': 'false'}, 'protected main'),
    ({'CANDIDATE': 'abc123'}, 'full lowercase commit'),
    ({'CANDIDATE': 'A' * 40}, 'full lowercase commit'),
    ({'POINTER_SHA256': 'f' * 63}, '64 lowercase hex'),
    ({'HAS_R2': 'false'}, 'not configured'),
    ({'STAGE_URL': ''}, 'not configured'),
])
def test_the_first_step_holds_bad_dispatches_before_checkout(change, held):
    script = STEPS[step('Reject a non-main dispatch')]['run']
    env = {'PATH': os.environ['PATH'], 'GITHUB_REF': 'refs/heads/main', 'GITHUB_REF_PROTECTED': 'true',
           'CANDIDATE': 'a' * 40, 'POINTER_SHA256': 'b' * 64, 'HAS_TOKEN': 'true', 'HAS_ACCOUNT': 'true',
           'HAS_R2': 'true', 'STAGE_URL': ORIGIN, **change}
    result = subprocess.run(['bash', '-e', '-o', 'pipefail'], input=script, env=env, capture_output=True, text=True)
    if held is None:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode == 1 and held in result.stdout


# --- scope ----------------------------------------------------------------------------------------

def test_scope_admits_a_data_only_candidate(repo, base):
    published = {f'dist/regions/morro-bay/{name}': '{"type":"FeatureCollection","features":[]}\n'
                 for name in ('depth-contours.geojson', 'depth-contours-overview.geojson')}
    sha = commit(repo, {preview.POINTER: pointer_bytes(), preview.CONTOURS: '{"type":"FeatureCollection","features":[]}\n',
                        **published}, 'morro data')
    assert controller.scope(repo, base, sha) == sorted([preview.POINTER, preview.CONTOURS, *published])
    assert controller.main(['scope', '--tree', str(repo), '--base', base, '--sha', sha]) == 0


@pytest.mark.parametrize('other', ['dist/regions/morro-bay/region.json', 'dist/regions/big-sur-coast/depth-contours.geojson',
                                   'catalog/relief/big-sur-coast.json', 'catalog/sources.json'])
def test_scope_holds_any_other_data_file(repo, base, other):
    sha = commit(repo, {preview.POINTER: pointer_bytes(), other: '{}\n'}, 'other data')
    with pytest.raises(controller.HoldError, match='outside the Morro data'):
        controller.scope(repo, base, sha)


def test_scope_holds_a_candidate_that_also_changes_code(repo, base, capsys):
    # Bug caught: the stage build would run candidate code nobody reviewed under a data-only label.
    sha = commit(repo, {preview.POINTER: pointer_bytes(), 'server/index.ts': 'export const x = 1\n'}, 'data + code')
    with pytest.raises(controller.HoldError, match='outside the Morro data: server/index.ts'):
        controller.scope(repo, base, sha)
    assert controller.main(['scope', '--tree', str(repo), '--base', base, '--sha', sha]) == 2
    assert 'Morro stage preview held' in capsys.readouterr().err


def test_scope_holds_a_symlinked_pointer_and_bad_shas(repo, base):
    (repo / preview.POINTER).unlink()
    os.symlink('../../server/index.ts', repo / preview.POINTER)
    sha = commit(repo, {}, 'symlink pointer')
    with pytest.raises(controller.HoldError, match='not a regular file'):
        controller.scope(repo, base, sha)
    with pytest.raises(controller.HoldError, match='full lowercase'):
        controller.scope(repo, base, sha[:12])


# --- origin, plan and config ----------------------------------------------------------------------

@pytest.mark.parametrize('origin', [
    'https://skippercast.fixture-account.workers.dev',           # the production Worker
    'https://skippercast.com', 'https://www.skippercast.com',     # production custom domains
    'http://skippercast-morro-stage.fixture-account.workers.dev',
    ORIGIN + '/', ORIGIN + '.evil.example', '',
    'https://other-stage.fixture-account.workers.dev',
])
def test_preview_origin_must_be_the_stage_workers_dev_address(origin):
    assert controller.check_origin(ORIGIN, 'skippercast-morro-stage') == ORIGIN
    with pytest.raises(controller.HoldError):
        controller.check_origin(origin, 'skippercast-morro-stage')


def planned(repo, base, tmp_path):
    sha = commit(repo, {preview.POINTER: pointer_bytes()}, 'morro data')
    out = tmp_path / 'plan'
    assert preview.main(['plan', '--tree', str(repo), '--sha', sha, '--pointer-sha256',
                         hashlib.sha256(pointer_bytes()).hexdigest(), '--wrangler', str(ROOT / 'wrangler.jsonc'),
                         '--out', str(out)]) == 0
    return sha, out


def test_place_config_writes_the_planned_config_once(repo, base, tmp_path):
    sha, out = planned(repo, base, tmp_path)
    dest = controller.place_config(out, repo, ORIGIN)
    assert dest.read_bytes() == (out / 'wrangler.stage.json').read_bytes()
    with pytest.raises(controller.HoldError, match='already exists'):
        controller.place_config(out, repo, ORIGIN)


def _retarget(out, mutate, *, rehash):
    config = json.loads((out / 'wrangler.stage.json').read_text())
    mutate(config)
    data = (json.dumps(config, indent=2, sort_keys=True) + '\n').encode()
    (out / 'wrangler.stage.json').write_bytes(data)
    if rehash:
        receipt = json.loads((out / 'plan.json').read_text())
        receipt['config_sha256'] = hashlib.sha256(data).hexdigest()
        (out / 'plan.json').write_text(json.dumps(receipt))


@pytest.mark.parametrize(('mutate', 'rehash', 'held'), [
    (lambda c: c.update(name='skippercast'), False, 'differs from the plan'),
    (lambda c: c.update(name='skippercast'), True, 'not isolated'),
    (lambda c: c['r2_buckets'][0].update(bucket_name='skippercast-feeds'), True, 'not isolated'),
    (lambda c: c.update(routes=[{'pattern': 'skippercast.com', 'custom_domain': True}]), True, 'not isolated'),
    (lambda c: c['r2_buckets'][0].update(bucket_name='other-feeds-stage'), True, 'planned Worker and bucket'),
])
def test_place_config_holds_a_tampered_or_production_config(repo, base, tmp_path, mutate, rehash, held):
    _, out = planned(repo, base, tmp_path)
    _retarget(out, mutate, rehash=rehash)
    with pytest.raises(controller.HoldError, match=held):
        controller.place_config(out, repo, ORIGIN)
    assert not (repo / 'wrangler.stage.json').exists()


def test_place_config_holds_another_checkout_or_a_damaged_plan(repo, base, tmp_path):
    _, out = planned(repo, base, tmp_path)
    commit(repo, {'notes.txt': 'later\n'}, 'later commit')
    with pytest.raises(controller.HoldError, match='not the planned commit'):
        controller.place_config(out, repo, ORIGIN)
    (out / 'plan.json').write_text('{"schema": ')
    assert controller.main(['place-config', '--plan-dir', str(out), '--tree', str(repo), '--origin', ORIGIN]) == 2


# --- stage bucket copy ----------------------------------------------------------------------------

class FakeClient:
    def __init__(self):
        self.calls, self.objects = [], {}

    def get_object(self, Bucket, Key):
        self.calls.append(('get', Bucket, Key))
        if Key not in self.objects:
            raise ClientError({'Error': {'Code': 'NoSuchKey'}, 'ResponseMetadata': {'HTTPStatusCode': 404}}, 'GetObject')

        return {'Body': io.BytesIO(self.objects[Key]), 'ResponseMetadata': {'HTTPStatusCode': 200}}

    def put_object(self, Bucket, Key, Body, **kwargs):
        self.calls.append(('put', Bucket, Key))
        if kwargs.get('IfNoneMatch') != '*':
            raise AssertionError('stage copy must be create-only')
        self.objects[Key] = Body.read()


@pytest.mark.parametrize('bucket', ['skippercast-feeds', 'skippercast-backups', 'skippercast-advisor-media',
                                    'skippercast-feeds-staging', 'Skippercast-feeds-stage'])
def test_stage_r2_refuses_any_bucket_but_a_stage_bucket(bucket):
    with pytest.raises(controller.HoldError, match='-stage bucket'):
        controller.StageR2(FakeClient(), bucket)


def test_stage_r2_reads_and_writes_only_its_stage_bucket():
    client = FakeClient()
    r2 = controller.StageR2(client, 'skippercast-feeds-stage')
    with r2.get('tiles/relief/morro-bay/x.pmtiles') as stream:
        assert stream is None

    r2.create('tiles/relief/morro-bay/x.pmtiles', io.BytesIO(b'tile'), 4)
    with r2.get('tiles/relief/morro-bay/x.pmtiles') as stream:
        assert stream.read() == b'tile'
    assert {bucket for _, bucket, _ in client.calls} == {'skippercast-feeds-stage'}


def test_copy_binds_the_planned_stage_bucket_and_never_rechecks_production(repo, base, tmp_path, monkeypatch):
    from skippercast.relief import stage_transport as stage

    _, out = planned(repo, base, tmp_path)
    seen = {}
    monkeypatch.setattr(controller, 'candidate_pointer', lambda tree, receipt: {'region': 'morro-bay'})
    monkeypatch.setattr(stage, 'copy_release', lambda pointer, github, r2, **kw: seen.update(r2=r2, **kw) or 7)
    r2 = controller.StageR2(FakeClient(), 'skippercast-feeds-stage')
    assert controller.copy(out, repo, {}, github=object(), r2=r2) == 7
    assert seen == {'r2': r2, 'allow_create': True, 'recheck': None}
    other = controller.StageR2(FakeClient(), 'other-feeds-stage')
    with pytest.raises(controller.HoldError, match='planned bucket'):
        controller.copy(out, repo, {}, github=object(), r2=other)
    with pytest.raises(controller.HoldError, match='planned bucket'):
        controller.copy(out, repo, {}, github=object(), r2=stage.R2(FakeClient()))


def test_copy_holds_when_the_candidate_pointer_is_not_the_planned_bytes(repo, base, tmp_path):
    sha, out = planned(repo, base, tmp_path)
    receipt = json.loads((out / 'plan.json').read_text())
    receipt['pointer_sha256'] = '0' * 64
    with pytest.raises(controller.HoldError, match='differs from the planned pointer'):
        controller.candidate_pointer(repo, receipt)
