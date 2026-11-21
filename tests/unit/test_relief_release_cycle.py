"""Fixture-only release cycle through the deployed-site and Git boundaries."""
from dataclasses import dataclass
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, HTTPServer
from io import BytesIO
import json
import os
import subprocess
import sys
from threading import Thread

from skippercast.relief.digests import write_index
from skippercast.relief.pmtiles_v3 import write_pmtiles
from tests._support import FIXTURES, ROOT

REGION = 'fixture-bay'
POINTER = f'catalog/relief/{REGION}.json'
STYLE_FIXTURES = FIXTURES / 'relief' / 'pointer-style'
TILE = (8, 5, 0)


@dataclass
class Release:
    generation: str
    pointer: bytes
    objects: dict[str, bytes]
    archive: str
    root: str
    chunk: str


def make_release(tmp, fixture, payload, *, previous=None):
    # Rebind the style fixture's placeholder archive and index to real tiny objects.
    pointer = json.loads((STYLE_FIXTURES / fixture).read_bytes())
    archive = write_pmtiles(tmp / 'relief.pmtiles', [(TILE, payload)], metadata={},
                           bounds=tuple(pointer['bounds']), minzoom=8, maxzoom=8,
                           center=(8, -121.15, 35.3)).read_bytes()
    index = tmp / 'index'
    index.mkdir()
    write_index(BytesIO(archive), index)
    digest = sha256(archive).hexdigest()
    root_digest = sha256((index / 'root.json').read_bytes()).hexdigest()
    pointer.update(region=REGION, sha256=digest, bytes=len(archive), digest_root_sha256=root_digest)
    if previous is not None:
        pointer['previous']['sha256'] = json.loads(previous.pointer)['sha256']
    stem = f'tiles/relief/{REGION}/{digest}'
    archive_key = stem + '.pmtiles'
    prefix = f'{stem}.digests/{root_digest}/'
    root, chunk = prefix + 'root.json', prefix + '8/0_0.json'
    objects = {archive_key: archive, root: (index / 'root.json').read_bytes(),
               chunk: (index / '8/0_0.json').read_bytes()}
    # Noncanonical v1 whitespace makes parse/re-encode distinguishable from byte restoration.
    raw = (json.dumps(pointer, indent=2 if previous is None else None) + '\n').encode()
    return Release(pointer['generation'], raw, objects, archive_key, root, chunk)


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True,
                          timeout=30).stdout


def head(repo, ref='HEAD'):
    return git(repo, 'rev-parse', ref).decode().strip()


def configure_git(repo):
    git(repo, 'config', 'user.name', 'Fixture Builder')
    git(repo, 'config', 'user.email', 'fixture@example.invalid')
    git(repo, 'config', 'core.autocrlf', 'false')


def commit_pointer(repo, release, version):
    path = repo / POINTER
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(release.pointer)
    git(repo, 'add', '--', POINTER)
    git(repo, 'commit', '-s', '-m', version)
    return head(repo)


def region_cli(command, repo, *args):
    return subprocess.run([sys.executable, str(ROOT / 'scripts/relief/region.py'), command,
                           '--region', REGION, '--repo', str(repo), *args],
                          check=False, capture_output=True, text=True, timeout=60)


def check_live(repo, out, base, commit, release, *, tampered=False):
    result = region_cli('live-check', repo, '--out', str(out), '--base', base)
    assert (result.returncode, result.stdout, result.stderr) == (int(tampered), '', '')
    checks = [dict(check='deploy', status='PASS', reason='equal'),
              dict(check='pointer', status='PASS', reason='identical')]
    if tampered:
        checks.append(dict(check='archive', key=release.archive, status='FAIL', reason='sha256'))
    else:
        checks.extend(dict(check=check, key=key, status='PASS', reason='') for check, key in (
            ('archive', release.archive), ('root', release.root), ('chunk', release.chunk),
            ('tile', f'{release.archive}#8/5/0'),
        ))
    report = out / REGION / 'live' / release.generation / 'live.json'
    assert json.loads(report.read_bytes()) == dict(
        region=REGION, base=base, merge=commit, deployed=commit, checks=checks,
        verdict='FAIL' if tampered else 'PASS', requests=4 if tampered else 6,
    )


def test_C1_C2_relief_release_cycle(tmp_path, monkeypatch):
    """C1: A rollback that rewrites v1 bytes or still resolves to v2 cannot recover.

    C2: Drive both commands through the shipped region CLI, not mocked internals.
    """
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', os.devnull)
    monkeypatch.setenv('GIT_ALLOW_PROTOCOL', 'file')
    monkeypatch.setenv('no_proxy', '127.0.0.1')
    monkeypatch.setenv('TMPDIR', str(tmp_path))
    original_tile = b'synthetic-relief-tile-v2'
    v1 = make_release(tmp_path / 'v1', 'v1.json', b'synthetic-relief-tile-v1')
    v2 = make_release(tmp_path / 'v2', 'v1_1-prev-v1.json', original_tile, previous=v1)
    origin, repo, out = (tmp_path / name for name in ('origin', 'checkout', 'out'))
    origin.mkdir()
    git(origin, 'init', '--initial-branch=main', '--object-format=sha1', '--template=')
    configure_git(origin)
    v1_commit = commit_pointer(origin, v1, 'Release v1')
    v2_commit = commit_pointer(origin, v2, 'Release v2')
    git(tmp_path, 'clone', '--template=', str(origin), str(repo))
    configure_git(repo)

    responses = {**v1.objects, **v2.objects}

    def serve_commit(commit):
        responses['deploy.json'] = json.dumps({'commit': commit}).encode()
        responses[POINTER] = git(origin, 'show', f'{commit}:{POINTER}')

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = responses.get(self.path.removeprefix('/'))
            if body is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    with HTTPServer(('127.0.0.1', 0), Handler) as server:
        thread = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01})
        thread.start()
        try:
            base = f'http://127.0.0.1:{server.server_port}'
            serve_commit(v2_commit)
            check_live(repo, out, base, v2_commit, v2)

            # Replace exactly one tile payload byte, keeping its archive key and length.
            archive = responses[v2.archive]
            assert archive.count(original_tile) == 1
            responses[v2.archive] = archive.replace(original_tile, b'X' + original_tile[1:])
            check_live(repo, out, base, v2_commit, v2, tampered=True)

            branch = 'rollback/fixture-bay'
            result = region_cli('rollback', repo, '--branch', branch)
            assert (result.returncode, result.stderr) == (0, ''), result.stdout
            rollback = head(repo, branch)
            assert git(repo, 'branch', '--show-current') == (branch + '\n').encode()
            assert head(repo, 'HEAD^') == head(repo, 'main') == v2_commit
            assert (git(repo, 'show', f'{rollback}:{POINTER}'), (repo / POINTER).read_bytes()) == (
                git(origin, 'show', f'{v1_commit}:{POINTER}'), v1.pointer,
            )

            # Simulate deploying the rollback using only the two temporary repos.
            git(origin, 'fetch', str(repo), branch)
            git(origin, 'merge', '--ff-only', 'FETCH_HEAD')
            serve_commit(head(origin))
            check_live(repo, out, base, rollback, v1)
        finally:
            server.shutdown()
            thread.join()
