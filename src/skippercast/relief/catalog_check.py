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
# The contour files a region config's `chart_files` can list (platform/build.py CHART_FILES); the Chart asks
# for a region's contours only when its region.json lists them.
_CONTOUR_CHARTS = frozenset({'depth-contours.geojson', 'depth-contours-overview.geojson'})


def _read_object(path: Path) -> dict:
    return package.decode_document(path.read_bytes())


def _validation_error(doc: dict, schema: dict) -> str:
    try:
        package.validate_schema(doc, schema)
    except package.ReleaseError as exc:
        return str(exc)
    return ''


def _release_configs(path: Path) -> dict[str, object]:
    """Region id -> its `config` path (relative to dist/) for every region the release index lists."""
    try:
        return {row['id']: row.get('config') for row in _read_object(path)['regions']}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {}


def _config_charts_no_contours(root: Path, config: object) -> bool:
    """The region's own config (dist/<config>) lists its chart files and none is a contour file."""
    if not isinstance(config, str) or Path(config).is_absolute() or '..' in Path(config).parts:
        return False
    try:
        files = _read_object(root / 'dist' / config).get('chart_files')
    except (OSError, ValueError, AttributeError):
        return False
    return (isinstance(files, list) and all(isinstance(name, str) for name in files)
            and not _CONTOUR_CHARTS.intersection(files))


def _terrain_only(doc: dict, root: Path, config: object) -> bool:
    """Terrain-only needs both: the pointer pins no contour style, and the region config charts no contours.

    The pointer alone cannot decide: a contour region (its region.json lists contour chart files) with a null
    contour style is still a contour region whose Chart would ask for the missing file.
    """
    style = doc.get('style')
    return (isinstance(style, dict) and 'contours' in style and style['contours'] is None
            and _config_charts_no_contours(root, config))


def _contours_error(path: Path, region: object, terrain_only: bool) -> str:
    try:
        provenance = _read_object(path).get('provenance')
    except FileNotFoundError:
        # Terrain-only regions ship relief shading alone, so they have no contour file.
        return '' if terrain_only and not path.is_symlink() else f'missing catalog/depth-contours/{path.name}'
    except (OSError, ValueError):
        return f'cannot read contours object for {path.stem}'
    if not isinstance(region, str) or not isinstance(provenance, dict) or provenance.get('region_id') != region:
        return 'contours provenance.region_id does not match pointer region'
    return ''


def check_catalog(root: str | Path) -> list[dict]:
    """Return five rows per pointer, ordered by filename; contours alone are allowed.

    A pointer with style.contours null whose region config (dist/regions/index.json `config`) lists no
    contour chart files is terrain-only: it may have no contour file, but a contour file that is present
    is checked as for any other pointer.
    """
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
    configs = _release_configs(root / _INDEX)
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
        listed = isinstance(region, str) and region in configs
        checks = (
            ('schema', schema_error),
            ('filename', '' if region == region_id else 'filename id does not match pointer region'),
            ('release-region', '' if listed else f'pointer region not listed in {_INDEX.as_posix()}'),
            ('contours', _contours_error(root / 'catalog/depth-contours' / f'{region_id}.geojson', region,
                                         _terrain_only(doc, root, configs.get(region_id)))),
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
