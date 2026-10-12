#!/usr/bin/env python3
"""Bound local commands in an existing private checkpoint. No scheduling or approval."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
import uuid


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def positive(value):
    value = float(value)
    if not math.isfinite(value) or value <= 0:
        raise ValueError('limits must be finite and positive')
    return value


def save(path, data):
    fd, name = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, indent=2, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextlib.contextmanager
def locked(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(path.suffix + '.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another command owns this checkpoint; do not launch a duplicate')
        data = json.loads(path.read_text()) if path.exists() else {}
        yield data


def summary(c, now=None):
    if c.get('version') != 1:
        raise ValueError('Unsupported run-control version')
    for key in ('started','deadline','last_seen','last_useful','reserve_seconds',
                'stagnation_seconds','token_limit','attempts_per_candidate'):
        value = c[key]
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
            raise ValueError('Malformed run-control number: '+key)
    if (c['deadline'] <= c['started'] or c['reserve_seconds'] <= 0
            or c['reserve_seconds'] >= c['deadline']-c['started']
            or c['stagnation_seconds'] <= 0 or c['token_limit'] <= 0
            or c['last_seen'] < c['started'] or c['last_useful'] < c['started']
            or c['attempts_per_candidate'] < 1):
        raise ValueError('Malformed persisted allowance')
    now = time.time() if now is None else now
    used = sum(v['input_tokens'] - v['cached_input_tokens'] + v['output_tokens']
               for v in c['usage'].values()) if c['usage'] else None
    reason = None
    if now < c['last_seen']:
        reason = 'Clock moved backwards; reconcile without renewing the allowance'
    elif any(a['status'] == 'running' for a in c['attempts']):
        reason = 'Unresolved running attempt; reconcile its process before recovery'
    elif now >= c['deadline'] - c['reserve_seconds']:
        reason = 'Only checkpoint/cleanup reserve remains'
    elif now - c['last_useful'] >= c['stagnation_seconds']:
        reason = 'No accepted useful artifact within the stagnation allowance'
    elif used is not None and used >= c['token_limit']:
        reason = 'Observed token ceiling reached'
    return {'action': 'STOP' if reason else 'ALLOW', 'reason': reason,
            'remaining_seconds': max(0, c['deadline'] - now),
            'accounted_tokens': used, 'token_scope': 'Imported unique response IDs only',
            'attempts': len(c['attempts']), 'useful_outputs': len(c['outputs']),
            'approval': False}


def initialize(data, *, scope, kind, seconds=3600, reserve=300,
               stagnation=1200, attempts=2, tokens=500000):
    if 'run_control' in data:
        raise ValueError('Run already exists; resume it rather than renew its budget')
    seconds, reserve, stagnation, tokens = map(positive, (seconds, reserve, stagnation, tokens))
    if reserve >= seconds or isinstance(attempts, bool) or attempts < 1:
        raise ValueError('Reserve must fit inside the allowance; attempts must be positive')
    now = time.time()
    data['run_control'] = dict(version=1, run_id=str(uuid.uuid4()), scope=scope, kind=kind,
        started=now, deadline=now + seconds, last_seen=now, last_useful=now,
        reserve_seconds=reserve, stagnation_seconds=stagnation, attempts_per_candidate=attempts,
        token_limit=tokens, attempts=[], outputs=[], usage={})


def account(c, rows):
    merged = dict(c['usage'])
    for row in rows:
        identifier = row['response_id']
        if not isinstance(identifier, str) or not identifier:
            raise ValueError('response_id required')
        u = row['usage']
        values = {}
        for key in ('input_tokens', 'cached_input_tokens', 'output_tokens'):
            value = u[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError('Measured input/cached/output counters are required integers')
            values[key] = value
        if values['cached_input_tokens'] > values['input_tokens']:
            raise ValueError('Cached input is a subset of input')
        reasoning = u.get('reasoning_output_tokens')
        if reasoning is not None and (isinstance(reasoning, bool) or
                not isinstance(reasoning, int) or not 0 <= reasoning <= values['output_tokens']):
            raise ValueError('Reasoning must be an output subset')
        values.update(reasoning_output_tokens=reasoning, model=row.get('model'),
                      effort=row.get('effort'))
        if identifier in merged and merged[identifier] != values:
            raise ValueError('Conflicting duplicate response ID; reconcile the source')
        merged[identifier] = values
    c['usage'] = merged


def execute(path, data, candidate, fingerprint, command, seconds, changed=''):
    c = data['run_control']
    decision = summary(c)
    if decision['action'] != 'ALLOW':
        raise ValueError(decision['reason'])
    if not command or not candidate or not fingerprint:
        raise ValueError('Candidate, input/method/policy fingerprint and argv required')
    previous = [a for a in c['attempts'] if a['candidate'] == candidate]
    if len(previous) >= c['attempts_per_candidate']:
        raise ValueError('Candidate attempt allowance exhausted; skip or escalate')
    if any(a['fingerprint'] == fingerprint for a in c['attempts']):
        raise ValueError('Unchanged attempt prohibited; reuse its saved result')
    if previous and not changed.strip():
        raise ValueError('Changed evidence/method receipt required for a retry')
    seconds = min(positive(seconds), c['deadline'] - c['reserve_seconds'] - time.time(),
                  c['stagnation_seconds'] - (time.time() - c['last_useful']))
    if seconds <= 0:
        raise ValueError('No command allowance remains')
    attempt = dict(id=len(c['attempts']) + 1, candidate=candidate,
                   fingerprint=fingerprint, changed=changed, argv=command,
                   started=time.time(), status='running', pid=None)
    c['attempts'].append(attempt)
    c['last_seen'] = time.time()
    save(path, data)  # Write intent before starting a process.
    proc = None
    old_handlers = {}
    def terminate(signum, _frame):
        # Avoid repeated ordinary termination signals interrupting cleanup.
        for sig in old_handlers:
            signal.signal(sig, signal.SIG_IGN)
        raise KeyboardInterrupt('Termination signal '+str(signum))
    for sig in (signal.SIGTERM, signal.SIGHUP):
        old_handlers[sig] = signal.signal(sig, terminate)
    start = time.monotonic()
    try:
        proc = subprocess.Popen(command, start_new_session=True)
        attempt['pid'] = proc.pid
        save(path, data)
        try:
            result = proc.wait(timeout=seconds)
            attempt.update(status='succeeded' if result == 0 else 'failed', returncode=result)
        except subprocess.TimeoutExpired:
            attempt.update(status='timed_out', returncode=None)
    except OSError as error:
        attempt.update(status='failed', error=str(error), returncode=None)
    except BaseException:
        attempt.update(status='interrupted', returncode=None)
        raise
    finally:
        if proc is not None:
            # Kill leftover children too; commands must not daemonize work outside this group.
            try:
                os.killpg(proc.pid, signal.SIGTERM)
                if proc.poll() is None:
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)
        attempt.update(finished=time.time(), elapsed_seconds=time.monotonic() - start)
        c['last_seen'] = time.time()
        save(path, data)
    return attempt


def record_output(c, attempt_id, artifact, receipt):
    attempt = next((a for a in c['attempts'] if a['id'] == attempt_id), None)
    if not attempt or attempt['status'] != 'succeeded':
        raise ValueError('An output must reference a completed successful attempt')
    evidence = json.loads(Path(receipt).read_text())
    sha = digest(artifact)
    if evidence.get('accepted') is not True or evidence.get('artifact_sha256') != sha:
        raise ValueError('Acceptance receipt must bind this artifact hash')
    if evidence.get('scope') != c['scope'] or evidence.get('kind') != c['kind']:
        raise ValueError('Receipt does not match the declared output class and scope')
    if any(o['sha256'] == sha for o in c['outputs']):
        raise ValueError('Unchanged artifact is not another useful delta')
    c['outputs'].append(dict(attempt=attempt_id, path=str(Path(artifact).resolve()),
                            sha256=sha, receipt=str(Path(receipt).resolve()),
                            receipt_sha256=digest(receipt)))
    c['last_useful'] = time.time()  # Never extends the mission deadline or token ceiling.


def recover(c, receipt):
    evidence = json.loads(Path(receipt).read_text())
    pending = [a for a in c['attempts'] if a['status'] == 'running']
    if not pending or evidence.get('run_id') != c['run_id'] or evidence.get('processes_stopped') is not True:
        raise ValueError('Recovery requires this run ID and explicit stopped-process evidence')
    for a in pending:
        if a['pid'] is not None:
            try:
                os.killpg(a['pid'], 0)
            except ProcessLookupError:
                pass
            else:
                raise ValueError('Process group still exists; do not restart it')
    for a in pending:
        a.update(status='interrupted', recovery_receipt=str(Path(receipt).resolve()),
                 recovery_sha256=digest(receipt))
    # Attempt counts, clock and usage remain intact.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('checkpoint', type=Path)
    sub = parser.add_subparsers(dest='action', required=True)
    init = sub.add_parser('init')
    init.add_argument('--scope', required=True)
    init.add_argument('--kind', choices=['private_handoff', 'public_habitat', 'render_preview', 'preparation'], required=True)
    for key, default in [('seconds',3600),('reserve',300),('stagnation',1200),('attempts',2),('tokens',500000)]:
        init.add_argument('--'+key, type=int, default=default)
    sub.add_parser('status')
    run = sub.add_parser('run')
    for key in ('candidate','fingerprint'):
        run.add_argument('--'+key, required=True)
    run.add_argument('--changed', default='')
    run.add_argument('--seconds', type=float, default=600)
    run.add_argument('argv', nargs=argparse.REMAINDER)
    usage = sub.add_parser('account'); usage.add_argument('--jsonl', type=Path, required=True)
    output = sub.add_parser('record-output')
    output.add_argument('--attempt', type=int, required=True)
    output.add_argument('--artifact', type=Path, required=True)
    output.add_argument('--receipt', type=Path, required=True)
    recovery = sub.add_parser('recover'); recovery.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    try:
        with locked(args.checkpoint) as data:
            if args.action == 'init':
                initialize(data, **{k:getattr(args,k) for k in ('scope','kind','seconds','reserve','stagnation','attempts','tokens')})
            c = data['run_control']
            result = None
            if args.action == 'run':
                command = args.argv[1:] if args.argv[:1] == ['--'] else args.argv
                result = execute(args.checkpoint,data,args.candidate,args.fingerprint,command,args.seconds,args.changed)
            elif args.action == 'account':
                account(c,[json.loads(line) for line in args.jsonl.read_text().splitlines() if line.strip()])
            elif args.action == 'record-output':
                record_output(c,args.attempt,args.artifact,args.receipt)
            elif args.action == 'recover':
                recover(c,args.receipt)
            if args.action != 'status':
                c['last_seen'] = max(c['last_seen'],time.time())
                save(args.checkpoint,data)
            result = result or summary(c)
            print(json.dumps(result,indent=2))
            return 0 if result.get('status','succeeded') == 'succeeded' and result.get('action') != 'STOP' else 2
    except KeyboardInterrupt:
        parser.exit(130,'Interrupted; checkpoint and process cleanup retained\n')
    except (ValueError,KeyError,TypeError,OSError) as error:
        parser.exit(2,str(error)+'\n')


if __name__ == '__main__':
    raise SystemExit(main())
