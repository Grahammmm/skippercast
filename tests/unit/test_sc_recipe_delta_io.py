"""RF0755-10: recipe-delta publication stays anchored to the admitted output directory.

Deterministic syscall hooks swap the output directory (or an ancestor) at one exact seam;
no sleeps, network or private files.
"""
import errno
import json
import os
from pathlib import Path

import pytest

from scripts.coast_diagnostics import recipe_delta as delta
from tests.unit.test_sc_recipe_delta import cli, compare, pair, tree_state, workspace  # noqa: F401


def swap_to(directory, target, moved):
    """Rename `directory` to `moved` and leave a symlink to `target` at its old name."""
    os.rename(directory, moved)
    os.symlink(target, directory)


def snapshot(tmp_path):
    return {name: tree_state(tmp_path / name) for name in ('recipes', 'left-meta', 'right-meta', 'workspace')}


def hook_once(monkeypatch, name, predicate, action):
    real = getattr(os, name)
    fired = []

    def wrapper(*args, **kwargs):
        if not fired and predicate(args, kwargs):
            fired.append(True)
            action(args, kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(os, name, wrapper)
    return fired


def is_create(args, kwargs):
    return len(args) > 1 and args[1] & os.O_EXCL and kwargs.get('dir_fd') is not None


def test_precreate_parent_swap_cannot_write_workspace(tmp_path, workspace, monkeypatch, capsys):
    paths = pair(tmp_path)
    reports = tmp_path / 'reports'
    reports.mkdir()
    before = snapshot(tmp_path)
    fired = hook_once(monkeypatch, 'open', is_create,
                      lambda a, k: swap_to(reports, workspace, tmp_path / 'moved'))
    code, captured = cli(paths, workspace, reports / 'delta.json', capsys)
    monkeypatch.undo()
    assert fired and code == 0, captured.err
    assert snapshot(tmp_path) == before                       # nothing reached workspace or metadata
    assert [p.name for p in (tmp_path / 'moved').iterdir()] == ['delta.json']
    assert (tmp_path / 'moved' / 'delta.json').read_bytes() == delta.serialize_report(compare(paths, workspace))


@pytest.mark.parametrize('variant', ['live-symlink', 'dangling-symlink', 'regular-file'])
def test_ancestor_swap_before_descriptor_walk_refuses(variant, tmp_path, workspace, monkeypatch, capsys):
    paths = pair(tmp_path)
    outer = tmp_path / 'outer'
    (outer / 'reports').mkdir(parents=True)
    out = outer / 'reports' / 'delta.json'
    before = snapshot(tmp_path)

    def replace(args, kwargs):
        os.rename(outer, tmp_path / 'outer-moved')
        if variant == 'live-symlink':
            os.symlink(workspace, outer)
        elif variant == 'dangling-symlink':
            os.symlink(tmp_path / 'nowhere', outer)
        else:
            outer.write_text('not a directory')

    fired = hook_once(monkeypatch, 'open', lambda a, k: a[0] == 'outer' and k.get('dir_fd') is not None, replace)
    code, captured = cli(paths, workspace, out, capsys)
    monkeypatch.undo()
    assert fired and code == 2 and captured.out == ''
    assert json.loads(captured.err)['status'] == 'INVALID'
    assert snapshot(tmp_path) == before
    assert list((tmp_path / 'outer-moved' / 'reports').iterdir()) == []


def test_prepublish_swap_keeps_one_directory_inode(tmp_path, workspace, monkeypatch, capsys):
    paths = pair(tmp_path)
    reports = tmp_path / 'reports'
    reports.mkdir()
    before = snapshot(tmp_path)
    fired = hook_once(monkeypatch, 'link', lambda a, k: True,
                      lambda a, k: swap_to(reports, tmp_path / 'left-meta', tmp_path / 'moved'))
    code, captured = cli(paths, workspace, reports / 'delta.json', capsys)
    monkeypatch.undo()
    assert fired and code == 0, captured.err
    assert snapshot(tmp_path) == before
    assert [p.name for p in (tmp_path / 'moved').iterdir()] == ['delta.json']
    assert (tmp_path / 'moved' / 'delta.json').read_bytes() == delta.serialize_report(compare(paths, workspace))


def test_cleanup_swap_never_unlinks_foreign_temporary(tmp_path, workspace, monkeypatch, capsys):
    paths = pair(tmp_path)
    reports = tmp_path / 'reports'
    reports.mkdir()
    foreign = tmp_path / 'foreign'
    foreign.mkdir()
    seen = []
    real_link = os.link

    def linking(source, destination, *args, **kwargs):
        seen.append(source)
        return real_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, 'link', linking)

    def redirect(args, kwargs):
        (foreign / args[0]).write_text('foreign canary')
        swap_to(reports, foreign, tmp_path / 'moved')

    fired = hook_once(monkeypatch, 'unlink', lambda a, k: k.get('dir_fd') is not None, redirect)
    code, captured = cli(paths, workspace, reports / 'delta.json', capsys)
    monkeypatch.undo()
    assert fired and code == 0, captured.err
    assert (foreign / seen[0]).read_text() == 'foreign canary'
    assert [p.name for p in foreign.iterdir()] == [seen[0]]
    assert [p.name for p in (tmp_path / 'moved').iterdir()] == ['delta.json']   # own temporary removed


def test_publish_race_preserves_concurrent_bytes_in_pinned_parent(tmp_path, workspace, monkeypatch, capsys):
    paths = pair(tmp_path)
    reports = tmp_path / 'reports'
    reports.mkdir()

    def arrive(args, kwargs):
        swap_to(reports, tmp_path / 'left-meta', tmp_path / 'moved')
        (tmp_path / 'moved' / 'delta.json').write_text('concurrent canary')

    fired = hook_once(monkeypatch, 'link', lambda a, k: True, arrive)
    code, captured = cli(paths, workspace, reports / 'delta.json', capsys)
    monkeypatch.undo()
    result = json.loads(captured.err)
    assert fired and code == 2 and captured.out == '' and 'output exists' in result['error']
    moved = tmp_path / 'moved'
    assert (moved / 'delta.json').read_text() == 'concurrent canary'
    retained = [p for p in moved.iterdir() if p.name != 'delta.json']
    assert len(retained) == 1 and retained[0].name in result['error']
    assert retained[0].read_bytes() == delta.serialize_report(compare(paths, workspace))


@pytest.mark.parametrize('failure', ['open', 'write', 'fsync', 'close', 'link'])
def test_fd_lifetime_and_failure_evidence(failure, tmp_path, workspace, monkeypatch, capsys):
    paths = pair(tmp_path)
    reports = tmp_path / 'reports'
    reports.mkdir()
    directories, files, open_dirs, ours = set(), set(), set(), set()
    real_open, real_close, real_write = os.open, os.close, os.write

    def opening(path, flags, *args, **kwargs):
        if failure == 'open' and is_create((path, flags), kwargs):
            raise OSError(errno.EACCES, 'synthetic open failure')
        descriptor = real_open(path, flags, *args, **kwargs)
        (directories if flags & os.O_DIRECTORY else files).add(descriptor)
        open_dirs.add(descriptor)
        if flags & os.O_WRONLY:
            ours.add(descriptor)
        return descriptor

    def closing(descriptor):
        open_dirs.discard(descriptor)
        real_close(descriptor)
        if failure == 'close' and descriptor in ours:
            raise OSError(errno.EIO, 'synthetic close failure')

    calls = []

    def writing(descriptor, data):
        if failure == 'write' and descriptor in ours:
            if calls:
                raise OSError(errno.ENOSPC, 'synthetic error after short write')
            calls.append(1)
            return real_write(descriptor, bytes(data)[:8])
        return real_write(descriptor, data)

    def fsyncing(descriptor):
        raise OSError(errno.EIO, 'synthetic fsync failure')

    def linking(*args, **kwargs):
        raise OSError(errno.EPERM, 'synthetic link failure')

    monkeypatch.setattr(os, 'open', opening)
    monkeypatch.setattr(os, 'close', closing)
    monkeypatch.setattr(os, 'write', writing)
    if failure == 'fsync':
        monkeypatch.setattr(os, 'fsync', fsyncing)
    if failure == 'link':
        monkeypatch.setattr(os, 'link', linking)
    code, captured = cli(paths, workspace, reports / 'delta.json', capsys)
    monkeypatch.undo()
    result = json.loads(captured.err)
    assert code == 2 and captured.out == '' and result['status'] == 'INVALID'
    assert not (reports / 'delta.json').exists()
    assert not any(d in open_dirs for d in directories)        # every directory descriptor was closed
    assert not any(f in open_dirs for f in files)
    names = [p.name for p in reports.iterdir()]
    if failure == 'open':
        assert names == []
    else:
        assert len(names) == 1 and names[0].startswith('.delta.json.incomplete-') and names[0] in result['error']


def test_missing_parent_still_refused_and_never_created(tmp_path, workspace, capsys):
    paths = pair(tmp_path)
    code, captured = cli(paths, workspace, tmp_path / 'absent' / 'delta.json', capsys)
    assert code == 2 and captured.out == '' and not (tmp_path / 'absent').exists()


def test_normal_report_is_byte_identical(tmp_path, workspace, capsys):
    paths = pair(tmp_path)
    reports = tmp_path / 'reports'
    reports.mkdir()
    code, captured = cli(paths, workspace, reports / 'delta.json', capsys)
    assert code == 0, captured.err
    expected = delta.serialize_report(compare(paths, workspace))
    assert (reports / 'delta.json').read_bytes() == expected
    assert [p.name for p in reports.iterdir()] == ['delta.json']
    assert list(workspace.iterdir()) == []
