"""Bind a SHA-256-pinned census as a local input to relief selection."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile

from . import receipts


class BindError(ValueError):
    """The requested binding could not be admitted."""


def _not_json(value):
    raise ValueError(f'{value} is not JSON')


def _validate_census(data, region):
    try:
        doc = json.loads(data, parse_constant=_not_json)
    except (ValueError, RecursionError) as exc:
        raise BindError('source is not valid JSON') from exc
    summary = doc.get('summary') if isinstance(doc, dict) else None
    if not isinstance(summary, dict) or not isinstance(summary.get('region'), str):
        raise BindError('census requires summary.region')
    if summary['region'] != region:
        raise BindError('census region mismatch')
    files = doc.get('files')
    if not isinstance(files, list) or any(
        not isinstance(row, dict) or not isinstance(row.get('path'), str) or not row['path']
        for row in files
    ):
        raise BindError('census requires a files list of rows with paths')


def _already_bound(region, census, data, digest):
    producer = region.receipt_path('census')
    for path in (region.dir, region.stages_dir, producer, census):
        if path.is_symlink():
            raise BindError(f'symlink refused: {path}')
    # Use select's pin rules, including the local producer's absolute output path.
    # Never read the paths named inside the receipt; only compare them.
    pinned = receipts.read_receipt(producer)
    if pinned is not None:
        outputs = pinned.get('outputs')
        if (pinned.get('stage') != 'census' or pinned.get('region') != region.id
                or pinned.get('status') != 'ok' or not isinstance(outputs, list)
                or not any(isinstance(row, dict) and row.get('path') in (str(census), 'census.json')
                           and row.get('sha256') == digest for row in outputs)):
            raise BindError('census receipt does not pin this region census')
    try:
        current = census.read_bytes()
    except FileNotFoundError:
        return False
    if current != data:
        raise BindError('destination census has different bytes')
    return True


def _write_atomic(path, data):
    with NamedTemporaryFile(dir=path.parent, prefix=f'.{path.name}.', delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)


def bind(region, source_path, sha256):
    """Bind once, returning without writes for an identical admitted input."""
    expected = sha256.lower()
    if not receipts.HEX64.fullmatch(expected):
        raise BindError('expected a 64-digit hexadecimal SHA-256')
    source = Path(source_path).expanduser()
    data = source.read_bytes()
    digest = receipts.sha256_bytes(data)
    if digest != expected:
        raise BindError('source SHA-256 mismatch')
    _validate_census(data, region.id)

    census = region.dir / 'census.json'
    binding = region.receipt_path('census_bind')
    pending = region.stages_dir / '.census_bind.pending'
    already_bound = _already_bound(region, census, data, digest)
    if pending.is_symlink():
        raise BindError(f'symlink refused: {pending}')
    if already_bound and not pending.exists():
        return
    if binding.is_symlink():
        raise BindError(f'symlink refused: {binding}')
    if source.resolve() in (binding, pending):
        raise BindError('source cannot also be the binding record')
    region.dir.mkdir(parents=True, exist_ok=True)
    # Serialize binders without creating a lock file on the idempotent path.
    fd = os.open(region.dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        already_bound = _already_bound(region, census, data, digest)
        if pending.is_symlink():
            raise BindError(f'symlink refused: {pending}')
        if pending.exists():
            record = pending.read_bytes()
            try:
                saved = json.loads(record)
            except (ValueError, RecursionError) as exc:
                raise BindError('invalid pending binding record') from exc
            if (not isinstance(saved, dict) or saved.get('region') != region.id
                    or saved.get('source_sha256') != digest or saved.get('size') != len(data)):
                raise BindError('pending binding record does not match census')
        elif already_bound:
            return
        else:
            record = receipts.canonical({'region': region.id, 'source_path': source_path,
                                         'source_sha256': digest, 'size': len(data),
                                         'time': receipts.iso(receipts.utc_now())}) + b'\n'
            region.stages_dir.mkdir(exist_ok=True)
            # Persist intent before installing the census, so a retry can finish
            # the record without backfilling genuinely pre-existing copies.
            _write_atomic(pending, record)
        if not already_bound:
            _write_atomic(census, data)
        _write_atomic(binding, record)
        pending.unlink()
    finally:
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(prog='region.py census-bind', description=__doc__)
    parser.add_argument('--region', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--from', dest='source', required=True)
    parser.add_argument('--sha256', required=True)
    args = parser.parse_args(argv)
    try:
        bind(receipts.Region(args.out, args.region), args.source, args.sha256)
    except (OSError, ValueError) as exc:
        print(f'census-bind: {exc}', file=sys.stderr)
        return 1
    return 0
