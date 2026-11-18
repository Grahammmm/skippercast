"""A failed or incomplete branch staging must not switch the R2 snapshot."""
import json
import os
from pathlib import Path
from shlex import quote
import shutil
import subprocess
import sys
from unittest.mock import patch

import pytest

from scripts import publish_r2
from tests._support import ROOT
from tests.integration.test_r2_snapshots import FakeS3, published

INDEX = 'index.json'
TILE = 'tiles/sample tile.json'
CONTENTS = {INDEX: json.dumps({'tile': TILE}), TILE: '{"sample":2}'}
POINTER = 'forecasts/' + publish_r2.CURRENT


def save_store(path, store):
    path.write_text(json.dumps({key: {**obj, 'Body': obj['Body'].decode()}
                                for key, obj in store.objects.items()}))


def load_store(path):
    store = FakeS3()
    store.objects = {key: {**obj, 'Body': obj['Body'].encode()}
                     for key, obj in json.loads(path.read_text()).items()}
    return store


def executable(path, source):
    path.write_text(source)
    path.chmod(0o755)


@pytest.fixture
def branch(tmp_path):
    tree = tmp_path / 'branch'
    tree.mkdir()
    state = tmp_path / 'store.json'
    prior = tmp_path / 'prior'
    prior.mkdir()
    (prior / INDEX).write_text('{"sample":1}')
    store = FakeS3()
    publish_r2.sync(store, 'fixture', prior, 'forecasts')
    save_store(state, store)
    for name, contents in CONTENTS.items():
        path = tree / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents)
    git = ['git', '-C', str(tree), '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid']
    for args in (['init', '-q'], ['add', '--all'], ['commit', '-qm', 'synthetic snapshot']):
        subprocess.run(git + args, check=True, timeout=30)
    (tree / TILE).write_text('uncommitted modification')
    (tree / 'untracked.json').write_text('{}')
    executable(tmp_path / 'python', '#!/bin/sh\nshift\n'
               f'exec {quote(sys.executable)} -m tests.unit.test_f21_01_audit {quote(str(state))} "$@"\n')
    return tree, state


def run_branch(branch):
    tree, state = branch
    env = {'PATH': f'{state.parent}{os.pathsep}{os.environ["PATH"]}', 'HOME': str(state.parent),
           'TMPDIR': str(state.parent), 'CLOUDFLARE_API_TOKEN': 'fixture', 'CLOUDFLARE_ACCOUNT_ID': 'fixture'}
    return subprocess.run(['bash', 'scripts/publish_branch_r2.sh', str(tree), 'forecasts'], cwd=ROOT, env=env,
                          capture_output=True, text=True, timeout=30)


@pytest.mark.parametrize('fault', ['archive-exit', 'extract-exit', 'extract-omits', 'extract-changes-bytes'])
def test_staging_fault_preserves_previous_release(branch, fault):
    _, state = branch
    before = state.read_bytes()
    marker = state.parent / 'fault-reached'
    mark = f'touch {quote(str(marker))}\n'
    if fault == 'archive-exit':
        real_git = shutil.which('git')
        assert real_git is not None
        executable(state.parent / 'git', f'#!/bin/sh\n{quote(real_git)} "$@" || exit $?\n'
                   f'if [ "$3" = archive ]; then\n{mark}exit 1\nfi\n')
    else:
        tar_path = shutil.which('tar')
        assert tar_path is not None
        real_tar = quote(tar_path)
        if fault == 'extract-changes-bytes':
            extract = f'{real_tar} "$@" || exit $?\n'
            damage = f'printf \'{{"sample":3}}\' > "${{@: -1}}/{TILE}"\n'
        else:
            extract = f'{real_tar} "$@" {INDEX} || exit $?\n'
            damage = ''
        status = 1 if fault == 'extract-exit' else 0
        executable(state.parent / 'tar', f'#!/bin/bash\n{extract}{damage}{mark}exit {status}\n')
    out = run_branch(branch)
    assert marker.exists(), out.stdout + out.stderr
    assert state.read_bytes() == before, 'Staging failure changed the object store or its current pointer'
    assert out.returncode != 0, out.stdout + out.stderr
    assert not state.with_suffix('.client').exists(), 'Staging failure reached the R2 client'


def test_complete_archive_switches_release(branch):
    _, state = branch
    prior = load_store(state).objects[POINTER]
    out = run_branch(branch)
    assert out.returncode == 0, out.stdout + out.stderr
    store = load_store(state)
    assert store.objects[POINTER]['IfMatch'] == prior['ETag']
    assert published(store) == {name: body.encode() for name, body in CONTENTS.items()}
    assert published(store, json.loads(prior['Body'])['generation']) == {INDEX: b'{"sample":1}'}


if __name__ == '__main__':
    # Child of the real shell publisher. Swap only the transport, never the uploader.
    path = Path(sys.argv.pop(1))
    store = load_store(path)

    def mock_client(*args):
        path.with_suffix('.client').touch()
        return store

    with patch.object(publish_r2, 'client', mock_client):
        status = publish_r2.run()
    save_store(path, store)
    sys.exit(status)
