"""Offline subprocess controls for the artifact review, including optimized mode."""
import ast
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

root, scratch = map(Path, sys.argv[1:3])
original_home = Path.home()
scratch.mkdir(parents=True, exist_ok=True)
for name in ('HOME', 'SKIPPERCAST_FOUR128_MISSION_ROOT', 'SKIPPERCAST_FOUR128_CODE_ROOT'):
    os.environ.pop(name, None)
os.environ['HOME'] = str(scratch)
os.environ['SKIPPERCAST_FOUR128_CODE_ROOT'] = str(root)
project = scratch / 'skippercast-data/2026-10-07-pge-south'
mission = project / 'scratch/source-reuse-admission-engineering-20261011/fixture'
os.environ['SKIPPERCAST_FOUR128_MISSION_ROOT'] = str(mission)
sys.path.insert(0, str(root / 'src'))
sys.path.insert(0, str(root / 'research/scripts'))


def offline_guard(event, args):
    if event.startswith(('socket.', 'subprocess.')) or event in ('os.system', 'os.exec', 'os.posix_spawn'):
        raise RuntimeError('offline probe forbids ' + event)
    if event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
        p = Path(os.fsdecode(args[0])).absolute()
        if any(p.is_relative_to(original_home / name) for name in ('skippercast-data', 'agent-work')):
            raise RuntimeError('probe forbids operator data read: ' + str(p))


sys.addaudithook(offline_guard)
spec = importlib.util.spec_from_file_location('artifact_review_probe_module', root / 'research/scripts/coastal_four128_artifact_review.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
if m.N != mission or m.DEFAULT_ROOT != mission or m.W != root:
    raise RuntimeError('pre-import roots/defaults not isolated')

checks = 0


def refused(call):
    global checks
    try:
        call()
    except ValueError as exc:
        if not str(exc).startswith('artifact review check failed:'):
            raise RuntimeError('unrelated error hid check') from exc
        checks += 1
    else:
        raise RuntimeError('invalid fixture accepted')


unit = 'synthetic-review.service'
cg = '/synthetic.slice/' + unit
props = dict(ExecMainPID='123', ControlGroup=cg, ActiveState='active', InvocationID='a' * 32,
             KillMode='control-group', KillSignal='9', RuntimeMaxUSec='3min')
readings = {'memory.max': '1073741824', 'memory.swap.max': '0', 'cpu.max': '200000 100000', 'pids.max': '32'}
parent = dict(readings, **{'memory.max': '3221225472', 'pids.max': '96'})
m.CONTEXT = {'slice': 'synthetic.slice'}


def resources(**changes):
    values = dict(unit=unit, props=props, cg=cg, readings=readings, parent_readings=parent, affinity=[0, 1], pid=123)
    values.update(changes)
    return m.validate_review_resources(**values)


if resources() is not True:
    raise RuntimeError('valid resource fixture refused')
for key, value in [('ExecMainPID', '999'), ('ControlGroup', '/wrong'), ('ActiveState', 'dead'),
                   ('InvocationID', '0' * 32), ('InvocationID', 'invalid'), ('KillMode', 'process'),
                   ('KillSignal', '15'), ('RuntimeMaxUSec', '1h')]:
    refused(lambda key=key, value=value: resources(props=dict(props, **{key: value})))
for key in readings:
    refused(lambda key=key: resources(readings=dict(readings, **{key: 'invalid'})))
    refused(lambda key=key: resources(parent_readings=dict(parent, **{key: 'invalid'})))
refused(lambda: resources(unit='wrong'))
refused(lambda: resources(cg='/wrong.slice/' + unit))
refused(lambda: resources(affinity=[]))
refused(lambda: resources(affinity=[0, 1, 2]))

context = dict(schema='coastal-release-runtime-context-v1', root=str(mission), execution_root=str(mission / 'execution'),
               native_store='var/coastal/authenticated.sqlite', mode='synthetic_rehearsal', rehearsal_synthetic=True,
               source={'sha256': 'a' * 64}, real_source_sha256='b' * 64)
context_path = mission / 'control/release-context.json'
context_path.parent.mkdir(parents=True)


def configure(doc):
    context_path.write_text(json.dumps(doc))
    return m.configure(mission)


configure(context)
if m.R != mission / 'execution' or m.FIXTURE is not True:
    raise RuntimeError('valid configure fixture did not bind')
for key, value in [('schema', 'wrong'), ('root', str(scratch / 'wrong')), ('execution_root', str(scratch / 'wrong')),
                   ('native_store', 'wrong'), ('mode', 'unknown'), ('rehearsal_synthetic', False),
                   ('real_source_sha256', 'a' * 64)]:
    doc = copy.deepcopy(context)
    doc[key] = value
    refused(lambda doc=doc: configure(doc))
# Real-continuation check has its own otherwise-valid inputs.
real = dict(context, mode='real_continuation', rehearsal_synthetic=False, real_source_sha256='a' * 64)
configure(real)
refused(lambda: configure(dict(real, real_source_sha256='b' * 64)))
refused(lambda: configure(dict(real, rehearsal_synthetic=True)))
# The synthetic path-allowance check cannot be hidden by bad metadata.
bad_root = project / 'outside-allowance'
(bad_root / 'control').mkdir(parents=True)
(bad_root / 'control/release-context.json').write_text(json.dumps(dict(context, root=str(bad_root), execution_root=str(bad_root / 'execution'))))
refused(lambda: m.configure(bad_root))
print(json.dumps(dict(status='OFFLINE_GATES_VERIFIED', refused_controls=checks, optimized=not __debug__,
                      isolated_defaults=True), sort_keys=True))
