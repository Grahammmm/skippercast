#!/usr/bin/env python3
"""Stamp or verify an offline handoff without interpreting the plan or inputs.

Save the JSON from `emit` unchanged and supply it to `verify --stamp FILE`
alongside the current plan and role assignments. Verification checks byte
identity, not provenance, approval, or permission to run a rebuild.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys


def _input(value: str) -> tuple[str, Path]:
    role, _, path = value.partition('=')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', role) or not path:
        raise argparse.ArgumentTypeError('expected ROLE=PATH with a nonempty role and path')
    return role, Path(path)


def _sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _stamp(plan: Path, inputs: dict[str, Path]) -> bytes:
    doc = {
        'format': 'rebuild-plan-stamp/v1',
        'plan_sha256': _sha256(plan),
        'inputs': [[role, _sha256(path)] for role, path in sorted(inputs.items())],
    }
    return (json.dumps(doc, indent=2) + '\n').encode('utf-8')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    emit = commands.add_parser('emit', help='write the handoff stamp to stdout')
    verify = commands.add_parser('verify', help='compare with an unchanged stamp from emit')
    verify.add_argument('--stamp', required=True, type=Path, help='saved stamp file')
    for command in (emit, verify):
        command.add_argument('--plan', required=True, type=Path, help='saved plan file')
        command.add_argument('--input', required=True, action='append', type=_input,
                             metavar='ROLE=PATH', help='explicit input file (repeatable)')
    args = parser.parse_args(argv)

    inputs = dict(args.input)
    if len(inputs) != len(args.input):
        parser.error('duplicate input role')
    try:
        current = _stamp(args.plan, inputs)
        if args.command == 'emit':
            sys.stdout.buffer.write(current)
            return 0
        if args.stamp.read_bytes() == current:
            print('Handoff stamp matches')
            return 0
    except OSError as exc:
        parser.error(str(exc))
    print('Handoff stamp mismatch', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
