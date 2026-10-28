"""Acyclic, locked campaign ledger and idempotent independently chained index.

Only write_verdict.py and archive_segment.py may call append; writer is a declared
ownership check, not a substitute for filesystem permissions or exclusive control.
"""
import argparse
import fcntl
import os
from pathlib import Path
import sys

from coast_refs import canonical, directory_fd, loads, sha256

GENESIS = '0' * 64
WRITERS = {'verdict': 'write_verdict.py', 'archived': 'archive_segment.py'}


def idempotency_key(row):
    if row['kind'] == 'verdict':
        return tuple(row[k] for k in ('kind','campaign_segment_id','plan_sha256','review_round','attempt'))
    return row['kind'], row['close_id']


def verify_bytes(raw):
    from validate_coast_receipt import validate_schema, _consistency
    rows = []
    previous = GENESIS
    keys = set()
    for i, line in enumerate(raw.splitlines(keepends=True), 1):
        if not line.endswith(b'\n'):
            raise ValueError('ledger truncated: missing final newline')
        row = loads(line)
        validate_schema(row)
        _consistency(row)
        if row['schema'] != 'coast-segment-ledger-v1' or canonical(row) != line:
            raise ValueError('ledger requires canonical coast ledger lines')
        if row['seq'] != i or row['prev_row_sha256'] != previous:
            raise ValueError('ledger sequence/previous-line hash mismatch')
        key = idempotency_key(row)
        if key in keys:
            raise ValueError('duplicate ledger idempotency key')
        keys.add(key)
        rows.append(row)
        previous = sha256(line)
    return rows


def _read(fd):
    os.lseek(fd, 0, os.SEEK_SET)
    chunks = []
    while chunk := os.read(fd, 1024 * 1024):
        chunks.append(chunk)
    return b''.join(chunks)


def verify(path):
    path = Path(path).absolute()
    with directory_fd(path.parent) as parent:
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            import stat
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError('ledger must be regular')
            return verify_bytes(_read(fd))
        finally:
            os.close(fd)


def append(path, payload, *, writer, resolver, root_id, raw_provenance=()):
    """Return exact existing/new row plus its full-line hash; retries never rewrite.

    Callers supply immutable payload WITHOUT seq/prev_row_sha256. An interrupted
    segment/index pair can be reconciled by repeating append_index with identical
    metadata; index failure must never be announced as accepted/archived.
    raw_provenance is the explicit up-front envelope union (admission
    sources[*].raw_provenance, selected and superseded) forwarded unchanged to
    validate(); it is never discovered here.
    """
    if writer != WRITERS.get(payload.get('kind')):
        raise ValueError('ledger writer does not own this row kind')
    if 'seq' in payload or 'prev_row_sha256' in payload:
        raise ValueError('ledger assigns sequence and previous-line hash')
    path = Path(path).absolute()
    with directory_fd(path.parent) as parent:
        lock = os.open(path.name + '.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent)
        try:
            import stat
            if not stat.S_ISREG(os.fstat(lock).st_mode) or os.fstat(lock).st_nlink != 1:
                raise ValueError('ledger lock must be regular with no hardlink aliases')
            fcntl.flock(lock, fcntl.LOCK_EX)
            fd = os.open(path.name, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent)
            try:
                import stat
                if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_nlink != 1:
                    raise ValueError('ledger must be regular with no hardlink aliases')
                raw = _read(fd)
                rows = verify_bytes(raw)
                key = idempotency_key(payload)
                for existing in rows:
                    if idempotency_key(existing) == key:
                        content = {k:v for k,v in existing.items() if k not in ('seq','prev_row_sha256')}
                        if canonical(content) != canonical(payload):
                            raise ValueError('same ledger key with different payload')
                        from validate_coast_receipt import validate
                        validate(existing,resolver,root_id=root_id,raw_provenance=raw_provenance)
                        return existing, sha256(canonical(existing))
                row = dict(payload,seq=len(rows)+1,prev_row_sha256=sha256(raw.splitlines(keepends=True)[-1]) if rows else GENESIS)
                from validate_coast_receipt import validate
                validate(row,resolver,root_id=root_id,raw_provenance=raw_provenance)
                line = canonical(row)
                # O_APPEND + flock serializes cooperating writers. A short write
                # is a preserved corrupt tail, never silently retried or repaired.
                if os.write(fd,line) != len(line):
                    raise OSError('partial ledger append; explicit reconciliation required')
                os.fsync(fd)
                os.fsync(parent)
                return row,sha256(line)
            finally:
                os.close(fd)
        finally:
            os.close(lock)


def _same_ledger_destination(segment_path, campaign_path):
    """Compare lexical destinations only; append owns physical path checks."""
    return os.path.abspath(segment_path) == os.path.abspath(campaign_path)


def append_index(segment_path, campaign_path, payload, *, writer, resolver, root_id, raw_provenance=()):
    if _same_ledger_destination(segment_path, campaign_path):
        raise ValueError('distinct_segment_campaign_ledgers_required')
    if payload.get('ledger_role') != 'segment' or payload.get('segment_row_sha256') is not None:
        raise ValueError('append_index requires segment payload')
    row, digest = append(segment_path,payload,writer=writer,resolver=resolver,root_id=root_id,raw_provenance=raw_provenance)
    index = dict(payload,ledger_role='campaign',segment_row_sha256=digest)
    index_row,index_digest = append(campaign_path,index,writer=writer,resolver=resolver,root_id=root_id,raw_provenance=raw_provenance)
    return dict(segment_row=row,segment_row_sha256=digest,campaign_row=index_row,campaign_row_sha256=index_digest)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command',required=True)
    check = sub.add_parser('verify')
    check.add_argument('ledger',type=Path)
    args = parser.parse_args(argv)
    try:
        rows=verify(args.ledger)
        print(f'chain_valid rows={len(rows)} scientific_acceptance=false')
        return 0
    except (ValueError,OSError,KeyError,TypeError) as error:
        print(str(error),file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
