"""Check reviewed relief pointer pairings without building or publishing anything."""
from __future__ import annotations

import argparse
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


def _contours_error(path: Path, region: object) -> str:
    try:
        provenance = _read_object(path).get('provenance')
    except FileNotFoundError:
        return f'missing catalog/depth-contours/{path.name}'
    except (OSError, ValueError):
        return f'cannot read contours object for {path.stem}'
    if not isinstance(region, str) or not isinstance(provenance, dict) or provenance.get('region_id') != region:
        return 'contours provenance.region_id does not match pointer region'
    return ''


def check_catalog(root: str | Path) -> list[dict]:
    """Return five rows per pointer, ordered by filename; contours alone are allowed."""
    root = Path(root)
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
            ('contours', _contours_error(root / 'catalog/depth-contours' / f'{region_id}.geojson', region)),
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
    args = parser.parse_args(argv)
    root = args.root if args.root is not None else repo_root()
    if not (root / _RELIEF / _SCHEMA).is_file():
        parser.error(f'--root must contain {_RELIEF / _SCHEMA}')

    rows = check_catalog(root)
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
