"""Synthetic saved receipts through the audit's CLI consumer boundary."""
import pytest

from scripts.relief import central_zone_receipt_audit as audit
from skippercast.relief import receipts


FAMILY = 'fixture-family'
REPORT = b'{"family":"fixture-family"}\n'
WATER = receipts.sha256_bytes(b'synthetic water')
COARSE = receipts.sha256_bytes(b'synthetic coarse grid')


def _output(path, data):
    return {'path': path, 'bytes': len(data), 'sha256': receipts.sha256_bytes(data)}


def _save(region, stage, *, scope=None, outputs=(), inputs=(), params=None, **extra):
    doc = {
        'schema': receipts.SCHEMA, 'region': region.id, 'stage': stage, 'scope': scope,
        'status': 'ok', 'attempt': 1, 'upstream': [], 'outputs': list(outputs),
        'inputs': list(inputs), 'params': params or {},
        'generation': receipts.generation(inputs, [], 'a' * 64, params or {}), **extra,
    }
    receipts.write_json_atomic(region.receipt_path(stage, scope), doc)
    return doc


@pytest.fixture
def saved_out(tmp_path):
    region = receipts.Region(tmp_path / 'out', 'big-sur-coast')
    report = region.dir / 'coarse/coarse.json'
    report.parent.mkdir(parents=True)
    report.write_bytes(REPORT)
    _save(region, 'coarse', outputs=[_output('coarse/coarse-3310.tif', b'synthetic coarse grid'),
                                    _output('coarse/coarse.json', REPORT)])
    _save(region, 'water', outputs=[_output('water/water.geojson', b'synthetic water')])
    _zone(region)
    return region


def _zone(region, *, coarse=COARSE, coarse_path='coarse/coarse-3310.tif', source=FAMILY):
    _save(region, 'zone', scope='public', inputs=[
        {'role': 'coarse', 'path': coarse_path, 'sha256': coarse},
        {'role': 'water', 'path': 'water/water.geojson', 'sha256': WATER},
    ], params={'coarse_source': source})


def _run(region, capsys):
    rc = audit.main(['--out', str(region.out_root), '--region', region.id])
    return rc, capsys.readouterr().out.splitlines()


def test_matched_hashes_without_input_bytes(saved_out, capsys):
    # The receipt digests suffice; using the full done check or opening the TIFF fails here.
    rc, lines = _run(saved_out, capsys)
    assert rc == 0
    assert lines == [f"water: match (zone='{WATER}' producer='{WATER}')",
                     f"coarse: match (zone='{COARSE}' producer='{COARSE}')",
                     f"coarse_source: match (zone='{FAMILY}' producer='{FAMILY}')"]


def test_swapped_water_uses_current_named_output_not_history_or_path(saved_out, capsys):
    # A replacement has the same path, and the old digest still exists in history and another
    # output. Matching by path, any producer digest, or an old generation would miss the swap.
    old = receipts.read_receipt(saved_out.receipt_path('water'))
    assert old is not None
    new = _output('water/water.geojson', b'replacement water')
    _save(saved_out, 'water', outputs=[_output('water/water.json', b'synthetic water'), new],
          params={'revision': 2}, generation_history={old['generation']: old})
    rc, lines = _run(saved_out, capsys)
    assert rc == 1
    assert lines[0] == f"water: mismatch (zone='{WATER}' producer='{new['sha256']}')"
    assert lines[1].startswith('coarse: match ')
    assert lines[2].startswith('coarse_source: match ')


def test_manual_legacy_coarse_without_receipt_is_unknown(saved_out, tmp_path, capsys):
    # A valid manual input and even a leftover report cannot stand in for producer evidence.
    saved_out.receipt_path('coarse').unlink()
    manual_grid = tmp_path / 'manual' / 'coarse-3310.tif'
    manual_grid.parent.mkdir()
    manual_grid.write_bytes(b'legacy coarse grid')
    _zone(saved_out, coarse=receipts.sha256_file(manual_grid), coarse_path=str(manual_grid))
    rc, lines = _run(saved_out, capsys)
    assert rc == 2
    assert lines[0].startswith('water: match ')
    assert [line.split(' (')[0] for line in lines[1:]] == ['coarse: unknown', 'coarse_source: unknown']


def test_wrong_coarse_digest_does_not_change_source_match(saved_out, capsys):
    # A matching source label (or unchanged path) cannot authenticate a different grid digest.
    _zone(saved_out, coarse=WATER)
    rc, lines = _run(saved_out, capsys)
    assert rc == 1
    assert lines[1] == f"coarse: mismatch (zone='{WATER}' producer='{COARSE}')"
    assert lines[2].startswith('coarse_source: match ')


def test_source_override_is_compared_to_report_not_producer_params(saved_out, capsys):
    # A manual label can agree with producer params while disagreeing with the receipted report.
    producer = receipts.read_receipt(saved_out.receipt_path('coarse'))
    assert producer is not None
    _save(saved_out, 'coarse', outputs=producer['outputs'], params={'family': 'override'})
    _zone(saved_out, source='override')
    rc, lines = _run(saved_out, capsys)
    assert rc == 1
    assert lines[1].startswith('coarse: match ')
    assert lines[2] == f"coarse_source: mismatch (zone='override' producer='{FAMILY}')"


def test_same_size_coarse_report_tamper_cannot_prove_family(saved_out, capsys):
    # The family is unchanged and the size still matches; trusting parsed content or size alone fails.
    (saved_out.dir / 'coarse/coarse.json').write_bytes(REPORT.replace(b'\n', b' '))
    rc, lines = _run(saved_out, capsys)
    assert rc == 2
    assert lines[1].startswith('coarse: match ')
    assert lines[2].startswith('coarse_source: unknown ')
    assert 'SHA-256' in lines[2]
