"""RF1831-7: a refused slim-file rebuild leaves the previous local slim files untouched."""
import gzip
import hashlib
import json
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
