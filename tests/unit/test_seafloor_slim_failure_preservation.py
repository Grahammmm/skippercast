"""RF1831-7: a refused slim-file rebuild leaves the previous local slim files untouched."""
import errno
import gzip
import hashlib
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from skippercast.seafloor import slim

VERDICT = {'inside': False, 'name': None, 'distanceM': None, 'screened': True}
KW = dict(region='synthetic', expires_at='2030-01-01T00:00:00+00:00', export_sha256='a' * 64,
          protected={'fingerprint': 'ps2-x', 'version': 2})


def feat(i, **extra):
    return {'type': 'Feature', 'geometry': None,
            'properties': {'id': f'synthetic-{i}', 'tier': 2, 'protected_place': dict(VERDICT), **extra}}


def snapshot(folder):
    return {p.name: p.read_bytes() for p in sorted(folder.iterdir())}


def seeded(tmp_path):
    first = slim.write_slim(tmp_path, export_features=[feat(1)], **KW)
    other = tmp_path / 'habitat-slim-0000000000000000.geojson.gz'
    other.write_bytes(b'older')
    (tmp_path / 'sentinel.txt').write_text('keep')
    return first, snapshot(tmp_path)


def test_missing_verdict_preserves_previous_slim_files(tmp_path):
    _, before = seeded(tmp_path)
    bad = feat(2)
    del bad['properties']['protected_place']
    with pytest.raises(ValueError, match='verdict'):
        slim.write_slim(tmp_path, export_features=[feat(1), bad], **KW)
    assert snapshot(tmp_path) == before


def test_size_refusal_preserves_previous_slim_files(tmp_path):
    _, before = seeded(tmp_path)
    with patch.object(slim, 'SLIM_MAX_BYTES', 1), pytest.raises(ValueError, match='budget'):
        slim.write_slim(tmp_path, export_features=[feat(2)], **KW)
    assert snapshot(tmp_path) == before


def test_serialization_refusal_preserves_previous_slim_files(tmp_path):
    _, before = seeded(tmp_path)
    with pytest.raises(TypeError):
        slim.write_slim(tmp_path, export_features=[feat(2, id=object())], **KW)
    assert snapshot(tmp_path) == before


def _partial_then_enospc(self, data):
    """A disk-full write: some bytes reach the file, then the write fails."""
    with open(self, 'wb') as handle:
        handle.write(data[:5])
    raise OSError(errno.ENOSPC, 'No space left on device')


@pytest.mark.parametrize('ident', [1, 2], ids=['same-bytes-same-name', 'new-bytes-new-name'])
def test_failed_replacement_write_preserves_previous_slim_files(tmp_path, ident):
    # Contract: a write error on the replacement keeps every earlier slim file byte-for-byte and leaves no temp file.
    # Catches: clearing stale files before the replacement is written (the manifest then names a deleted file), and a
    # half-written replacement left behind. ident 1 rebuilds the same content, so the new name equals the old one.
    first, before = seeded(tmp_path)
    with patch.object(Path, 'write_bytes', _partial_then_enospc), pytest.raises(OSError) as err:
        slim.write_slim(tmp_path, export_features=[feat(ident)], **KW)
    assert err.value.errno == errno.ENOSPC
    assert (tmp_path / first['slim_file']).read_bytes() == before[first['slim_file']]
    assert snapshot(tmp_path) == before


def test_failed_install_preserves_previous_slim_files(tmp_path):
    # Catches: a failure between the temp write and the install (os.replace) that strands the temp file or has already
    # removed the older files.
    _, before = seeded(tmp_path)
    with patch.object(os, 'replace', side_effect=OSError(errno.EIO, 'I/O error')), pytest.raises(OSError):
        slim.write_slim(tmp_path, export_features=[feat(2)], **KW)
    assert snapshot(tmp_path) == before


def test_stale_files_are_removed_only_after_the_replacement_is_installed(tmp_path):
    # Catches: stale cleanup moved back before the install, or the install skipped (a plain in-place write).
    first, _ = seeded(tmp_path)
    seen = {}
    real_replace = os.replace

    def spy(src, dst):
        seen['stale_present_at_install'] = sorted(p.name for p in tmp_path.glob('habitat-slim*.geojson.gz'))
        real_replace(src, dst)
    with patch.object(os, 'replace', spy):
        fields = slim.write_slim(tmp_path, export_features=[feat(2)], **KW)
    assert first['slim_file'] in seen['stale_present_at_install']
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([fields['slim_file'], 'sentinel.txt'])


def test_rebuild_to_the_same_name_keeps_the_file_and_clears_older_ones(tmp_path):
    # Catches: cleanup that deletes the freshly installed file when the new content hash equals the old one.
    first, _ = seeded(tmp_path)
    again = slim.write_slim(tmp_path, export_features=[feat(1)], **KW)
    assert again == first
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([first['slim_file'], 'sentinel.txt'])
    assert gzip.decompress((tmp_path / first['slim_file']).read_bytes())


def test_pass_through_write_control_still_replaces_the_files(tmp_path):
    # Control: the same patch point with a healthy write is a normal rebuild, so the failures above come from the
    # injected error and not from the harness.
    first, _ = seeded(tmp_path)
    real = Path.write_bytes
    with patch.object(Path, 'write_bytes', lambda self, data: real(self, data)):
        fields = slim.write_slim(tmp_path, export_features=[feat(3)], **KW)
    assert fields['slim_file'] != first['slim_file']
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([fields['slim_file'], 'sentinel.txt'])


def test_success_and_intentional_absence_keep_cleanup_contract(tmp_path):
    first, _ = seeded(tmp_path)
    fields = slim.write_slim(tmp_path, export_features=[feat(3)], **KW)
    packed = (tmp_path / fields['slim_file']).read_bytes()
    assert fields['slim_sha256'] == hashlib.sha256(packed).hexdigest()
    assert fields['slim_file'] != first['slim_file']
    assert packed == gzip.compress(gzip.decompress(packed), mtime=0)
    assert json.loads(gzip.decompress(packed))['features'][0]['properties']['id'] == 'synthetic-3'
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted([fields['slim_file'], 'sentinel.txt'])
    assert slim.write_slim(tmp_path, export_features=[feat(3)], **{**KW, 'protected': None}) == {}
    assert [p.name for p in tmp_path.iterdir()] == ['sentinel.txt']
    assert slim.write_slim(tmp_path, export_features=[], **KW) == {}
    fresh = tmp_path / 'fresh'
    fresh.mkdir()
    with patch.object(slim, 'SLIM_MAX_BYTES', 1), pytest.raises(ValueError):
        slim.write_slim(fresh, export_features=[feat(4)], **KW)
    assert list(fresh.iterdir()) == []
