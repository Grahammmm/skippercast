"""Offline checks at the transfer command's entry point."""

import hashlib
import json
import shutil

import pytest

from scripts.relief import run_input_transfer


def sha256(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def transfer(tmp_path):
    source = tmp_path / 'origin'
    destination = tmp_path / 'destination'
    source.mkdir()
    destination.mkdir()
    pins, copies = {}, {}
    for role, data in {'coarse': b'\xff\x00grid\r\n', 'water': b'{"type":"FeatureCollection","features":[]}'}.items():
        original = source / f'{role}.source'
        original.write_bytes(data)
        copy = destination / f'{role}.copy'
        shutil.copyfile(original, copy)
        pins[role] = {'path': str(original), 'sha256': sha256(data)}
        copies[role] = copy
    record = tmp_path / 'run-inputs.json'
    record.write_text(json.dumps({
        'schema': 'sc-run-inputs/1', 'region': 'central', 'inputs': pins,
        'coarse_source': 'synthetic', 'coarse_date': None, 'norm': 'unattested-cache',
    }), encoding='utf-8')
    return record, pins, copies, source


def check(record, copies):
    argv = ['central', '--inputs', str(record)]
    for role, path in copies.items():
        argv.extend(['--copy', role, str(path)])
    return run_input_transfer.main(argv)


def test_byte_identical_copies_pass_across_roots(transfer, capsys):
    # A verifier that resolves recorded paths or requires the same filenames fails this move.
    record, _, copies, source = transfer
    source.rename(source.with_name('moved-origin'))
    assert check(record, copies) == 0
    assert capsys.readouterr().out.splitlines() == ['coarse: match', 'water: match']


def test_one_byte_corruption_fails_even_when_original_matches(transfer, capsys):
    # Existence, size, or hashing the still-valid source instead would miss the corruption.
    record, pins, copies, _ = transfer
    damaged = b'\xfe\x00grid\r\n'
    copies['coarse'].write_bytes(damaged)
    assert check(record, copies) == 1
    assert capsys.readouterr().out.splitlines() == [
        f"coarse: mismatch (expected {pins['coarse']['sha256']}, got {sha256(damaged)})",
        'water: match',
    ]


@pytest.mark.parametrize('supply_missing_path', [False, True], ids=['no-role-binding', 'no-local-file'])
def test_missing_pinned_role_fails(transfer, capsys, supply_missing_path):
    # Checking only supplied roles, or falling back to the source, would conceal an incomplete copy.
    record, _, copies, source = transfer
    if supply_missing_path:
        copies['water'] = source.parent / 'nonexistent'
        detail = 'local copy is absent or not a regular file'
    else:
        copies.pop('water')
        detail = 'no local copy supplied'
    assert check(record, copies) == 1
    assert capsys.readouterr().out.splitlines() == ['coarse: match', f'water: missing ({detail})']


def test_local_copy_without_a_role_pin_is_unverifiable(transfer, capsys):
    # A readable extra file, even one matching another role's digest, is not an attested copy.
    record, _, copies, _ = transfer
    copies['basemap'] = copies['coarse']
    assert check(record, copies) == 1
    assert capsys.readouterr().out.splitlines() == [
        'basemap: unverifiable (no recorded SHA-256)', 'coarse: match', 'water: match',
    ]
