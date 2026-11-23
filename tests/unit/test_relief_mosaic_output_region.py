"""Bind the public mosaic receipt to the producer's emitted region."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.relief import region as cli
from skippercast.relief import mosaic, receipts


@pytest.mark.parametrize('emitted_segment', [
    pytest.param('morro-bay', id='wrong'),
    pytest.param(None, id='missing'),
    pytest.param('central-coast', id='matching'),
])
def test_public_mosaic_output_region(tmp_path, monkeypatch, emitted_segment):
    region = receipts.Region(tmp_path, 'central-coast')
    region.dir.mkdir()
    config = region.dir / 'region.json'
    config.write_text(json.dumps({'id': region.id}), encoding='utf-8')
    grid = region.dir / 'grid.tif'
    grid.write_bytes(b'fixture only')
    source = {'id': 'tiny-grid', 'rights_class': 'public', 'sha256': receipts.sha256_file(grid)}
    sources = region.dir / 'select' / 'sources.json'

    def select(out):
        (out / sources.name).write_text(json.dumps({
            'scope': 'public', 'sources': [dict(source, path=str(grid))],
        }), encoding='utf-8')

    assert receipts.run_stage(receipts.StageRun(region, 'select', select, '1' * 64)).state == 'ok'
    public_fields = {
        'schema_version': 1,
        'status': 'review_required',
        'region_sha256': receipts.sha256_file(config),
        'source_table_sha256': receipts.sha256_file(sources),
        'sources': [dict(source, code=1)],
    }
    manifest = dict(public_fields, sources=[dict(public_fields['sources'][0], path=str(grid),
                                                support_path=str(region.dir / 'mask.tif'))])
    if emitted_segment is not None:
        manifest['segment'] = emitted_segment
    raw_manifest = json.dumps(manifest).encode('utf-8')
    raster_names = ('elevation.tif', 'contributor.tif', 'support_count.tif')

    def run_coast_tool(argv, *, check):
        assert check and Path(argv[1]).name == 'coast_mosaic.py'
        out = Path(argv[argv.index('--output') + 1])
        out.mkdir()
        (out / 'manifest.json').write_bytes(raw_manifest)
        for name in raster_names:
            (out / name).write_bytes(b'fixture only')

    monkeypatch.setattr(mosaic, 'subprocess', SimpleNamespace(run=run_coast_tool))
    rc = cli.main(['mosaic', '--out', str(tmp_path), '--region', region.id,
                   '--scope', 'public', '--region-config', str(config)])
    doc = receipts.read_receipt(region.receipt_path('mosaic', 'public'))
    assert doc is not None
    target = region.dir / 'mosaic' / 'public'
    if emitted_segment != region.id:
        # A producer can exit zero and write all three rasters yet mislabel (or omit)
        # the segment. The valid input config and producer exit alone cannot seal it.
        assert (rc, doc['status'], target.exists()) == (1, 'failed', False)
        assert doc['outputs'] == []
        assert 'mosaic manifest segment' in doc['error']
        failed = region.resolve(doc['failed_dir'])
        assert (failed / 'manifest.json').read_bytes() == raw_manifest
    else:
        assert (rc, doc['status']) == (0, 'ok')
        assert receipts.check(region, 'mosaic', 'public').done
        assert {row['path'] for row in doc['outputs']} == {
            f'mosaic/public/{name}' for name in (*raster_names, 'manifest.json')
        }
        expected = dict(public_fields, segment=region.id)
        assert (target / 'manifest.json').read_bytes() == receipts.canonical(expected) + b'\n'
