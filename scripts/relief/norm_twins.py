#!/usr/bin/env python3
"""Audit (and optionally repair) normalized-cache buckets that hold more than one build of a source.

``select`` refuses a source with two normalized builds (``ambiguous_normalized_twins``) and silently
leaves its tile out of the mosaic. The usual cause is a normalizer code change: the build folder name
includes the normalizer digest, so re-running ``normalize`` after any edit adds a second build next to
the one an earlier release pinned, even when every output byte is identical.

    norm_twins.py [--norm DIR]                                   audit only; changes nothing
    norm_twins.py [--norm DIR] --apply --quarantine DIR          move the newer, byte-identical builds aside

A bucket is *repairable* only when every build proves its outputs: the sidecar pins ``grid.tif`` and
``support.tif`` as sha256 values, both files exist as regular files whose bytes hash to those pins, and
all builds carry the same pins. Matching sidecar text alone proves nothing (two missing outputs or a
corrupted file would still "match"), so the bytes are hashed here. The oldest build stays (earlier
releases pin it) and every newer one is moved, never deleted, to ``DIR/<bucket>/<build>``. A bucket
whose builds disagree or fail that check is a *conflict*: nothing is moved (in any bucket) and the exit
code is 1 so a person decides.

``--apply`` is all-or-nothing and undoable. Before any move it checks every destination (no existing
target, no symlink at ``DIR/<bucket>``, every resolved destination inside the resolved ``DIR`` and
outside the private vault, same filesystem so each move is one atomic rename), then writes
``DIR/moved-<UTC time>.json`` listing every planned ``from``/``to`` pair. The record is written through
a fresh randomly named temporary (created exclusively, never through an existing link) and swapped in
atomically. Each move is written ahead as ``moving`` before its rename and ``moved`` after it. If a move
(or a record write) fails, the moves already made are renamed back and the record ends ``rolled-back``.

Recovery (the record is a write-ahead log, not the truth; the folders are). If the record's status is
anything but ``complete`` or ``rolled-back`` (``in-progress`` after a crash, ``needs-recovery`` after an
undo that failed), the run did not finish. Judge every ``from``/``to`` pair by the folders alone, whatever
its ``state`` says: ``from`` present and ``to`` absent = not moved; ``to`` present and ``from`` absent =
moved, and ``mv to from`` undoes it (the oldest build was never touched). ``planned`` always means the
rename was never started; ``moving``, ``undoing`` and a ``moved`` that an unwritable record could not
update are only hints. Rename a moved pair back, or leave it moved if you want the repair.

Exit codes: 0 no bucket has twins (or all repaired), 1 conflict (or a refused path or failed move),
2 repairable twins remain (audit mode). Nothing here normalizes, downloads or publishes.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile

HEX64 = re.compile(r'[0-9a-f]{64}')
OUTPUT_NAMES = ('grid.tif', 'support.tif')
DEFAULT_NORM = Path('/mnt/agentorange-backup/seafloor-relief-cache/_norm')
PRIVATE = Path('/mnt/privatevault')


def _refuse_private(path, what):
    resolved = Path(os.path.abspath(path))
    if resolved == PRIVATE or PRIVATE in resolved.parents or Path(os.path.realpath(path)).is_relative_to(PRIVATE):
        raise SystemExit(f'norm_twins: {what} is under {PRIVATE}: refused')


def _builds(bucket):
    """Real (non-symlink) build folders with a sidecar, like select.twins."""
    return [p for p in sorted(bucket.iterdir())
            if HEX64.fullmatch(p.name) and p.is_dir() and not p.is_symlink() and (p / 'sidecar.json').is_file()]


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _proven_outputs(build):
    """The build's output pins when the sidecar pins both outputs and the files' bytes match; else None."""
    try:
        doc = json.loads((build / 'sidecar.json').read_text())
    except (OSError, ValueError):
        return None
    pins = doc.get('outputs') if isinstance(doc, dict) else None
    if not isinstance(pins, dict) or set(pins) != set(OUTPUT_NAMES):
        return None
    if not all(isinstance(v, str) and HEX64.fullmatch(v) for v in pins.values()):
        return None
    for name in OUTPUT_NAMES:
        path = build / name
        try:
            if path.is_symlink() or not path.is_file() or _sha256(path) != pins[name]:
                return None
        except OSError:
            return None
    return pins


def audit(norm):
    """Return (repairable, conflicts): {bucket: [build names, oldest first]} / {bucket: [build names]}."""
    repairable, conflicts = {}, {}
    for bucket in sorted(p for p in norm.iterdir() if HEX64.fullmatch(p.name) and p.is_dir() and not p.is_symlink()):
        builds = _builds(bucket)
        if len(builds) < 2:
            continue
        proven = {build.name: _proven_outputs(build) for build in builds}
        distinct = {json.dumps(p, sort_keys=True) for p in proven.values()}
        names = [b.name for b in sorted(builds, key=lambda b: ((b / 'sidecar.json').stat().st_mtime_ns, b.name))]
        if len(distinct) == 1 and None not in proven.values():
            repairable[bucket.name] = names
        else:
            conflicts[bucket.name] = names
    return repairable, conflicts


def _inside(path, root):
    return Path(os.path.realpath(path)).is_relative_to(root)


def _plan(norm, repairable, root):
    """Check every destination before anything moves; return [(source, target)] or exit with a refusal."""
    plan = []
    for bucket, names in repairable.items():
        bucket_dir = root / bucket
        if bucket_dir.is_symlink() or (os.path.lexists(bucket_dir) and not bucket_dir.is_dir()):
            raise SystemExit(f'norm_twins: {bucket_dir} is a symlink or not a folder: refused')
        if not _inside(bucket_dir, root):
            raise SystemExit(f'norm_twins: {bucket_dir} resolves outside the quarantine: refused')
        _refuse_private(bucket_dir, f'destination {bucket_dir}')
        for name in names[1:]:  # names[0] is the oldest build: it stays.
            source, target = norm / bucket / name, bucket_dir / name
            if source.is_symlink() or not source.is_dir():
                raise SystemExit(f'norm_twins: {source} is not a real build folder: refused')
            if os.path.lexists(target):
                raise SystemExit(f'norm_twins: {target} already exists: refused')
            if not _inside(target.parent, root):
                raise SystemExit(f'norm_twins: {target} resolves outside the quarantine: refused')
            _refuse_private(target, f'destination {target}')
            if os.stat(source).st_dev != os.stat(root).st_dev:
                raise SystemExit(f'norm_twins: {source} and {root} are on different filesystems '
                                 '(a move must be one atomic rename so it can be rolled back): refused')
            plan.append((source, target))
    return plan


def _write_record(path, status, moves):
    """Replace the record atomically. The temporary has a random name and is created with O_EXCL, so a
    pre-planted file or symlink can never be written through; os.replace swaps a link itself, never follows it."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as handle:
            handle.write(json.dumps({'status': status, 'moves': moves}, indent=1) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _where(source, target):
    """Where a planned build really is: 'source' (not moved), 'target' (moved) or 'unknown'."""
    at_source, at_target = os.path.lexists(source), os.path.lexists(target)
    if at_source and not at_target:
        return 'source'
    if at_target and not at_source:
        return 'target'
    return 'unknown'


def _undo(plan, moves, attempted, journal):
    """Rename every attempted move back, judging each by the filesystem. Returns [(target, why)] that stayed."""
    stuck = []
    for index in reversed(attempted):
        source, target = plan[index]
        where = _where(source, target)
        if where == 'source':  # that rename never happened
            moves[index]['state'] = 'planned'
            continue
        if where == 'target':
            moves[index]['state'] = 'undoing'
            journal('in-progress')  # best effort: the undo goes ahead even when the record cannot be written
            try:
                os.rename(target, source)
                moves[index]['state'] = 'rolled-back'
                continue
            except OSError as back:
                stuck.append((str(target), str(back)))
                moves[index]['state'] = 'moved'
                continue
        stuck.append((str(target), 'neither or both of source and destination exist'))
    return stuck


def quarantine(norm, repairable, destination):
    destination.mkdir(parents=True, exist_ok=True)
    root = Path(os.path.realpath(destination))
    _refuse_private(root, 'quarantine')
    plan = _plan(norm, repairable, root)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    record = root / f'moved-{stamp}.json'
    count = 0
    while os.path.lexists(record):
        count += 1
        record = root / f'moved-{stamp}-{count}.json'
    moves = [{'from': str(s), 'to': str(t), 'state': 'planned'} for s, t in plan]
    stale = []  # record writes that failed after the first move: the record may be out of date

    def journal(status):
        try:
            _write_record(record, status, moves)
            return True
        except OSError:
            stale.append(status)
            return False

    try:
        _write_record(record, 'in-progress', moves)  # the record exists before the first move
    except OSError as exc:
        raise SystemExit(f'norm_twins: cannot write {record} ({exc}); nothing was moved') from exc
    made = []       # bucket folders this run created
    attempted = []  # moves whose rename was started: the record says 'moving' before each one
    try:
        for index, (source, target) in enumerate(plan):
            if not os.path.lexists(target.parent):
                target.parent.mkdir()
                made.append(target.parent)
            if target.parent.is_symlink() or not _inside(target.parent, root):
                raise OSError(f'{target.parent} resolves outside the quarantine')
            moves[index]['state'] = 'moving'
            _write_record(record, 'in-progress', moves)  # intent first: if this fails nothing was renamed
            attempted.append(index)
            os.rename(source, target)
            moves[index]['state'] = 'moved'
            _write_record(record, 'in-progress', moves)
    except OSError as exc:
        stuck = _undo(plan, moves, attempted, journal)
        for folder in reversed(made):
            try:
                folder.rmdir()
            except OSError:
                pass
        journal('needs-recovery' if stuck else 'rolled-back')
        note = (f'; the record {record} could not be brought up to date, so decide from the folders as '
                'the module docstring says' if stale else f'; see {record}')
        if stuck:
            raise SystemExit(f'norm_twins: move failed ({exc}) and could not be undone for {stuck}{note}') from exc
        raise SystemExit(f'norm_twins: move failed ({exc}); earlier moves were undone{note}') from exc
    try:
        _write_record(record, 'complete', moves)
    except OSError as exc:  # every move is done and recorded as moved; only the final status is missing
        raise SystemExit(f'norm_twins: all {len(moves)} moves were made but {record} could not be marked '
                         f'complete ({exc}); its entries say moved, undo by the docstring rule if unwanted') from exc
    return [{'from': m['from'], 'to': m['to']} for m in moves]


def main(argv=None):
    parser = argparse.ArgumentParser(prog='norm_twins.py', description=(__doc__ or '').split('\n\n')[0])
    parser.add_argument('--norm', type=Path, default=DEFAULT_NORM, help='normalized cache root (default: the backup _norm)')
    parser.add_argument('--apply', action='store_true', help='move repairable twins aside (needs --quarantine)')
    parser.add_argument('--quarantine', type=Path, help='folder that receives the moved builds')
    args = parser.parse_args(argv)
    if args.apply and args.quarantine is None:
        parser.error('--apply needs --quarantine DIR')
    for path, what in ((args.norm, '--norm'), (args.quarantine, '--quarantine')):
        if path is not None:
            _refuse_private(path, what)
    if not args.norm.is_dir():
        print(f'norm_twins: {args.norm} is not a directory', file=sys.stderr)
        return 1
    if args.quarantine is not None and Path(os.path.realpath(args.quarantine)).is_relative_to(os.path.realpath(args.norm)):
        parser.error('--quarantine must be outside --norm')
    repairable, conflicts = audit(args.norm)
    print(json.dumps({'repairable_buckets': len(repairable), 'conflict_buckets': len(conflicts),
                      'conflicts': sorted(conflicts)}, sort_keys=True))
    if conflicts:
        return 1
    if not repairable:
        return 0
    if not args.apply:
        return 2
    moves = quarantine(args.norm, repairable, args.quarantine)
    print(json.dumps({'moved': len(moves)}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
