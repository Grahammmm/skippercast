"""F20-04: archive private raw responses without widening the public projection."""
import os
from pathlib import Path

import pytest

from tests.contract.test_shore_habitat import importer, synthetic_bodies


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    root = tmp_path.resolve()
    monkeypatch.setattr(importer, 'ROOT', root)
    monkeypatch.chdir(root)
    return root


@pytest.mark.parametrize('case', ['served', 'client', 'catalog', 'outside', 'traversal',
                                  'linked-root', 'linked-parent', 'linked-leaf',
                                  'linked-file', 'hardlinked-file', 'shared-dir', 'served-alias', 'output-collision'])
def test_unsafe_save_is_refused_before_reading_either_source(checkout, monkeypatch, capsys, case):
    # A late or lexical-only check lets the source reader run (and may reach dist/ through an alias).
    served = checkout / 'dist'
    served.mkdir()
    sentinel = served / 'do-not-change.json'
    sentinel.write_bytes(b'SYNTHETIC-SENTINEL')
    private = checkout / 'var'
    if case != 'linked-root':
        private.mkdir(mode=0o700)
    destination = {
        'served': served / 'sources', 'client': served / 'client',
        'catalog': checkout / 'catalog/shore-habitat',
        'outside': checkout.parent / 'sources', 'traversal': private / '../dist/sources',
    }.get(case, private / 'sources')
    if case == 'linked-root':
        private.symlink_to(served, target_is_directory=True)
    elif case == 'linked-parent':
        (private / 'alias').symlink_to(served, target_is_directory=True)
        destination = private / 'alias/sources'
    elif case == 'linked-leaf':
        destination.symlink_to(served / 'not-created', target_is_directory=True)
    elif case in {'linked-file', 'hardlinked-file', 'shared-dir', 'served-alias'}:
        destination.mkdir(mode=0o700)
        raw = destination / 'ccc-access-points.json'
        if case == 'linked-file':
            raw.symlink_to(sentinel)
        elif case == 'hardlinked-file':
            os.link(sentinel, raw)
        elif case == 'shared-dir':
            destination.chmod(0o755)
        else:
            served.rename(checkout / 'original-dist')
            sentinel = checkout / 'original-dist' / sentinel.name
            served.symlink_to(private, target_is_directory=True)

    def unexpected_source(*args):
        pytest.fail('read a source before rejecting an unsafe save destination')

    monkeypatch.setattr(importer, 'download', unexpected_source)
    monkeypatch.setattr(importer, 'load_saved', unexpected_source)
    output = destination / 'receipts.json' if case == 'output-collision' else Path('output.geojson')
    for source_args in ([], ['--sources', 'offline']):
        assert importer.main(['--save-sources', str(destination), '--output', str(output), *source_args]) == 1
        assert '--save-sources' in capsys.readouterr().err
    assert not output.exists()
    assert sentinel.read_bytes() == b'SYNTHETIC-SENTINEL'


def test_owner_only_raw_save_can_rebuild_identical_public_bytes(checkout, monkeypatch):
    # Persist the real raw bytes and receipts, but expose only the reviewed projection.
    bodies, receipts = synthetic_bodies('2026-01-01T00:00:00Z')
    monkeypatch.setattr(importer, 'download', lambda region: (bodies, receipts))
    output = checkout / 'dist/regions/synthetic/shore-habitat.geojson'
    args = ['--output', str(output)]
    assert importer.main(['--save-sources', 'var/shore/snapshot', *args]) == 0
    private = checkout / 'var/shore/snapshot'
    raw = private / 'ccc-access-points.json'
    marker = b'SYNTHETIC-DESCRIPTION'
    assert raw.read_bytes() == bodies['access'] and marker in raw.read_bytes()
    assert private.stat().st_mode & 0o777 == 0o700
    assert {p.name for p in private.iterdir()} == {*importer.SOURCE_FILES.values(), 'receipts.json'}
    assert all(p.stat().st_mode & 0o777 == 0o600 for p in private.iterdir())
    public = output.read_bytes()
    assert b'Synthetic approach' in public
    assert all(marker not in p.read_bytes() for p in (checkout / 'dist').rglob('*') if p.is_file())
    assert importer.main(['--sources', str(private), *args]) == 0
    assert output.read_bytes() == public
