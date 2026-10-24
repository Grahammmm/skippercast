"""Read-only per-source/grid composition report for a fixed coast-sample-v1 sample.

The report explains which source_id + grid_sha256 groups a supplied deterministic
sample includes. It recomputes the selection with the unchanged producer function
(skills/coast-campaign-shared/scripts/coast_sample.py: sample) only to reject a
tampered document; it never emits a newly chosen sample, applies quotas or minimums,
resamples, or calls a model. Composition is not source quality, coverage, eligibility
proof or scientific acceptance. See docs/engineering/sc_sample_audit.md.

CLI: sample_coverage.py --sample FILE --plan-sha256 HEX --bridge-sha256 HEX --out NEWFILE
Exit 0 report written; 3 INVALID document/bindings; 4 refused path/size/output; 2 usage.
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import stat
import sys

METHOD_VERSION = 'coast-sample-v1'
REPORT_VERSION = 'sc-sample-audit-v1'
VERDICT = 'COMPOSITION_REPORTED_REVIEW_REQUIRED'
WARNING = ('Sample composition only: this is not source quality, coverage, eligibility proof '
           'or scientific acceptance, and it grants no admission, hold release or review tier.')
DOCUMENT_FIELDS = ('method_version', 'seed', 'target', 'size', 'map_done', 'eligible', 'selected')
POPULATIONS = ('map_done', 'eligible', 'selected')
GROUP_FIELDS = ('map_done', 'eligible', 'selected', 'eligible_unselected', 'ineligible')

# Tool-local denial-of-service bounds for this new report only.
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_AGGREGATE_BYTES = 16 * 1024 * 1024
MAX_ROWS = 4096
MAX_OUTPUT_BYTES = 8 * 1024 * 1024

EXIT_OK = 0
EXIT_INVALID = 3
EXIT_REFUSED = 4

ROOT = Path(__file__).resolve().parents[2]
PRODUCER_PATH = ROOT / 'skills' / 'coast-campaign-shared' / 'scripts' / 'coast_sample.py'
_PRODUCER_MODULE = '_sc_sample_audit_coast_sample'
_HEX = frozenset('0123456789abcdef')


class SampleAuditInvalid(ValueError):
    """The supplied sample document, bindings or report failed a named check."""

    def __init__(self, reason, detail=''):
        super().__init__('%s: %s' % (reason, detail) if detail else reason)
        self.reason = reason


class SampleAuditRefused(OSError):
    """A path, size or output-write precondition refused the operation before use."""

    def __init__(self, reason, detail=''):
        super().__init__('%s: %s' % (reason, detail) if detail else reason)
        self.reason = reason


def _load_producer():
    module = sys.modules.get(_PRODUCER_MODULE)
    if module is not None:
        return module
    spec = importlib.util.spec_from_file_location(_PRODUCER_MODULE, PRODUCER_PATH)
    if spec is None or spec.loader is None:
        raise ImportError('coast_sample producer not loadable')
    module = importlib.util.module_from_spec(spec)
    sys.modules[_PRODUCER_MODULE] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(_PRODUCER_MODULE, None)
        raise
    return module


def producer_sample_function():
    return _load_producer().sample


def _is_sha256(value):
    return isinstance(value, str) and len(value) == 64 and set(value) <= _HEX


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False,
                      ensure_ascii=True).encode('ascii')


def decode_key(key):
    """Split source_id#grid_sha256#index on the LAST two separators; reject noncanonical keys."""
    if not isinstance(key, str):
        raise SampleAuditInvalid('bad_type', 'window key must be a string')
    parts = key.rsplit('#', 2)
    if len(parts) != 3:
        raise SampleAuditInvalid('malformed_key', repr(key[:80]))
    source_id, grid, index = parts
    if not source_id or not _is_sha256(grid):
        raise SampleAuditInvalid('malformed_key', repr(key[:80]))
    if not index or not index.isascii() or not index.isdigit() or (len(index) > 1 and index[0] == '0'):
        raise SampleAuditInvalid('malformed_key', repr(key[:80]))
    try:
        rebuilt = _load_producer().window_key(source_id, grid, int(index))
    except ValueError as error:
        raise SampleAuditInvalid('malformed_key', str(error)) from None
    if rebuilt != key:
        raise SampleAuditInvalid('malformed_key', 'noncanonical ' + repr(key[:80]))
    return source_id, grid, int(index)


def _validate_shape(document):
    if not isinstance(document, dict):
        raise SampleAuditInvalid('bad_type', 'sample document must be an object')
    try:
        size = len(canonical_bytes(document))
    except (TypeError, ValueError) as error:
        raise SampleAuditInvalid('bad_type', 'not canonical JSON: %s' % error) from None
    if size > MAX_FILE_BYTES:
        raise SampleAuditInvalid('input_too_large', '%d bytes' % size)
    for field in DOCUMENT_FIELDS:
        if field not in document:
            raise SampleAuditInvalid('missing_field', field)
    extra = sorted(set(document) - set(DOCUMENT_FIELDS))
    if extra:
        raise SampleAuditInvalid('unexpected_field', ','.join(map(str, extra))[:200])
    if not isinstance(document['method_version'], str) or not isinstance(document['seed'], str):
        raise SampleAuditInvalid('bad_type', 'method_version/seed must be strings')
    for field in ('target', 'size'):
        if type(document[field]) is not int:
            raise SampleAuditInvalid('bad_type', field + ' must be an integer')
    for field in POPULATIONS:
        values = document[field]
        if not isinstance(values, list) or any(not isinstance(k, str) for k in values):
            raise SampleAuditInvalid('bad_type', field + ' must be a list of strings')
    if len(document['map_done']) > MAX_ROWS or len(document['eligible']) > MAX_ROWS \
            or len(document['selected']) > MAX_ROWS:
        raise SampleAuditInvalid('row_cap_exceeded', 'max %d keys per population' % MAX_ROWS)


def _verify(document, plan_sha256, bridge_sha256):
    """Reject anything that is not exactly the producer output for these bindings."""
    _validate_shape(document)
    if not _is_sha256(plan_sha256) or not _is_sha256(bridge_sha256):
        raise SampleAuditInvalid('invalid_binding', 'plan/bridge must be lowercase SHA256 hex')
    if document['method_version'] != METHOD_VERSION:
        raise SampleAuditInvalid('method_mismatch', document['method_version'][:80])
    for field in POPULATIONS:
        if len(set(document[field])) != len(document[field]):
            raise SampleAuditInvalid('duplicate_key', field)
    decoded = {}
    for field in POPULATIONS:
        for key in document[field]:
            decoded[key] = decode_key(key)
    for field in POPULATIONS:
        if document[field] != sorted(document[field]):
            raise SampleAuditInvalid('not_canonical_order', field)
    done, eligible, selected = (set(document[f]) for f in POPULATIONS)
    if not eligible <= done:
        raise SampleAuditInvalid('eligible_not_in_map_done', '%d keys' % len(eligible - done))
    try:
        expected = producer_sample_function()(document['map_done'], document['eligible'],
                                              plan_sha256=plan_sha256, bridge_sha256=bridge_sha256)
    except ValueError as error:
        raise SampleAuditInvalid('producer_rejected', str(error)) from None
    if document['seed'] != expected['seed']:
        raise SampleAuditInvalid('seed_mismatch', 'seed does not match plan/bridge bindings')
    if document['target'] != expected['target']:
        raise SampleAuditInvalid('target_mismatch', '%d != %d' % (document['target'], expected['target']))
    if document['size'] != expected['size'] or len(document['selected']) != expected['size']:
        raise SampleAuditInvalid('size_mismatch', 'expected %d' % expected['size'])
    if not selected <= eligible:
        raise SampleAuditInvalid('selected_not_eligible', '%d keys' % len(selected - eligible))
    if document['selected'] != expected['selected']:
        raise SampleAuditInvalid('selected_mismatch', 'selected list is not the deterministic selection')
    if canonical_bytes(expected) != canonical_bytes(document):
        raise SampleAuditInvalid('document_mismatch', 'document differs from producer output')
    return decoded


def _build_groups(document, decoded):
    eligible, selected = set(document['eligible']), set(document['selected'])
    groups = {}
    for key in document['map_done']:
        source_id, grid, _ = decoded[key]
        row = groups.setdefault((source_id, grid), {f: [] for f in GROUP_FIELDS})
        row['map_done'].append(key)
        if key in eligible:
            row['eligible'].append(key)
            row['selected' if key in selected else 'eligible_unselected'].append(key)
        else:
            row['ineligible'].append(key)
    rows = []
    for (source_id, grid) in sorted(groups):
        populations = groups[(source_id, grid)]
        row = {'source_id': source_id, 'grid_sha256': grid}
        for field in GROUP_FIELDS:
            keys = sorted(populations[field])
            row[field] = keys
            row[field + '_count'] = len(keys)
        rows.append(row)
    return rows


def _check_complete(groups, document, decoded):
    """Report completeness gate: every key lands in exactly one group, totals reconcile."""
    seen = {f: [] for f in GROUP_FIELDS}
    for row in groups:
        for field in GROUP_FIELDS:
            if row[field + '_count'] != len(row[field]):
                raise SampleAuditInvalid('report_incomplete', 'count mismatch')
            seen[field].extend(row[field])
    for field in POPULATIONS:
        if sorted(seen[field]) != document[field]:
            raise SampleAuditInvalid('report_incomplete', field)
    expected_pairs = sorted({decoded[k][:2] for k in document['map_done']})
    if [(r['source_id'], r['grid_sha256']) for r in groups] != expected_pairs:
        raise SampleAuditInvalid('report_incomplete', 'groups')
    eligible = set(document['eligible'])
    if sorted(seen['ineligible']) != sorted(k for k in document['map_done'] if k not in eligible):
        raise SampleAuditInvalid('report_incomplete', 'ineligible')
    if sorted(seen['eligible_unselected']) != sorted(eligible - set(document['selected'])):
        raise SampleAuditInvalid('report_incomplete', 'eligible_unselected')
    return {f: len(seen[f]) for f in GROUP_FIELDS}


def audit_sample(sample_document, plan_sha256, bridge_sha256):
    """Return the composition report for a verified coast-sample-v1 document (no mutation)."""
    decoded = _verify(sample_document, plan_sha256, bridge_sha256)
    groups = _build_groups(sample_document, decoded)
    totals = _check_complete(groups, sample_document, decoded)
    totals['groups'] = len(groups)
    return {
        'report_version': REPORT_VERSION,
        'method_version': METHOD_VERSION,
        'verdict': VERDICT,
        'warning': WARNING,
        'input_sha256': hashlib.sha256(canonical_bytes(sample_document)).hexdigest(),
        'bindings': {'plan_sha256': plan_sha256, 'bridge_sha256': bridge_sha256,
                     'seed': sample_document['seed']},
        'sample': {'target': sample_document['target'], 'size': sample_document['size'],
                   'selected': list(sample_document['selected'])},
        'populations': {f: 'PRESENT' if sample_document[f] else 'EMPTY' for f in POPULATIONS},
        'totals': totals,
        'groups': groups,
    }


def _reject_nonfinite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise SampleAuditInvalid('nonfinite_output')
    if isinstance(value, dict):
        for item in value.values():
            _reject_nonfinite(item)
    elif isinstance(value, list):
        for item in value:
            _reject_nonfinite(item)


def serialize_report(report):
    _reject_nonfinite(report)
    data = json.dumps(report, sort_keys=True, indent=1, allow_nan=False, ensure_ascii=True).encode('ascii') + b'\n'
    if len(data) > MAX_OUTPUT_BYTES:
        raise SampleAuditInvalid('output_too_large', '%d bytes' % len(data))
    return data


def _check_ancestry(path):
    """Refuse a symlink at any existing component; return lstat of the leaf or None."""
    absolute = Path(os.path.abspath(path))
    current = Path(absolute.anchor)
    leaf = None
    for part in absolute.parts[1:]:
        current = current / part
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            if current != absolute:
                raise SampleAuditRefused('missing_ancestor', str(current)) from None
            return absolute, None
        if stat.S_ISLNK(info.st_mode):
            raise SampleAuditRefused('symlink_refused', str(current))
        if current != absolute and not stat.S_ISDIR(info.st_mode):
            raise SampleAuditRefused('ancestor_not_directory', str(current))
        leaf = info
    return absolute, leaf


def read_bounded(path, budget=MAX_AGGREGATE_BYTES):
    absolute, info = _check_ancestry(path)
    if info is None:
        raise SampleAuditRefused('missing_input', str(absolute))
    if not stat.S_ISREG(info.st_mode):
        raise SampleAuditRefused('not_regular_file', str(absolute))
    limit = min(MAX_FILE_BYTES, budget)
    if info.st_size > limit:
        raise SampleAuditRefused('input_too_large', '%d bytes' % info.st_size)
    fd = os.open(absolute, os.O_RDONLY | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0))
    try:
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino) or not stat.S_ISREG(opened.st_mode):
            raise SampleAuditRefused('input_changed', str(absolute))
        chunks, total = [], 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise SampleAuditRefused('input_too_large', '> %d bytes' % limit)
            chunks.append(chunk)
    finally:
        os.close(fd)
    return b''.join(chunks)


def _parse_json(data):
    def pairs(items):
        keys = [k for k, _ in items]
        if len(set(keys)) != len(keys):
            raise SampleAuditInvalid('duplicate_json_key')
        return dict(items)

    def constant(name):
        raise SampleAuditInvalid('nonfinite_input', name)

    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as error:
        raise SampleAuditInvalid('bad_json', str(error)[:200]) from None


def write_new(path, data):
    absolute, info = _check_ancestry(path)
    if info is not None:
        raise SampleAuditRefused('output_exists', str(absolute))
    if len(data) > MAX_OUTPUT_BYTES:
        raise SampleAuditRefused('output_too_large', '%d bytes' % len(data))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | getattr(os, 'O_CLOEXEC', 0)
    try:
        fd = os.open(absolute, flags, 0o644)
    except FileExistsError:
        raise SampleAuditRefused('output_exists', str(absolute)) from None
    try:
        view = memoryview(data)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    except BaseException:
        os.close(fd)
        os.unlink(absolute)  # only the file this call just created exclusively
        raise
    os.close(fd)
    return absolute


def main(argv=None):
    parser = argparse.ArgumentParser(description='coast-sample-v1 composition report (read-only)')
    parser.add_argument('--sample', required=True, help='coast-sample-v1 output JSON file')
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--bridge-sha256', required=True)
    parser.add_argument('--out', required=True, help='new report file; never overwritten')
    args = parser.parse_args(argv)
    try:
        raw = read_bounded(args.sample)
        document = _parse_json(raw)
        report = audit_sample(document, args.plan_sha256, args.bridge_sha256)
        report['sample_file_sha256'] = hashlib.sha256(raw).hexdigest()
        data = serialize_report(report)
        write_new(args.out, data)
    except SampleAuditInvalid as error:
        print('INVALID %s' % error, file=sys.stderr)
        return EXIT_INVALID
    except (SampleAuditRefused, OSError) as error:
        print('REFUSED %s' % error, file=sys.stderr)
        return EXIT_REFUSED
    print('REPORTED %s (REVIEW REQUIRED; composition is not acceptance)' % args.out)
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
