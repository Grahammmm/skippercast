"""F10-14: a shared shard costs one decode, never a skipped integrity check."""
from collections import Counter
import json
from unittest.mock import patch

import pytest

from skippercast.pipeline import verification_archive as archive

NOW = 1790092800
REGION = 'test-region'
FORECASTS = [{'id': 'f', 'station': 'synthetic', 'model': 'synthetic', 'time': NOW, 'cycle': NOW - 3600}]
OBSERVATIONS = [{'id': 'o', 'station': 'synthetic', 'time': NOW}]


@pytest.mark.parametrize('case', ['same-root', 'copied', 'prune', 'checksum', 'missing', 'metadata', 'late-checksum'])
def test_verification_write_prune_shares_only_valid_immutable_shards(tmp_path, case):
    # Use two actual shard kinds and leave a managed orphan: a no-op prune would
    # otherwise look like a successful fail-closed pruning test.
    first = archive.write_archive(tmp_path, REGION, FORECASTS, OBSERVATIONS, NOW)
    paths = {entry['path'] for entry in first['shards']}
    shard = tmp_path / first['shards'][0]['path']
    orphan = shard.with_name('0' * 64 + '.json.gz')
    destination = tmp_path / 'copy' if case == 'copied' else tmp_path

    def damage():
        data = shard.read_bytes()
        shard.write_bytes(bytes([data[0] ^ 1]) + data[1:])

    if case in ('same-root', 'copied', 'prune'):
        if case == 'prune':
            archive.write_archive(tmp_path, REGION, FORECASTS, OBSERVATIONS, NOW + 1)
        if case == 'copied':
            orphan = destination / orphan.relative_to(tmp_path)
            orphan.parent.mkdir(parents=True)
        orphan.touch()
        with patch.object(archive, '_decode', wraps=archive._decode) as decode:
            if case == 'prune':
                assert archive.prune_archive(tmp_path) == 1
            else:
                archive.write_archive(destination, REGION, FORECASTS, OBSERVATIONS, NOW + 1, tmp_path)
        assert not orphan.exists()
        assert Counter(call.args[-1]['path'] for call in decode.call_args_list) == dict.fromkeys(paths, 1)
        for name in ('verification-state.json', 'verification-state.previous.json'):
            restored = archive.load_archive(destination, REGION, required=True, manifest_name=name)
            assert (restored['forecasts'], restored['observations']) == (FORECASTS, OBSERVATIONS)
        return

    archive.write_archive(tmp_path, REGION, FORECASTS, OBSERVATIONS, NOW + 1)
    orphan.touch()
    if case == 'late-checksum':
        # Corrupt the previous blob after it has been decoded but before prune.
        # The new empty manifest does not rewrite/check this blob in its writer.
        write_generation = archive._write_generation

        def damage_after_validation(*args, **kwargs):
            damage()
            return write_generation(*args, **kwargs)

        with patch.object(archive, '_write_generation', side_effect=damage_after_validation):
            with pytest.raises(ValueError, match='checksum'):
                archive.write_archive(tmp_path, REGION, [], [], NOW + 2)
    else:
        if case == 'missing':
            shard.unlink()
            reason = 'Missing'
        elif case == 'checksum':
            damage()
            reason = 'checksum'
        else:
            previous = tmp_path / 'verification-state.previous.json'
            manifest = json.loads(previous.read_bytes())
            manifest['shards'][0]['raw_sha256'] = '0' * 64
            previous.write_text(json.dumps(manifest), encoding='utf-8')
            reason = 'checksum|metadata'
        with pytest.raises(ValueError, match=reason):
            archive.prune_archive(tmp_path)
    assert orphan.exists()
