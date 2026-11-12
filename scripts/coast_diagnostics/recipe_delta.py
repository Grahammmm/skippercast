"""Read-only delta between two frozen coast recipe snapshots (sc-recipe-delta-v1).

Each side is one recipe file plus its explicit staged metadata snapshot. Each side
is validated independently by the existing validate_recipe.validate_recipe; this
tool never runs a recipe, downloads, writes into a workspace or imports the stage
driver, acquisition code or live settings. The comparison covers every recipe leaf
and every metadata JSON file the validator actually read on either side, as JSON
Pointers into the logical object {"recipe": document, "metadata": {relative_path:
document}}. Arrays are compared by position (source order is a change, never
normalised). Missing and null are distinct: an absent side has *_present=false and
a null value.

CLI:
  python3 scripts/coast_diagnostics/recipe_delta.py --left-recipe L.json \\
      --left-metadata LEFT_ROOT --right-recipe R.json --right-metadata RIGHT_ROOT \\
      --workspace-root WS --out NEW_REPORT.json

Exit 0 publishes one new, complete report (never overwrites). Exit 2 = INVALID (any
validation failure, duplicate JSON key, non-finite number, unsafe path, refused schema
reference, cap, refused output or report I/O failure): nothing is published under the
requested name, and a JSON error goes to stderr. A report is REVIEW REQUIRED
only: semantic_approval and execution_allowed are always false. v1 admits no new
slug, makes no compatibility judgement, computes no budget and changes no source
permission.
"""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import stat
import sys
import threading

REPO = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = REPO / 'validate_recipe.py'
SCHEMA_ID = 'sc-recipe-delta-v1'
STATUS_UNCHANGED = 'UNCHANGED_REVIEW_REQUIRED'
STATUS_CHANGED = 'CHANGED_REVIEW_REQUIRED'
EXIT_OK = 0
EXIT_INVALID = 2
# Tool-local denial-of-service bounds. These are read at call time (never bound as
# defaults). The existing validator's tighter MAX_JSON_BYTES still applies per file.
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_ROWS = 4096
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
# The only metadata paths the validator may read (relative to a snapshot root).
_SLUG = r'[a-z0-9]+(?:-[a-z0-9]+)*'
METADATA_ALLOWLIST = re.compile(
    r'(?:schemas/coast-recipe-v1\.schema\.json|catalog/sources\.json|catalog/coastal-sectors\.json'
    r'|regions/' + _SLUG + r'/region\.json)\Z')
_LOCK = threading.Lock()
_ABSENT = object()


class RecipeDeltaError(ValueError):
    """INVALID: no success report may be produced."""


@contextlib.contextmanager
def _no_bytecode():
    """Imports made by this read-only tool never write __pycache__; the caller's setting returns."""
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        yield
    finally:
        sys.dont_write_bytecode = previous


def _load_validator():
    """The validate_recipe.py next to this checkout (or relocated copy); no sys.path search."""
    existing = sys.modules.get('validate_recipe')
    if existing is not None and getattr(existing, '__file__', None) \
            and Path(existing.__file__).resolve() == VALIDATOR_PATH.resolve():
        return existing
    name = '_sc_recipe_delta_validator_' + hashlib.sha256(str(VALIDATOR_PATH).encode()).hexdigest()[:16]
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, VALIDATOR_PATH)
    if spec is None or spec.loader is None:
        raise ImportError('validate_recipe.py not found next to this tool: ' + str(VALIDATOR_PATH))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        with _no_bytecode():
            spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


if __name__ == '__main__':
    # Standalone CLI: no import made by this process (validator, lazy jsonschema) writes bytecode.
    sys.dont_write_bytecode = True
validator = _load_validator()


# ------------------------------------------------------------------ bounded input

class _Budget:
    def __init__(self):
        self.total = 0


def _checked_path(path, *, directory=False):
    """Ancestry/type check through the validator's own safe_path, as a delta error."""
    try:
        return validator.safe_path(Path(path), directory=directory)
    except validator.RecipeError as error:
        raise RecipeDeltaError(str(error)) from error


def _read_bounded(path, budget, label):
    """Ancestry, regular-file type and size are checked before any byte is read."""
    path = _checked_path(path)
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise RecipeDeltaError(label + ' is missing') from error
    if not stat.S_ISREG(info.st_mode):
        raise RecipeDeltaError(label + ': unsafe path: special file or directory')
    limit = min(MAX_FILE_BYTES, validator.MAX_JSON_BYTES)
    if info.st_size > limit:
        raise RecipeDeltaError(label + ': exceeds the per-file input cap')
    if budget.total + info.st_size > MAX_TOTAL_BYTES:
        raise RecipeDeltaError(label + ': exceeds the aggregate input cap')
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0) \
        | getattr(os, 'O_CLOEXEC', 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise RecipeDeltaError(label + ': cannot open safely (' + error.__class__.__name__ + ')') from error
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
            raise RecipeDeltaError(label + ': file changed while being checked')
        chunks, size = [], 0
        while True:
            chunk = os.read(descriptor, 65536)
            if not chunk:
                break
            size += len(chunk)
            if size > limit:
                raise RecipeDeltaError(label + ': exceeds the per-file input cap')
            chunks.append(chunk)
    finally:
        os.close(descriptor)
    data = b''.join(chunks)
    if budget.total + len(data) > MAX_TOTAL_BYTES:
        raise RecipeDeltaError(label + ': exceeds the aggregate input cap')
    budget.total += len(data)
    return data, hashlib.sha256(data).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RecipeDeltaError('duplicate JSON key: ' + key)
        result[key] = value
    return result


def _constant(value):
    raise RecipeDeltaError('non-finite JSON number: ' + value)


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise RecipeDeltaError('non-finite JSON number')
    if isinstance(value, dict):
        for item in value.values():
            _finite(item)
    elif isinstance(value, list):
        for item in value:
            _finite(item)


def _parse(data, label):
    try:
        document = json.loads(data.decode('utf-8'), object_pairs_hook=_pairs, parse_constant=_constant)
    except RecipeDeltaError as error:
        raise RecipeDeltaError(label + ': ' + str(error)) from error
    except (UnicodeError, json.JSONDecodeError) as error:
        raise RecipeDeltaError(label + ': invalid JSON: ' + str(error)) from error
    try:
        _finite(document)   # e.g. 1e999 parses to inf without parse_constant
    except RecipeDeltaError as error:
        raise RecipeDeltaError(label + ': ' + str(error)) from error
    return document


def _metadata_relative(root, path):
    """Relative allowlisted path of a validator read inside the staged snapshot root."""
    path = Path(path)
    if '..' in path.parts:
        raise RecipeDeltaError('validator read refused: parent traversal')
    try:
        relative = path.absolute().relative_to(Path(root).absolute()).as_posix()
    except ValueError as error:
        raise RecipeDeltaError('validator read outside the staged metadata snapshot') from error
    if not METADATA_ALLOWLIST.fullmatch(relative):
        raise RecipeDeltaError('validator read not on the metadata allowlist: ' + relative)
    return relative


SCHEMA_RELATIVE = 'schemas/coast-recipe-v1.schema.json'
SCHEMA_DIALECT = 'https://json-schema.org/draft/2020-12/schema'
_REFERENCE_KEYS = ('$ref', '$dynamicRef', '$recursiveRef')


def _closed_schema(schema, label):
    """Fail closed before jsonschema can resolve anything outside this one staged document.

    The validator hands the staged schema to jsonschema, whose reference resolver does
    not go through read_json: an unknown URI would be retrieved (urllib for http(s) and
    file). So only document-internal references are admitted: every $ref/$dynamicRef/
    $recursiveRef must be a string fragment beginning with '#'; $id is allowed only at the
    root (it then just names the root resource, so '#...' still resolves inside it);
    $schema only at the root and only as the 2020-12 dialect the validator uses. Keys are
    checked wherever they occur (including under properties/const/default), which may
    refuse an unusual but harmless schema; that is the intended fail-closed direction.
    """
    def refuse(pointer, why):
        raise RecipeDeltaError(label + ': schema reference refused at ' + (pointer or '/') + ': ' + why)

    if not isinstance(schema, dict):
        refuse('', 'schema root must be an object')
    if '$schema' in schema and schema['$schema'] != SCHEMA_DIALECT:
        refuse('/$schema', 'only the 2020-12 dialect is admitted')
    if '$id' in schema and not isinstance(schema['$id'], str):
        refuse('/$id', 'root $id must be a string')

    def walk(value, pointer, root):
        if isinstance(value, dict):
            for key, item in value.items():
                here = pointer + '/' + _escape(key)
                if key in _REFERENCE_KEYS and not (isinstance(item, str) and item.startswith('#')):
                    refuse(here, 'only document-internal fragment references are admitted')
                if not root and key in ('$id', '$schema'):
                    refuse(here, 'nested ' + key + ' would change reference resolution')
                walk(item, here, False)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, pointer + '/' + str(index), False)

    walk(schema, '', True)


# ------------------------------------------------------------------ one side

def _validate_side(recipe_path, metadata_root, workspace_root, budget, side):
    raw, recipe_sha = _read_bounded(recipe_path, budget, side + ' recipe')
    document = _parse(raw, side + ' recipe')
    root = Path(metadata_root)
    try:
        root = validator.safe_path(root, directory=True)
    except validator.RecipeError as error:
        raise RecipeDeltaError(side + ' metadata snapshot root: ' + str(error)) from error
    if not root.is_dir():
        raise RecipeDeltaError(side + ' metadata snapshot root must be an existing directory')
    files = {}

    def recording_read_json(path):
        relative = _metadata_relative(root, path)
        if relative in files:
            return copy.deepcopy(files[relative][1])
        target = _checked_path(root / relative)   # symlink/special ancestry before existence
        try:
            target.lstat()
        except FileNotFoundError as error:
            raise RecipeDeltaError(side + ' missing metadata file: ' + relative) from error
        data, digest = _read_bounded(target, budget, side + ' metadata ' + relative)
        parsed = _parse(data, side + ' metadata ' + relative)
        if relative == SCHEMA_RELATIVE:
            _closed_schema(parsed, side + ' metadata ' + relative)   # before jsonschema sees it
        files[relative] = (digest, parsed)
        return copy.deepcopy(parsed)

    with _LOCK, _no_bytecode(), _replaced(validator, 'read_json', recording_read_json):
        result = validator.validate_recipe(copy.deepcopy(document), workspace_root=Path(workspace_root),
                                           metadata_root=root)
    if not isinstance(result, dict) or result.get('valid') is not True:
        raise RecipeDeltaError(side + ' recipe did not validate')
    return {'slug': result['slug'], 'recipe_sha256': recipe_sha, 'document': document,
            'metadata': {name: files[name][1] for name in sorted(files)},
            'metadata_sha256': {name: files[name][0] for name in sorted(files)}}


@contextlib.contextmanager
def _replaced(owner, name, value):
    original = getattr(owner, name)
    setattr(owner, name, value)
    try:
        yield
    finally:
        setattr(owner, name, original)


# ------------------------------------------------------------------ diff

def _escape(token):
    return token.replace('~', '~0').replace('/', '~1')


def _same_leaf(a, b):
    # Type-exact: true != 1, 1 != 1.0, so a JSON type change is a reported change.
    return type(a) is type(b) and a == b


def _changes(before, after):
    """Sorted change rows between two JSON-compatible values (arrays by position)."""
    rows = []

    def add(tokens, a, b):
        if len(rows) >= MAX_ROWS:
            raise RecipeDeltaError('change rows exceed the row cap')
        rows.append((tuple(tokens), {
            'pointer': ''.join('/' + _escape(str(value)) for _, value in tokens),
            'before_present': a is not _ABSENT, 'before': None if a is _ABSENT else a,
            'after_present': b is not _ABSENT, 'after': None if b is _ABSENT else b}))

    def walk(a, b, tokens):
        if a is _ABSENT and b is _ABSENT:
            return
        if a is not _ABSENT and b is not _ABSENT:
            if isinstance(a, dict) and isinstance(b, dict):
                for key in sorted(set(a) | set(b)):
                    walk(a.get(key, _ABSENT), b.get(key, _ABSENT), tokens + [(1, key)])
                return
            if isinstance(a, list) and isinstance(b, list):
                for index in range(max(len(a), len(b))):
                    walk(a[index] if index < len(a) else _ABSENT,
                         b[index] if index < len(b) else _ABSENT, tokens + [(0, index)])
                return
            if _same_leaf(a, b):
                return
        add(tokens, a, b)

    walk(before, after, [])
    # Arrays sort numerically by index, object members by key; one container kind per level.
    rows.sort(key=lambda item: item[0])
    return [copy.deepcopy(r) for _, r in rows]


# ------------------------------------------------------------------ public API

def compare_recipes(left_recipe, right_recipe, left_metadata_root, right_metadata_root, workspace_root):
    """Return a JSON-compatible sc-recipe-delta-v1 report, or raise RecipeDeltaError (INVALID)."""
    budget = _Budget()
    try:
        left = _validate_side(left_recipe, left_metadata_root, workspace_root, budget, 'left')
        right = _validate_side(right_recipe, right_metadata_root, workspace_root, budget, 'right')
        changes = _changes({'recipe': left['document'], 'metadata': left['metadata']},
                           {'recipe': right['document'], 'metadata': right['metadata']})
    except RecipeDeltaError:
        raise
    except AssertionError:
        raise   # offline sentinels and test doubles are never folded into INVALID
    except Exception as error:   # validator RecipeError, KeyError, TypeError, schema errors, OSError
        raise RecipeDeltaError(str(error) or error.__class__.__name__) from error
    if len(changes) > MAX_ROWS:
        raise RecipeDeltaError('change rows exceed the row cap')
    return {
        'schema': SCHEMA_ID,
        'status': STATUS_CHANGED if changes else STATUS_UNCHANGED,
        'semantic_approval': False,
        'execution_allowed': False,
        'not_for_navigation': True,
        'left': {key: left[key] for key in ('slug', 'recipe_sha256', 'metadata_sha256')},
        'right': {key: right[key] for key in ('slug', 'recipe_sha256', 'metadata_sha256')},
        'change_count': len(changes),
        'changes': changes,
    }


def serialize_report(report):
    """Deterministic bytes: sorted keys, two-space indent, ASCII, no NaN/Infinity."""
    try:
        text = json.dumps(report, sort_keys=True, indent=2, ensure_ascii=True, allow_nan=False)
    except ValueError as error:
        raise RecipeDeltaError('report is not finite JSON: ' + str(error)) from error
    return (text + '\n').encode('ascii')


def _within(path, root):
    path, root = Path(path).absolute(), Path(root).absolute()
    return path == root or root in path.parents


def _check_output(out, protected_roots):
    out = Path(out)
    if '..' in out.parts:
        raise RecipeDeltaError('output path refused: parent traversal')
    out = _checked_path(out)
    for root in protected_roots:
        if _within(out, root):
            raise RecipeDeltaError('output path refused: inside an input snapshot or the workspace root')
    try:
        out.lstat()
    except FileNotFoundError:
        pass
    else:
        raise RecipeDeltaError('output exists; reports are never overwritten')
    parent = _checked_path(out.parent, directory=True)
    if not parent.is_dir():
        raise RecipeDeltaError('output parent directory must already exist')
    return out


def write_report(report, out, *, protected_roots):
    """Publish exactly one new, complete, bounded file; never overwrite or leave a partial final name.

    Bytes go to a new exclusive '.<name>.incomplete-<pid>-<random>' file beside the
    target, are fully written, fsynced and closed, and only then hard-linked to the final
    name (link() refuses an existing name, so a concurrent writer is never overwritten).
    The temporary name, created by this call, is then unlinked. On any write, fsync,
    close or publish failure the final name is untouched, the incomplete bytes are kept
    under their distinct name as failure evidence (named in the error) and INVALID is raised.
    """
    data = serialize_report(report)
    if len(data) > MAX_OUTPUT_BYTES:
        raise RecipeDeltaError('report exceeds the output cap')
    out = _check_output(out, protected_roots)
    temporary = out.parent / ('.' + out.name + '.incomplete-' + str(os.getpid()) + '-' + os.urandom(4).hex())
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_CLOEXEC', 0)
    try:
        descriptor = os.open(temporary, flags, 0o644)
    except OSError as error:
        raise RecipeDeltaError('output cannot be created safely (' + error.__class__.__name__ + ')') from error
    failure = None
    try:
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError('write made no progress')
            view = view[written:]
        os.fsync(descriptor)
    except OSError as error:
        failure = error
    try:
        os.close(descriptor)
    except OSError as error:
        failure = failure or error
    if failure is not None:
        raise RecipeDeltaError('report write failed (' + failure.__class__.__name__ + ': ' + str(failure)
                               + '); final name not published; incomplete bytes retained as '
                               + temporary.name) from failure
    try:
        os.link(temporary, out)   # our own fresh regular file; link() never replaces an existing name
    except FileExistsError as error:
        raise RecipeDeltaError('output exists; reports are never overwritten; unpublished report retained as '
                               + temporary.name) from error
    except OSError as error:
        raise RecipeDeltaError('report write failed (publish ' + error.__class__.__name__
                               + '); final name not published; report retained as ' + temporary.name) from error
    with contextlib.suppress(OSError):
        os.unlink(temporary)   # only the temporary name this call created; the final link remains
    return hashlib.sha256(data).hexdigest()


def _invalid(error):
    return json.dumps({'status': 'INVALID', 'valid': False, 'error': str(error),
                       'semantic_approval': False, 'execution_allowed': False},
                      sort_keys=True, allow_nan=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for name in ('--left-recipe', '--left-metadata', '--right-recipe', '--right-metadata',
                 '--workspace-root', '--out'):
        parser.add_argument(name, required=True, type=Path)
    args = parser.parse_args(argv)
    protected = [args.left_metadata, args.right_metadata, args.workspace_root]
    try:
        _check_output(args.out, protected)   # fail fast, before reading any input
        report = compare_recipes(args.left_recipe, args.right_recipe, args.left_metadata,
                                 args.right_metadata, args.workspace_root)
        digest = write_report(report, args.out, protected_roots=protected)
    except (RecipeDeltaError, OSError) as error:   # any residual I/O failure is INVALID, never a traceback
        print(_invalid(error), file=sys.stderr)
        return EXIT_INVALID
    print(json.dumps({'status': report['status'], 'change_count': report['change_count'],
                      'out': str(args.out), 'report_sha256': digest,
                      'semantic_approval': False, 'execution_allowed': False}, sort_keys=True))
    return EXIT_OK


if __name__ == '__main__':
    sys.exit(main())
