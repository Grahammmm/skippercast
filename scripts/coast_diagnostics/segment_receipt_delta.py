"""Explain changes between two frozen coast-segment-receipt-v1 documents.

Read-only, offline, metadata-only. The comparator reads exactly the two receipt
files named on the command line plus the pinned local receipt schema. It never
resolves, stats or opens any file, archive or raw source named by a receipt Ref:
every Ref is inert declared text. It does not call the S-019 validate_receipt()
or Resolver.read(), never reruns, resumes, hashes payloads, accepts outputs or
verifies closure.

For each receipt it validates the shape against the pinned schema (remote
retrieval denied) and recomputes determinism_digest with the frozen S-019 v1
content_identity projection (sorted compact UTF-8 JSON, no trailing newline).
Different segment_slug / campaign_segment_id / coordinator_segment_id is
NOT_COMPARABLE. Otherwise an sc-segment-delta-v1 report lists ordered RFC 6901
JSON Pointer leaf changes in two separate arrays: content_changes (inside the
determinism projection) and bookkeeping_changes (the excluded envelope fields).

Every report declares evidence_scope=declared_metadata_only,
referenced_bytes_verified=false, semantic_approval=false, closure_verified=false
and semantic_comparability=UNVERIFIED. `closed` is shown only as a declared
before/after value; no closure verdict is issued or revoked.

Exit codes: 0 valid same-segment diagnostic, 1 NOT_COMPARABLE, 2 malformed or
unsafe input (including refused paths, caps and an existing --out file).
"""
import argparse
import copy
import hashlib
import json
import math
import os
import re
import stat
import sys
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

REPORT_SCHEMA = 'sc-segment-delta-v1'
ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / 'skills' / 'coast-campaign-shared' / 'schemas' / 'coast-segment-receipt-v1.schema.json'
SCHEMA_SHA256 = '73dc8b02224d7c8e958bd9a9534f06cc66a7c2fea64cd562313520f784506550'

# Frozen S-019 v1 projection (scripts/validate_coast_receipt.py content_identity).
CONTENT_FIELDS = ('schema', 'schema_version', 'campaign_segment_id', 'coordinator_segment_id',
                  'segment_slug', 'recipe_sha256', 'recipe', 'code_commit', 'skill_commit',
                  'inputs', 'outputs', 'qa', 'tier1')
# Envelope fields the projection intentionally excludes (lifecycle bookkeeping).
BOOKKEEPING_FIELDS = ('created_utc', 'author_profile', 'author_model', 'card_id', 'run',
                      'closed', 'signoff', 'archive')
DIGEST_FIELD = 'determinism_digest'
IDENTITY_FIELDS = ('segment_slug', 'campaign_segment_id', 'coordinator_segment_id')
REF_KEYS = frozenset({'root_id', 'path', 'sha256', 'bytes'})
FACETS = ('code', 'tool', 'parameters', 'recipe', 'source', 'output', 'qa', 'tier', 'reference')
PRODUCER_FACETS = ('code', 'tool', 'recipe')

# Tool-local denial-of-service bounds for this new report tool only.
MAX_INPUT_BYTES = 2 * 1024 * 1024
MAX_AGGREGATE_BYTES = 16 * 1024 * 1024
MAX_ROWS = 4096
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
# Nesting/node bounds checked iteratively before any recursive step (parse, schema,
# copy, diff), so unsafe nesting is a refusal (exit 2), never a RecursionError.
# Every JSON value takes at least one input byte, so the node cap never binds a
# document that already fits the per-file input cap.
MAX_DEPTH = 64
MAX_NODES = MAX_INPUT_BYTES
FLAGS = dict(evidence_scope='declared_metadata_only', referenced_bytes_verified=False,
             semantic_approval=False, closure_verified=False, semantic_comparability='UNVERIFIED')

_VALIDATOR = None


class InvalidReceipt(ValueError):
    """Malformed or unsafe input: exit 2, nothing is explained or written."""


# ------------------------------------------------------------ JSON / digest ---

def loads_strict(raw):
    """Strict UTF-8 JSON: duplicate keys and nonfinite numbers are refused."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise InvalidReceipt(f'duplicate JSON key: {key}')
            result[key] = value
        return result

    def nonfinite(token):
        raise InvalidReceipt(f'nonfinite JSON number: {token}')
    try:
        text = raw.decode('utf-8')
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=nonfinite)
    except InvalidReceipt:
        raise
    except RecursionError:
        raise InvalidReceipt(f'nesting depth cap exceeded ({MAX_DEPTH} levels; parser recursion)') from None
    except (UnicodeDecodeError, ValueError) as error:
        raise InvalidReceipt(f'malformed JSON: {error}') from None
    require_finite(value)
    return value


def require_finite(value):
    """Iterative JSON-tree gate, run before anything recursive touches ``value``.

    Refuses non-JSON types and non-string keys, nonfinite numbers, nesting
    deeper than MAX_DEPTH containers (which also refuses cycles) and more than
    MAX_NODES values (which also refuses shared-subtree blow-up).
    """
    stack, nodes = [(value, 1)], 0
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if nodes > MAX_NODES:
            raise InvalidReceipt(f'node cap exceeded ({MAX_NODES} JSON values)')
        if isinstance(item, (dict, list)):
            if depth > MAX_DEPTH:
                raise InvalidReceipt(f'nesting depth cap exceeded ({MAX_DEPTH} levels)')
            if isinstance(item, dict):
                for key, child in item.items():
                    if not isinstance(key, str):
                        raise InvalidReceipt(f'schema: not a JSON value: non-string object key {type(key).__name__}')
                    stack.append((child, depth + 1))
            else:
                stack.extend((child, depth + 1) for child in item)
        elif isinstance(item, float):
            if not math.isfinite(item):
                raise InvalidReceipt('nonfinite JSON number (NaN/Infinity or overflow)')
        elif item is not None and not isinstance(item, (str, int)):  # bool is an int
            raise InvalidReceipt(f'schema: not a JSON value: {type(item).__name__}')


def canonical_compact(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def content_identity(receipt):
    """Frozen v1 content projection; lifecycle bookkeeping is excluded."""
    return {key: receipt[key] for key in CONTENT_FIELDS}


def determinism_digest(receipt):
    """sha256 of sorted compact UTF-8 JSON of content_identity, no newline."""
    return hashlib.sha256(canonical_compact(content_identity(receipt))).hexdigest()


# ------------------------------------------------------------------ schema ---

def deny_retrieval(uri):
    raise InvalidReceipt('remote schema retrieval denied: ' + str(uri))


def _contains_reference(value):
    if isinstance(value, dict):
        return any(k in ('$ref', '$dynamicRef') or _contains_reference(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_contains_reference(v) for v in value)
    return False


_RFC3339_DATE_TIME = re.compile(
    r'([0-9]{4})-([0-9]{2})-([0-9]{2})[Tt]([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.[0-9]+)?'
    r'(?:[Zz]|[+-]([0-9]{2}):([0-9]{2}))', re.ASCII)


def is_rfc3339_date_time(value):
    """Strict RFC 3339 section 5.6 date-time (ASCII digits, real calendar date)."""
    if not isinstance(value, str):
        return True  # format assertions apply to strings only
    match = _RFC3339_DATE_TIME.fullmatch(value)
    if not match:
        return False
    year, month, day, hour, minute, second = (int(match.group(i)) for i in range(1, 7))
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    month_days = (31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    if not (1 <= month <= 12 and 1 <= day <= month_days[month - 1]):
        return False
    if hour > 23 or minute > 59 or second > 60:  # 60: RFC 3339 leap second
        return False
    if match.group(7) is not None and (int(match.group(7)) > 23 or int(match.group(8)) > 59):
        return False
    return True


# Every format the pinned schema uses must have an enforced local checker here;
# jsonschema's optional third-party format dependencies are never relied upon.
ENFORCED_FORMATS = {'date-time': is_rfc3339_date_time}


def _schema_formats(schema):
    found, stack = set(), [schema]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if isinstance(item.get('format'), str):
                found.add(item['format'])
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return found


def enforced_format_checker(schema):
    """A FormatChecker that enforces every format named by ``schema`` or refuses."""
    missing = sorted(_schema_formats(schema) - set(ENFORCED_FORMATS))
    if missing:
        raise InvalidReceipt('capability: schema format(s) without an enforced offline checker: '
                             + ', '.join(missing) + '; refusing to claim schema validation')
    checker = FormatChecker(formats=())
    for name, function in ENFORCED_FORMATS.items():
        checker.checks(name)(function)
    return checker


def build_validator(schema):
    """Draft 2020-12 validator that can never fetch anything and enforces formats."""
    if _contains_reference(schema):
        raise InvalidReceipt('schema references are refused (no retrieval is permitted)')
    Draft202012Validator.check_schema(schema)
    format_checker = enforced_format_checker(schema)
    try:
        import referencing  # jsonschema >= 4.18
        options = dict(registry=referencing.Registry(retrieve=deny_retrieval))
    except ImportError:  # older jsonschema: a resolver whose remote fetch always refuses
        from jsonschema import RefResolver

        class DenyResolver(RefResolver):
            def resolve_remote(self, uri):
                deny_retrieval(uri)
        options = dict(resolver=DenyResolver.from_schema(schema))
    return Draft202012Validator(schema, format_checker=format_checker, **options)


def receipt_validator(budget=None):
    global _VALIDATOR
    if _VALIDATOR is None or _VALIDATOR[0] != SCHEMA_SHA256:
        raw = read_bounded(SCHEMA_PATH, budget if budget is not None else Budget())
        if hashlib.sha256(raw).hexdigest() != SCHEMA_SHA256:
            raise InvalidReceipt('pinned receipt schema hash mismatch')
        _VALIDATOR = (SCHEMA_SHA256, build_validator(loads_strict(raw)))
    return _VALIDATOR[1]


def validate_shape(receipt, side, budget=None):
    if not isinstance(receipt, dict):
        raise InvalidReceipt(f'schema: {side}: receipt must be a JSON object')
    errors = sorted(receipt_validator(budget).iter_errors(receipt), key=lambda e: list(map(str, e.path)))
    if errors:
        first = errors[0]
        where = '/' + '/'.join(escape(str(p)) for p in first.path)
        raise InvalidReceipt(f'schema: {side}: {where}: {first.message[:200]}')


def check_digest(receipt, side):
    recomputed = determinism_digest(receipt)
    if receipt[DIGEST_FIELD] != recomputed:
        raise InvalidReceipt(f'determinism digest mismatch: {side}')
    return recomputed


# ---------------------------------------------------------------- diffing ---

def escape(token):
    return token.replace('~', '~0').replace('/', '~1')


def make_row(pointer, before_present, before, after_present, after):
    return dict(pointer=pointer, before_present=before_present, before=before,
                after_present=after_present, after=after)


def _same(a, b):
    """Equality exactly as the frozen canonical encoding sees it (0.0 vs -0.0, 1 vs 1.0 differ)."""
    return type(a) is type(b) and canonical_compact(a) == canonical_compact(b)


def _leaves(value, pointer):
    if isinstance(value, dict) and value:
        for key in sorted(value):
            yield from _leaves(value[key], pointer + '/' + escape(key))
    elif isinstance(value, list) and value:
        for index, item in enumerate(value):
            yield from _leaves(item, f'{pointer}/{index}')
    else:
        yield pointer, value


class _Rows(list):
    def add(self, item):
        if len(self) >= MAX_ROWS:
            raise InvalidReceipt(f'row cap exceeded ({MAX_ROWS} changed leaves)')
        self.append(item)


def _diff(before, after, pointer, before_present, after_present, rows):
    if before_present and after_present:
        if isinstance(before, dict) and isinstance(after, dict):
            for key in sorted(set(before) | set(after)):
                _diff(before.get(key), after.get(key), pointer + '/' + escape(key),
                      key in before, key in after, rows)
        elif isinstance(before, list) and isinstance(after, list):
            for index in range(max(len(before), len(after))):
                _diff(before[index] if index < len(before) else None,
                      after[index] if index < len(after) else None,
                      f'{pointer}/{index}', index < len(before), index < len(after), rows)
        elif not _same(before, after):
            rows.add(make_row(pointer, True, before, True, after))
    elif before_present:
        for leaf, value in _leaves(before, pointer):
            rows.add(make_row(leaf, True, value, False, None))
    elif after_present:
        for leaf, value in _leaves(after, pointer):
            rows.add(make_row(leaf, False, None, True, value))


def leaf_diff(before, after, fields, rows):
    for key in sorted(fields):
        _diff(before.get(key), after.get(key), '/' + escape(key), key in before, key in after, rows)
    return rows


def _resolve(document, pointer):
    value = document
    for token in pointer.split('/')[1:]:
        token = token.replace('~1', '/').replace('~0', '~')
        if isinstance(value, dict) and token in value:
            value = value[token]
        elif isinstance(value, list) and token.isdigit() and int(token) < len(value):
            value = value[int(token)]
        else:
            return None
    return value


def _is_ref(value):
    return isinstance(value, dict) and set(value) == REF_KEYS


def facets_for(pointer, left, right):
    parts = pointer.split('/')[1:]
    head = parts[0] if parts else ''
    found = set()
    if pointer in ('/code_commit', '/skill_commit') or (
            head == 'outputs' and len(parts) >= 4 and parts[2] == 'tool' and parts[3] == 'code_commit'):
        found.add('code')
    if head == 'outputs' and len(parts) >= 3:
        found.add({'tool': 'tool', 'parameters': 'parameters', 'contributing_sources': 'source',
                   'artifact': 'output', 'measured_format': 'output'}.get(parts[2], 'output'))
    if head in ('recipe', 'recipe_sha256'):
        found.add('recipe')
    if head == 'inputs':
        found.add('source')
    if head == 'qa':
        found.add('qa')
    if head == 'tier1':
        found.add('tier')
    parent = '/' + '/'.join(parts[:-1]) if len(parts) > 1 else ''
    for document in (left, right):
        if (parent and _is_ref(_resolve(document, parent))) or _is_ref(_resolve(document, pointer)):
            found.add('reference')
    return found


# ------------------------------------------------------------- comparison ---

def _prepare(value, side, budget=None):
    if isinstance(value, (bytes, bytearray)):
        raw = bytes(value)
        if len(raw) > MAX_INPUT_BYTES:
            raise InvalidReceipt(f'{side}: input cap exceeded ({MAX_INPUT_BYTES} bytes)')
        receipt = loads_strict(raw)
        info = dict(supplied=True, raw_sha256=hashlib.sha256(raw).hexdigest(), raw_bytes=len(raw))
    elif isinstance(value, dict):
        require_finite(value)  # iterative depth/node/type gate before deepcopy or schema
        receipt = copy.deepcopy(value)
        info = dict(supplied=False, raw_sha256=None, raw_bytes=None)
    else:
        raise InvalidReceipt(f'schema: {side}: expected raw JSON bytes or a JSON object')
    validate_shape(receipt, side, budget)
    if receipt.get('schema') != 'coast-segment-receipt-v1':
        raise InvalidReceipt(f'schema: {side}: expected coast-segment-receipt-v1')
    recomputed = check_digest(receipt, side)
    return receipt, info, dict(declared=receipt[DIGEST_FIELD], recomputed=recomputed)


def compare_receipts(left, right, *, _budget=None):
    """Return an sc-segment-delta-v1 report for two original receipts.

    ``left``/``right`` are the raw file bytes (hashed and strictly parsed) or
    already-parsed JSON objects (raw hash then recorded as not supplied).
    Raises InvalidReceipt for malformed input; returns status NOT_COMPARABLE
    for different segment identities. Never reads anything a Ref names.
    """
    try:
        return _compare(left, right, _budget)
    except RecursionError:  # defensive: the iterative gate should make this unreachable
        raise InvalidReceipt('unsafe recursion while comparing (defensive guard)') from None


def _check_consistency(before, after, content):
    """Every content field changed by canonical bytes has rows, and only those fields do."""
    for key in CONTENT_FIELDS:
        changed = canonical_compact(before[key]) != canonical_compact(after[key])
        prefix = '/' + escape(key)
        has_rows = any(item['pointer'] == prefix or item['pointer'].startswith(prefix + '/') for item in content)
        if changed != has_rows:
            raise InvalidReceipt(f'internal projection/digest inconsistency at {prefix}')


def _compare(left, right, _budget):
    before, left_info, left_digest = _prepare(left, 'left', _budget)
    after, right_info, right_digest = _prepare(right, 'right', _budget)
    report = dict(schema=REPORT_SCHEMA, review_status='REVIEW REQUIRED', **FLAGS,
                  input_files=dict(left=left_info, right=right_info),
                  determinism_digest=dict(left=left_digest, right=right_digest,
                                          changed=left_digest['recomputed'] != right_digest['recomputed'],
                                          encoding='sha256 of sorted compact UTF-8 JSON of content_identity, '
                                                   'no trailing newline (raw file hashes are separate)'),
                  declared_closed=dict(before=before['closed'], after=after['closed']),
                  content_identity_fields=list(CONTENT_FIELDS), bookkeeping_fields=list(BOOKKEEPING_FIELDS))
    identity = _Rows()
    for key in IDENTITY_FIELDS:
        if not _same(before[key], after[key]):
            identity.add(make_row('/' + escape(key), True, before[key], True, after[key]))
    if identity:
        report.update(status='NOT_COMPARABLE', comparable=False, identity_changes=list(identity),
                      semantic_comparability_reason='different segment identity; nothing is explained')
        return report
    content = leaf_diff(content_identity(before), content_identity(after), CONTENT_FIELDS, _Rows())
    bookkeeping_before = {k: before[k] for k in BOOKKEEPING_FIELDS if k in before}
    bookkeeping_after = {k: after[k] for k in BOOKKEEPING_FIELDS if k in after}
    bookkeeping = _Rows()
    bookkeeping.extend(content)  # one shared row budget across both arrays
    leaf_diff(bookkeeping_before, bookkeeping_after, BOOKKEEPING_FIELDS, bookkeeping)
    bookkeeping = bookkeeping[len(content):]
    if bool(content) != report['determinism_digest']['changed']:
        raise InvalidReceipt('internal projection/digest inconsistency')
    _check_consistency(before, after, content)
    facets = {name: [] for name in FACETS}
    for section, rows in (('content', content), ('bookkeeping', bookkeeping)):
        for item in rows:
            for name in sorted(facets_for(item['pointer'], before, after)):
                facets[name].append(dict(item, section=section))
    producer = [item['pointer'] for item in content
                if facets_for(item['pointer'], before, after) & set(PRODUCER_FACETS)]
    report.update(status='DIAGNOSTIC', comparable=True,
                  segment_identity={key: before[key] for key in IDENTITY_FIELDS},
                  content_changes=list(content), bookkeeping_changes=list(bookkeeping), facets=facets,
                  producer=dict(changed=bool(producer), pointers=producer),
                  counts=dict(content_changes=len(content), bookkeeping_changes=len(bookkeeping)),
                  semantic_comparability_reason=(
                      'declared producer identity changed' if producer else
                      'declared producer identity matches; declared metadata cannot establish scientific '
                      'comparability'))
    return report


# ------------------------------------------------------------ bounded I/O ---

class Budget:
    def __init__(self):
        self.used = 0

    def take(self, size, path):
        if self.used + size > MAX_AGGREGATE_BYTES:
            raise InvalidReceipt(f'aggregate input cap exceeded ({MAX_AGGREGATE_BYTES} bytes) at {path}')
        self.used += size


def _checked_parts(path):
    text = os.fspath(path)
    if '\0' in text:
        raise InvalidReceipt('refused path: NUL byte')
    absolute = text if os.path.isabs(text) else os.path.join(os.getcwd(), text)
    if absolute != os.path.normpath(absolute) or absolute.startswith('//'):
        raise InvalidReceipt(f'refused path: must be normalized (no ., .. or //): {text}')
    parts = absolute.split('/')[1:]
    if not parts or not parts[-1]:
        raise InvalidReceipt(f'refused path: not a file name: {text}')
    return parts


def _open_parent(parts, text):
    """Walk from / with O_NOFOLLOW so no ancestor may be a symlink."""
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in parts[:-1]:
            try:
                new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                raise InvalidReceipt(f'cannot open {text}: missing ancestor') from None
            except (NotADirectoryError, OSError) as error:
                raise InvalidReceipt(f'refused symlink or non-directory ancestor in {text}: {error.strerror}') from None
            os.close(fd)
            fd = new
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_bounded(path, budget):
    """Read one explicit regular file: no symlink anywhere, size-capped."""
    text = os.fspath(path)
    parts = _checked_parts(text)
    parent = _open_parent(parts, text)
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, 'O_NOCTTY', 0)
        try:
            fd = os.open(parts[-1], flags, dir_fd=parent)
        except FileNotFoundError:
            raise InvalidReceipt(f'cannot open {text}: missing') from None
        except OSError as error:
            raise InvalidReceipt(f'refused symlink or unreadable file {text}: {error.strerror}') from None
    finally:
        os.close(parent)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise InvalidReceipt(f'refused {text}: not a regular file')
        if info.st_size > MAX_INPUT_BYTES:
            raise InvalidReceipt(f'refused {text}: input cap exceeded ({MAX_INPUT_BYTES} bytes)')
        budget.take(info.st_size, text)
        chunks, remaining = [], info.st_size + 1
        while remaining > 0:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b''.join(chunks)
        if len(raw) != info.st_size:
            raise InvalidReceipt(f'refused {text}: file changed while reading')
        return raw
    finally:
        os.close(fd)


def serialize(report):
    try:
        data = (json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')
    except ValueError:
        raise InvalidReceipt('nonfinite value in report') from None
    if len(data) > MAX_OUTPUT_BYTES:
        raise InvalidReceipt(f'output cap exceeded ({MAX_OUTPUT_BYTES} bytes)')
    return data


def write_new(path, data):
    """Create a new file; never overwrite, never follow a symlink."""
    text = os.fspath(path)
    parts = _checked_parts(text)
    parent = _open_parent(parts, text)
    try:
        try:
            fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=parent)
        except FileExistsError:
            raise InvalidReceipt(f'refused --out {text}: file exists (no overwrite)') from None
        except OSError as error:
            raise InvalidReceipt(f'refused --out {text}: {error.strerror}') from None
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        except BaseException:
            os.close(fd)
            os.unlink(parts[-1], dir_fd=parent)
            raise
        os.close(fd)
    finally:
        os.close(parent)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--left', required=True, help='original coast-segment-receipt-v1 JSON file (before)')
    parser.add_argument('--right', required=True, help='original coast-segment-receipt-v1 JSON file (after)')
    parser.add_argument('--out', required=True, help='new report file; must not exist')
    args = parser.parse_args(argv)
    try:
        budget = Budget()
        _checked_parts(args.out)
        left = read_bounded(args.left, budget)
        right = read_bounded(args.right, budget)
        report = compare_receipts(left, right, _budget=budget)
        write_new(args.out, serialize(report))
    except (InvalidReceipt, OSError) as error:
        print('INVALID: ' + str(error), file=sys.stderr)
        return 2
    summary = dict(status=report['status'], out=args.out, review_status='REVIEW REQUIRED',
                   content_changes=len(report.get('content_changes', [])),
                   bookkeeping_changes=len(report.get('bookkeeping_changes', [])))
    print(json.dumps(summary, sort_keys=True))
    return 1 if report['status'] == 'NOT_COMPARABLE' else 0


if __name__ == '__main__':
    raise SystemExit(main())
