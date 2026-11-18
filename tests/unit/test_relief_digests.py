"""Test digest receipts, package provenance, and malformed archive refusal offline."""
import gzip
import hashlib
from io import BytesIO
import json
import struct

import pytest

from scripts.relief import region as cli
from skippercast.relief import digests, package, receipts
from tests._support import ROOT

REGION = 'morro-bay'


def archive(payload=b'tile-one'):
    # One z8 x0 y0 tile: ID 21845, one tile, data length, offset 0 (+1).
    directory = gzip.compress(b'\x01\xd5\xaa\x01\x01' + bytes([len(payload), 1]), mtime=0)
    metadata = gzip.compress(b'{}', mtime=0)
    data_offset = 127 + len(directory) + len(metadata)
    end = data_offset + len(payload)
    header = b'PMTiles\x03' + struct.pack('<11Q', 127, len(directory), 127 + len(directory), len(metadata),
                                         end, 0, data_offset, len(payload), 1, 1, 1)
    return header + bytes([1, 2, 1, 2, 8, 8]) + bytes(25) + directory + metadata + payload


def run(region, stage, *args):
    return cli.main([stage, '--out', str(region.out_root), '--region', region.id, *map(str, args)])


def produce(region, payload):
    def build(out):
        (out / 'relief.pmtiles').write_bytes(payload)

    assert receipts.run_stage(receipts.StageRun(
        region, 'tiles', build, 'a' * 64,
        scope='public', target='layers/public', plan=receipts.Plan(params={'archive': receipts.sha256_bytes(payload)}),
    )).state == 'ok'


def test_digest_stage_binds_archive_and_packages_all_outputs(tmp_path, monkeypatch, capsys):
    region = receipts.Region(tmp_path / 'out', REGION)
    assert run(region, 'digests') == 3  # no current tile producer
    produce(region, archive())
    assert run(region, 'digests') == 0
    built = receipts.check(region, 'digests')
    assert built.done and built.receipt is not None
    doc = built.receipt
    tile_receipt = receipts.check(region, 'tiles', 'public').receipt
    assert tile_receipt is not None
    assert doc['upstream'] == [{'stage': 'tiles', 'scope': 'public',
                               'generation': tile_receipt['generation']}]
    assert doc['inputs'] == [{'path': package.ARCHIVE, 'role': 'relief_archive',
                              'sha256': receipts.sha256_bytes(archive())}]
    root = region.dir / package.DIGEST_ROOT
    chunk = root.parent / '8/0_0.json'
    assert json.loads(chunk.read_bytes()) == [[0, 0, hashlib.sha256(b'tile-one').hexdigest()]]
    assert json.loads(root.read_bytes()) == {'chunks': {'8/0_0.json': receipts.sha256_file(chunk)}}
    assert run(region, 'digests') == 0
    assert '[digests] DONE' in capsys.readouterr().out

    # The real package gate requires every digest file to come from a current
    # receipt and includes the digest root's file hash in the release.
    config = tmp_path / 'repo-config'
    rights = {'public_display': 'allowed', 'license': 'public-domain'}
    for name, data in {
        'catalog/sources.json': {'sources': [{'id': 'synthetic-grid', 'review_status': 'approved', 'rights': rights}]},
        f'regions/{REGION}/region.json': {'bounds': [-122, 34, -120, 36]},
        'catalog/relief/pointer.schema.json': json.loads((ROOT / 'catalog/relief/pointer.schema.json').read_bytes()),
    }.items():
        path = config / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(receipts.canonical(data))
    monkeypatch.setattr(package, 'repo_root', lambda: config)
    manifest = tmp_path / 'manifest.json'
    manifest.write_bytes(receipts.canonical({
        'region': REGION, 'bounds': [-121.3, 35.1, -121, 35.5], 'minzoom': 8, 'maxzoom': 8,
        'layer_paths': [package.ARCHIVE, *(r['path'] for r in doc['outputs'])],
        'sources': [{'id': 'synthetic-grid', 'attribution': 'Synthetic survey', 'rights_class': 'public',
                     'label': 'estimated', 'vertical_datum': 'NAVD88', 'survey_dates': ['2020'], 'rights': rights}],
        'detail_summary': {'mask': 'transparent-nodata', 'depth_bands': [
            {'source_id': 'synthetic-grid', 'min_depth_m': 0, 'max_depth_m': 20, 'resolution_m': 2, 'support_class': 2},
        ]},
        'native_support_by_zoom': {'8': {'tiles': 1, 'limit_m': 91.44, 'sources': []}},
    }))
    assert run(region, 'package', '--manifest', manifest, '--upstream', 'tiles:public', '--upstream', 'digests') == 0
    release_receipt = receipts.check(region, 'package')
    assert release_receipt.done and release_receipt.receipt is not None
    release = json.loads((region.dir / release_receipt.receipt['outputs'][0]['path']).read_bytes())
    assert release['digest_root_sha256'] == receipts.sha256_file(root)
    assert [row for row in release['layers'] if row['path'] != package.ARCHIVE] == doc['outputs']

    chunk.write_bytes(b'[]')
    assert receipts.check(region, 'digests').state == 'unproved'
    assert receipts.check(region, 'package').state == 'stale'
    assert run(region, 'digests') == 0
    assert receipts.sha256_file(root) == release['digest_root_sha256']
    produce(region, archive(b'tile-two'))
    assert not receipts.check(region, 'digests').done
    assert run(region, 'digests') == 0
    rebuilt = receipts.check(region, 'digests')
    assert rebuilt.done and rebuilt.receipt is not None
    assert rebuilt.receipt['generation'] != doc['generation']
    assert json.loads(chunk.read_bytes()) == [[0, 0, hashlib.sha256(b'tile-two').hexdigest()]]


@pytest.mark.parametrize(('mutate', 'message'), [
    (lambda b: b[:7] + b'\x02' + b[8:], 'PMTiles v3'),
    (lambda b: b[:-1], 'section is outside'),
    (lambda b: b[:98] + b'\x03' + b[99:], 'compression not supported'),
    (lambda b: b[:72] + struct.pack('<Q', 2) + b[80:], 'addressed tile count'),
    (lambda b: b[:101] + b'\x12' + b[102:], 'zooms above z17'),
])
def test_malformed_archive_never_writes_index(tmp_path, mutate, message):
    with pytest.raises(digests.DigestError, match=message):
        digests.write_index(BytesIO(mutate(archive())), tmp_path)
    assert not list(tmp_path.iterdir())


def test_failed_archive_retains_failed_attempt_without_publishing_index(tmp_path):
    region = receipts.Region(tmp_path, REGION)
    produce(region, archive()[:-1])
    assert run(region, 'digests') == 1
    failed = receipts.read_receipt(region.receipt_path('digests'))
    assert failed is not None
    assert failed['status'] == 'failed' and 'section is outside' in failed['error']
    assert (region.dir / failed['failed_dir']).is_dir()
    assert not (region.dir / package.DIGEST_ROOT).exists()
