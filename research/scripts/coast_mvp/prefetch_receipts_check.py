"""Offline, metadata-only S-029 checker; never imports or runs the downloader.

Source shape: coastal/prefetch.py final manifest rows (536-542), inventory
(117-160), status (359-363), baseline 35cfd0ecefce1c9ad3819b73d6dc775677d8d9fe.
Operator disposition on t_91f0c26c, 2026-10-24 11:44 PDT supersedes the
original all-green requirement: producer evidence cannot establish pass caps
or request history. Final-file sizes are NOT received bytes (retries/resumes).

CLI inputs are explicit sanitized copies inside --input-root. Receipts is a
directory of *.jsonl manifests (including per-source subdirectories). Inventory
is the existing schema_version=1/files plan. Reviewed hosts is a supplied JSON
array of exact DNS hostnames, not a replacement for any operational allowlist.
Receipt path is opaque provenance: no payload is opened or hashed. Hash PASS
means receipt SHA256 and byte count agree with supplied inventory, NOT a fresh
payload verification, publisher authentication or semantic acceptance.

The optional --synthetic-accounting file is ONLY a comparator test input:
  {"schema": "s029-synthetic-received-v1", "synthetic": true,
   "received_bytes": <nonnegative integer>}
It is deliberately not a producer/status field. Its cap row is explicitly
SYNTHETIC_ONLY and cannot qualify a real pass. All other unsupported gates stay
HELD even with that record. There is no supported all-PASS real-prefetch path.

Output has exactly one row per gate. Exit 1 on any FAIL, else 3 on any HELD,
else 0. NOT_ESTABLISHED never means zero. No writes, fetches, DNS, retry,
registry edits, service actions, or new downloader/status flags exist here.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import hashlib
import json
import os
from pathlib import PurePosixPath
import re
import stat
from urllib.parse import urlsplit

RECEIVED_CAP_BYTES = 80_000_000_000
RAW_GROWTH_CAP_BYTES = 100_000_000_000
DURATION_CAP_SECONDS = 86_400
REQUESTS_PER_HOST_CAP = 2
# Local parser bounds, not download-policy caps.
MAX_METADATA_BYTES = 16 * 1024 * 1024
MAX_METADATA_FILES = 10_000
SHA = re.compile(r'[a-f0-9]{64}\Z')
HOST = re.compile(r'(?=.{1,253}\Z)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?'
                  r'(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+\Z')
SEGMENTS = frozenset(('C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'C7a', 'C7b',
                      'S1', 'S2', 'S3', 'S4', 'S5', 'S6',
                      'N1', 'N2', 'N3', 'N4', 'N5', 'N6', 'N6b', 'N7'))
GATES = ('input_schema', 'receipt_schema', 'inventory_coverage',
         'sha256_inventory', 'bytes_inventory', 'reviewed_endpoint_hosts',
         'received_bytes', 'raw_growth', 'duration', 'requests_per_host',
         'contact_history', 'retry_pacing')


class Invalid(ValueError):
    """Invalid or unsafe metadata; no retry is performed."""


def nonnegative_int(value):
    return type(value) is int and value >= 0


def sha(value):
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def text(value):
    return isinstance(value, str) and bool(value.strip())


def endpoint_host(value):
    if not text(value) or any(ord(c) <= 32 or ord(c) == 127 for c in value):
        raise Invalid('URL must be unambiguous HTTPS metadata')
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if (parsed.scheme != 'https' or parsed.username is not None
                or parsed.password is not None or parsed.fragment
                or parsed.port not in (None, 443) or not host
                or not HOST.fullmatch(host)):
            raise Invalid('Invalid HTTPS endpoint')
    except ValueError as exc:
        raise Invalid('Invalid HTTPS endpoint') from exc
    return host


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise Invalid('Duplicate JSON key')
        result[key] = value
    return result


def parse_json(data):
    def invalid_constant(value):
        raise Invalid('Non-finite JSON value')
    try:
        return json.loads(data, object_pairs_hook=unique_object,
                          parse_constant=invalid_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Invalid('Malformed JSON metadata') from exc


def relative_parts(value):
    if (not isinstance(value, str) or not value or '\\' in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise Invalid('Expected root-relative metadata path')
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ('', '.', '..') for p in value.split('/')):
        raise Invalid('Unsafe metadata path')
    return path.parts


@contextmanager
def directory_at(parent, parts):
    """Descriptor-relative no-follow traversal; reject intermediate/leaf links."""
    fd = os.dup(parent)
    try:
        for part in parts:
            new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = new
        yield fd
    finally:
        os.close(fd)


class Metadata:
    def __init__(self, root_fd):
        self.root_fd = root_fd
        self.bindings = []

    def read_at(self, parent, name, label):
        if len(self.bindings) >= MAX_METADATA_FILES:
            raise Invalid('Metadata file count exceeded')
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            before = os.fstat(fd)
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_METADATA_BYTES:
                raise Invalid('Expected bounded regular metadata file')
            with os.fdopen(fd, 'rb', closefd=False) as stream:
                data = stream.read(MAX_METADATA_BYTES + 1)
            after = os.fstat(fd)
            if (len(data) > MAX_METADATA_BYTES or len(data) != before.st_size
                    or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
                raise Invalid('Metadata changed or exceeded size bound')
        finally:
            os.close(fd)
        self.bindings.append({'path': label, 'sha256': hashlib.sha256(data).hexdigest(),
                              'bytes': len(data)})
        return data

    def json(self, name):
        parts = relative_parts(name)
        with directory_at(self.root_fd, parts[:-1]) as fd:
            return parse_json(self.read_at(fd, parts[-1], name))

    def manifests(self, name):
        parts = relative_parts(name)
        result = []

        def visit(fd, prefix, depth):
            if depth > 32:
                raise Invalid('Metadata directory depth exceeded')
            for entry in sorted(os.listdir(fd)):
                mode = os.stat(entry, dir_fd=fd, follow_symlinks=False).st_mode
                label = prefix + '/' + entry
                if stat.S_ISLNK(mode) or not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
                    raise Invalid('Symlink or special metadata entry refused')
                if stat.S_ISDIR(mode):
                    with directory_at(fd, (entry,)) as child:
                        visit(child, label, depth + 1)
                elif entry.endswith('.jsonl'):
                    data = self.read_at(fd, entry, label)
                    for line in data.splitlines():
                        if not line.strip():
                            raise Invalid('Blank manifest record')
                        result.append(parse_json(line))
        with directory_at(self.root_fd, parts) as fd:
            visit(fd, name, 0)
        return result


def validate_inventory(plan):
    if (not isinstance(plan, dict) or type(plan.get('schema_version')) is not int
            or plan['schema_version'] != 1 or not isinstance(plan.get('files'), list)
            or not isinstance(plan.get('unresolved', []), list)):
        raise Invalid('Expected producer schema_version=1/files inventory')
    indexed = {}
    for row in plan['files']:
        if not isinstance(row, dict):
            raise Invalid('Inventory row is not an object')
        endpoint_host(row.get('url'))
        if (not isinstance(row.get('source'), str)
                or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', row['source'])
                or not text(row.get('licence')) or not valid_segments(row.get('segments'))
                or (row.get('bytes') is not None and
                    (not nonnegative_int(row['bytes']) or row['bytes'] == 0))
                or (row.get('sha256') is not None and not sha(row['sha256']))):
            raise Invalid('Malformed inventory row')
        # Exact duplicates can arise from segment association; conflicting identity cannot.
        old = indexed.get(row['url'])
        if old and any(old.get(k) != row.get(k) for k in ('source', 'bytes', 'sha256', 'licence')):
            raise Invalid('Conflicting inventory identity')
        indexed[row['url']] = row
    return indexed


def valid_segments(value):
    return (isinstance(value, list) and bool(value)
            and all(isinstance(v, str) and v in SEGMENTS for v in value))


def valid_receipt(row):
    if not isinstance(row, dict):
        return False
    try:
        endpoint_host(row.get('url'))
        endpoint_host(row.get('final_url'))
        fetched = datetime.fromisoformat(row.get('fetched_at', ''))
        return (sha(row.get('sha256')) and nonnegative_int(row.get('bytes'))
                and row['bytes'] > 0 and text(row.get('path'))
                and PurePosixPath(row['path']).is_absolute()
                and row.get('review_required') is True
                and row.get('verification') in ('publisher-sha256', 'http-size-and-local-sha256')
                and text(row.get('licence')) and valid_segments(row.get('segments'))
                and 'etag' in row and (row['etag'] is None or isinstance(row['etag'], str))
                and 'last_modified' in row
                and (row['last_modified'] is None or isinstance(row['last_modified'], str))
                and fetched.tzinfo is not None)
    except (ValueError, TypeError):
        return False


def cap_comparison(record):
    """Only admitted synthetic accounting schema; never a real pass attestation."""
    if (not isinstance(record, dict)
            or set(record) != {'schema', 'synthetic', 'received_bytes'}
            or record['schema'] != 's029-synthetic-received-v1'
            or record['synthetic'] is not True
            or not nonnegative_int(record['received_bytes'])):
        raise Invalid('Malformed synthetic accounting record')
    return 'PASS' if record['received_bytes'] <= RECEIVED_CAP_BYTES else 'FAIL'


def exit_code(rows):
    states = [r['status'] for r in rows]
    if any(state not in ('PASS', 'FAIL', 'HELD') for state in states):
        raise Invalid('Unknown gate state')
    return 1 if 'FAIL' in states else 3 if not states or 'HELD' in states else 0


def check(input_root, *, receipts='receipts', inventory='inventory.json',
          reviewed_hosts='reviewed-hosts.json', synthetic_accounting=None):
    rows = {gate: {'gate': gate, 'status': 'HELD', 'reason': 'NOT_ESTABLISHED'}
            for gate in GATES}

    def set_gate(gate, state, reason, **extra):
        rows[gate] = {'gate': gate, 'status': state, 'reason': reason, **extra}

    bindings = []
    try:
        root = os.fspath(input_root)
        if not os.path.isabs(root):
            raise Invalid('Input root must be absolute')
        # Open each absolute-root component without following links, before any read.
        parts = relative_parts(root[1:])
        base = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
        try:
            with directory_at(base, parts) as fd:
                metadata = Metadata(fd)
                bindings = metadata.bindings
                plan = metadata.json(inventory)
                hosts = metadata.json(reviewed_hosts)
                if (not isinstance(hosts, list) or not hosts or
                        any(not isinstance(h, str) or not HOST.fullmatch(h) for h in hosts)
                        or len(set(hosts)) != len(hosts)):
                    raise Invalid('Expected nonempty unique exact reviewed-host list')
                indexed = validate_inventory(plan)
                records = metadata.manifests(receipts)
                accounting = metadata.json(synthetic_accounting) if synthetic_accounting is not None else {}
        finally:
            os.close(base)
        set_gate('input_schema', 'PASS', 'SUPPORTED_SANITIZED_METADATA')
        if records:
            if not all(valid_receipt(row) for row in records):
                set_gate('receipt_schema', 'FAIL', 'MALFORMED_RECEIPT')
            elif len({r['url'] for r in records}) != len(records):
                set_gate('receipt_schema', 'FAIL', 'DUPLICATE_RECEIPT_IDENTITY')
            else:
                set_gate('receipt_schema', 'PASS', 'PRODUCER_SHAPE')
                covered = {r['url'] for r in records}
                coverage = covered == set(indexed) and not plan.get('unresolved')
                set_gate('inventory_coverage', 'PASS' if coverage else 'FAIL',
                         'EXACT_INVENTORY_COVERAGE' if coverage else 'INVENTORY_COVERAGE_MISMATCH')
                hashes = all(r['url'] in indexed and sha(indexed[r['url']].get('sha256'))
                             and r['sha256'] == indexed[r['url']]['sha256'] for r in records)
                sizes = all(r['url'] in indexed and indexed[r['url']].get('bytes') == r['bytes']
                            for r in records)
                set_gate('sha256_inventory', 'PASS' if hashes else 'FAIL',
                         'RECEIPT_MATCHES_INVENTORY' if hashes else 'UNVERIFIED_OR_MISMATCHED_HASH')
                set_gate('bytes_inventory', 'PASS' if sizes else 'FAIL',
                         'RECEIPT_MATCHES_INVENTORY' if sizes else 'UNVERIFIED_OR_MISMATCHED_SIZE')
                allowed = all(endpoint_host(r[k]) in hosts for r in records for k in ('url', 'final_url'))
                set_gate('reviewed_endpoint_hosts', 'PASS' if allowed else 'FAIL',
                         'ENDPOINTS_ONLY_NO_CONTACT_HISTORY' if allowed else 'EXCLUDED_ENDPOINT_HOST')
        if synthetic_accounting is not None:
            state = cap_comparison(accounting)
            set_gate('received_bytes', state, 'SYNTHETIC_ONLY',
                     evidence_scope='synthetic_comparator_not_prefetch_qualification',
                     measured=accounting['received_bytes'], limit=RECEIVED_CAP_BYTES)
    except (Invalid, OSError, TypeError, RecursionError) as exc:
        set_gate('input_schema', 'FAIL', 'INVALID_OR_UNSAFE_METADATA',
                 error_type=type(exc).__name__)
    output_rows = list(rows.values())
    return {'schema_version': 1, 'review_required': True, 'semantic_approval': False,
            'prefetch_qualified': False,
            'note': 'Metadata comparison only. Missing evidence is not zero; holds remain.',
            'limits': {'received_bytes': RECEIVED_CAP_BYTES, 'raw_growth_bytes': RAW_GROWTH_CAP_BYTES,
                       'duration_seconds': DURATION_CAP_SECONDS, 'requests_per_host': REQUESTS_PER_HOST_CAP},
            'inputs': sorted(bindings, key=lambda b: b['path']),
            'gates': output_rows, 'exit_code': exit_code(output_rows)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-root', required=True)
    parser.add_argument('--receipts', default='receipts')
    parser.add_argument('--inventory', default='inventory.json')
    parser.add_argument('--reviewed-hosts', default='reviewed-hosts.json')
    parser.add_argument('--synthetic-accounting')
    args = parser.parse_args(argv)
    report = check(args.input_root, receipts=args.receipts, inventory=args.inventory,
                   reviewed_hosts=args.reviewed_hosts, synthetic_accounting=args.synthetic_accounting)
    print(json.dumps(report, sort_keys=True, indent=2))
    return report['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())
