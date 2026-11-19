"""Synthetic render deadlines, with the real managed writer and readback."""
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
from unittest.mock import patch

import pytest

from skippercast.coastal import child_release
from skippercast.coastal.handoff import common
from skippercast.coastal.render import governed


HOLD = 'render_stage_deadline_exhausted'


def _preview(_root, _item, _now, _horizon, _shared_range):
    binding = 'a' * 64
    terrain = 'sample/terrain/'
    demo = 'sample/inspector/'
    files = []

    def add(path, content, role, contract=None):
        data = content if isinstance(content, bytes) else governed._json_bytes(content)
        files.append((path, data, role, contract))
        ref = dict(path=path, bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        if contract:
            ref['contract'] = contract
        return ref

    mesh = add(terrain + 'terrain-mesh.npz', b'mesh', 'render', 'coastal-terrain-only-mesh-v1')
    png = add(terrain + 'preview.png', b'preview', 'render', 'coastal-terrain-only-png-v1')
    render = dict(schema=governed.terrain.RESULT, state='done', render_binding=binding,
                  synthetic=True, artifacts=[mesh, png], **governed.FLAGS)
    receipt = add(terrain + 'render-receipt.json', render, 'control', governed.terrain.RESULT)
    add(terrain + 'complete.json', dict(schema='coastal-terrain-only-complete-v1',
                                       binding=binding, receipt=receipt), 'control')
    html = dict(add(demo + 'terrain-demo.html', b'inspector', 'render'), path='terrain-demo.html')
    inspector = dict(schema=governed.demo.SCHEMA, state='done', render_receipt=receipt,
                     html=html, **governed.FLAGS)
    demo_receipt = add(demo + 'demo-receipt.json', inspector, 'control')
    add(demo + 'complete.json', dict(schema='coastal-terrain-demo-complete-v1',
                                     receipt=demo_receipt, html=html), 'control')
    return dict(id='sample', binding=binding, receipt=render, demo=inspector, files=files)


def _fixture(stack, root, case):
    from skippercast.coastal.output_writer import partition_declarations

    output = root / 'render'
    partition: dict[str, Any] = partition_declarations(0, 65 * governed.MIB, str(root))
    grant = dict(partition['children']['render'], output_partition=partition,
                 output_partition_role='render')
    deadline_mono = time.monotonic() + (1.5 if case == 'blocked' else 20)
    clock = dict(deadline_monotonic=deadline_mono)
    release = dict(child_grant=grant, grant_digest=common.digest(grant), output_root=str(output),
                   stage_clock=clock, global_clock=clock)
    stack.enter_context(patch.object(child_release, 'validate_child_release', return_value=release))
    stack.enter_context(patch.object(common, 'load', return_value={'deadline_epoch': time.time() + 10}))
    stack.enter_context(patch.object(governed, 'load_owner_render_plan', return_value=({}, {})))
    stack.enter_context(patch.object(governed, 'load_render_prerequisites',
                                     return_value=([{'id': 'sample'}], [1, 2], None, None)))
    stack.enter_context(patch.object(governed, '_prepare', _preview))
    original_write = governed.ManagedOutputs.write_bytes

    def write(manager, name, data, **kwargs):
        result = original_write(manager, name, data, **kwargs)
        if name == 'sample/terrain/terrain-mesh.npz':
            if case == 'expired':
                # Wall time moves beyond the approved horizon during an actual write.
                expired = time.time() + 60
                stack.enter_context(patch.object(time, 'time', return_value=expired))
            if case == 'blocked':
                # The next real managed write must acquire this same flock via a new fd.
                lock = stack.enter_context(manager.lock_path.open('r+b'))
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return result

    stack.enter_context(patch.object(governed.ManagedOutputs, 'write_bytes', write))


@pytest.mark.parametrize('case', ['valid', 'expired', 'blocked', 'cli-valid', 'cli-expired'])
def test_governed_render_deadline(tmp_path, monkeypatch, capsys, case):
    from contextlib import ExitStack

    root = tmp_path.resolve()
    context_path = root / 'context.json'
    context = {'stage_clock': {'root': str(root)}}
    context_path.write_text(json.dumps(context))
    scenario = case.removeprefix('cli-')
    output = root / 'render'
    original_popen = subprocess.Popen

    def launch(argv, **kwargs):
        # Only inject synthetic inputs in the real worker process. Keep the
        # actual timeout/kill/reap path and all managed reservations and writes.
        assert argv[:3] == [sys.executable, '-m', governed.__name__]
        return original_popen([sys.executable, __file__, str(root), scenario], **kwargs)

    monkeypatch.setattr(subprocess, 'Popen', launch)
    # Install the same fixture locally so this regression also runs against
    # main's original in-process implementation (except its unbounded flock).
    with ExitStack() as stack:
        if scenario != 'blocked':
            _fixture(stack, root, scenario)
        now = time.time()
        started = time.monotonic()
        if case.startswith('cli-'):
            code = governed.main(['--context', str(context_path), '--source-root', str(root),
                                  '--inputs', str(context_path)])
            response = json.loads(capsys.readouterr().out)
            if scenario == 'expired':
                assert code == 2
                assert response['state'] == 'held' and response['holds'] == [HOLD]
            else:
                assert code == 0 and response['batch']['state'] == 'done'
        elif scenario == 'valid':
            assert governed.run_governed(context, root, context_path, now=now,
                                         horizon=now + 10)['batch']['state'] == 'done'
        else:
            with pytest.raises(TimeoutError, match=HOLD):
                governed.run_governed(context, root, context_path, now=now, horizon=now + 10)
    # The blocked case has no cooperative return: only a hard worker deadline
    # can retain the first file and return before the longer caller horizon.
    if scenario == 'blocked':
        assert time.monotonic() - started < 8
    assert (output / 'sample/terrain/terrain-mesh.npz').read_bytes() == b'mesh'
    if scenario == 'valid':
        assert governed.verify_completed_batch(output)['batch']['state'] == 'done'
    else:
        assert not (output / 'batch-complete.json').exists()
        assert not (output / 'sample/terrain/preview.png').exists()


if __name__ == '__main__':
    from contextlib import ExitStack

    with ExitStack() as fixtures:
        _fixture(fixtures, Path(sys.argv[1]), sys.argv[2])
        raise SystemExit(governed._render_worker())
