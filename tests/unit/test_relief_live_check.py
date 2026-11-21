"""C1–C3: exercise the live command with a tiny real Git history and loopback site."""
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
import json
from pathlib import Path
import subprocess
import sys
from threading import Thread
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from skippercast.relief import digests, live_check
from skippercast.relief.pmtiles_v3 import write_pmtiles
from tests._support import ROOT

REGION = 'fixture-bay'
GENERATION = 'a' * 64
POINTER = f'catalog/relief/{REGION}.json'
PAYLOAD = b'synthetic-tile'


def encoded(value):
    return json.dumps(value).encode()


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def commit(repo, subject):
    git(repo, 'add', '.')
    git(repo, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test',
        'commit', '--no-gpg-sign', '-m', subject)
    return git(repo, 'rev-parse', 'HEAD')


def row(check, reason, *, fail=False, key=None):
    result = dict(check=check, status='FAIL' if fail else 'PASS', reason=reason)
    return result if key is None else dict(result, key=key)


@pytest.fixture
def release(tmp_path):
    tiles = {(8, 5, 0): PAYLOAD, (9, 0, 0): b'zoom-nine'}
    archive = write_pmtiles(tmp_path / 'tiny.pmtiles', tiles.items(), metadata={},
                            bounds=(-121., 35., -120., 36.), minzoom=8, maxzoom=9,
                            center=(8, -120.5, 35.5)).read_bytes()
    index = tmp_path / 'index'
    index.mkdir()
    digests.write_index(BytesIO(archive), index)
    digest = sha256(archive).hexdigest()
    root_digest = sha256((index / 'root.json').read_bytes()).hexdigest()
    stem = f'tiles/relief/{REGION}/{digest}'
    prefix = f'{stem}.digests/{root_digest}/'
    pointer = dict(region=REGION, generation=GENERATION, sha256=digest, bytes=len(archive),
                   minzoom=8, maxzoom=9, digest_root_sha256=root_digest,
                   schema='sc-relief-pointer/1', status='reviewed', private=False)
    return SimpleNamespace(pointer=pointer, archive=stem + '.pmtiles', root=prefix + 'root.json',
                           chunks=[prefix + f'{z}/0_0.json' for z in (8, 9)],
                           objects={POINTER: encoded(pointer), stem + '.pmtiles': archive,
                                    **{prefix + p.relative_to(index).as_posix(): p.read_bytes()
                                       for p in index.rglob('*.json')}})


@pytest.fixture
def checkout(tmp_path, release):
    origin = tmp_path / 'origin'
    origin.mkdir()
    git(origin, 'init', '--initial-branch=main')
    notes = origin / 'notes'
    notes.write_text('initial')
    stale = commit(origin, 'Initial')
    git(origin, 'switch', '-c', 'data')
    pointer = origin / POINTER
    pointer.parent.mkdir(parents=True)
    pointer.write_bytes(release.objects[POINTER])
    side = commit(origin, 'Reviewed pointer')
    git(origin, 'switch', 'main')
    git(origin, '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.test',
        'merge', '--no-gpg-sign', '--no-ff', '--no-edit', 'data')
    merge = git(origin, 'rev-parse', 'HEAD')
    notes.write_text('later head without pointer change')
    head = commit(origin, 'Unrelated change')
    repo = tmp_path / 'clone'
    git(tmp_path, 'clone', '--no-local', str(origin), str(repo))
    git(repo, 'remote', 'set-url', 'origin', '../origin')
    git(repo, 'fetch', 'origin', 'main')  # establish observable old FETCH_HEAD and origin/main
    notes.write_text('only present at origin')
    deployed = commit(origin, 'Deployed descendant')
    return SimpleNamespace(repo=repo, origin=origin, stale=stale, side=side,
                           merge=merge, head=head, deployed=deployed,
                           out=tmp_path / 'out', report=tmp_path / 'out' / REGION / 'live' / GENERATION / 'live.json')


@pytest.fixture
def site(release, checkout):
    responses = {key: (200, {}, body) for key, body in release.objects.items()}
    responses['deploy.json'] = 200, {}, encoded({'commit': checkout.deployed})
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append((self.command, self.path, self.headers.get('Range')))
            status, headers, body = responses.get(self.path.removeprefix('/'), (404, {}, b''))
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_HEAD = do_POST = do_GET

        def log_message(self, format, *args):
            pass

    with HTTPServer(('127.0.0.1', 0), Handler) as server:
        thread = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01})
        thread.start()
        try:
            yield SimpleNamespace(base=f'http://127.0.0.1:{server.server_port}',
                                  responses=responses, requests=requests)
        finally:
            server.shutdown()
            thread.join()


def argv(checkout, site, *, out=None, region=REGION, base=None):
    return ['--region', region, '--out', str(out or checkout.out), '--repo', str(checkout.repo),
            '--base', base or site.base]


def report(checkout, site, deployed, checks, verdict, requests):
    return dict(region=REGION, base=site.base, merge=checkout.merge, deployed=deployed,
                checks=checks, verdict=verdict, requests=requests)


def trace(*keys):
    return [('GET', '/' + key, None) for key in keys]


def verified(release, deploy_reason='ancestor'):
    return [row('deploy', deploy_reason), row('pointer', 'identical'),
            row('archive', '', key=release.archive), row('root', '', key=release.root),
            row('chunk', '', key=release.chunks[0]), row('tile', '', key=f'{release.archive}#8/5/0'),
            row('chunk', '', key=release.chunks[1]), row('tile', '', key=f'{release.archive}#9/0/0')]


def test_C1_dispatch_fetches_new_descendant_and_proves_merge_not_head(checkout, release, site):
    """C1: Dispatch must find the module; stale refs, HEAD or the side commit are wrong evidence."""
    result = subprocess.run([sys.executable, str(ROOT / 'scripts/relief/region.py'), 'live-check',
                             *argv(checkout, site)], check=False, capture_output=True, text=True)
    assert (result.returncode, result.stdout, result.stderr) == (0, '', '')
    assert checkout.merge not in (checkout.side, checkout.head)
    assert json.loads(checkout.report.read_bytes()) == report(
        checkout, site, checkout.deployed, verified(release), 'PASS', 7)
    assert site.requests == trace('deploy.json', POINTER, release.archive, release.root, *release.chunks)


@pytest.mark.parametrize('which, reason', [('merge', 'equal'), ('stale', 'stale'),
                                           ('unknown', 'unknown-commit'), ('side', 'diverged')])
def test_C1_deploy_commit_relations(checkout, release, site, which, reason):
    """C1: An old, unrelated or unknown build must not authorize the pointer/chain."""
    # The side commit used to introduce the pointer is an ancestor of the merge;
    # create a sibling of that commit for the genuinely divergent case.
    if which == 'side':
        git(checkout.repo, 'switch', '-c', 'unrelated', checkout.stale)
        (checkout.repo / 'notes').write_text('divergent checkout object')
        checkout.side = commit(checkout.repo, 'Divergent')
        git(checkout.repo, 'switch', 'main')
    deployed = getattr(checkout, which) if which != 'unknown' else 'f' * 40
    site.responses['deploy.json'] = 200, {}, encoded({'commit': deployed})
    passed = which == 'merge'
    assert live_check.main(argv(checkout, site)) == (0 if passed else 1)
    checks = verified(release, reason) if passed else [row('deploy', reason, fail=True)]
    assert json.loads(checkout.report.read_bytes()) == report(
        checkout, site, deployed, checks, 'PASS' if passed else 'FAIL', 7 if passed else 2)
    tail = (POINTER, release.archive, release.root, *release.chunks) if passed else ()
    assert site.requests == trace('deploy.json', *tail)


@pytest.mark.parametrize('case', ['deploy-404', 'deploy-invalid', 'pointer-404', 'pointer-differs',
                                  'pointer-redirect', 'pointer-oversize', 'archive-404', 'archive-redirect',
                                  'archive-oversize', 'tile-tamper'])
def test_C1_transport_and_identity_fail_closed(checkout, release, site, case):
    """C1: Errors and substitutions fail at the offending object, with no downstream/probe GET."""
    step, reason = case.split('-', 1)
    deploy, pointer = verified(release)[:2]
    deployed = checkout.deployed
    if step == 'deploy':
        key, prior, deployed = 'deploy.json', (), None
        checks = [row('deploy', 'missing' if reason == '404' else 'invalid', fail=True)]
        if reason == 'invalid':
            site.responses[key] = 200, {}, b'{'  # JSON error, not an ancestry failure
    elif step == 'pointer':
        key, prior = POINTER, ('deploy.json',)
        checks = [deploy, row('pointer', 'missing' if reason == '404' else reason, fail=True)]
        if reason == 'differs':
            site.responses[key] = 200, {}, release.objects[key] + b'\n'
    else:
        key, prior = release.archive, ('deploy.json', POINTER)
        checks = [deploy, pointer, row('archive', 'sha256' if step == 'tile' else
                                      'missing' if reason == '404' else reason, fail=True, key=key)]
        if reason == 'redirect':
            checks[-1] = row('fetch', 'redirect', fail=True, key=key)
        if step == 'tile':
            original = release.objects[key]
            tampered = original.replace(PAYLOAD, b'X' + PAYLOAD[1:])
            assert (tampered[:127], len(tampered), tampered != original) == (original[:127], len(original), True)
            site.responses[key] = 200, {}, tampered
    if reason == '404':
        del site.responses[key]
    elif reason == 'redirect':
        site.responses['not-allowed'] = site.responses[key]
        site.responses[key] = 302, {'Location': '/not-allowed'}, b''
    elif reason == 'oversize':
        body = release.objects[key] + b'!' if step == 'archive' else b'!' * ((1 << 20) + 1)
        site.responses[key] = 200, {}, body
    assert live_check.main(argv(checkout, site)) == 1
    assert json.loads(checkout.report.read_bytes()) == report(
        checkout, site, deployed, checks, 'FAIL', len(prior) + 2)
    assert site.requests == trace(*prior, key)


def test_C1_opener_timeout_and_reads_are_bounded(monkeypatch):
    """C1: An unbounded read can drain arbitrary bytes even if the hash then fails."""
    opens, read_sizes, closes = [], [], []

    class Response(BytesIO):
        status = 200

        def read(self, size: int | None = -1, /):
            read_sizes.append(size)
            return super().read(size)

        def close(self):
            if not self.closed:
                closes.append(True)
            super().close()

    def open_request(request, *, timeout):
        opens.append((request.get_method(), request.full_url, timeout))
        return Response(b'x' * (65536 + 50))

    opener = SimpleNamespace(open=open_request)
    configured = []

    def build(*handlers):
        configured.append(len(handlers))
        return opener

    monkeypatch.setattr(live_check, 'build_opener', build)
    transport = live_check.Site('https://example.test')
    first = transport.fetch('one', max_bytes=65536)
    second = transport.fetch('two', max_bytes=9)
    assert first is not None and b''.join(first) == b'x' * (65536 + 1)
    assert second is not None and b''.join(second) == b'x' * 10
    assert (configured, opens, read_sizes, closes, transport.requests) == (
        [1], [('GET', 'https://example.test/one', 15), ('GET', 'https://example.test/two', 15)],
        [65536, 1, 10], [True, True], 3)


def test_C1_default_base_and_connection_failure(checkout, site, monkeypatch):
    """C1: Omitting --base uses the public origin; a connection failure still writes FAIL."""
    def offline(request, *, timeout):
        assert (request.full_url, timeout) == ('https://skippercast.com/deploy.json', 15)
        raise URLError('offline fixture')

    monkeypatch.setattr(live_check, 'build_opener', lambda *_: SimpleNamespace(open=offline))
    args = argv(checkout, site)[:-2]
    assert live_check.main(args) == 1
    expected = report(checkout, site, None, [row('deploy', 'transport', fail=True)], 'FAIL', 2)
    assert json.loads(checkout.report.read_bytes()) == dict(expected, base='https://skippercast.com')


def test_C2_run_leaves_entire_clone_byte_unchanged(checkout, release, site):
    """C2: Running status without optional-lock suppression or fetching in the clone mutates .git."""
    def snapshot():
        return {p.relative_to(checkout.repo): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in checkout.repo.rglob('*') if p.is_file()}

    before = snapshot()
    assert before[Path('.git/FETCH_HEAD')][0].startswith(checkout.head.encode())
    assert git(checkout.repo, 'rev-parse', 'refs/remotes/origin/main') == checkout.head
    assert live_check.main(argv(checkout, site)) == 0
    assert git(checkout.repo, 'rev-parse', 'refs/remotes/origin/main') == checkout.head
    assert snapshot() == before
    assert json.loads(checkout.report.read_bytes()) == report(
        checkout, site, checkout.deployed, verified(release), 'PASS', 7)
    assert not list(checkout.out.glob('relief-history-*'))


def test_C2_failed_fetch_removes_disposable_repo(checkout, site, monkeypatch, capsys):
    """C2: Cleanup must include a Git error after git init, before any HTTP or report."""
    git(checkout.origin, 'branch', '-m', 'main', 'not-main')
    seen = []
    real_git = live_check._git

    def observe(repo, *args, **kwargs):
        if args[-3:] == ('fetch', 'origin', 'main'):
            seen.append(repo)
            assert (repo / 'objects/info/alternates').is_file()
        return real_git(repo, *args, **kwargs)

    monkeypatch.setattr(live_check, '_git', observe)
    assert live_check.main(argv(checkout, site)) == 2
    assert len(seen) == 1 and seen[0].parent == checkout.out
    assert (list(checkout.out.iterdir()), site.requests) == ([], [])
    assert 'returned non-zero exit status 128' in capsys.readouterr().err


@pytest.mark.parametrize('case', ['region', 'base', 'dirty', 'repo-subdir', 'missing-pointer',
                                  'invalid-generation', 'inside-clone', 'escaped-out'])
def test_C2_local_refusals_never_fetch_or_write(checkout, release, site, case):
    """C2: Bad local input is exit 2, not a deployment verdict or an unsafe path write."""
    args = argv(checkout, site)
    if case == 'region':
        args = argv(checkout, site, region='..')
    elif case == 'base':
        args = argv(checkout, site, base='file:///not-a-site')
    elif case == 'dirty':
        (checkout.repo / POINTER).write_bytes(b'local edit')
    elif case == 'repo-subdir':
        args[5] = str(checkout.repo / 'catalog')
    elif case == 'missing-pointer':
        git(checkout.repo, 'switch', '--detach', checkout.stale)
    elif case == 'invalid-generation':
        (checkout.repo / POINTER).write_bytes(encoded(dict(release.pointer, generation='../../escape')))
        commit(checkout.repo, 'Malformed local pointer')
    elif case == 'inside-clone':
        args = argv(checkout, site, out=checkout.repo / 'forbidden')
    else:
        checkout.out.mkdir()
        (checkout.out / REGION).symlink_to(checkout.repo, target_is_directory=True)
    assert (live_check.main(args), site.requests, checkout.report.exists()) == (2, [], False)
    assert not (checkout.repo / 'forbidden').exists()
    assert not (checkout.repo / 'live').exists()


def test_C2_usage_is_argparse_exit_two():
    """C2: Missing required flags are a usage error, not a live FAIL."""
    with pytest.raises(SystemExit) as error:
        live_check.main([])
    assert (type(error.value), error.value.code) == (SystemExit, 2)


@pytest.mark.parametrize('fail_replace', [False, True])
def test_C2_atomic_report_replacement(checkout, release, site, monkeypatch, fail_replace):
    """C2: Readers see the old complete receipt until replacement; failed replacement leaves it intact."""
    checkout.report.parent.mkdir(parents=True)
    checkout.report.write_bytes(b'old receipt')
    expected = report(checkout, site, checkout.deployed, verified(release), 'PASS', 7)
    actual_replace = Path.replace
    observed = []

    def replace(source, destination):
        assert destination == checkout.report
        observed.append((source.parent, destination.read_bytes(), json.loads(source.read_bytes())))
        if fail_replace:
            raise PermissionError('stub publication refusal')
        return actual_replace(source, destination)

    monkeypatch.setattr(Path, 'replace', replace)
    assert live_check.main(argv(checkout, site)) == (2 if fail_replace else 0)
    assert observed == [(checkout.report.parent, b'old receipt', expected)]
    assert list(checkout.report.parent.iterdir()) == [checkout.report]
    if fail_replace:
        assert checkout.report.read_bytes() == b'old receipt'
    else:
        assert json.loads(checkout.report.read_bytes()) == expected


def test_C3_remaining_allowance_and_twentieth_request(checkout, release, site, monkeypatch):
    """C3: The Git fetch counts; a future archive caller cannot issue a twenty-first request."""
    keys = [f'fixture/{i}' for i in range(18)]
    for key in keys:
        site.responses[key] = 200, {}, b'x'

    def larger_chain(pointer, fetch, *, budget):
        assert (pointer, budget) == (release.pointer, 17)
        for key in keys:
            body = fetch(key, max_bytes=1)
            assert body is not None and b''.join(body) == b'x'
        pytest.fail('transport admitted a twenty-first operation')

    monkeypatch.setattr(live_check.live_archive, 'check_archive', larger_chain)
    assert live_check.main(argv(checkout, site)) == 1
    checks = verified(release)[:2] + [row('fetch', 'budget', fail=True, key=keys[-1])]
    assert json.loads(checkout.report.read_bytes()) == report(
        checkout, site, checkout.deployed, checks, 'FAIL', 20)
    assert site.requests == trace('deploy.json', POINTER, *keys[:-1])
