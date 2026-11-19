"""Offline STAGE contract. No release, Cloudflare credentials, or remote calls."""
from dataclasses import replace
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import io
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
from threading import Thread
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from botocore.exceptions import ClientError
import pytest
import yaml

from scripts.relief import stage_release as cli
from skippercast.relief import envelope, package, publish, stage_transport as stage
from tests._support import ROOT
from tests.unit.test_relief_package import CHUNK, LAYERS, REGION, approved, assembly  # noqa: F401


def digest(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(autouse=True)
def network_off(monkeypatch):
    def no_network(*_, **__):
        pytest.fail('fixture attempted a remote call')

    connect = socket.create_connection

    def loopback_only(address, *args, **kwargs):
        if address[0] != '127.0.0.1':
            no_network()
        return connect(address, *args, **kwargs)

    monkeypatch.setattr(socket, 'create_connection', loopback_only)
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


def prepare(reviewed, output, issuer, **updates):
    return stage.prepare_release(reviewed.release.parent, reviewed.review, scope_path=reviewed.scope,
                                 pointer=reviewed.pointer | updates, approval_from_queue=issuer, output=output)


def asset_name(key, data):
    return digest(data) + Path(key).suffix


def test_stage_emits_only_checked_public_assets_after_queue_lookup(reviewed, tmp_path):
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


@pytest.mark.parametrize('case', ['issuer', 'approval', 'wrong-region', 'wrong-envelope', 'missing-scope',
                                 'out-of-scope', 'pointer', 'inventory', 'send-time'])
def test_stage_refuses_before_exposing_assets(reviewed, tmp_path, monkeypatch, case):
    # A plausible on-disk approval or stale plan cannot substitute for current queue/chain evidence.
    resolve = lambda *_: reviewed.approval
    updates = {}
    match = ''
    if case == 'issuer':
        def resolve(*_):
            raise stage.StageError('designated queue has no positive R8 record')
        match = 'queue'
    elif case in {'approval', 'wrong-region', 'wrong-envelope'}:
        document = json.loads(reviewed.approval.read_text())
        sha = digest(reviewed.review.read_bytes())
        verdict = {
            'approval': 'RETURN',
            'wrong-region': f'APPROVED release elsewhere envelope={sha}',
            'wrong-envelope': f'APPROVED release {REGION} envelope={"f" * 64}',
        }[case]
        returned = tmp_path / 'returned-record.json'
        returned.write_text(json.dumps(document | {'verdict': verdict}))
        resolve = lambda *_: returned
        match = 'verdict'
    elif case == 'missing-scope':
        reviewed.scope.unlink()
        match = 'cannot read RELIEF-PUBLISH-SCOPE'
    elif case == 'out-of-scope':
        reviewed.scope.write_text('elsewhere\n')
        match = 'not in RELIEF-PUBLISH-SCOPE'
    elif case == 'pointer':
        updates['release_sha256'] = 'f' * 64
        match = 'pointer differs'
    elif case == 'inventory':
        original = publish.plan

        def changed_plan(*args, **kwargs):
            plan = original(*args, **kwargs)
            return replace(plan, objects=tuple(obj for obj in plan.objects if obj.path != CHUNK))

        # Only this branch needs a faulty planner: the real one rejects missing chunks.
        monkeypatch.setattr(publish, 'plan', changed_plan)
        match = 'inventory'
    else:
        match = 'local stage'
        build_pointer = envelope.build_pointer

        def change_after_review(*args):
            pointer = build_pointer(*args)
            (reviewed.region.dir / package.ARCHIVE).write_bytes(b'corrupted post-check')
            return pointer

        monkeypatch.setattr(envelope, 'build_pointer', change_after_review)
    if case in {'issuer', 'approval', 'wrong-region', 'wrong-envelope', 'missing-scope', 'out-of-scope'}:
        monkeypatch.setattr(stage, 'TemporaryDirectory', lambda **_: pytest.fail('created a staging directory before authorization'))
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


def copy(reviewed, github, s3, **updates):
    return stage.copy_release(reviewed.pointer | updates, github.client, stage.R2(s3),
                              allow_create=True, recheck=lambda: s3.calls.append(('recheck', None)))


def test_real_planner_stage_assets_can_be_copied_from_the_reviewed_pointer(reviewed, tmp_path, monkeypatch):
    # Producer/consumer replay: independently fabricated release assets would
    # hide a planner-to-stage naming or digest mismatch at the hosted copy boundary.
    reviewed.scope.write_text(f'{REGION}\n')
    output = tmp_path / 'checked-assets'
    tag = prepare(reviewed, output, lambda *_: reviewed.approval)
    github, s3 = LocalGitHub(reviewed, monkeypatch), LocalS3()
    assert github.release['tag_name'] == tag
    rows = github.release['assets']
    assert isinstance(rows, list)
    for row in rows:
        github.data[row['url']] = (output / row['name']).read_bytes()
    assert copy(reviewed, github, s3) == len(reviewed.objects)
    assert s3.objects == reviewed.objects


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


@pytest.mark.parametrize('case, match', [
    ('missing release', '404'), ('foreign release', 'same-repo'), ('swapped tag', 'same-repo'),
    ('missing asset', 'asset list'), ('foreign asset', 'asset identity'), ('truncated asset', 'SHA-256 or size'),
    ('swapped asset', 'SHA-256 or size'), ('oversize asset', 'exceeds expected size'),
    ('unchecked attachment', 'asset identity'), ('bad digest ref', 'digest root reference'),
    ('wrong root from pointer', 'missing GitHub release asset'),
    ('correct digest short of listed size', 'SHA-256 or size mismatch'),
    ('archive listing conflicts with pointer size', 'GitHub release asset size is outside its expected bound'),
])
def test_invalid_release_or_asset_never_reaches_r2(reviewed, monkeypatch, case, match):
    # The last bad asset must prevent *every* PUT for this release, not merely its own.
    # Even with a matching digest, trusting a lying asset length or dropping the
    # pointer/listing check would miss a size mismatch (or read an unapproved length).
    github, s3 = LocalGitHub(reviewed, monkeypatch), LocalS3()
    rows = github.release['assets']
    assert isinstance(rows, list)
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
    elif case == 'correct digest short of listed size':
        # No pointer length for the chunk; its bytes and digest are unchanged.
        rows[0]['size'] = len(github.data[rows[0]['url']]) + 1
    elif case == 'archive listing conflicts with pointer size':
        updates['bytes'] = len(github.data[archive_url]) + 1
    else:
        root = json.dumps({'chunks': {'../../approval.json': 'a' * 64}}).encode()
        updates['digest_root_sha256'] = digest(root)
        rows[1].update(name=digest(root) + '.json', size=len(root))
        github.data[rows[1]['url']] = root
    with pytest.raises((stage.StageError, HTTPError), match=match):
        copy(reviewed, github, s3, **updates)
    assert not s3.calls
    if case == 'archive listing conflicts with pointer size':
        assert archive_url not in github.requests


@pytest.mark.parametrize('host', ['release-assets.githubusercontent.com', 'untrusted.invalid'])
def test_asset_redirect_never_forwards_the_github_token(monkeypatch, host):
    # The application may follow an approved media hop only with a fresh request;
    # reusing the API request headers would forward Authorization to the CDN.
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


def test_real_opener_refuses_redirect_before_forwarding_authorization(monkeypatch):
    # Application checks need to see the 302; urllib's default redirect handler
    # would follow Location first and forward the API Authorization header.
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.path, self.headers.get('Authorization')))
            if self.path == '/initial':
                self.send_response(302)
                self.send_header('Location', '/destination')
                self.end_headers()
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{}')

    with HTTPServer(('127.0.0.1', 0), Handler) as server:
        monkeypatch.setattr(stage, '_API', f'http://127.0.0.1:{server.server_port}')
        worker = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01})
        worker.start()
        try:
            with pytest.raises(HTTPError) as caught:
                stage.GitHubRelease('offline-read-token').metadata('/initial')
            with caught.value as error:
                assert error.code == 302
            assert requests == [('/initial', 'Bearer offline-read-token')]
        finally:
            server.shutdown()
            worker.join()


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


@pytest.fixture
def git_tree(tmp_path):
    tree = tmp_path / 'tree'
    tree.mkdir()

    def git(*args):
        return subprocess.run(['git', '-C', str(tree), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test',
                               *args], capture_output=True, text=True, check=True).stdout.strip()

    git('init', '-q')
    return tree, git


def test_exact_git_blobs_and_no_pointer_deploy(reviewed, tmp_path, git_tree):
    # Exercise the real Git selection. An empty historical commit must not read
    # R2 configuration; a dirty file must not replace the selected pointer.
    tree, git = git_tree
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


@pytest.mark.parametrize('case, match', [
    ('symlink entry', 'non-regular file'),
    ('catalog symlink', 'catalogue is not a Git tree'),
    ('oversize blob', 'pointer path or size'),
    ('region mismatch', 'region does not match'),
])
def test_selection_rejects_untrusted_git_entries(reviewed, git_tree, case, match):
    # A blob-only mode check can accept symlinks, missing tree validation can
    # treat a catalog symlink as empty, and valid JSON proves neither bounded
    # size nor that the blob belongs to the region named by its path.
    tree, git = git_tree
    catalog = tree / 'catalog'
    relief = catalog / 'relief'
    if case == 'catalog symlink':
        catalog.symlink_to('elsewhere')
    else:
        relief.mkdir(parents=True)
        if case == 'symlink entry':
            # Even ignored filenames must be regular; a symlink is also a Git blob.
            (relief / 'README.md').symlink_to('elsewhere')
        else:
            name = 'different-region' if case == 'region mismatch' else REGION
            padding = ' ' * (1 << 20) if case == 'oversize blob' else ''
            (relief / f'{name}.json').write_text(json.dumps(reviewed.pointer) + padding)
    git('add', 'catalog')
    git('commit', '-qm', 'invalid catalogue fixture')
    with pytest.raises(stage.StageError, match=match):
        cli.pointers(tree, git('rev-parse', 'HEAD'))


def test_controller_with_pointer_holds_when_dl10_is_missing(reviewed, tmp_path, monkeypatch):
    # The offline build-ahead must not silently become production-ready before DL-10 is present.
    event = tmp_path / 'event.json'
    event.write_text(json.dumps(MAIN_EVENT))
    monkeypatch.setattr(cli, 'pointers', lambda *_: [reviewed.pointer])
    monkeypatch.setitem(sys.modules, 'skippercast.relief.publish', None)
    env = MAIN_ENV | dict(GITHUB_EVENT_PATH=str(event), STAGE_TREE='synthetic-unused', DEPLOY_SHA='d' * 40)
    with pytest.raises(stage.StageError, match='DL-10 publish core unavailable'):
        cli.run(env, probe=False)


@pytest.mark.parametrize('case', ['ci rerun failed', 'manual deploy', 'automatic copy'])
def test_controller_pins_selected_sha_and_creation_authority(reviewed, tmp_path, monkeypatch, case):
    # The trigger SHA can differ from the older green ancestor selected by source.
    # An intervening failed rerun blocks the first PUT; a staged release is not authority.
    # Passing allow_create=True unconditionally would let a manual deploy write
    # the missing keys that only automatic copy may create.
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
            failed = case == 'ci rerun failed' and len(ci_shas) == 2
            run = MAIN_EVENT['workflow_run'] | {'head_sha': sha, 'id': 10 + len(ci_shas),
                                                'conclusion': 'failure' if failed else 'success'}
            return Body(json.dumps({'total_count': 1, 'workflow_runs': [run]}).encode())
        return metadata(request)

    monkeypatch.setattr(stage, '_open', open_request)
    event = tmp_path / 'event.json'
    event.write_text(json.dumps(MAIN_EVENT))
    env = MAIN_ENV | dict(GITHUB_EVENT_PATH=str(event), STAGE_TREE='synthetic-unused', DEPLOY_SHA=selected,
                          STAGE_GITHUB_READ_TOKEN='offline-only')
    if case == 'manual deploy':
        event.write_text(json.dumps({'inputs': {'action': 'deploy'}}))
        with pytest.raises(stage.StageError, match='manual deploy'):
            cli.run(env | {'GITHUB_EVENT_NAME': 'workflow_dispatch'}, probe=False)
        assert ci_shas == [selected]
        assert s3.calls == [('get', next(iter(reviewed.objects)))]
        assert not s3.objects
    else:
        if case == 'ci rerun failed':
            with pytest.raises(cli.source.SourceError, match='exact-SHA'):
                cli.run(env, probe=False)
            assert not s3.objects and all(op == 'get' for op, _ in s3.calls)
        else:
            cli.run(env, probe=False)
            assert s3.objects == reviewed.objects
        assert ci_shas == [selected, selected]


@pytest.mark.parametrize('case, match', [
    ('invalid pointer size', 'invalid relief metadata at bytes'),
    ('unapproved source', 'does not have public display rights'),
    ('no public display', 'does not have public display rights'),
])
def test_controller_validates_pointer_and_current_rights_before_io(reviewed, tmp_path, monkeypatch, case, match):
    # Dropping the controller schema check defers malformed pointer fields to
    # after CI I/O; dropping metadata validation trusts stale pointer rights.
    pointer = reviewed.pointer.copy()
    registry = reviewed.config / 'catalog/sources.json'
    rows = json.loads(registry.read_text())
    if case == 'invalid pointer size':
        pointer['bytes'] = 0  # Pointer-only field, not checked by validate_metadata.
    elif case == 'unapproved source':
        rows['sources'][0]['review_status'] = 'pending'
    else:
        rows['sources'][0]['rights']['public_display'] = 'private'
    registry.write_text(json.dumps(rows))
    monkeypatch.setattr(cli, 'CONTROLLER', reviewed.config)
    monkeypatch.setattr(cli, 'pointers', lambda *_: [pointer])

    def unexpected_io(*_):
        pytest.fail('invalid selected pointer reached provider I/O')

    monkeypatch.setattr(stage, '_open', unexpected_io)
    monkeypatch.setattr(stage.R2, 'connect', unexpected_io)
    event = tmp_path / 'event.json'
    event.write_text(json.dumps(MAIN_EVENT))
    env = MAIN_ENV | dict(GITHUB_EVENT_PATH=str(event), STAGE_TREE='synthetic-unused', DEPLOY_SHA='d' * 40,
                          STAGE_GITHUB_READ_TOKEN='offline-only')
    with pytest.raises(package.ReleaseError, match=match):
        cli.run(env, probe=False)


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
