"""F19-16: a failed rebuild must not put new pixels beside old metadata."""
import hashlib
import json
from pathlib import Path

import pytest


@pytest.mark.gis
@pytest.mark.parametrize('failure', ['malformed', 'no-offset', 'install'])
def test_failed_rebuild_preserves_the_identifiable_pair(tmp_path, monkeypatch, failure):
    from scripts import build_chlorophyll_layer as cl

    monkeypatch.setitem(cl.SECTORS, 'synthetic', (0, 0, 1, 1))
    receipt = tmp_path / 'receipt.json'
    out = tmp_path / 'synthetic'
    png, metadata = out / 'chlorophyll.png', out / 'chlorophyll.json'

    def build(value, sample_at):
        receipt.write_text(json.dumps({'sample_at': sample_at, 'samples': [
            {'latitude': lat, 'longitude': lon, 'chlorophyll': value}
            for lat in (0, 1) for lon in (0, 1)
        ]}))
        return cl.build('synthetic', tmp_path, receipt=receipt, px_m=100_000)

    first, second = '2026-01-01T00:00:00Z', '2026-01-02T00:00:00Z'
    build(0.1, first)
    original = png.read_bytes(), metadata.read_bytes()

    def refuse_metadata_install(path, dest):
        if Path(dest) == metadata:
            raise OSError('synthetic metadata install failure')
        return replace(path, dest)

    replace = Path.replace
    with monkeypatch.context() as m:
        if failure == 'install':
            m.setattr(Path, 'replace', refuse_metadata_install)
            with pytest.raises(OSError, match='synthetic metadata install failure'):
                build(8.0, second)
        else:
            invalid = 'not-a-timestamp' if failure == 'malformed' else second.removesuffix('Z')
            with pytest.raises(ValueError):
                build(8.0, invalid)

    # Check exact bytes, not just that both files still exist. The old writer
    # put the second render on disk before the timestamp could be rejected.
    assert (png.read_bytes(), metadata.read_bytes()) == original
    assert {entry.name for entry in out.iterdir()} == {png.name, metadata.name}
    old_meta = json.loads(original[1])
    assert old_meta['sample_at'] == first
    assert old_meta['image']['sha256'] == hashlib.sha256(original[0]).hexdigest()

    build(8.0, second)
    new_png = png.read_bytes()
    new_meta = json.loads(metadata.read_bytes())
    assert original[0].startswith(b'\x89PNG\r\n\x1a\n')
    assert new_png != original[0]
    assert new_meta['sample_at'] == second
    assert new_meta['image']['sha256'] == hashlib.sha256(new_png).hexdigest()
