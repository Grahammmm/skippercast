"""Offline contract tests for census binding and the unchanged select consumer."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from skippercast.relief import census_bind, receipts
from tests._support import NOW, ROOT


REGION = 'test-coast'
# Noncanonical formatting and CRLF expose any reserialization of source bytes.
DATA = b'{\r\n "summary": {"region": "test-coast"}, "files": [{"path": "not-local.tif"}]\r\n}\r\n'
SHA = hashlib.sha256(DATA).hexdigest()


def arguments(out, source, sha=SHA, region=REGION):
    return ['--region', region, '--out', str(out), '--from', str(source), '--sha256', sha]


@pytest.fixture
def paths(tmp_path):
    tmp = tmp_path.resolve()  # select refuses symlinked ancestors (including a scratch alias).
    source = tmp / 'admitted.json'
    source.write_bytes(DATA)
    return source, tmp / 'out'


def snapshot(root):
    # Include mtimes and inode numbers to detect replace-with-identical-bytes.
    return {p.relative_to(root): (p.lstat().st_mtime_ns, p.lstat().st_ino,
                                 p.readlink() if p.is_symlink() else p.read_bytes() if p.is_file() else None)
            for p in [root, *root.rglob('*')]}


def pin(out, *, sha=SHA, path='census.json'):
    producer = out / REGION / 'stages/census.json'
    producer.parent.mkdir(parents=True, exist_ok=True)
    producer.write_text(json.dumps({'stage': 'census', 'scope': 'local', 'region': REGION, 'status': 'ok',
                                    'outputs': [{'path': str(path), 'sha256': sha, 'bytes': len(DATA)}]}))
    return producer


@pytest.mark.parametrize('absolute', [False, True], ids=['C1: relative producer pin', 'C1: absolute producer pin'])
def test_C1_copies_bytes_before_recording_provenance(paths, monkeypatch, absolute):
    """C1: Both producer pin forms work; copy must be an atomic rename before the record."""
    source, out = paths
    census = out / REGION / 'census.json'
    producer = pin(out, path=census if absolute else 'census.json')
    binding = producer.with_name('census_bind.json')
    original_producer = snapshot(producer)
    monkeypatch.chdir(source.parent)
    monkeypatch.setattr(receipts, 'utc_now', lambda: NOW)
    replace = Path.replace
    moves = []

    def inspect_move(temp, target):
        if target == census:
            assert not target.exists()
            assert temp.parent == census.parent
            assert temp.read_bytes() == DATA
        if target == binding:
            assert census.read_bytes() == DATA
        moves.append(target)
        return replace(temp, target)

    monkeypatch.setattr(Path, 'replace', inspect_move)
    assert census_bind.main(arguments(out, source.name, SHA.upper())) == 0
    assert moves == [producer.parent / '.census_bind.pending', census, binding]
    assert census.read_bytes() == DATA
    assert json.loads(binding.read_bytes()) == {'region': REGION, 'source_path': source.name,
                                                'source_sha256': SHA, 'size': len(DATA),
                                                'time': '2026-09-28T12:00:00Z'}
    assert snapshot(producer) == original_producer
    assert sorted(str(p.relative_to(out / REGION)) for p in (out / REGION).rglob('*')) == [
        'census.json', 'stages', 'stages/census.json', 'stages/census_bind.json']


@pytest.mark.gis
def test_C1_region_dispatch_and_unchanged_select_plan(paths):
    """C1: region.py dispatches the new command; select pins the original bytes without an upstream receipt."""
    from skippercast.relief import select

    source, out = paths
    invoke = subprocess.run([sys.executable, str(ROOT / 'scripts/relief/region.py'),
                             'census-bind', *arguments(out, source)], capture_output=True, text=True, check=False)
    assert (invoke.returncode, invoke.stdout, invoke.stderr) == (0, '', '')
    census = out / REGION / 'census.json'
    args = ['--region', REGION, '--out', str(out), '--cache', str(source.parent / 'unused-cache')]
    for flag, doc in [('region-config', {'bounds': [-123, 35, -122, 36]}),
                      ('registry', {'sources': []}), ('provenance', {'source_rows': []})]:
        path = source.parent / f'{flag}.json'
        path.write_text(json.dumps(doc))
        args.extend([f'--{flag}', str(path)])
    assert select.main(args) == 0
    selected = json.loads((out / REGION / 'stages/select.json').read_bytes())
    assert [i for i in selected['inputs'] if i['role'] == 'census'] == [
        {'path': 'census.json', 'sha256': SHA, 'role': 'census'}]
    assert selected['upstream'] == []
    assert census.read_bytes() == DATA
    assert not (out / REGION / 'stages/census.json').exists()


@pytest.mark.parametrize('failure', ['census', 'binding'])
def test_failed_write_recovers_on_retry(paths, monkeypatch, failure):
    source, out = paths
    census = out / REGION / 'census.json'
    binding = out / REGION / 'stages/census_bind.json'
    write = census_bind._write_atomic

    def fail_write(path, data):
        if path == (census if failure == 'census' else binding):
            raise OSError('disk full')
        write(path, data)

    with monkeypatch.context() as patch:
        patch.setattr(census_bind, '_write_atomic', fail_write)
        assert census_bind.main(arguments(out, source)) == 1
    assert census.exists() == (failure == 'binding')
    assert not binding.exists()
    alternate = source.with_name('retry.json')
    alternate.write_bytes(DATA)
    assert census_bind.main(arguments(out, alternate)) == 0
    assert census.read_bytes() == DATA
    record = json.loads(binding.read_bytes())
    assert record['source_sha256'] == SHA
    assert record['source_path'] == str(source)
    before = snapshot(out)
    assert census_bind.main(arguments(out, alternate)) == 0
    assert snapshot(out) == before


@pytest.mark.parametrize('prior_bind', [False, True], ids=['C2: existing copy', 'C2: repeat bind'])
def test_C2_identical_destination_is_a_no_op(paths, prior_bind):
    """C2: Idempotency must not rewrite data or refresh/backfill provenance."""
    source, out = paths
    census = out / REGION / 'census.json'
    if prior_bind:
        assert census_bind.main(arguments(out, source)) == 0
    else:
        census.parent.mkdir(parents=True)
        census.write_bytes(DATA)
    alternate = source.with_name('identical-elsewhere.json')
    alternate.write_bytes(DATA)
    before = snapshot(source.parent)
    assert census_bind.main(arguments(out, alternate)) == 0
    assert snapshot(source.parent) == before


@pytest.mark.parametrize(('data', 'sha', 'error'), [
    pytest.param(DATA, '0' * 64, 'source SHA-256 mismatch', id='C2: mismatching pin'),
    pytest.param(DATA, 'f' * 63, 'expected a 64-digit hexadecimal SHA-256', id='C2: malformed pin'),
    pytest.param(b'not JSON', None, 'source is not valid JSON', id='C2: non-JSON'),
    pytest.param(b'{"summary":{"region":"test-coast"},"files":[],"extra":NaN}', None,
                 'source is not valid JSON', id='C2: non-JSON constant'),
    pytest.param(DATA.replace(b'test-coast', b'elsewhere'), None, 'census region mismatch', id='C2: wrong region'),
    pytest.param(b'{}', None, 'census requires summary.region', id='C2: no region identity'),
    pytest.param(b'{"summary":{"region":"test-coast"},"files":{}}', None,
                 'census requires a files list of rows with paths', id='C2: files not a list'),
    pytest.param(b'{"summary":{"region":"test-coast"},"files":[{}]}', None,
                 'census requires a files list of rows with paths', id='C2: missing row path'),
])
def test_C2_refuses_invalid_source_before_creating_out(paths, capsys, data, sha, error):
    """C2: Validation must run on fresh OUT before the first mkdir/write."""
    source, out = paths
    source.write_bytes(data)
    before = snapshot(source.parent)
    assert census_bind.main(arguments(out, source, sha or hashlib.sha256(data).hexdigest())) == 1
    assert capsys.readouterr() == ('', f'census-bind: {error}\n')
    assert snapshot(source.parent) == before


@pytest.mark.parametrize('conflict', [
    'destination', 'producer with no census', 'producer with identical census', 'pin for another path', 'unreadable pin',
], ids=lambda conflict: f'C2: {conflict}')
def test_C2_refuses_conflicts_before_writing(paths, capsys, conflict):
    """C2: A conflicting producer pin wins even over an identical destination."""
    source, out = paths
    census = out / REGION / 'census.json'
    if conflict == 'destination':
        census.parent.mkdir(parents=True)
        census.write_bytes(DATA.rstrip())  # semantically identical JSON, different bytes
        error = 'destination census has different bytes'
    else:
        error = 'census receipt does not pin this region census'
        if conflict == 'pin for another path':
            pin(out, path=source)
        elif conflict == 'unreadable pin':
            pin(out).write_bytes(b'[]')
            error = 'census.json: not a JSON object'
        else:
            pin(out, sha='0' * 64)
            if conflict == 'producer with identical census':
                census.write_bytes(DATA)
    before = snapshot(source.parent)
    assert census_bind.main(arguments(out, source)) == 1
    assert capsys.readouterr() == ('', f'census-bind: {error}\n')
    assert snapshot(source.parent) == before


def test_C3_external_paths_are_not_followed(paths, monkeypatch):
    """C3: Embedded paths are not read; the source is untouched outside OUT/<id>."""
    source, out = paths
    decoy = source.with_name('not-local.tif')
    decoy.write_bytes(b'not part of the binding')
    monkeypatch.chdir(source.parent)
    before = snapshot(source), snapshot(decoy)
    read = Path.read_bytes
    seen = []

    def watch_reads(path):
        seen.append(path)
        return read(path)

    with monkeypatch.context() as patch:
        patch.setattr(Path, 'read_bytes', watch_reads)
        assert census_bind.main(arguments(out, source)) == 0
    assert set(seen) == {source, out / REGION / 'census.json'}  # absent destination is checked, not read
    assert (snapshot(source), snapshot(decoy)) == before
    assert sorted(p.name for p in source.parent.iterdir()) == [source.name, decoy.name, out.name]
    assert sorted(p.name for p in out.iterdir()) == [REGION]
    assert sorted(p.name for p in (out / REGION / 'stages').iterdir()) == ['census_bind.json']


@pytest.mark.parametrize('relative', ['.', 'stages', 'stages/census.json', 'census.json', 'stages/census_bind.json'],
                         ids=lambda name: f'C3: symlink at {name}')
def test_C3_refuses_output_symlinks(paths, capsys, relative):
    """C3: Output aliases must not send reads/writes outside the region directory."""
    source, out = paths
    path = out / REGION / relative
    path.parent.mkdir(parents=True)
    path.symlink_to(source.parent / 'external')
    before = snapshot(source.parent)
    assert census_bind.main(arguments(out, source)) == 1
    assert capsys.readouterr() == ('', f'census-bind: symlink refused: {path}\n')
    assert snapshot(source.parent) == before


def test_C3_refuses_source_at_binding_record_path(paths, capsys):
    """C3: The audit record must not overwrite its own source file."""
    _, out = paths
    source = out / REGION / 'stages/census_bind.json'
    source.parent.mkdir(parents=True)
    source.write_bytes(DATA)
    before = snapshot(out)
    assert census_bind.main(arguments(out, source)) == 1
    assert capsys.readouterr() == ('', 'census-bind: source cannot also be the binding record\n')
    assert snapshot(out) == before


def test_C3_refuses_region_traversal(paths, capsys):
    """C3: A region ID cannot introduce another destination root."""
    source, out = paths
    before = snapshot(source.parent)
    assert census_bind.main(arguments(out, source, region='../escape')) == 1
    assert capsys.readouterr() == ('', "census-bind: invalid region id '../escape'\n")
    assert snapshot(source.parent) == before
