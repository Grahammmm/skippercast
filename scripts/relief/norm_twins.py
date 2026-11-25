#!/usr/bin/env python3
"""Audit (and optionally repair) normalized-cache buckets that hold more than one build of a source.

``select`` refuses a source with two normalized builds (``ambiguous_normalized_twins``) and silently
leaves its tile out of the mosaic. The usual cause is a normalizer code change: the build folder name
includes the normalizer digest, so re-running ``normalize`` after any edit adds a second build next to
the one an earlier release pinned, even when every output byte is identical.

    norm_twins.py [--norm DIR]                                   audit only; changes nothing
    norm_twins.py [--norm DIR] --apply --quarantine DIR          move the newer, byte-identical builds aside

A bucket is *repairable* when all its builds carry identical ``outputs`` pins: the oldest build stays
(earlier releases pin it) and every newer one is moved, never deleted, to ``DIR/<bucket>/<build>``;
``DIR/moved-<UTC time>.json`` lists each move so it can be undone. A bucket whose builds disagree on
their outputs is a *conflict*: nothing is moved (in any bucket) and the exit code is 1 so a person decides.
Exit codes: 0 no bucket has twins (or all repaired), 1 conflict (or a refused path), 2 repairable twins
remain (audit mode). Nothing here normalizes, downloads or publishes.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sys

HEX64 = re.compile(r'[0-9a-f]{64}')
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


def audit(norm):
    """Return (repairable, conflicts): {bucket: [build names, oldest first]} / {bucket: [build names]}."""
    repairable, conflicts = {}, {}
    for bucket in sorted(p for p in norm.iterdir() if HEX64.fullmatch(p.name) and p.is_dir() and not p.is_symlink()):
        builds = _builds(bucket)
        if len(builds) < 2:
            continue
        docs = {}
        for build in builds:
            try:
                docs[build.name] = json.loads((build / 'sidecar.json').read_text())
            except (OSError, ValueError):
                docs[build.name] = None
        outputs = {json.dumps(d.get('outputs'), sort_keys=True) if isinstance(d, dict) else None for d in docs.values()}
        names = [b.name for b in sorted(builds, key=lambda b: ((b / 'sidecar.json').stat().st_mtime_ns, b.name))]
        if len(outputs) == 1 and None not in outputs:
            repairable[bucket.name] = names
        else:
            conflicts[bucket.name] = names
    return repairable, conflicts


def quarantine(norm, repairable, destination):
    destination.mkdir(parents=True, exist_ok=True)
    moves = []
    for bucket, names in repairable.items():
        for name in names[1:]:  # names[0] is the oldest build: it stays.
            target = destination / bucket / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise SystemExit(f'norm_twins: {target} already exists: refused')
            shutil.move(str(norm / bucket / name), str(target))
            moves.append({'from': str(norm / bucket / name), 'to': str(target)})
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    (destination / f'moved-{stamp}.json').write_text(json.dumps({'moves': moves}, indent=1) + '\n')
    return moves


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
