"""F20-02: terrain publication must honor all upstream pins before upload."""
from functools import partial
import hashlib
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from scripts.coast import publish_assets as pa


TILE = '/data/coast-wide/example.bin'
BODY = b'tile'
DIGEST = hashlib.sha256(BODY).hexdigest()
SOURCE = 'https://terrain.example.invalid/source'
CATALOG = [{'id': 'usgs-naip', 'review_status': 'approved', 'documentation_url': SOURCE,
            'rights': {'commercial_use': 'allowed'}}]


@pytest.fixture
def publisher(monkeypatch, tmp_path):
    def run(first, second, body=BODY):
        sources = {'sources': [{'url': SOURCE}]}
        documents = {
            pa.TERRAIN_INDEX[0]: {**sources, 'asset': first},
            pa.TERRAIN_INDEX[1]: {'asset': second},
            pa.TERRAIN_INDEX[2]: sources,
        }
        responses = {path: json.dumps(doc).encode() for path, doc in documents.items()}
        responses[TILE] = body
        requested = []

        def get(path, origin, headers=None):
            requested.append(path)
            return 200, {}, responses[path]

        upload = Mock()
        monkeypatch.setattr(pa, 'get', get)
        monkeypatch.setattr(pa, 'plan', partial(pa.plan, catalog=CATALOG))
        monkeypatch.setattr(pa, 'upload', upload)
        monkeypatch.setattr(pa, 'os', SimpleNamespace(environ={
            'CLOUDFLARE_API_TOKEN': 'synthetic', 'CLOUDFLARE_ACCOUNT_ID': 'synthetic',
        }))
        monkeypatch.setattr(pa, 'sys', SimpleNamespace(path=[]))
        monkeypatch.setitem(sys.modules, 'scripts.publish_r2', SimpleNamespace(client=Mock()))
        return partial(pa.main, ['--groups', 'terrain', '--out', str(tmp_path), '--upload']), requested, upload

    return run


@pytest.mark.parametrize('pin_first', [True, False], ids=['pin-before-bare', 'bare-before-pin'])
@pytest.mark.parametrize('body', [BODY, b'fake'], ids=['matching-bytes', 'changed-same-length-bytes'])
def test_shared_terrain_pin_survives_bare_reference(publisher, pin_first, body):
    # A later bare reference must not let different bytes acquire a new identity.
    pin = {'url': TILE, 'sha256': DIGEST, 'bytes': len(BODY)}
    first, second = (pin, TILE) if pin_first else (TILE, pin)
    main, requested, upload = publisher(first, second, body=body)
    if body != BODY:
        with pytest.raises(ValueError, match='example.bin: bytes differ from the upstream manifest'):
            main()
        assert TILE in requested
        upload.assert_not_called()
    else:
        assert main() == 0
        upload.assert_called_once()
        entry = json.loads(upload.call_args.args[-1])['objects'][TILE]
        assert (entry['sha256'], entry['bytes']) == (DIGEST, len(BODY))


@pytest.mark.parametrize('field,other', [('sha256', 'f' * 64), ('bytes', len(BODY) + 1)])
@pytest.mark.parametrize('same_index', [False, True], ids=['across-indexes', 'within-index'])
def test_conflicting_terrain_pins_refuse_before_asset_fetch(publisher, capsys, field, other, same_index):
    # Last-writer-wins is invalid both within an index and across indexes.
    pin = {'url': TILE, 'sha256': DIGEST, 'bytes': len(BODY)}
    conflict = {**pin, field: other}
    main, requested, upload = publisher(*(([pin, conflict], None) if same_index else (pin, conflict)))
    assert main() == 1
    assert f'REFUSED terrain: {TILE} has conflicting upstream {field} pins' in capsys.readouterr().out
    assert requested == pa.TERRAIN_INDEX
    upload.assert_not_called()


def test_size_only_pin_is_merged_with_digest(publisher):
    # The bytes match the digest but violate the independently declared size.
    main, _, upload = publisher({'url': TILE, 'bytes': len(BODY) + 1}, {'url': TILE, 'sha256': DIGEST})
    with pytest.raises(ValueError, match='example.bin: bytes differ from the upstream manifest'):
        main()
    upload.assert_not_called()


def test_copied_index_must_match_declared_size(publisher, capsys):
    # Re-pinning the exact downloaded index must not erase a declared size mismatch.
    copied = pa.TERRAIN_INDEX[2]
    data = json.dumps({'sources': [{'url': SOURCE}]}).encode()
    main, requested, upload = publisher(None, {'url': copied, 'sha256': hashlib.sha256(data).hexdigest(),
                                               'bytes': len(data) + 1})
    assert main() == 1
    assert f'REFUSED terrain: {copied} differs from the byte count' in capsys.readouterr().out
    assert requested == pa.TERRAIN_INDEX
    upload.assert_not_called()
