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
PINS = {'DETAIL_SHA256': 'c' * 64, 'OVERVIEW_SHA256': 'd' * 64, 'CATALOGUE_SHA256': 'e' * 64}


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
    assert set(triggers['workflow_dispatch']['inputs']) == {'candidate', 'pointer_sha256', 'detail_sha256',
                                                            'overview_sha256', 'catalogue_sha256', 'origin'}
    assert WORKFLOW['permissions'] == {'contents': 'read'}
    job = WORKFLOW['jobs']['preview']
    assert list(WORKFLOW['jobs']) == ['fetch', 'preview']
    for clause in ("github.event_name == 'workflow_dispatch'", "github.repository == 'Grahammmm/skippercast'",
                   "github.ref == 'refs/heads/main'", 'github.ref_protected'):
        assert clause in job['if']
    assert job['environment'] == 'morro-stage-preview'
    assert WORKFLOW['env']['STAGE_WORKER'].endswith('-stage') and WORKFLOW['env']['STAGE_BUCKET'].endswith('-stage')


def test_workflow_reads_only_the_cloudflare_secrets_and_only_after_every_guard():
    secrets = set(re.findall(r'secrets\.([A-Z0-9_]+)', WORKFLOW_TEXT))
    assert secrets == {'CLOUDFLARE_API_TOKEN', 'CLOUDFLARE_ACCOUNT_ID', 'R2_PUBLISH_TOKEN'}
    body = '\n'.join(line for line in WORKFLOW_TEXT.splitlines() if not line.lstrip().startswith('#'))
    for production in ("'skippercast-feeds'", 'skippercast-feeds ', 'skippercast-backups', 'skippercast-advisor-media',
                       'cloudflare_deploy.sh', 'd1 ', 'CUSTOM_DOMAINS', 'pull_request_target', 'vars.'):
        assert production not in body
    # Credentials reach only the bucket, copy and deploy steps, all after the re-plan (the first step
    # only learns whether each is set).
    holders = [i for i, s in enumerate(STEPS) if 'secrets.' in json.dumps(s.get('env', {}))]
    assert holders == [step('Reject a non-main dispatch'), step('Create the stage bucket'), step('Copy the candidate'),
                       step('Copy the public basemap'), step('Deploy the stage Worker only')]
    assert all(value.endswith("!= '' }}") for value in STEPS[holders[0]]['env'].values())
    assert min(holders[1:]) > step('Re-plan after the build')
    bucket = STEPS[step('Create the stage bucket')]
    assert bucket['working-directory'] == '${{ runner.temp }}' and '*-stage)' in bucket['run']
    deploy = STEPS[step('Deploy the stage Worker only')]
    assert deploy['run'].startswith('$WRANGLER deploy --config wrangler.stage.json ')
    assert set(deploy['env']) == {'CLOUDFLARE_API_TOKEN', 'CLOUDFLARE_ACCOUNT_ID'}


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
             step('Plan the isolated stage config'), step("Render the candidate's /sources credits"),
             step('Feed the /sources overlay into the build input'), step('Install locked web dependencies'),
             step('Build Worker and fingerprinted site'), step('Re-plan after the build'),
             step('Create the stage bucket'), step('Copy the candidate'), step('Copy the public basemap'),
             step('Place the checked stage config'),
             step('Deploy the stage Worker only'), step('Require the preview to serve exactly')]
    assert order == sorted(order)
    # Controller copies, never the candidate's, run every guard.
    for name in ('Require the candidate', 'Plan the isolated', 'Re-plan after', 'Copy the candidate', 'Copy the public basemap',
                 'Place the checked'):
        assert '"$CONTROLLER/scripts/relief/' in STEPS[step(name)]['run']
    assert '--worker "$STAGE_WORKER" --bucket "$STAGE_BUCKET"' in STEPS[step('Plan the isolated')]['run']
    assert 'cmp "$PLAN_DIR/plan.json" "$PLAN_DIR.rebuilt/plan.json"' in STEPS[step('Re-plan after')]['run']
    # No credential reaches the candidate's own dependency install, overlay or build scripts.
    for name in ('Install locked web dependencies', 'Build Worker and fingerprinted site',
                 "Render the candidate's /sources credits", 'Feed the /sources overlay'):
        assert 'env' not in STEPS[step(name)]
    assert 'secrets.' not in json.dumps(WORKFLOW['jobs']['preview']['env'])


def test_previewsite_is_recorded_and_only_the_fetch_job_can_read_drafts():
    # G approved PREVIEWSITE (2026-11-25): the hold step is gone, the header records the approval's limits.
    assert not [s for s in STEPS if 'PREVIEWSITE' in s.get('name', '')]
    assert 'not recorded yet' not in WORKFLOW_TEXT
    for limit in ('PREVIEWSITE', 'does NOT approve go-live', 'no custom domain', 'existing Cloudflare key'):
        assert limit in WORKFLOW_TEXT
    fetch_job, preview_job = WORKFLOW['jobs']['fetch'], WORKFLOW['jobs']['preview']
    assert fetch_job['permissions'] == {'contents': 'write'} and 'permissions' not in preview_job
    assert preview_job['needs'] == 'fetch' and fetch_job['if'] == preview_job['if']
    assert 'environment' not in fetch_job
    steps = fetch_job['steps']
    body = json.dumps(steps)
    # No Cloudflare secret, candidate code, dependency install from the candidate or build in the write job.
    assert 'secrets.' not in body and 'pnpm' not in body and 'npm ' not in body and 'wrangler' not in body.lower()
    checkouts = [s for s in steps if str(s.get('uses', '')).startswith('actions/checkout@')]
    assert [c['with']['ref'] for c in checkouts] == ['${{ github.workflow_sha }}', '${{ inputs.candidate }}']
    assert checkouts[1]['with']['sparse-checkout'].split() == ['catalog/relief/morro-bay.json']
    assert all(c['with']['persist-credentials'] is False for c in checkouts)
    runs = [s.get('run', '') for s in steps]
    assert runs[0].count('exit 1') == 2 and 'refs/heads/main' in runs[0]
    fetch_step = next(s for s in steps if s.get('name', '').startswith('Fetch the candidate pointer'))
    assert fetch_step['env'] == {'PREVIEW_RELEASE_READ_TOKEN': '${{ github.token }}'}
    assert fetch_step['run'].startswith('python3 -I "$CONTROLLER/scripts/relief/morro_stage_controller.py" fetch')
    # The copy reads only the fetched files; no GitHub token reaches the preview job.
    assert 'github.token' not in json.dumps(preview_job)
    download = [i for i, s in enumerate(STEPS) if str(s.get('uses', '')).startswith('actions/download-artifact@')]
    assert len(download) == 1 and step('Create the stage bucket') < download[0] < step('Copy the candidate')
    upload = next(s for s in steps if str(s.get('uses', '')).startswith('actions/upload-artifact@'))
    assert upload['with']['name'] == STEPS[download[0]]['with']['name']
    assert '--assets-dir "$RUNNER_TEMP/preview-assets"' in STEPS[step('Copy the candidate')]['run']
    assert STEPS[download[0]]['with']['path'] == '${{ runner.temp }}/preview-assets'


def test_sources_credits_are_a_build_input_and_the_served_page_is_the_built_one():
    # M9 receipt 230aecce: a plain build serves stale credits and a copy after the build is never served, so the
    # overlay (pinned to all four dispatch digests) feeds dist/sources.html before the build names the page.
    render = STEPS[step("Render the candidate's /sources credits")]['run']
    for flag in ('--pointer-sha256 "$POINTER_SHA256"', '--detail-sha256 "$DETAIL_SHA256"',
                 '--overview-sha256 "$OVERVIEW_SHA256"', '--catalogue-sha256 "$CATALOGUE_SHA256"'):
        assert flag in render
    assert '--out "$RUNNER_TEMP/sources-overlay"' in render
    assert step('Feed the /sources overlay') < step('Build Worker and fingerprinted site')
    build = STEPS[step('Build Worker and fingerprinted site')]['run']
    assert build.index('pnpm build') < build.index('sources-shell.html') < build.index('git checkout -- dist/sources.html')
    served = STEPS[step('Require the preview to serve exactly')]['run']
    for check in ('"$STAGE_URL/sources"', 'cmp -s "$served/sources.html" "$PLAN_DIR/sources-shell.html"',
                  '= "$DETAIL_SHA256"', '= "$OVERVIEW_SHA256"'):
        assert check in served


def feed(tmp_path, receipt, page=b'<html>credits</html>\n'):
    (tmp_path / 'sources-overlay').mkdir()
    (tmp_path / 'sources-overlay/sources.html').write_bytes(page)
    plan = tmp_path / 'plan'
    plan.mkdir()
    (plan / 'sources-overlay.json').write_text(json.dumps(receipt))
    tree = tmp_path / 'tree'
    (tree / 'dist').mkdir(parents=True)
    (tree / 'dist/sources.html').write_bytes(b'stale\n')
    env = {'PATH': os.environ['PATH'], 'RUNNER_TEMP': str(tmp_path), 'PLAN_DIR': str(plan)}
    result = subprocess.run(['bash', '-e', '-o', 'pipefail'], input=STEPS[step('Feed the /sources overlay')]['run'],
                            env=env, cwd=tree, capture_output=True, text=True)
    return result, (tree / 'dist/sources.html').read_bytes()


def test_feed_places_only_the_page_its_receipt_names(tmp_path):
    page = b'<html>credits</html>\n'
    result, placed = feed(tmp_path, {'html_sha256': hashlib.sha256(page).hexdigest()}, page)
    assert result.returncode == 0, result.stdout + result.stderr
    assert placed == page


@pytest.mark.parametrize('receipt', [{'html_sha256': 'f' * 64}, {'html_sha256': 'F' * 64}, {}, {'html_sha256': None}])
def test_feed_holds_a_page_that_differs_from_its_receipt(tmp_path, receipt):
    result, placed = feed(tmp_path, receipt)
    assert result.returncode == 1 and 'held' in result.stdout
    assert placed == b'stale\n'


def test_every_action_is_pinned_to_a_full_commit():
    for job in WORKFLOW['jobs'].values():
        for s in job['steps']:
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
    # The same whole-value rule for the other two inputs: one valid line must not carry extra lines.
    ({'CANDIDATE': 'a' * 40 + '\nnot-a-sha'}, 'full lowercase commit'),
    ({'CANDIDATE': 'not-a-sha\n' + 'a' * 40}, 'full lowercase commit'),
    ({'POINTER_SHA256': 'b' * 64 + '\nx'}, '64 lowercase hex'),
    ({'POINTER_SHA256': 'x\n' + 'b' * 64}, '64 lowercase hex'),
    # The overlay pins get the same whole-value rule (missing, short, uppercase or multi-line all hold).
    ({'DETAIL_SHA256': ''}, '64 lowercase hex'),
    ({'OVERVIEW_SHA256': 'c' * 63}, '64 lowercase hex'),
    ({'CATALOGUE_SHA256': 'D' * 64}, '64 lowercase hex'),
    ({'DETAIL_SHA256': 'c' * 64 + '\nx'}, '64 lowercase hex'),
    ({'STAGE_URL': ''}, 'origin must be'),
    ({'STAGE_URL': 'https://skippercast.fixture-account.workers.dev'}, 'origin must be'),
    ({'STAGE_URL': 'https://skippercast.com'}, 'origin must be'),
    ({'STAGE_URL': ORIGIN + '/x'}, 'origin must be'),
    # Review t_47dd1c14: the whole value is checked, and with the controller's DNS-label rule.
    ({'STAGE_URL': ORIGIN + '\nhttps://skippercast.com'}, 'origin must be'),
    ({'STAGE_URL': 'https://skippercast.com\n' + ORIGIN}, 'origin must be'),
    ({'STAGE_URL': 'https://skippercast-morro-stage.-account.workers.dev'}, 'origin must be'),
    ({'STAGE_URL': 'https://skippercast-morro-stage.account-.workers.dev'}, 'origin must be'),
    ({'STAGE_URL': 'https://skippercast-morro-stage.' + 'a' * 64 + '.workers.dev'}, 'origin must be'),
    ({'STAGE_URL': 'https://skippercast-morro-stage.Fixture.workers.dev'}, 'origin must be'),
    ({'STAGE_URL': 'https://skippercast-morro-stage.' + 'a' * 63 + '.workers.dev'}, None),
    ({'HAS_R2': 'false'}, 'not configured'),
    ({'HAS_TOKEN': 'false'}, 'not configured'),
])
def test_the_first_step_holds_bad_dispatches_before_checkout(change, held):
    script = STEPS[step('Reject a non-main dispatch')]['run']
    env = {'PATH': os.environ['PATH'], 'GITHUB_REF': 'refs/heads/main', 'GITHUB_REF_PROTECTED': 'true',
           'STAGE_WORKER': WORKFLOW['env']['STAGE_WORKER'],
           'CANDIDATE': 'a' * 40, 'POINTER_SHA256': 'b' * 64, 'HAS_TOKEN': 'true', 'HAS_ACCOUNT': 'true',
           'HAS_R2': 'true', 'STAGE_URL': ORIGIN, **PINS, **change}
    result = subprocess.run(['bash', '-e', '-o', 'pipefail'], input=script, env=env, capture_output=True, text=True)
    if held is None:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode == 1 and held in result.stdout


def test_the_first_step_and_place_config_agree_on_every_origin():
    # The pre-checkout hold must refuse everything check_origin (run later, after credentials) refuses.
    script = STEPS[step('Reject a non-main dispatch')]['run']
    worker = WORKFLOW['env']['STAGE_WORKER']
    origins = [ORIGIN, ORIGIN + '\n', '\n' + ORIGIN, ORIGIN + '\nhttps://skippercast.com', f'https://{worker}.a.workers.dev',
               f'https://{worker}.-a.workers.dev', f'https://{worker}.a-.workers.dev', f'https://{worker}.a--b.workers.dev',
               f'https://{worker}.{"b" * 63}.workers.dev', f'https://{worker}.{"b" * 64}.workers.dev',
               f'https://{worker}.a.b.workers.dev', f'https://{worker}..workers.dev', f'https://{worker}.a.workers.dev.',
               f'https://{worker}.a.workers.dev:443', f'HTTPS://{worker}.a.workers.dev', f'https://{worker}.a_b.workers.dev']
    for origin in origins:
        env = {'PATH': os.environ['PATH'], 'GITHUB_REF': 'refs/heads/main', 'GITHUB_REF_PROTECTED': 'true',
               'STAGE_WORKER': worker, 'CANDIDATE': 'a' * 40, 'POINTER_SHA256': 'b' * 64, 'HAS_TOKEN': 'true',
               'HAS_ACCOUNT': 'true', 'HAS_R2': 'true', 'STAGE_URL': origin, **PINS}
        step_ok = subprocess.run(['bash', '-e', '-o', 'pipefail'], input=script, env=env, capture_output=True,
                                 text=True).returncode == 0
        try:
            controller_ok = controller.check_origin(origin, worker) == origin
        except controller.HoldError:
            controller_ok = False
        assert step_ok == controller_ok, repr(origin)


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


def test_copy_holds_without_the_fetched_preview_assets(repo, base, tmp_path, monkeypatch):
    _, out = planned(repo, base, tmp_path)
    monkeypatch.setattr(controller, 'candidate_pointer', lambda tree, receipt: {'region': 'morro-bay'})
    with pytest.raises(controller.HoldError, match='fetched preview assets'):
        controller.copy(out, repo, {}, r2=controller.StageR2(FakeClient(), 'skippercast-feeds-stage'))


# --- draft preview release objects -----------------------------------------------------------------
# Producer/consumer replay on the reviewed relief fixture: the box writes the assets, the fetch job
# hands over files, and the unchanged stage_transport.copy_release accepts exactly those bytes.

from tests.unit.test_relief_package import assembly  # noqa: E402,F401
from tests.unit.test_relief_stage_transport import reviewed  # noqa: E402,F401


@pytest.fixture
def released(reviewed, tmp_path):
    pointer = tmp_path / 'pointer.json'
    pointer.write_bytes(pointer_bytes(reviewed.pointer))
    return reviewed, pointer, hashlib.sha256(pointer.read_bytes()).hexdigest()


def stage_client():
    return FakeClient(), 'skippercast-feeds-stage'


def copy_from(directory, pointer):
    from skippercast.relief import stage_transport as stage

    client, bucket = stage_client()
    count = stage.copy_release(pointer, controller.LocalRelease(directory), controller.StageR2(client, bucket),
                               allow_create=True, recheck=None)
    return count, client.objects


def test_preview_assets_round_trip_through_the_unchanged_stage_copy(released, tmp_path):
    reviewed, pointer, sha = released
    out = tmp_path / 'assets'
    result = controller.prepare_assets(pointer, sha, tmp_path / 'out', out)
    tag = f"relief-preview-morro-bay-{reviewed.pointer['envelope_sha256']}"
    assert result == {'tag': tag, 'assets': len(reviewed.objects), 'bytes': sum(map(len, reviewed.objects.values()))}
    manifest = json.loads((out / controller.ASSET_MANIFEST).read_text())
    assert manifest['schema'] == controller.ASSET_SCHEMA and manifest['tag'] == tag
    count, objects = copy_from(out, reviewed.pointer)
    assert count == len(reviewed.objects) and objects == reviewed.objects
    # The production reader never sees this: a different tag name, and the CLI writes a new directory only.
    assert not tag.startswith(f"relief-morro-bay-")
    with pytest.raises(controller.HoldError, match='new assets directory'):
        controller.prepare_assets(pointer, sha, tmp_path / 'out', out)


def test_preview_assets_hold_a_wrong_pointer_digest_or_a_missing_object(released, tmp_path):
    reviewed, pointer, sha = released
    with pytest.raises(controller.HoldError, match='pinned pointer digest'):
        controller.prepare_assets(pointer, '0' * 64, tmp_path / 'out', tmp_path / 'a')
    archive = next(p for p in (tmp_path / 'out').rglob('*') if p.is_file() and p.read_bytes() ==
                   reviewed.objects[next(k for k in reviewed.objects if k.endswith('.pmtiles'))])
    archive.write_bytes(archive.read_bytes() + b'x')
    with pytest.raises(controller.HoldError, match='lacks object'):
        controller.prepare_assets(pointer, sha, tmp_path / 'out', tmp_path / 'b')
    other = dict(reviewed.pointer, region='cambria-san-simeon')
    pointer.write_bytes(pointer_bytes(other))
    with pytest.raises(Exception):
        controller.prepare_assets(pointer, hashlib.sha256(pointer.read_bytes()).hexdigest(), tmp_path / 'out',
                                  tmp_path / 'c')
    assert not (tmp_path / 'b').exists() or not any(p.suffix == '.pmtiles' for p in (tmp_path / 'b').iterdir())


@pytest.mark.parametrize(('mutate', 'match'), [
    (lambda d, m: m.update(tag='relief-preview-morro-bay-' + 'f' * 64), 'not fetched for this pointer'),
    (lambda d, m: m.update(schema='other'), 'not fetched for this pointer'),
    (lambda d, m: (d / ('1' * 64 + '.json')).write_text('{}'), 'differ from their manifest'),
    (lambda d, m: (d / 'notes.txt').write_text('x'), 'unexpected entry'),
    (lambda d, m: (d / ('2' * 64 + '.json')).symlink_to(d / controller.ASSET_MANIFEST), 'unexpected entry'),
])
def test_local_release_answers_only_for_its_own_pointer_and_files(released, tmp_path, mutate, match):
    reviewed, pointer, sha = released
    out = tmp_path / 'assets'
    controller.prepare_assets(pointer, sha, tmp_path / 'out', out)
    manifest = json.loads((out / controller.ASSET_MANIFEST).read_text())
    mutate(out, manifest)
    (out / controller.ASSET_MANIFEST).write_text(json.dumps(manifest))
    with pytest.raises(controller.HoldError, match=match):
        copy_from(out, reviewed.pointer)


def test_local_release_bytes_are_still_checked_by_the_stage_copy(released, tmp_path):
    from skippercast.relief import stage_transport as stage

    reviewed, pointer, sha = released
    out = tmp_path / 'assets'
    controller.prepare_assets(pointer, sha, tmp_path / 'out', out)
    archive = out / f"{reviewed.pointer['sha256']}.pmtiles"
    data = bytearray(archive.read_bytes())
    data[0] ^= 1
    archive.write_bytes(bytes(data))
    client, bucket = stage_client()
    with pytest.raises(stage.StageError, match='SHA-256 or size mismatch'):
        stage.copy_release(reviewed.pointer, controller.LocalRelease(out), controller.StageR2(client, bucket),
                           allow_create=True, recheck=None)
    assert not [c for c in client.calls if c[0] == 'put']
    with pytest.raises(controller.HoldError, match='unexpected release tag'):
        controller.LocalRelease(out).assets(f"relief-preview-morro-bay-{reviewed.pointer['envelope_sha256']}")


API = 'https://api.github.com/repos/Grahammmm/skippercast'
TAG = 'relief-preview-morro-bay-' + 'e' * 64


def draft(**changes):
    row = {'id': 7, 'tag_name': TAG, 'draft': True, 'prerelease': False, 'url': f'{API}/releases/7',
           'assets_url': f'{API}/releases/7/assets',
           'assets': [{'id': 9, 'name': 'a' * 64 + '.pmtiles', 'size': 4, 'state': 'uploaded',
                       'url': f'{API}/releases/assets/9'}]}
    row.update(changes)
    return row


@pytest.mark.parametrize(('pages', 'match'), [
    ([[draft(draft=False)]], 'same-repo draft'),
    ([[draft(prerelease=True)]], 'same-repo draft'),
    ([[draft(url=f'{API}/releases/8')]], 'same-repo draft'),
    ([[draft(), draft(id=8)]], 'exactly one'),
    ([[draft(tag_name='relief-morro-bay-' + 'e' * 64)]], 'exactly one'),
    ([[]], 'exactly one'),
    ([{'message': 'Not Found'}], 'invalid GitHub release listing'),
    ([[draft(assets=[])]], 'asset inventory'),
    ([[draft(assets=[dict(draft()['assets'][0], name='../x.pmtiles')])]], 'invalid preview release asset'),
    ([[draft(assets=[dict(draft()['assets'][0], state='new')])]], 'invalid preview release asset'),
    ([[draft(assets=[dict(draft()['assets'][0], url='https://example.invalid/9')])]], 'invalid preview release asset'),
])
def test_draft_release_reader_accepts_only_one_same_repo_draft(pages, match):
    reader = controller.DraftRelease('offline', opener=lambda page: pages[page - 1])
    with pytest.raises(controller.HoldError, match=match):
        reader.assets(TAG)


def test_draft_release_reader_pages_and_refuses_the_production_tag():
    filler = [{'id': i, 'tag_name': f'v{i}'} for i in range(100)]
    reader = controller.DraftRelease('offline', opener=lambda page: [filler, [draft()]][page - 1])
    assert reader.assets(TAG) == {'a' * 64 + '.pmtiles': controller_stage().Asset(9, 4)}
    with pytest.raises(controller.HoldError, match='only a preview release'):
        reader.assets('relief-morro-bay-' + 'e' * 64)


def controller_stage():
    from skippercast.relief import stage_transport as stage
    return stage


class FakeDraft:
    def __init__(self, files):
        self.files = files

    def assets(self, tag):
        self.tag = tag
        return {name: controller_stage().Asset(i, size) for i, (name, (size, _)) in enumerate(sorted(self.files.items()), 1)}

    def download(self, asset):
        name = sorted(self.files)[asset.id - 1]
        return io.BytesIO(self.files[name][1])


def test_fetch_writes_the_draft_assets_and_a_manifest_the_copy_accepts(released, tmp_path):
    reviewed, pointer, sha = released
    files = {controller_stage().Object(k, hashlib.sha256(v).hexdigest(), 1 << 30).name: (len(v), v)
             for k, v in reviewed.objects.items()}
    fake = FakeDraft(files)
    result = controller.fetch(pointer, sha, tmp_path / 'fetched', release=fake)
    assert fake.tag == f"relief-preview-morro-bay-{reviewed.pointer['envelope_sha256']}" == result['tag']
    count, objects = copy_from(tmp_path / 'fetched', reviewed.pointer)
    assert count == len(reviewed.objects) and objects == reviewed.objects


@pytest.mark.parametrize(('delta', 'match'), [(b'x', 'exceeds its listed size'), (None, 'shorter than')])
def test_fetch_holds_an_asset_whose_bytes_disagree_with_its_listed_size(released, tmp_path, delta, match):
    reviewed, pointer, sha = released
    key, data = next(iter(reviewed.objects.items()))
    name = controller_stage().Object(key, hashlib.sha256(data).hexdigest(), 1 << 30).name
    body = data + delta if delta else data[:-1]
    with pytest.raises(controller.HoldError, match=match):
        controller.fetch(pointer, sha, tmp_path / 'fetched', release=FakeDraft({name: (len(data), body)}))
    with pytest.raises(controller.HoldError, match='pinned pointer digest'):
        controller.fetch(pointer, '0' * 64, tmp_path / 'other', release=FakeDraft({}))


# --- public basemap into the stage bucket -----------------------------------------------------------

BASEMAP = b'synthetic basemap archive bytes'


def basemap_doc(**changes):
    doc = {'schema_version': 1, 'key': 'tiles/basemap/ca-coast-20261011.pmtiles', 'bytes': len(BASEMAP),
           'sha256': hashlib.sha256(BASEMAP).hexdigest(), 'license': 'ODbL-1.0'}
    doc.update(changes)
    return json.dumps(doc).encode()


def public(manifest=None, archive=BASEMAP):
    seen = []

    def get(url):
        seen.append(url)
        if url == f'{controller.PUBLIC_SITE}/feeds/tiles/basemap/manifest.json':
            return io.BytesIO(basemap_doc() if manifest is None else manifest)
        if url == f'{controller.PUBLIC_SITE}/feeds/tiles/basemap/ca-coast-20261011.pmtiles':
            return io.BytesIO(archive)
        raise AssertionError(url)
    get.seen = seen
    return get


def test_basemap_copies_the_public_archive_then_its_manifest_into_the_stage_bucket():
    client = FakeClient()
    get = public()
    result = controller.copy_basemap(controller.StageR2(client, 'skippercast-feeds-stage'), get=get)
    assert result == {'archive': 'tiles/basemap/ca-coast-20261011.pmtiles', 'sha256': hashlib.sha256(BASEMAP).hexdigest(),
                      'created': True}
    puts = [key for op, _, key in client.calls if op == 'put']
    assert puts == ['tiles/basemap/ca-coast-20261011.pmtiles', 'tiles/basemap/manifest.json']
    assert client.objects['tiles/basemap/manifest.json'] == basemap_doc()
    assert {bucket for _, bucket, _ in client.calls} == {'skippercast-feeds-stage'}
    assert all(url.startswith('https://skippercast.g4651.workers.dev/feeds/') for url in get.seen)
    # A repeat reads back both and writes nothing.
    again = controller.copy_basemap(controller.StageR2(client, 'skippercast-feeds-stage'), get=public())
    assert again['created'] is False and [k for op, _, k in client.calls if op == 'put'] == puts


@pytest.mark.parametrize('manifest', [
    b'not json', basemap_doc(key='tiles/basemap/../x.pmtiles'), basemap_doc(key='tiles/relief/morro-bay/x.pmtiles'),
    basemap_doc(schema_version=2), basemap_doc(bytes=0), basemap_doc(bytes=2 << 30), basemap_doc(sha256='A' * 64),
    b' ' * (1 << 17),
])
def test_basemap_holds_a_manifest_that_does_not_name_one_pinned_archive(manifest):
    client = FakeClient()
    with pytest.raises(controller.HoldError, match='basemap manifest'):
        controller.copy_basemap(controller.StageR2(client, 'skippercast-feeds-stage'), get=public(manifest))
    assert not client.objects


def test_basemap_holds_wrong_bytes_and_a_different_existing_stage_copy():
    from skippercast.relief import stage_transport as stage

    client = FakeClient()
    with pytest.raises(stage.StageError, match='SHA-256 or size mismatch'):
        controller.copy_basemap(controller.StageR2(client, 'skippercast-feeds-stage'), get=public(archive=b'x' * len(BASEMAP)))
    assert not client.objects
    client.objects['tiles/basemap/ca-coast-20261011.pmtiles'] = BASEMAP
    client.objects['tiles/basemap/manifest.json'] = basemap_doc(license='other')
    with pytest.raises(stage.StageError, match='SHA-256 or size mismatch'):
        controller.copy_basemap(controller.StageR2(client, 'skippercast-feeds-stage'), get=public())


def test_basemap_binds_the_planned_stage_bucket(repo, base, tmp_path):
    _, out = planned(repo, base, tmp_path)
    assert controller.basemap(out, {}, r2=controller.StageR2(FakeClient(), 'skippercast-feeds-stage'), get=public())['created']
    with pytest.raises(controller.HoldError, match='planned bucket'):
        controller.basemap(out, {}, r2=controller.StageR2(FakeClient(), 'other-feeds-stage'), get=public())
    step_ = STEPS[step('Copy the public basemap')]
    assert set(step_['env']) == {'STAGE_R2_PUBLISH_TOKEN', 'STAGE_CLOUDFLARE_ACCOUNT_ID'}
    assert step_['run'] == 'python3 -I "$CONTROLLER/scripts/relief/morro_stage_controller.py" basemap --plan-dir "$PLAN_DIR"'
