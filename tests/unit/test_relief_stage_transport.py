"""Offline STAGE contract. No release, Cloudflare credentials, or remote calls."""
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from types import ModuleType, SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from botocore.exceptions import ClientError
import pytest
import yaml

from scripts.relief import stage_release as cli
from skippercast.relief import envelope, package, stage_transport as stage
from tests._support import ROOT
from tests.unit.test_relief_package import CHUNK, LAYERS, REGION, approved, assembly  # noqa: F401


def digest(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(autouse=True)
def network_off(monkeypatch):
    def no_network(*_, **__):
        pytest.fail('fixture attempted a remote call')

    monkeypatch.setattr(stage, '_open', no_network)
    monkeypatch.setattr('botocore.httpsession.URLLib3Session.send', no_network)


@pytest.fixture
def reviewed(tmp_path, assembly, monkeypatch):
    chunk = json.dumps([[128, 64, '1' * 64]]).encode()
    root = json.dumps({'chunks': {'8/2_1.json': digest(chunk)}}).encode()
    monkeypatch.setitem(LAYERS, CHUNK, chunk)
    monkeypatch.setitem(LAYERS, package.DIGEST_ROOT, root)
    region, release, _, review, approval = approved(tmp_path / 'out')
    scope = tmp_path / 'RELIEF-PUBLISH-SCOPE'
    scope.write_text('ALL\n')
    pointer = envelope.build_pointer(approval, review)
    archive = LAYERS[package.ARCHIVE]
    stem = f'tiles/relief/{REGION}/{digest(archive)}'
    dirstem = f'{stem}.digests/{digest(root)}'
    objects = {f'{dirstem}/8/2_1.json': chunk, f'{dirstem}/root.json': root, f'{stem}.pmtiles': archive}
    return SimpleNamespace(region=region, release=release, review=review, approval=approval,
                           scope=scope, pointer=pointer, objects=objects, config=assembly)


@pytest.fixture
def dl10(reviewed, monkeypatch):
    """Replace only the unmerged planner. The E2E-12a review chain is real."""
    standin = ModuleType('skippercast.relief.publish')

    def plan(release_dir, approval, review, *, scope_path):
        chain = envelope.verify_chain(approval, review)
        assert release_dir == reviewed.release.parent
        if scope_path.read_text().strip() not in ('ALL', chain.release['region']):
            raise package.ReleaseError('fixture scope refuses region')
        keys = dict(zip((CHUNK, package.DIGEST_ROOT, package.ARCHIVE), reviewed.objects))
        objects = tuple(SimpleNamespace(path=row['path'], key=keys[row['path']], sha256=row['sha256'], size=row['bytes'])
                        for row in chain.release['layers'] if row['path'] in keys)
        return SimpleNamespace(region_dir=chain.region_dir, envelope_sha256=chain.envelope_sha256, objects=objects)

    standin.plan = plan
    monkeypatch.setitem(sys.modules, standin.__name__, standin)
    return standin


def prepare(reviewed, output, issuer, **updates):
    return stage.prepare_release(reviewed.release.parent, reviewed.review, scope_path=reviewed.scope,
                                 pointer=reviewed.pointer | updates, approval_from_queue=issuer, output=output)


def asset_name(key, data):
    return digest(data) + Path(key).suffix


def test_stage_emits_only_checked_public_assets_after_queue_lookup(reviewed, dl10, tmp_path):
    # A local inventory-only or basename-driven exporter could leak the extra zone/QA inputs.
    def issuer(region, sha):
        assert (region, sha) == (REGION, digest(reviewed.review.read_bytes()))
        assert not output.exists()
        return reviewed.approval

    output = tmp_path / 'stage'
    tag = prepare(reviewed, output, issuer)
    assert tag == f'relief-{REGION}-{digest(reviewed.review.read_bytes())}'
    assert {p.name: p.read_bytes() for p in output.iterdir()} == {
        asset_name(key, data): data for key, data in reviewed.objects.items()}
    with pytest.raises(stage.StageError, match='new stage directory'):
        prepare(reviewed, output, lambda *_: reviewed.approval)


@pytest.mark.parametrize('case', ['issuer', 'approval', 'scope', 'pointer', 'inventory', 'send-time'])
def test_stage_refuses_before_exposing_assets(reviewed, dl10, tmp_path, monkeypatch, case):
    # A plausible on-disk approval or stale plan cannot substitute for current queue/chain evidence.
    resolve = lambda *_: reviewed.approval
    updates = {}
    match = ''
    if case == 'issuer':
        def resolve(*_):
            raise stage.StageError('designated queue has no positive R8 record')
        match = 'queue'
    elif case == 'approval':
        document = json.loads(reviewed.approval.read_text())
        reviewed.approval.write_text(json.dumps(document | {'verdict': 'RETURN'}))
        match = 'verdict'
    elif case == 'scope':
        reviewed.scope.write_text('elsewhere\n')
        match = 'scope'
    elif case == 'pointer':
        updates['release_sha256'] = 'f' * 64
        match = 'pointer differs'
    else:
        original = dl10.plan

        def changed_plan(*args, **kwargs):
            plan = original(*args, **kwargs)
            if case == 'inventory':
                plan.objects = tuple(obj for obj in plan.objects if obj.path != CHUNK)
            return plan

        monkeypatch.setattr(dl10, 'plan', changed_plan)
        match = 'inventory' if case == 'inventory' else 'local stage'
        if case == 'send-time':
            build_pointer = envelope.build_pointer

            def change_after_review(*args):
                pointer = build_pointer(*args)
                (reviewed.region.dir / package.ARCHIVE).write_bytes(b'corrupted post-check')
                return pointer

            monkeypatch.setattr(envelope, 'build_pointer', change_after_review)
    with pytest.raises((stage.StageError, package.ReleaseError), match=match):
        prepare(reviewed, tmp_path / 'not-staged', resolve, **updates)
    assert not (tmp_path / 'not-staged').exists()


class Body(io.BytesIO):
    status = 200
    headers = {}


class LocalGitHub:
    """Synthetic wire replies for the actual same-repo release resolver."""
    def __init__(self, reviewed, monkeypatch):
        prefix = f'https://api.github.com/repos/{stage.REPOSITORY}/releases'
        tag = f"relief-{REGION}-{reviewed.pointer['envelope_sha256']}"
        self.url = f'{prefix}/tags/{tag}'
        self.data = {}
        self.requests = []
        self.release = dict(id=10, tag_name=tag, url=f'{prefix}/10', assets_url=f'{prefix}/10/assets',
                            draft=False, prerelease=False, assets=[])
        for i, (key, data) in enumerate(reviewed.objects.items(), 42):
            url = f'{prefix}/assets/{i}'
            self.release['assets'].append(dict(id=i, url=url, name=asset_name(key, data), size=len(data), state='uploaded'))
            self.data[url] = data
        monkeypatch.setattr(stage, '_open', self.open)
        self.client = stage.GitHubRelease('offline-read-token')

    def open(self, request):
        url = request.full_url
        self.requests.append(url)
        assert request.get_method() == 'GET' and request.get_header('Range') is None
        if url == self.url:
            if self.release is None:
                raise HTTPError(url, 404, 'offline', {}, None)
            return Body(json.dumps(self.release).encode())
        return Body(self.data[url])


class LocalS3:
    # Strict wire-side checks: a plain PUT, HEAD shortcut, missing body, or range read fails the fixture.
    def __init__(self):
        self.calls = []
        self.objects = {}
        self.corrupt = False
        self.race = False

    def get_object(self, Bucket, Key):
        assert Bucket == 'skippercast-feeds'
        self.calls.append(('get', Key))
        if Key not in self.objects:
            raise ClientError({'Error': {'Code': 'NoSuchKey'}, 'ResponseMetadata': {'HTTPStatusCode': 404}}, 'GetObject')
        return {'Body': Body(self.objects[Key]), 'ResponseMetadata': {'HTTPStatusCode': 200}}

    def put_object(self, *, Bucket, Key, Body, ContentLength, IfNoneMatch, **_):
        assert Bucket == 'skippercast-feeds' and IfNoneMatch == '*' and Key not in self.objects
        assert stat.S_ISREG(os.fstat(Body.fileno()).st_mode)
        payload = Body.read()
        assert len(payload) == ContentLength
        self.calls.append(('put', Key))
        self.objects[Key] = (bytes([payload[0] ^ 1]) + payload[1:]) if self.corrupt else payload
        if self.race:
            raise ClientError({'Error': {'Code': 'PreconditionFailed'}, 'ResponseMetadata': {'HTTPStatusCode': 412}}, 'PutObject')


def copy(reviewed, github, s3, *, allow_create=True, **updates):
    return stage.copy_release(reviewed.pointer | updates, github.client, stage.R2(s3),
                              allow_create=allow_create, recheck=lambda: s3.calls.append(('recheck', None)))


@pytest.mark.parametrize('racing_create', [False, True])
def test_normal_copy_and_idempotent_repeat(reviewed, monkeypatch, racing_create):
    # A 412 is not success on its own; both new and existing keys must get full byte read-back.
    github, s3 = LocalGitHub(reviewed, monkeypatch), LocalS3()
    s3.race = racing_create
    assert copy(reviewed, github, s3) == len(reviewed.objects)
    assert s3.objects == reviewed.objects
    assert [op for op, _ in s3.calls] == ['get', 'recheck', 'put', 'get', 'get', 'put', 'get', 'get', 'put', 'get']
    s3.calls.clear()
    assert copy(reviewed, github, s3) == len(reviewed.objects)
    assert s3.calls == [('get', key) for key in reviewed.objects]


@pytest.mark.parametrize('already_exists', [False, True])
def test_readback_corruption_blocks_without_overwriting(reviewed, monkeypatch, already_exists):
    # Same-size corruption defeats size-only or HEAD/ETag-only proof.
    github, s3 = LocalGitHub(reviewed, monkeypatch), LocalS3()
    first = next(iter(reviewed.objects))
    if already_exists:
        s3.objects[first] = b'x' * len(reviewed.objects[first])
    s3.corrupt = True
    with pytest.raises(stage.StageError, match='R2 read-back: SHA-256'):
        copy(reviewed, github, s3)
    assert s3.calls[-1] == ('get', first)
    assert [key for op, key in s3.calls if op == 'put'] == ([] if already_exists else [first])


def test_manual_deploy_cannot_create_missing_objects(reviewed, monkeypatch):
    github, s3 = LocalGitHub(reviewed, monkeypatch), LocalS3()
    with pytest.raises(stage.StageError, match='manual deploy'):
        copy(reviewed, github, s3, allow_create=False)
    assert not s3.objects


@pytest.mark.parametrize('case, match', [
    ('missing release', '404'), ('foreign release', 'same-repo'), ('swapped tag', 'same-repo'),
    ('missing asset', 'asset list'), ('foreign asset', 'asset identity'), ('truncated asset', 'SHA-256 or size'),
    ('swapped asset', 'SHA-256 or size'), ('oversize asset', 'exceeds expected size'),
    ('unchecked attachment', 'asset identity'), ('bad digest ref', 'digest root reference'),
    ('wrong root from pointer', 'missing GitHub release asset'),
])
def test_invalid_release_or_asset_never_reaches_r2(reviewed, monkeypatch, case, match):
    # The last bad asset must prevent *every* PUT for this release, not merely its own.
    github, s3 = LocalGitHub(reviewed, monkeypatch), LocalS3()
    rows = github.release['assets']
    archive_url = rows[-1]['url']
    updates = {}
    if case == 'missing release':
        github.release = None
    elif case == 'foreign release':
        github.release['assets_url'] = 'https://api.github.com/repos/elsewhere/skippercast/releases/10/assets'
    elif case == 'swapped tag':
        github.release['tag_name'] += '-other'
    elif case == 'missing asset':
        rows.pop()
    elif case == 'foreign asset':
        rows[-1]['url'] = rows[-1]['url'].replace(stage.REPOSITORY, 'elsewhere/skippercast')
    elif case == 'truncated asset':
        github.data[archive_url] = github.data[archive_url][:-1]
    elif case == 'swapped asset':
        github.data[archive_url] = b'x' * rows[-1]['size']
    elif case == 'oversize asset':
        github.data[archive_url] += b'x'
    elif case == 'unchecked attachment':
        rows[-1]['name'] = 'approval.json'
    elif case == 'wrong root from pointer':
        updates['digest_root_sha256'] = 'f' * 64
    else:
        root = json.dumps({'chunks': {'../../approval.json': 'a' * 64}}).encode()
        updates['digest_root_sha256'] = digest(root)
        rows[1].update(name=digest(root) + '.json', size=len(root))
        github.data[rows[1]['url']] = root
    with pytest.raises((stage.StageError, HTTPError), match=match):
        copy(reviewed, github, s3, **updates)
    assert not s3.calls


@pytest.mark.parametrize('host', ['release-assets.githubusercontent.com', 'untrusted.invalid'])
def test_asset_redirect_never_forwards_the_github_token(monkeypatch, host):
    requests = []

    def respond(request):
        requests.append(request)
        if len(requests) == 1:
            raise HTTPError(request.full_url, 302, 'offline', {'Location': f'https://{host}/asset?synthetic=1'}, None)
        return Body(b'asset')

    monkeypatch.setattr(stage, '_open', respond)
    release = stage.GitHubRelease('offline-read-token')
    if host.endswith('.invalid'):
        with pytest.raises(stage.StageError, match='download refused'):
            release.download(stage.Asset(42, 5))
        assert len(requests) == 1
    else:
        with release.download(stage.Asset(42, 5)) as stream:
            assert stream.read() == b'asset'
        assert requests[1].get_header('Authorization') is None
    assert requests[0].get_header('Authorization') == 'Bearer offline-read-token'


MAIN_ENV = dict(GITHUB_REPOSITORY=stage.REPOSITORY, GITHUB_REF='refs/heads/main', GITHUB_REF_PROTECTED='true',
                RUNNER_ENVIRONMENT='github-hosted', GITHUB_EVENT_NAME='workflow_run')
MAIN_EVENT = dict(action='completed', workflow_run=dict(name='Offline checks', path='.github/workflows/ci.yml',
                  event='push', head_branch='main', conclusion='success', status='completed',
                  head_repository={'full_name': stage.REPOSITORY}, head_sha='e' * 40))


@pytest.mark.parametrize('env, event, mode', [
    ({}, MAIN_EVENT, 'copy'),
    ({'GITHUB_EVENT_NAME': 'workflow_dispatch'}, {'inputs': {'action': 'deploy'}}, 'read-back'),
    ({'GITHUB_EVENT_NAME': 'workflow_dispatch'}, {'inputs': {'action': 'rollback'}}, None),
    ({'GITHUB_REF': 'refs/heads/topic'}, MAIN_EVENT, None),
    ({'GITHUB_REF_PROTECTED': 'false'}, MAIN_EVENT, None),
    ({'RUNNER_ENVIRONMENT': 'self-hosted'}, MAIN_EVENT, None),
    ({'GITHUB_REPOSITORY': 'elsewhere/skippercast'}, MAIN_EVENT, None),
    ({'GITHUB_EVENT_NAME': 'pull_request_target'}, MAIN_EVENT, None),
    ({}, MAIN_EVENT | {'workflow_run': MAIN_EVENT['workflow_run'] | {'event': 'pull_request'}}, None),
    ({}, MAIN_EVENT | {'workflow_run': MAIN_EVENT['workflow_run'] | {'head_repository': {'full_name': 'other/skippercast'}}}, None),
])
def test_event_admission(env, event, mode):
    # The same apparent main name must not allow a PR, fork, manual rollback, or non-hosted worker.
    if mode is None:
        with pytest.raises(stage.StageError):
            cli.deploy_mode(MAIN_ENV | env, event)
    else:
        assert cli.deploy_mode(MAIN_ENV | env, event) == mode


def test_exact_git_blobs_and_no_pointer_deploy(reviewed, tmp_path):
    # Exercise the real Git selection. An empty historical commit must not read
    # R2 configuration; a dirty file must not replace the selected pointer.
    tree = tmp_path / 'tree'
    tree.mkdir()

    def git(*args):
        return subprocess.run(['git', '-C', str(tree), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test',
                               *args], capture_output=True, text=True, check=True).stdout.strip()

    git('init', '-q')
    git('commit', '--allow-empty', '-qm', 'empty')
    empty_sha = git('rev-parse', 'HEAD')
    event = tmp_path / 'event.json'
    event.write_text(json.dumps(MAIN_EVENT))
    output = tmp_path / 'github-output'
    env = MAIN_ENV | dict(GITHUB_EVENT_PATH=str(event), GITHUB_OUTPUT=str(output), STAGE_TREE=str(tree), DEPLOY_SHA=empty_sha)
    cli.run(env, probe=True)
    cli.run(env, probe=False)
    assert output.read_text() == 'required=false\n'
    path = tree / 'catalog' / 'relief' / f'{REGION}.json'
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(reviewed.pointer))
    git('add', 'catalog')
    git('commit', '-qm', 'reviewed pointer fixture')
    selected = git('rev-parse', 'HEAD')
    path.write_text('{}')
    assert cli.pointers(tree, selected) == [reviewed.pointer]
    with pytest.raises(cli.source.SourceError, match='candidate checkout'):
        cli.pointers(tree, empty_sha)


def test_controller_with_pointer_holds_when_dl10_is_missing(reviewed, tmp_path, monkeypatch):
    # The offline build-ahead must not silently become production-ready before DL-10 is present.
    event = tmp_path / 'event.json'
    event.write_text(json.dumps(MAIN_EVENT))
    monkeypatch.setattr(cli, 'pointers', lambda *_: [reviewed.pointer])
    monkeypatch.setitem(sys.modules, 'skippercast.relief.publish', None)
    env = MAIN_ENV | dict(GITHUB_EVENT_PATH=str(event), STAGE_TREE='synthetic-unused', DEPLOY_SHA='d' * 40)
    with pytest.raises(stage.StageError, match='DL-10 publish core unavailable'):
        cli.run(env, probe=False)


def test_controller_uses_selected_sha_for_both_ci_rechecks(reviewed, dl10, tmp_path, monkeypatch):
    # The trigger SHA can differ from the older green ancestor selected by source.
    # An intervening failed rerun blocks the first PUT; a staged release is not authority.
    github = LocalGitHub(reviewed, monkeypatch)
    s3 = LocalS3()
    selected = 'd' * 40
    monkeypatch.setattr(cli, 'CONTROLLER', reviewed.config)
    monkeypatch.setattr(cli, 'pointers', lambda tree, sha: [reviewed.pointer] if sha == selected else pytest.fail('wrong SHA'))
    monkeypatch.setattr(stage.R2, 'connect', lambda *_: stage.R2(s3))
    metadata = github.open
    ci_shas = []

    def open_request(request):
        url = urlsplit(request.full_url)
        if url.path.endswith('/git/ref/heads/main'):
            return Body(json.dumps({'ref': 'refs/heads/main', 'object': {'type': 'commit', 'sha': 'e' * 40}}).encode())
        if '/compare/' in url.path:
            assert url.path.endswith('/' + selected + '...' + 'e' * 40)
            return Body(b'{"status":"ahead","behind_by":0}')
        if url.path.endswith('/actions/workflows/ci.yml/runs'):
            sha, = parse_qs(url.query)['head_sha']
            ci_shas.append(sha)
            run = MAIN_EVENT['workflow_run'] | {'head_sha': sha, 'id': 10 + len(ci_shas),
                                                'conclusion': 'success' if len(ci_shas) == 1 else 'failure'}
            return Body(json.dumps({'total_count': 1, 'workflow_runs': [run]}).encode())
        return metadata(request)

    monkeypatch.setattr(stage, '_open', open_request)
    event = tmp_path / 'event.json'
    event.write_text(json.dumps(MAIN_EVENT))
    env = MAIN_ENV | dict(GITHUB_EVENT_PATH=str(event), STAGE_TREE='synthetic-unused', DEPLOY_SHA=selected,
                          STAGE_GITHUB_READ_TOKEN='offline-only')
    with pytest.raises(cli.source.SourceError, match='exact-SHA'):
        cli.run(env, probe=False)
    assert ci_shas == [selected, selected]
    assert not s3.objects and all(op == 'get' for op, _ in s3.calls)


def test_workflow_requires_stage_success_and_isolates_the_secret_step():
    # Deployment scheduling is an independent YAML boundary, not owned by Python's event tests.
    jobs = yaml.safe_load((ROOT / '.github/workflows/deploy-cloudflare.yml').read_text())['jobs']
    assert jobs['deploy']['needs'] == ['source', 'stage_relief']
    assert "needs.stage_relief.result == 'success'" in jobs['deploy']['if']
    assert 'needs' not in jobs['rollback']
    job = jobs['stage_relief']
    assert job['runs-on'] == 'ubuntu-latest' and job['needs'] == 'source'
    candidate, controller, probe, _, _, copy_step = job['steps']
    assert candidate['with']['ref'] == '${{ needs.source.outputs.sha }}'
    assert controller['with']['ref'] == '${{ github.workflow_sha }}'
    assert all(step['with']['persist-credentials'] is False for step in (candidate, controller))
    assert copy_step['if'] == f"steps.{probe['id']}.outputs.required == 'true'"
    assert {k for k, v in copy_step['env'].items() if 'secrets.' in v} == {'R2_PUBLISH_TOKEN', 'CLOUDFLARE_ACCOUNT_ID'}
    assert all('secrets.' not in repr(value) for value in (job['env'], job['steps'][:-1]))
    assert '.stage-controller/scripts/relief/stage_release.py' in copy_step['run']
