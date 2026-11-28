"""Check reviewed relief pointer pairings without building or publishing anything."""
from __future__ import annotations

import argparse
from collections.abc import Collection
import json
from pathlib import Path
import sys

from skippercast.paths import repo_root
from skippercast.relief import package

_RELIEF = Path('catalog/relief')
_SCHEMA = 'pointer.schema.json'
_INDEX = Path('dist/regions/index.json')


def _read_object(path: Path) -> dict:
    return package.decode_document(path.read_bytes())


def _validation_error(doc: dict, schema: dict) -> str:
    try:
        package.validate_schema(doc, schema)
    except package.ReleaseError as exc:
        return str(exc)
    return ''


def _release_regions(path: Path) -> set[str]:
    try:
        return {row['id'] for row in _read_object(path)['regions']}
    except (OSError, ValueError, KeyError, TypeError):
        return set()


def _no_contours_expected(doc: dict, region_id: str, terrain_only: Collection[str]) -> bool:
    """A designated terrain-only region whose own pointer explicitly pins no contour style."""
    style = doc.get('style')
    return (region_id in terrain_only and doc.get('region') == region_id
            and isinstance(style, dict) and 'contours' in style and style['contours'] is None)


def _contours_error(path: Path, region: object, no_contours: bool) -> str:
    try:
        provenance = _read_object(path).get('provenance')
    except FileNotFoundError:
        # Terrain-only regions ship relief shading alone, so they have no contour file.
        return '' if no_contours and not path.is_symlink() else f'missing catalog/depth-contours/{path.name}'
    except (OSError, ValueError):
        return f'cannot read contours object for {path.stem}'
    if not isinstance(region, str) or not isinstance(provenance, dict) or provenance.get('region_id') != region:
        return 'contours provenance.region_id does not match pointer region'
    return ''


def check_catalog(root: str | Path, terrain_only: Collection[str] = ()) -> list[dict]:
    """Return five rows per pointer, ordered by filename; contours alone are allowed.

    `terrain_only` is the caller's designated list of regions that ship no contours (the stage tooling's
    TERRAIN_ONLY_REGIONS); it never comes from the checked tree. Such a region may have no contour file
    when its pointer pins style.contours null; a contour file that is present is checked as usual. The
    default (none designated) keeps every pointer strict.
    """
    root = Path(root)
    if isinstance(terrain_only, (str, bytes)):
        raise TypeError('terrain_only must be a collection of region ids, not one string')
    terrain_only = frozenset(terrain_only)
    pointers = sorted(path for path in (root / _RELIEF).glob('*.json') if path.name != _SCHEMA)
    if not pointers:
        return []

    schema = _read_object(root / _RELIEF / _SCHEMA)
    # Project the existing lineage rule, retaining its local references. This
    # gives lineage its own row even if unrelated pointer metadata is invalid.
    lineage_schema = {
        '$defs': schema['$defs'],
        'required': ['previous'],
        'properties': {'previous': schema['properties']['previous']},
    }
    regions = _release_regions(root / _INDEX)
    rows = []
    for path in pointers:
        region_id = path.stem
        try:
            doc = _read_object(path)
        except (OSError, ValueError):
            doc = {}
            schema_error = 'cannot read pointer JSON object'
        else:
            schema_error = _validation_error(doc, schema)
        region = doc.get('region')
        listed = isinstance(region, str) and region in regions
        checks = (
            ('schema', schema_error),
            ('filename', '' if region == region_id else 'filename id does not match pointer region'),
            ('release-region', '' if listed else f'pointer region not listed in {_INDEX.as_posix()}'),
            ('contours', _contours_error(root / 'catalog/depth-contours' / f'{region_id}.geojson', region,
                                         _no_contours_expected(doc, region_id, terrain_only))),
            ('lineage', 'previous must be null or match the pointer lineage schema'
             if _validation_error(doc, lineage_schema) else ''),
        )
        rows.extend({'region': region_id, 'check': check, 'status': 'FAIL' if error else 'PASS',
                     'reason': error or 'ok'} for check, error in checks)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, help='SkipperCast checkout (default: package checkout)')
    parser.add_argument('--json', action='store_true', help='emit JSON rows on stdout and the summary on stderr')
    parser.add_argument('--terrain-only', action='append', default=[], metavar='REGION',
                        help='designated terrain-only region (repeatable): may have no contour file')
    args = parser.parse_args(argv)
    root = args.root if args.root is not None else repo_root()
    if not (root / _RELIEF / _SCHEMA).is_file():
        parser.error(f'--root must contain {_RELIEF / _SCHEMA}')

    rows = check_catalog(root, terrain_only=frozenset(args.terrain_only))
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            print('{region} {check} {status}: {reason}'.format(**row))
    failures = sum(row['status'] == 'FAIL' for row in rows)
    print(f'CATALOG FAIL {failures}' if failures else 'CATALOG OK', file=sys.stderr if args.json else sys.stdout)
    return int(failures > 0)


if __name__ == '__main__':
    raise SystemExit(main())
