"""Offline receipt fixtures for the cross-region rebuild CLI."""
from importlib import import_module
import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts.relief import rebuild_plan as cli
from skippercast.relief import mosaic, package, receipts, render_config, tiles
from tests._support import ROOT


KEYS = ('select', 'mosaic.public', 'tiles.public', 'zone.public', 'digests',
        'inventory', 'contours', 'package', 'shots', 'qa', 'envelope')
STAMP = '1' * 64


def record(out, region, key, digest, *, params=None, upstream=()):
    stage, _, scope = key.partition('.')
    path = receipts.Region(out, region).receipt_path(stage, scope or None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(receipts.canonical(dict(
        schema=receipts.SCHEMA, region=region, stage=stage, scope=scope or None,
        status='ok', attempt=1, generation=STAMP, outputs=[],
        code={'stage_digest': digest}, params=params or {},
        upstream=[{'stage': name, 'scope': scope, 'generation': STAMP} for name, scope in upstream],
    )))


def row(key, *reasons):
    return {'stage': key, 'action': 'rebuild' if reasons else 'reuse', 'reasons': list(reasons)}


def report(blocks, heavy):
    return {'regions': [{'region': region, 'stages': stages} for region, stages in blocks],
            'summary': {'regions': len(blocks), 'rebuild_heavy': heavy}}


def invoke(out, *args):
    return subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/relief/rebuild_plan.py'),
                           '--out', str(out), *args], capture_output=True, text=True, cwd=out.parent)


def snapshot(root):
    return {path: (path.stat().st_mtime_ns, path.read_bytes() if path.is_file() else None)
            for path in (root, *root.rglob('*'))}


@pytest.mark.parametrize('as_json', [pytest.param(False, id='C1: ordered text blocks and heavy count'),
                                    pytest.param(True, id='C1: one complete JSON document')])
def test_c1_cross_region_report(tmp_path, as_json):
    """C1: Keep caller order and scoped stages; count only mosaic/tiles needing work."""
    mosaic_digest = receipts.stage_digest(receipts.module_code_files(mosaic))
    tiles_digest = receipts.stage_digest(receipts.module_code_files(tiles))
    record(tmp_path, 'west-test', 'mosaic.public', mosaic_digest)
    record(tmp_path, 'west-test', 'tiles.private', tiles_digest)
    record(tmp_path, 'west-test', 'tiles.public', '0' * 64, params={'baked': '0' * 64})
    record(tmp_path, 'west-test', 'digests', '0' * 64, upstream=[('tiles', 'public')])
    before = snapshot(tmp_path)
    result = invoke(tmp_path, *(['--json'] if as_json else []), 'west-test', 'east-test')
    assert (result.returncode, result.stderr) == (0, '')
    if as_json:
        assert json.loads(result.stdout) == report([
            ('west-test', [row('select', 'missing'), row('mosaic.public'), row('tiles.private'),
                           row('tiles.public', 'code', 'style:baked'), row('zone.public', 'missing'),
                           row('digests', 'code', 'upstream:tiles.public'),
                           *(row(key, 'missing') for key in KEYS[5:])]),
            ('east-test', [row(key, 'missing') for key in KEYS]),
        ], 3)
    else:
        assert result.stdout == '\n'.join([
            'region west-test',
            '  select  rebuild  missing',
            '  mosaic.public  reuse  -',
            '  tiles.private  reuse  -',
            '  tiles.public  rebuild  code, style:baked',
            '  zone.public  rebuild  missing',
            '  digests  rebuild  code, upstream:tiles.public',
            *(f'  {key}  rebuild  missing' for key in KEYS[5:]),
            'region east-test',
            *(f'  {key}  rebuild  missing' for key in KEYS),
            'regions=2 rebuild_heavy=3', '',
        ])
    # C2: Catch region creation, locks, output materialization and receipt rewrites.
    assert snapshot(tmp_path) == before


def test_c1_style_is_resolved_per_region(tmp_path, monkeypatch, capsys):
    """C1: Using one region's style for the whole report misclassifies legacy tiles."""
    monkeypatch.setattr(render_config, '_config', lambda region: (
        {'style': render_config.LEGACY} if region == 'legacy-test' else None))
    _, modern = render_config.resolve_style('modern-test')
    assert modern is not None
    digest = receipts.stage_digest(receipts.module_code_files(tiles))
    for region in ('modern-test', 'legacy-test'):
        record(tmp_path, region, 'tiles.public', digest, params={'baked': modern.digest('baked')})
    assert cli.main(['--out', str(tmp_path), '--json', 'modern-test', 'legacy-test']) == 0
    output = capsys.readouterr()
    assert output.err == ''
    assert json.loads(output.out) == report([
        ('modern-test', [row(key, 'missing') if key != 'tiles.public' else row(key) for key in KEYS]),
        ('legacy-test', [row(key, 'missing') if key != 'tiles.public' else row(key, 'style:baked') for key in KEYS]),
    ], 3)


@pytest.mark.parametrize('stage', [
    pytest.param('select', marks=pytest.mark.gis, id='C1: select producer digest parity'),
    pytest.param('digests', id='C1: digests producer digest parity'),
    pytest.param('package', id='C1: package producer digest parity'),
    pytest.param('qa', id='C1: QA producer digest parity'),
    pytest.param('envelope', id='C1: envelope producer digest parity'),
])
def test_c1_legacy_producer_digest(tmp_path, monkeypatch, capsys, stage):
    """C1: Producer hashes must reuse, but a one-byte code edit must not."""
    producer = import_module(f'skippercast.relief.{stage}')
    out = tmp_path / 'out'
    out.mkdir()
    argv = ['--out', str(out), '--region', 'test-bay']
    if stage == 'select':
        argv += ['--cache', str(tmp_path / 'cache'), '--registry', str(tmp_path / 'registry.json'),
                 '--provenance', str(tmp_path / 'provenance.json'), '--region-config', str(tmp_path / 'region.json')]
    if stage == 'package':
        manifest = tmp_path / 'manifest.json'
        manifest.write_bytes(receipts.canonical(dict.fromkeys(package.METADATA) | {
            'region': 'test-bay', 'layer_paths': [package.ARCHIVE],
        }))
        argv += ['--manifest', str(manifest), '--upstream', 'tiles:public']
    if stage in ('qa', 'envelope'):
        argv += ['--generation', STAMP]
    if stage == 'qa':
        argv += ['--release-sha256', STAMP, '--upstream', 'mosaic:public',
                 '--elevation', str(tmp_path / 'e.tif'), '--contributor', str(tmp_path / 'c.tif'),
                 '--shots', str(tmp_path / 'shots.json')]

    # Capture the real producer's StageRun without executing its plan, build or writer.
    captured = []

    def capture(run):
        captured.append(run.code_digest)
        return receipts.Result(state='ok', stage=run.stage, scope=run.scope, generation=STAMP,
                               reason='fixture', receipt=run.region.receipt_path(run.stage, run.scope))

    with monkeypatch.context() as patch:
        patch.setattr(receipts, 'run_stage', capture)
        assert producer.main(argv) == 0
    capsys.readouterr()
    (digest,) = captured
    record(out, 'test-bay', stage, digest)

    # Compare the complete CLI document, not just internally computed hashes.
    def observe():
        assert cli.main(['--out', str(out), '--json', 'test-bay']) == 0
        output = capsys.readouterr()
        assert output.err == ''
        return json.loads(output.out)

    expected = [row(key) if key == stage else row(key, 'missing') for key in KEYS]
    assert observe() == report([('test-bay', expected)], 2)

    assert producer.__file__ is not None
    source = Path(producer.__file__)
    changed = tmp_path / 'relief' / source.name
    changed.parent.mkdir()
    if stage == 'qa':
        # Keep the other QA hash inputs byte-identical, including its relative contour contract.
        contract = tmp_path / 'platform/depth_contours.py'
        contract.parent.mkdir()
        contract.write_bytes((source.parent.parent / 'platform/depth_contours.py').read_bytes())
    original = source.read_bytes()
    changed.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    monkeypatch.setattr(producer, '__file__', str(changed))
    if stage == 'select':
        monkeypatch.setattr(producer.__spec__, 'origin', str(changed))
    expected[KEYS.index(stage)] = row(stage, 'code')
    assert observe() == report([('test-bay', expected)], 2)


@pytest.mark.parametrize(('args', 'message'), [
    pytest.param(['test-bay'], 'the following arguments are required: --out', id='C3: no OUT option'),
    pytest.param(['--out', '.'], 'the following arguments are required: REGION', id='C3: no regions'),
    pytest.param(['--out', '.', '../away'], "invalid region id '../away'", id='C3: invalid region'),
])
def test_c3_usage_errors(args, message, monkeypatch, tmp_path, capsys):
    """C3: Bad invocations fail with argparse's exit code and no partial report."""
    monkeypatch.chdir(tmp_path)
    assert_error(args, message, capsys)


def assert_error(args, message, capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(args)
    assert (type(error.value), error.value.code) == (SystemExit, 2)
    output = capsys.readouterr()
    assert (output.out, output.err.splitlines()[-1]) == ('', f'rebuild_plan.py: error: {message}')


@pytest.mark.parametrize(('kind', 'errno', 'reason'), [
    pytest.param('absent', 2, 'No such file or directory', id='C3: OUT does not exist'),
    pytest.param('file', 20, 'Not a directory', id='C3: OUT is not a directory'),
    pytest.param('denied', 13, 'Permission denied', id='C3: OUT cannot be listed'),
    pytest.param('stages', 13, 'Permission denied', id='C3: receipt directory cannot be listed'),
])
def test_c3_unreadable_out(tmp_path, monkeypatch, capsys, kind, errno, reason):
    """C3: Unreadable OUT must not be mistaken for an empty region."""
    out = tmp_path / 'out'
    unreadable = out
    if kind == 'file':
        out.touch()
    elif kind in ('denied', 'stages'):
        if kind == 'stages':
            unreadable = out / 'test-bay' / 'stages'
        unreadable.mkdir(parents=True)
        scandir = cli.os.scandir

        def denied(path):
            if path == unreadable:
                raise PermissionError(errno, reason, str(path))
            return scandir(path)

        monkeypatch.setattr(cli.os, 'scandir', denied)
    assert_error(['--out', str(out), 'test-bay'], f"[Errno {errno}] {reason}: '{unreadable}'", capsys)


def test_c3_unreadable_receipt_does_not_emit_partial_report(tmp_path, capsys):
    """C3: A later unreadable receipt does not leave an earlier region's report on stdout."""
    path = receipts.Region(tmp_path, 'bad-test').receipt_path('select')
    path.parent.mkdir(parents=True)
    path.write_bytes(b'[]')
    assert_error(['--out', str(tmp_path), 'empty-test', 'bad-test'],
                 'select.json: not a JSON object', capsys)


def test_c3_missing_installed_select(tmp_path, monkeypatch, capsys):
    """C3: Cannot report missing receipts as guesses when select's code cannot be located."""
    monkeypatch.setattr(cli, 'find_spec', lambda _: None)
    assert_error(['--out', str(tmp_path), 'test-bay'], 'select has no installed source file', capsys)
