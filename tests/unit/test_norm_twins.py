"""Contract tests for scripts/relief/norm_twins.py (twin builds in the normalized cache).

Contract: select drops a source that has two normalized builds, so a duplicate build with the same
output bytes must be found and moved aside (never deleted), the build an earlier release pinned must
stay, and a bucket whose builds disagree must never be touched.
"""

import json
import os

import pytest

from scripts.relief import norm_twins

SOURCE_A, SOURCE_B, SOURCE_C = 'a' * 64, 'b' * 64, 'c' * 64
OLD, NEW = '1' * 64, '2' * 64


def build(norm, source, name, outputs, mtime):
    folder = norm / source / name
    folder.mkdir(parents=True)
    sidecar = folder / 'sidecar.json'
    sidecar.write_text(json.dumps({'normalizer_digest': name, 'outputs': outputs}))
    os.utime(sidecar, ns=(mtime, mtime))
    (folder / 'grid.tif').write_bytes(b'grid ' + name.encode())
    return folder


@pytest.fixture
def cache(tmp_path):
    norm = tmp_path / '_norm'
    same = {'grid.tif': 'g1', 'support.tif': 's1'}
    build(norm, SOURCE_A, OLD, same, 1_000)   # pinned by an earlier release
    build(norm, SOURCE_A, NEW, same, 2_000)   # re-normalized after a code change, identical bytes
    build(norm, SOURCE_B, OLD, same, 1_000)   # healthy bucket: one build
    (norm / '_receipts').mkdir()              # shared non-bucket folder must be ignored
    return norm


def tree(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob('*'))


def test_audit_reports_identical_twins_and_changes_nothing(cache, capsys):
    """A debug-only report that moved files would hide the silent tile loss it exists to expose."""
    before = tree(cache)
    assert norm_twins.main(['--norm', str(cache)]) == 2
    assert json.loads(capsys.readouterr().out)['repairable_buckets'] == 1
    assert tree(cache) == before


def test_apply_moves_only_the_newer_build_and_records_it(cache, tmp_path):
    """Keeping the wrong build would orphan the release that pins the old one; a delete would be unrecoverable."""
    quarantine = tmp_path / 'quarantine'
    assert norm_twins.main(['--norm', str(cache), '--apply', '--quarantine', str(quarantine)]) == 0
    assert (cache / SOURCE_A / OLD / 'grid.tif').is_file()
    assert not (cache / SOURCE_A / NEW).exists()
    assert (quarantine / SOURCE_A / NEW / 'grid.tif').read_bytes() == b'grid ' + NEW.encode()
    assert (cache / SOURCE_B / OLD).is_dir()
    (record,) = quarantine.glob('moved-*.json')
    assert json.loads(record.read_text())['moves'][0]['from'] == str(cache / SOURCE_A / NEW)
    assert norm_twins.main(['--norm', str(cache)]) == 0  # nothing ambiguous remains


def test_conflicting_outputs_block_every_move(cache, tmp_path, capsys):
    """Builds that disagree need a person; moving the 'repairable' ones first would hide the conflict's context."""
    build(cache, SOURCE_C, OLD, {'grid.tif': 'x'}, 1_000)
    build(cache, SOURCE_C, NEW, {'grid.tif': 'y'}, 2_000)
    before = tree(cache)
    assert norm_twins.main(['--norm', str(cache), '--apply', '--quarantine', str(tmp_path / 'q')]) == 1
    assert json.loads(capsys.readouterr().out)['conflicts'] == [SOURCE_C]
    assert tree(cache) == before


def test_symlinked_build_is_not_a_twin(cache, tmp_path):
    """select ignores symlinked builds, so counting one would move a real build for nothing."""
    outside = build(tmp_path / 'elsewhere', SOURCE_B, NEW, {'grid.tif': 'g1', 'support.tif': 's1'}, 3_000)
    (cache / SOURCE_B / NEW).symlink_to(outside)
    assert norm_twins.main(['--norm', str(cache), '--apply', '--quarantine', str(tmp_path / 'q')]) == 0
    assert (cache / SOURCE_B / NEW).is_symlink()


def test_apply_needs_a_quarantine_outside_the_cache_and_refuses_the_private_vault(cache, tmp_path):
    """A quarantine inside the cache would recreate the twin; the vault is never read or written."""
    with pytest.raises(SystemExit):
        norm_twins.main(['--norm', str(cache), '--apply'])
    with pytest.raises(SystemExit):
        norm_twins.main(['--norm', str(cache), '--apply', '--quarantine', str(cache / 'q')])
    with pytest.raises(SystemExit):
        norm_twins.main(['--norm', '/mnt/privatevault/x'])
