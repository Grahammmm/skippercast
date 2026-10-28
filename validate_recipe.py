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


def _shape(document, metadata_root):
    # Do not use validate.check: its emergency off/missing-dependency fallback is
    # inappropriate here. Missing jsonschema fails closed; no remote refs exist.
    try:
        from jsonschema import Draft202012Validator
    except ImportError as error:
        raise RecipeError('jsonschema is required for recipe validation') from error
    schema = read_json(metadata_root / 'schemas/coast-recipe-v1.schema.json')
    Draft202012Validator.check_schema(schema)
    problems = list(Draft202012Validator(schema).iter_errors(document))
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
