"""Read-only coast recipe validation; no fetching, execution or output creation.

CLI: python validate_recipe.py RECIPE [RECIPE ...] --workspace-root ROOT
Optional --metadata-root selects an explicit offline source snapshot (default: this
checkout). ROOT is an already admitted local workspace, not a live coast root.
No runtime/settings/downloader modules are imported. Valid means REVIEW REQUIRED,
not native coverage, compatible datums, source-use permission or semantic approval.
Future recipe expansion needs its owner's admission; v1 initially admits four slugs.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import stat
import sys

REPO = Path(__file__).resolve().parent
ADMITTED_SLUGS = frozenset((
    'morro-bay', 'cambria-san-simeon', 'south-big-sur-san-simeon',
    'santa-cruz-monterey-bay',
))
MAX_CACHE_BUDGET_BYTES = 25_000_000_000
MAX_JSON_BYTES = 2_000_000
SLUG = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*\Z')


class RecipeError(ValueError):
    """A recipe or its offline metadata is not valid; no execution is allowed."""


def safe_path(path: Path, *, directory: bool = False) -> Path:
    """Reject symlinks (even dangling), special files and parent traversal.

    Check from the filesystem root toward the leaf before reading any bytes.
    Absent tails are valid for an output directory; this function creates nothing.
    This is a static checker, not a race-safe future writing API.
    """
    path = Path(path).absolute()
    if '..' in path.parts:
        raise RecipeError('unsafe path: parent traversal')
    components = list(reversed(path.parents)) + [path]
    for index, component in enumerate(components):
        try:
            mode = component.lstat().st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise RecipeError('unsafe path: symlink')
        if index < len(components) - 1 or directory:
            if not stat.S_ISDIR(mode):
                raise RecipeError('unsafe path: expected directory')
        elif not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise RecipeError('unsafe path: special file')
    return path


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise RecipeError('JSON duplicate key: ' + key)
        result[key] = value
    return result


def _constant(value):
    raise RecipeError('JSON non-finite number: ' + value)


def read_json(path: Path):
    path = safe_path(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_JSON_BYTES:
        raise RecipeError('JSON input must be a bounded regular file')
    try:
        return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=_pairs,
                          parse_constant=_constant)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise RecipeError('invalid JSON: ' + str(error)) from error


def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        raise RecipeError('non-finite numeric value')
    if isinstance(value, dict):
        for item in value.values():
            _finite(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _finite(item)


REFERENCE_KEYWORDS = ('$ref', '$dynamicRef')
ANCHOR_KEYWORDS = ('$anchor', '$dynamicAnchor')
PLAIN_NAME = re.compile(r'[A-Za-z_][-A-Za-z0-9._]*\Z')
ARRAY_INDEX = re.compile(r'(?:0|[1-9][0-9]*)\Z')
NOT_ADMITTED = 'schema reference not admitted: '


def _location(parts):
    return '/' + '/'.join(str(part).replace('~', '~0').replace('/', '~1') for part in parts)


def _refuse_retrieval(uri):
    """Retrieval callback for the validator: never fetch, never touch I/O."""
    raise RecipeError('schema retrieval refused: ' + str(uri))


def _walk(node, parts=()):
    yield parts, node
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, parts + (key,))
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _walk(value, parts + (index,))


def _pointer_target(schema, fragment):
    """Resolve a same-document JSON pointer exactly, or return False."""
    from urllib.parse import unquote
    if re.search(r'%(?![0-9A-Fa-f]{2})', fragment):
        return False
    try:
        decoded = unquote(fragment[1:], errors='strict')
    except UnicodeError:
        return False
    node = schema
    for raw in decoded.split('/'):
        if re.search(r'~(?![01])', raw):
            return False
        segment = raw.replace('~1', '/').replace('~0', '~')
        if isinstance(node, dict) and segment in node:
            node = node[segment]
        elif isinstance(node, list) and ARRAY_INDEX.match(segment) and int(segment) < len(node):
            node = node[int(segment)]
        else:
            return False
    return True


def _check_references(schema):
    """Admit only same-document fragments of this self-contained schema.

    Runs before any instance evaluation and walks the WHOLE document, so a
    reference in a branch no instance would traverse is refused too. Anything
    that needs another resource (absolute, file, relative, protocol-relative,
    URN, empty or dynamic external references) is refused, as is an embedded
    resource identifier, which would rebase later fragments. The root $id and
    $schema are identifiers, not fetch instructions. Keywords inside data
    positions such as const/enum are refused conservatively as well.
    """
    anchors = {node[key] for _, node in _walk(schema) if isinstance(node, dict)
               for key in ANCHOR_KEYWORDS if isinstance(node.get(key), str)}
    for parts, node in _walk(schema):
        if not isinstance(node, dict):
            continue
        if parts and '$id' in node:
            raise RecipeError(NOT_ADMITTED + 'embedded resource identifier at ' + _location(parts + ('$id',)))
        for key in REFERENCE_KEYWORDS:
            if key not in node:
                continue
            where = ' at ' + _location(parts + (key,))
            reference = node[key]
            if not isinstance(reference, str):
                raise RecipeError(NOT_ADMITTED + 'malformed reference' + where)
            if not reference.startswith('#'):
                raise RecipeError(NOT_ADMITTED + 'external resource' + where)
            fragment = reference[1:]
            if fragment == '' or (fragment.startswith('/') and _pointer_target(schema, fragment)):
                continue
            if PLAIN_NAME.match(fragment) and fragment in anchors:
                continue
            raise RecipeError(NOT_ADMITTED + 'unresolved local fragment' + where)


def _registry_api():
    """The referencing Registry class (jsonschema >= 4.18), else None."""
    try:
        from referencing import Registry
    except ImportError:
        return None
    return Registry


def _offline_validator(validator_class, schema, **options):
    """A validator whose resolver can only see bundled metaschemas and `schema`."""
    registry = _registry_api()
    if registry is not None:
        # jsonschema combines this with its bundled specifications only; the
        # retrieval callback replaces the default remote-retrieving registry.
        offline = registry(retrieve=lambda uri: _refuse_retrieval(uri))
        return validator_class(schema, registry=offline, **options)
    from jsonschema import RefResolver

    class OfflineResolver(RefResolver):
        def resolve_remote(self, uri):
            return _refuse_retrieval(uri)

    return validator_class(schema, resolver=OfflineResolver.from_schema(
        schema, id_of=validator_class.ID_OF), **options)


def _resolution_errors():
    """Reference-resolution failures of either jsonschema resolver generation."""
    import jsonschema.exceptions as exceptions
    errors = []
    try:
        from referencing.exceptions import Unresolvable
        errors.append(Unresolvable)
    except ImportError:
        pass
    legacy = (getattr(exceptions, '_RefResolutionError', None)
              or vars(exceptions).get('RefResolutionError'))
    if legacy is not None:
        errors.append(legacy)
    return tuple(errors)


def _shape(document, metadata_root):
    # Do not use validate.check: its emergency off/missing-dependency fallback is
    # inappropriate here. Missing jsonschema fails closed. Validation is offline
    # for any operator-supplied metadata root: references are checked before
    # evaluation and the resolver has no retrieval (docs/engineering/sc_recipe_offline.md).
    try:
        from jsonschema import Draft202012Validator
    except ImportError as error:
        raise RecipeError('jsonschema is required for recipe validation') from error
    schema = read_json(metadata_root / 'schemas/coast-recipe-v1.schema.json')
    try:
        _finite(schema)
    except RecipeError as error:
        raise RecipeError('schema document ' + str(error)) from error
    unresolvable = _resolution_errors()
    try:
        meta = _offline_validator(Draft202012Validator, Draft202012Validator.META_SCHEMA,
                                  format_checker=Draft202012Validator.FORMAT_CHECKER)
        # Same first-error rule as Draft202012Validator.check_schema, offline.
        for problem in meta.iter_errors(schema):
            raise RecipeError('schema document invalid at ' + _location(problem.absolute_path)
                              + ': ' + problem.message)
        _check_references(schema)
        problems = list(_offline_validator(Draft202012Validator, schema).iter_errors(document))
    except unresolvable as error:
        raise RecipeError('schema reference unresolvable offline: ' + str(error)) from error
    if problems:
        first = problems[0]
        raise RecipeError('schema ' + '/'.join(map(str, first.absolute_path)) + ': ' + first.message)


def validate_recipe(document, *, workspace_root: Path, metadata_root: Path = REPO) -> dict:
    """Bind a recipe to offline region/catalog metadata without creating files.

    source_review_status and datum_policy are required exact projections of the
    catalog, not allow/deny or depth-qualification verdicts. A candidate/restricted
    source may be described here; it is never thereby approved for use.
    """
    metadata_root = safe_path(metadata_root, directory=True)
    _finite(document)
    _shape(document, metadata_root)
    slug = document['slug']
    if not SLUG.fullmatch(slug) or slug not in ADMITTED_SLUGS:
        raise RecipeError('unadmitted region slug')
    region = read_json(metadata_root / 'regions' / slug / 'region.json')
    if region['id'] != slug:
        raise RecipeError('region identity mismatch')
    box = document['bbox']
    west, south, east, north = box
    if not west < east or not south < north:
        raise RecipeError('bbox order must be west,south,east,north with positive extent')
    if box != region['bounds']:
        raise RecipeError('bbox differs from frozen region bounds (no rounding)')
    sectors = read_json(metadata_root / 'catalog/coastal-sectors.json')['sectors']
    ca_south = min(row['latitude'][0] for row in sectors)
    ca_north = max(row['latitude'][1] for row in sectors)
    if south < ca_south or north > ca_north:
        raise RecipeError('bbox outside supported CA discovery latitude coverage')
    if document['depth_target_ft'] != region['boat']['bottom_depth_limit_ft']:
        raise RecipeError('depth target differs from region planning limit')
    catalog = read_json(metadata_root / 'catalog/sources.json')['sources']
    by_id = {row['id']: row for row in catalog}
    if len(by_id) != len(catalog):
        raise RecipeError('duplicate catalog source identity')
    sources = document['sources']
    if any(source not in by_id for source in sources):
        raise RecipeError('unknown catalog source')
    if sources != region['source_bindings']['bathymetry']:
        raise RecipeError('sources differ from frozen bathymetry bindings/order')
    if any('bathymetry' not in by_id[source]['needs'] for source in sources):
        raise RecipeError('source lacks catalog bathymetry support')
    statuses = {source: by_id[source]['review_status'] for source in sources}
    if document['source_review_status'] != statuses:
        raise RecipeError('source review status differs from catalog')
    datums = {source: (by_id[source].get('vertical_datum')
                      if by_id[source].get('vertical_datum') is not None else 'unknown')
              for source in sources}
    if document['datum_policy']['vertical_datum_by_source'] != datums:
        raise RecipeError('datum policy differs from catalog (null stays unknown)')
    # Schema caps are supplemented with exact identity/root binding and a real
    # filesystem ancestry check; shape validation alone cannot rule out symlinks.
    if document['output_root'] != 'runs/coast-recipes/' + slug:
        raise RecipeError('output root is not exclusive to this slug')
    workspace = safe_path(workspace_root, directory=True)
    if not workspace.is_dir():
        raise RecipeError('workspace root must be an existing admitted directory')
    safe_path(workspace / document['output_root'], directory=True)
    return {'slug': slug, 'status': 'REVIEW REQUIRED', 'valid': True,
            'semantic_approval': False, 'execution_allowed': False,
            'not_for_navigation': True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recipes', nargs='+', type=Path)
    parser.add_argument('--workspace-root', required=True, type=Path)
    parser.add_argument('--metadata-root', default=REPO, type=Path)
    args = parser.parse_args(argv)
    results = []
    failed = False
    for path in args.recipes:
        try:
            result = validate_recipe(read_json(path), workspace_root=args.workspace_root,
                                     metadata_root=args.metadata_root)
        except (ValueError, OSError, KeyError, TypeError) as error:
            failed = True
            result = {'path': str(path), 'status': 'INVALID', 'valid': False,
                      'error': str(error), 'semantic_approval': False, 'execution_allowed': False}
        results.append(result)
    print(json.dumps(results, sort_keys=True, allow_nan=False))
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
