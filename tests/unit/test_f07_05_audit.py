"""The terrain CLI must not turn a private receipt or error into console data."""
import hashlib
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from research.scripts import check_terrain_acceptance
from skippercast.coastal.render import terrain_only


PRIVATE = 'synthetic-private-terrain-sentinel'
COUNTS = dict(support_cells=4, vertices=4, triangles=2)
EMPTY_COUNTS = dict.fromkeys(COUNTS, 0)


def cli_args(root):
    return ['--root', str(root), '--acceptance', str(root / 'acceptance.json'),
            '--output-dir', PRIVATE]


def run_captured(root, monkeypatch, capsys):
    """Exercise the existing consumer with the real CLI output, no external process."""
    captured = []

    def run(command, **kwargs):
        assert command[1:4] == ['-B', '-m', 'skippercast.coastal.render.terrain_only']
        code = terrain_only.main(command[4:])
        stdout, stderr = capsys.readouterr()
        captured.append(stdout)
        assert not stderr
        return subprocess.CompletedProcess(command, code, stdout, stderr)

    args = SimpleNamespace(python=sys.executable, pythonpath=None, output_dir=PRIVATE,
                           style=None, timeout_s=5)
    with monkeypatch.context() as patch:
        patch.setattr(check_terrain_acceptance, 'subprocess', SimpleNamespace(run=run))
        parsed = check_terrain_acceptance.render_core(args, root)
    stdout, = captured
    assert PRIVATE not in stdout and str(root) not in stdout
    assert len(stdout.splitlines()) == 1
    return json.loads(stdout), parsed


def test_success_and_reuse_keep_full_receipt_only_on_disk(tmp_path, monkeypatch, capsys):
    acceptance = dict(synthetic=True, limitations=[PRIVATE], crs=PRIVATE)
    (tmp_path / 'acceptance.json').write_text(json.dumps(acceptance))
    mesh = dict(crs=PRIVATE, crs_wkt=f'{PRIVATE}-wkt', affine=[1, 0, 987654321, 0, -1, 987654321],
                vertical={'datum': PRIVATE}, nodata=None, support=SimpleNamespace(sum=lambda: 4),
                vertices=[None] * 4, faces=[None] * 2)
    monkeypatch.setattr(terrain_only, 'verify', lambda root, document, **kw: document)
    monkeypatch.setattr(terrain_only, 'build_terrain', lambda *a: mesh)
    monkeypatch.setattr(terrain_only, 'render_terrain', lambda *a: ({'image_legends': [PRIVATE]}, None))
    monkeypatch.setattr(terrain_only, 'save_mesh', lambda path, mesh: path.write_bytes(b'synthetic mesh'))
    monkeypatch.setattr(terrain_only, 'write_png', lambda path, pixels: path.write_bytes(b'synthetic image'))
    for package in ('numpy', 'rasterio'):
        monkeypatch.setitem(sys.modules, package, SimpleNamespace(__version__='synthetic'))

    receipt_path = tmp_path / PRIVATE / 'render-receipt.json'
    for _ in range(2):  # Fresh and reused outputs use the same console contract.
        summary, parsed = run_captured(tmp_path, monkeypatch, capsys)
        receipt_bytes = receipt_path.read_bytes()
        receipt = json.loads(receipt_bytes)
        assert receipt['acceptance'] == acceptance
        assert receipt['affine'] == mesh['affine'] and receipt['crs_wkt'] == mesh['crs_wkt']
        assert [artifact['path'] for artifact in receipt['artifacts']] == [
            f'{PRIVATE}/terrain-mesh.npz', f'{PRIVATE}/preview.png']
        assert summary == expected('done', [], COUNTS, hashlib.sha256(receipt_bytes.rstrip(b'\n')).hexdigest())
        assert (parsed['exit_code'], parsed['stdout_state'], parsed['stdout_holds']) == (0, 'done', [])


def expected(state, holds, counts, receipt_content_sha256):
    return dict(schema='coastal-terrain-only-console-v1', state=state, holds=holds, counts=counts,
                receipt_content_sha256=receipt_content_sha256, source_accessed=False,
                imagery_used=False, internal_diagnostic=True, publication_prohibited=True,
                website='held', habitat='unassessed')


@pytest.mark.parametrize('failure', ['missing-input', 'private-error', 'known-hold'])
def test_consumer_gets_fixed_failed_status(tmp_path, monkeypatch, capsys, failure):
    hold = 'render_failed'
    if failure != 'missing-input':
        (tmp_path / 'acceptance.json').write_text('{}')
        if failure == 'known-hold':
            hold = 'terrain_only_dependency:jsonschema'

    def refuse(*args, **kwargs):
        if failure == 'missing-input':
            pytest.fail('renderer reached without acceptance')
        if failure == 'private-error':
            print(PRIVATE)
            print(tmp_path / PRIVATE, file=sys.stderr)
            raise ValueError(f'terrain_only_input_schema: {PRIVATE} at {tmp_path / PRIVATE}')
        raise ValueError(hold)

    monkeypatch.setattr(terrain_only, 'preview', refuse)
    summary, parsed = run_captured(tmp_path, monkeypatch, capsys)
    assert summary == expected('held', [hold], EMPTY_COUNTS, None)
    assert (parsed['exit_code'], parsed['stdout_state'], parsed['stdout_holds']) == (2, 'held', [hold])
    assert not (tmp_path / PRIVATE).exists()


def test_argument_error_does_not_echo_private_tokens(tmp_path, capsys):
    assert terrain_only.main([*cli_args(tmp_path), f'--{PRIVATE}']) == 2
    stdout, stderr = capsys.readouterr()
    assert not stderr
    assert json.loads(stdout) == expected('held', ['invalid_arguments'], EMPTY_COUNTS, None)


def test_preexisting_log_handler_and_raw_fd_writes_stay_off_console(tmp_path, monkeypatch, capfd):
    """Contract: library diagnostics never reach the console, even past Python stream swaps.

    A rasterio-style logger handler created before `main` keeps the original stderr and
    a C library writes straight to fd 2; swapping sys.stdout/sys.stderr alone leaks both.
    """
    import logging
    import os

    (tmp_path / 'acceptance.json').write_text('{}')
    logger = logging.getLogger('rasterio.synthetic')
    handler = logging.StreamHandler(sys.stderr)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    def leak(*args, **kwargs):
        logger.warning('%s', tmp_path / PRIVATE)
        os.write(2, f'{PRIVATE}\n'.encode())
        os.write(1, f'{PRIVATE}\n'.encode())
        raise ValueError('terrain_only_dependency:jsonschema')

    monkeypatch.setattr(terrain_only, 'preview', leak)
    try:
        code = terrain_only.main(cli_args(tmp_path))
        logger.warning('after-main-log-still-works')  # logging restored after the held summary
    finally:
        logger.removeHandler(handler)
    stdout, stderr = capfd.readouterr()
    assert code == 2 and PRIVATE not in stdout + stderr and str(tmp_path) not in stdout + stderr
    assert json.loads(stdout) == expected('held', ['terrain_only_dependency:jsonschema'], EMPTY_COUNTS, None)
    assert 'after-main-log-still-works' in stderr
