"""Contract tests for scripts/relief/norm_twins.py (twin builds in the normalized cache).

Contract: select drops a source that has two normalized builds, so a duplicate build with the same
output bytes must be found and moved aside (never deleted), the build an earlier release pinned must
stay, a bucket whose builds disagree (or whose bytes do not match their pins) must never be touched,
and --apply is all-or-nothing: every destination is checked first, the move record exists before the
first move, a failed move is rolled back, and no move can land outside the quarantine or in the vault.
"""

import hashlib
import json
import os

import pytest

from scripts.relief import norm_twins

SOURCE_A, SOURCE_B, SOURCE_C = 'a' * 64, 'b' * 64, 'c' * 64
OLD, NEW = '1' * 64, '2' * 64


def sha(data):
    return hashlib.sha256(data).hexdigest()


def build(norm, source, name, mtime, payload=b'same bytes', pins=None):
    """A build whose sidecar pins the real hashes of its two output files (unless `pins` overrides)."""
    folder = norm / source / name
    folder.mkdir(parents=True)
    grid, support = b'grid ' + payload, b'support ' + payload
    (folder / 'grid.tif').write_bytes(grid)
    (folder / 'support.tif').write_bytes(support)
    outputs = {'grid.tif': sha(grid), 'support.tif': sha(support)} if pins is None else pins
    sidecar = folder / 'sidecar.json'
    sidecar.write_text(json.dumps({'normalizer_digest': name, 'outputs': outputs}))
    os.utime(sidecar, ns=(mtime, mtime))
    return folder


@pytest.fixture
def cache(tmp_path):
    norm = tmp_path / '_norm'
    build(norm, SOURCE_A, OLD, 1_000)   # pinned by an earlier release
    build(norm, SOURCE_A, NEW, 2_000)   # re-normalized after a code change, identical bytes
    build(norm, SOURCE_B, OLD, 1_000)   # healthy bucket: one build
    (norm / '_receipts').mkdir()        # shared non-bucket folder must be ignored
    return norm


def tree(root):
    return sorted(str(p.relative_to(root)) for p in root.rglob('*'))


def apply(cache, quarantine):
    return norm_twins.main(['--norm', str(cache), '--apply', '--quarantine', str(quarantine)])


def test_audit_reports_identical_twins_and_changes_nothing(cache, capsys):
    """A debug-only report that moved files would hide the silent tile loss it exists to expose."""
    before = tree(cache)
    assert norm_twins.main(['--norm', str(cache)]) == 2
    assert json.loads(capsys.readouterr().out)['repairable_buckets'] == 1
    assert tree(cache) == before


def test_apply_moves_only_the_newer_build_and_records_it(cache, tmp_path):
    """Keeping the wrong build would orphan the release that pins the old one; a delete would be unrecoverable."""
    quarantine = tmp_path / 'quarantine'
    assert apply(cache, quarantine) == 0
    assert (cache / SOURCE_A / OLD / 'grid.tif').is_file()
    assert not (cache / SOURCE_A / NEW).exists()
    assert (quarantine / SOURCE_A / NEW / 'grid.tif').read_bytes() == b'grid same bytes'
    assert (cache / SOURCE_B / OLD).is_dir()
    (record,) = quarantine.glob('moved-*.json')
    doc = json.loads(record.read_text())
    assert doc['status'] == 'complete'
    assert doc['moves'] == [{'from': str(cache / SOURCE_A / NEW), 'to': str(quarantine / SOURCE_A / NEW), 'moved': True}]
    assert norm_twins.main(['--norm', str(cache)]) == 0  # nothing ambiguous remains


def test_conflicting_outputs_block_every_move(cache, tmp_path, capsys):
    """Builds that disagree need a person; moving the 'repairable' ones first would hide the conflict's context."""
    build(cache, SOURCE_C, OLD, 1_000, payload=b'x')
    build(cache, SOURCE_C, NEW, 2_000, payload=b'y')
    before = tree(cache)
    assert apply(cache, tmp_path / 'q') == 1
    assert json.loads(capsys.readouterr().out)['conflicts'] == [SOURCE_C]
    assert tree(cache) == before


def test_pins_that_match_but_file_bytes_that_do_not_are_a_conflict(cache, tmp_path, capsys):
    """Equal sidecars are not equal files: a corrupted twin carrying the old pins would be quarantined as 'identical'."""
    (cache / SOURCE_A / NEW / 'grid.tif').write_bytes(b'bit rot')  # sidecar still pins the original hash
    before = tree(cache)
    assert apply(cache, tmp_path / 'q') == 1
    assert json.loads(capsys.readouterr().out)['conflicts'] == [SOURCE_A]
    assert tree(cache) == before


@pytest.mark.parametrize('damage', ['no-outputs-key', 'null-outputs', 'files-missing', 'one-pin-only', 'not-hex-pin'])
def test_unproven_outputs_are_never_twins(tmp_path, capsys, damage):
    """Two builds that both lack proof of their outputs used to 'match' ('null' == 'null') and get moved."""
    norm = tmp_path / '_norm'
    for name, mtime in ((OLD, 1_000), (NEW, 2_000)):
        folder = build(norm, SOURCE_A, name, mtime)
        doc = json.loads((folder / 'sidecar.json').read_text())
        if damage == 'no-outputs-key':
            del doc['outputs']
        elif damage == 'null-outputs':
            doc['outputs'] = None
        elif damage == 'files-missing':
            (folder / 'grid.tif').unlink()
            (folder / 'support.tif').unlink()
        elif damage == 'one-pin-only':
            doc['outputs'] = {'grid.tif': doc['outputs']['grid.tif']}
        else:
            doc['outputs'] = {'grid.tif': 'g1', 'support.tif': 's1'}
        (folder / 'sidecar.json').write_text(json.dumps(doc))
        os.utime(folder / 'sidecar.json', ns=(mtime, mtime))
    before = tree(norm)
    assert apply(norm, tmp_path / 'q') == 1
    assert json.loads(capsys.readouterr().out)['conflicts'] == [SOURCE_A]
    assert tree(norm) == before


def test_symlinked_build_is_not_a_twin(cache, tmp_path):
    """select ignores symlinked builds, so counting one would move a real build for nothing."""
    outside = build(tmp_path / 'elsewhere', SOURCE_B, NEW, 3_000)
    (cache / SOURCE_B / NEW).symlink_to(outside)
    assert apply(cache, tmp_path / 'q') == 0
    assert (cache / SOURCE_B / NEW).is_symlink()


def test_apply_needs_a_quarantine_outside_the_cache_and_refuses_the_private_vault(cache, tmp_path):
    """A quarantine inside the cache would recreate the twin; the vault is never read or written."""
    with pytest.raises(SystemExit):
        norm_twins.main(['--norm', str(cache), '--apply'])
    with pytest.raises(SystemExit):
        apply(cache, cache / 'q')
    with pytest.raises(SystemExit):
        norm_twins.main(['--norm', '/mnt/privatevault/x'])


def two_repairable_buckets(cache):
    build(cache, SOURCE_B, NEW, 2_000)  # SOURCE_B now has a twin too


def test_a_later_collision_is_found_before_the_first_move(cache, tmp_path):
    """Moving bucket A and then hitting B's existing target left A moved with no record and no way to undo."""
    two_repairable_buckets(cache)
    quarantine = tmp_path / 'q'
    (quarantine / SOURCE_B / NEW).mkdir(parents=True)
    before = tree(cache)
    with pytest.raises(SystemExit, match='already exists'):
        apply(cache, quarantine)
    assert tree(cache) == before
    assert not list(quarantine.glob('moved-*'))


@pytest.mark.parametrize('escape', ['vault', 'elsewhere'])
def test_a_symlinked_quarantine_bucket_cannot_redirect_a_move(cache, tmp_path, monkeypatch, escape):
    """quarantine/<bucket> -> vault made mkdir and the move write into the vault; only the root was checked."""
    vault = tmp_path / 'vault'
    vault.mkdir()
    monkeypatch.setattr(norm_twins, 'PRIVATE', vault)
    target_dir = vault if escape == 'vault' else tmp_path / 'elsewhere'
    target_dir.mkdir(exist_ok=True)
    quarantine = tmp_path / 'q'
    quarantine.mkdir()
    (quarantine / SOURCE_A).symlink_to(target_dir)
    before = tree(cache)
    with pytest.raises(SystemExit, match='refused'):
        apply(cache, quarantine)
    assert tree(cache) == before
    assert list(target_dir.iterdir()) == []


def test_a_failed_move_is_rolled_back_and_the_record_says_so(cache, tmp_path, monkeypatch):
    """A failure on the second move must not leave the first build moved; the record exists before any move."""
    two_repairable_buckets(cache)
    quarantine = tmp_path / 'q'
    real_rename, calls = os.rename, []

    def flaky(src, dst, *a, **k):
        calls.append(src)
        if len(calls) == 1:  # the record is written before the first move
            (record,) = quarantine.glob('moved-*.json')
            planned = json.loads(record.read_text())
            assert planned['status'] == 'in-progress' and len(planned['moves']) == 2
        if len(calls) == 2:
            raise OSError('disk full')
        return real_rename(src, dst, *a, **k)

    monkeypatch.setattr(norm_twins.os, 'rename', flaky)
    before = tree(cache)
    with pytest.raises(SystemExit, match='undone'):
        apply(cache, quarantine)
    assert tree(cache) == before
    (record,) = quarantine.glob('moved-*.json')
    doc = json.loads(record.read_text())
    assert doc['status'] == 'rolled-back' and not any(m['moved'] for m in doc['moves'])
    assert [p.name for p in quarantine.iterdir()] == [record.name]  # created bucket folders were removed again
