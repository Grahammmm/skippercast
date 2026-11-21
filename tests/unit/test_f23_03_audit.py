"""A data branch writer delayed between Git and R2 cannot restore older bytes."""
from contextlib import nullcontext
import json
import os
from pathlib import Path
from shlex import quote
import subprocess
import sys
from unittest.mock import patch

import pytest

from scripts import publish_r2
from tests._support import ROOT
from tests.unit.test_f21_01_audit import executable, load_store, save_store

BRANCH = ROOT / 'scripts/publish_branch_snapshot.sh'
MIRROR = ROOT / 'scripts/publish_branch_r2.sh'
CURRENT = 'data/' + publish_r2.CURRENT


def command(*args, cwd, env, check=True):
    return subprocess.run(args, cwd=cwd, env=env, check=check, capture_output=True, text=True, timeout=30)


def push(writer, label, payload, env):
    tree = writer / 'published'
    command('bash', str(BRANCH), '--load', 'data', str(tree), cwd=writer, env=env)
    (tree / 'latest.json').write_text(json.dumps({'sample': payload}))
    command('bash', str(BRANCH), 'data', str(tree), f'Synthetic {label}', cwd=writer, env=env)
    return command('git', 'rev-parse', 'HEAD', cwd=tree, env=env).stdout.strip()


def mirror(writer, env):
    return command('bash', str(MIRROR), str(writer / 'published'), 'data', cwd=ROOT, env=env, check=False)


def current(state):
    objects = load_store(state).objects
    pointer = objects[CURRENT]
    generation = json.loads(pointer['Body'])['generation']
    release = json.loads(objects[f'data/.r2-releases/{generation}.json']['Body'])
    digest = release['files']['latest.json']
    return pointer, json.loads(objects[f'data/.r2-objects/{digest}']['Body'])['sample']


@pytest.mark.parametrize('pause', ['before-mirror', 'before-pointer-read', 'before-pointer-put'])
def test_delayed_writer_cannot_replace_newer_data_snapshot(tmp_path, pause):
    # Real archived commits and lease pushes; just the R2 transport is fake.
    # A guard before the CAS baseline read fails the read interleave. A
    # content-only no-op fails the PUT interleave when B restores seed bytes.
    state = tmp_path / 'store.json'
    state.write_text('{}')
    executable(tmp_path / 'python', '#!/bin/sh\nshift\n'
               f'exec {quote(sys.executable)} -m tests.unit.test_f23_03_audit {quote(str(state))} "$@"\n')
    env = {'PATH': f'{tmp_path}{os.pathsep}{os.environ["PATH"]}', 'HOME': str(tmp_path), 'TMPDIR': str(tmp_path),
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_ALLOW_PROTOCOL': 'file',
           'CLOUDFLARE_API_TOKEN': 'fixture', 'CLOUDFLARE_ACCOUNT_ID': 'fixture'}
    remote = tmp_path / 'origin.git'
    command('git', 'init', '-q', '--bare', str(remote), cwd=tmp_path, env=env)
    for label in ('seed', 'a', 'b'):
        command('git', 'clone', '-q', str(remote), label, cwd=tmp_path, env=env)
    seed, a, b = (tmp_path / label for label in ('seed', 'a', 'b'))
    seed_commit = push(seed, 'seed', 'seed', env)
    seeded = mirror(seed, env)
    assert seeded.returncode == 0, seeded.stdout + seeded.stderr
    seed_pointer, served = current(state)
    assert served == 'seed' and seed_pointer['IfNoneMatch'] == '*'
    a_commit = push(a, 'a', 'older', env)

    if pause == 'before-mirror':
        b_commit = push(b, 'b', 'newer', env)
        promoted = mirror(b, env)
        assert promoted.returncode == 0, promoted.stdout + promoted.stderr
        winner, served = current(state)
        assert served == 'newer' and winner['IfMatch'] == seed_pointer['ETag']
        resumed = mirror(a, env)
    else:
        resumed = mirror(a, {**env, 'FIXTURE_INTERLEAVE': pause})
        b_commit, = (tmp_path / 'winner').read_text().splitlines()
        winner, served = current(tmp_path / 'winner.json')
        assert served == ('seed' if pause == 'before-pointer-put' else 'newer')

    assert current(state) == (winner, served), 'A replaced B on R2'
    assert winner['IfMatch'] == seed_pointer['ETag'] and winner['ETag'] != seed_pointer['ETag']
    if pause == 'before-pointer-put':
        assert resumed.returncode == 1 and 'PreconditionFailed' in resumed.stdout
        assert json.loads(winner['Body'])['generation'] == json.loads(seed_pointer['Body'])['generation']
    else:
        assert resumed.returncode == 0, resumed.stdout + resumed.stderr
    assert len({seed_commit, a_commit, b_commit}) == 3
    assert command('git', '--git-dir', str(remote), 'rev-parse', 'refs/heads/data', cwd=tmp_path,
                   env=env).stdout.strip() == b_commit
    assert json.loads(winner['Body'])['source_commit'] == b_commit


if __name__ == '__main__':
    state = Path(sys.argv.pop(1))
    store = load_store(state)
    pause = os.environ.pop('FIXTURE_INTERLEAVE', None)

    def promote_b():
        env = os.environ.copy()
        b = state.parent / 'b'
        label = 'seed' if pause == 'before-pointer-put' else 'newer'
        # R2 would already expose A's immutable uploads to both writers.
        save_store(state, store)
        commit = push(b, 'b', label, env)
        result = mirror(b, env)
        assert result.returncode == 0, result.stdout + result.stderr
        winner = load_store(state)
        save_store(state.with_name('winner.json'), winner)
        state.with_name('winner').write_text(commit)
        store.objects = winner.objects

    get_object = store.get_object

    def before_read(Bucket, Key):
        if Key == CURRENT and not state.with_name('winner').exists():
            promote_b()
        return get_object(Bucket=Bucket, Key=Key)

    hooks = {'before-pointer-read': {'get_object': before_read}, 'before-pointer-put': {'before_commit': promote_b}}
    hook = patch.multiple(store, **hooks[pause]) if pause else nullcontext()
    with hook, patch.object(publish_r2, 'client', return_value=store):
        status = publish_r2.run()
    save_store(state, store)
    sys.exit(status)
