"""Before-Zone pickup tests: only saved receipts and disposable byte fixtures."""
import argparse
import hashlib
import json
from pathlib import Path

import pytest

from scripts.relief import central_zone_pickup_pair as pickup, run_region
from skippercast.relief import receipts

REGION = 'central-fixture'
WATER = b'{"type":"FeatureCollection","features":[],"name":"one"}\n'


def write_json(path, doc):
    path.write_text(json.dumps(doc), encoding='utf-8')


def output_row(root, path):
    data = (root / path).read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def save_pair(out, date=None):
    root = out / REGION
    (root / 'stages').mkdir(parents=True)
    coarse, water = 'saved/coarse-a', 'saved/water-b'
    for target in (coarse, water, 'saved/water-old'):
        (root / target).mkdir(parents=True)
    (root / coarse / 'coarse-3310.tif').write_bytes(b'synthetic raster bytes\n')
    report = {'family': 'synthetic-family', 'region': REGION}
    if date is not None:
        report['date'] = date
    write_json(root / coarse / 'coarse.json', report)
    (root / water / 'water.geojson').write_bytes(WATER)
    (root / 'saved/water-old/water.geojson').write_bytes(WATER.replace(b'one', b'two'))
    write_json(root / water / 'water.json', {'region': REGION})
    stages = (('coarse', coarse, ('coarse-3310.tif', 'coarse.json'), 'a'),
              ('water', water, ('water.geojson', 'water.json'), 'b'))
    for stage, target, names, digit in stages:
        write_json(root / 'stages' / f'{stage}.json', {
            'schema': 'sc-stage-receipt/1', 'region': REGION, 'stage': stage, 'scope': None,
            'generation': digit * 64, 'status': 'ok', 'attempt': 1, 'target': target,
            'params': {'family': 'not-the-report-family'}, 'upstream': [],
            'outputs': [output_row(root, f'{target}/{name}') for name in names],
        })
    return root


def invoke(out, capsys):
    rc = pickup.main(['--out', str(out), '--region', REGION])
    captured = capsys.readouterr()
    assert not captured.err
    return rc, json.loads(captured.out)


@pytest.mark.parametrize('date', [None, '2026-01-02'])
def test_pair_matches_runner_and_is_a_closed_record_fragment(tmp_path, capsys, monkeypatch, date):
    # Catches guessing paths from stage names, pinning report bytes as raster
    # bytes, copying params.family, or inventing a date for a current receipt.
    out = tmp_path.resolve() / 'out'
    save_pair(out, date)
    zone = []
    run_region.bind_zone_inputs(run_region.Config(forbidden_root=tmp_path / 'denied'), out, REGION, zone)
    bound = dict(zip(zone[::2], zone[1::2], strict=True))

    def not_a_done_check(*args, **kwargs):
        pytest.fail('pickup must not enter the runner done/lock check')

    monkeypatch.setattr(receipts, 'check', not_a_done_check)
    rc, pair = invoke(out, capsys)
    assert rc == 0
    expected = {}
    for role in ('coarse', 'water'):
        path = bound[f'--{role}']
        expected[role] = {'path': path, 'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest()}
    assert pair == {'inputs': expected, 'coarse_source': bound['--coarse-source'], 'coarse_date': date}

    # The actual consumer accepts the fragment verbatim in the caller's record.
    record = tmp_path / 'record.json'
    write_json(record, {'schema': 'sc-run-inputs/1', 'region': REGION, 'norm': None, **pair})
    args = argparse.Namespace(inputs=record, region=REGION, coarse=None, water=None,
                              coarse_source=None, coarse_date=None, norm=None)
    _, pins = run_region.load_inputs(args, argparse.ArgumentParser())
    assert (args.coarse, args.water) == (bound['--coarse'], bound['--water'])
    assert pins == {role: entry['sha256'] for role, entry in expected.items()}


@pytest.mark.parametrize(('change', 'reason'), [
    ('region', 'expected an ok receipt'),  # accepting a neighboring region's receipt
    ('extra-generation', 'exactly one water.geojson'),  # first matching basename wins
    ('foreign-output', 'outside the receipt target'),  # accepting a pinned sidecar from another generation
    ('water-bytes', 'SHA-256'),  # checking names or sizes without reading both streams
    ('coarse-bytes', 'SHA-256'),  # verifying just water or the coarse metadata
    ('report-bytes', 'SHA-256'),  # extracting provenance from unverified report bytes
    ('report-symlink', 'outside the receipt target'),  # following an otherwise byte-identical escape
])
def test_refuses_without_either_pin(tmp_path, capsys, change, reason):
    out = tmp_path.resolve() / 'out'
    root = save_pair(out)
    receipt = root / 'stages/water.json'
    doc = json.loads(receipt.read_bytes())
    if change == 'region':
        doc['region'] = 'other-central-fixture'
    elif change == 'extra-generation':
        doc['outputs'].append(output_row(root, 'saved/water-old/water.geojson'))
    elif change == 'foreign-output':
        other = root / 'saved/water-old/water.json'
        other.write_bytes((root / 'saved/water-b/water.json').read_bytes())
        doc['outputs'].append(output_row(root, other.relative_to(root)))
    elif change == 'water-bytes':
        (root / 'saved/water-b/water.geojson').write_bytes((root / 'saved/water-old/water.geojson').read_bytes())
    elif change == 'coarse-bytes':
        path = root / 'saved/coarse-a/coarse-3310.tif'
        path.write_bytes(path.read_bytes().replace(b'raster', b'RASTER'))
    elif change == 'report-bytes':
        path = root / 'saved/coarse-a/coarse.json'
        path.write_bytes(path.read_bytes().replace(b'family"', b'FAMILY"', 1))
    elif change == 'report-symlink':
        path = root / 'saved/coarse-a/coarse.json'
        outside = tmp_path / 'coarse.json'
        path.rename(outside)
        path.symlink_to(outside)
    write_json(receipt, doc)
    rc, refusal = invoke(out, capsys)
    assert rc == 1
    assert refusal.keys() == {'error'}
    assert reason in refusal['error']
