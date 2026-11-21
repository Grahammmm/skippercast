#!/usr/bin/env python3
"""Report release-region config readiness without running or publishing relief."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
from unittest.mock import patch

from skippercast import validate
from skippercast.relief import package, render_config

COLUMNS = ('region', 'region_json', 'coast_json', 'render', 'style', 'previews', 'ready')
INDEX = 'dist/regions/index.json'


def _read(path):
    return package.decode_document(path.read_bytes())


def _invalid(error):
    return f'invalid: {str(error).splitlines()[0]}'


def _release_regions(root):
    rows = _read(root / INDEX).get('regions')
    if not isinstance(rows, list) or not rows:
        raise ValueError('expected a nonempty regions list')
    ids = []
    for row in rows:
        region = row.get('id') if isinstance(row, dict) else None
        if not isinstance(region, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', region):
            raise ValueError('invalid release region id')
        if region in ids:
            raise ValueError(f'duplicate release region id {region}')
        ids.append(region)
    return ids


def _region(path, region_id):
    try:
        region = _read(path)
        errors = validate.errors('region', region)
        if errors:
            return _invalid(errors[0]), None
        if region['id'] != region_id:
            return _invalid(f'id must equal {region_id}'), None
    except FileNotFoundError:
        return 'missing', None
    except (ValueError, OSError, validate.MissingDependency) as error:
        return _invalid(error), None
    return 'ok', region


def _coast(path, region_id):
    try:
        coast = _read(path)
    except FileNotFoundError:
        return 'missing'
    except (ValueError, OSError) as error:
        return _invalid(error)
    if coast.get('slug') != region_id:
        return _invalid(f'slug must equal {region_id}')
    depth = coast.get('depth_target_ft')
    if not isinstance(depth, (int, float)) or depth < 300:
        return _invalid('depth_target_ft must be at least 300')
    sources = coast.get('sources')
    if not isinstance(sources, list) or not all(isinstance(source, str) for source in sources):
        return _invalid('sources must be a list of source ids')
    reviews = coast.get('source_review_status')
    if not isinstance(reviews, dict):
        return _invalid('source_review_status must be an object')
    for source in sources:
        if source not in reviews:
            return _invalid(f'missing source_review_status for {source}')
    for source in sources:
        if reviews[source] != 'approved':
            return f'review: {source}={reviews[source]}'
    return 'ok'


def _render(region_id, region):
    try:
        # Use the same loader as previews(), but check the validated window list
        # independently: previews() itself refuses an unavailable style pin.
        config = render_config._config(region_id)
    except (OSError, ValueError, ImportError) as error:
        return _invalid(error), 'invalid: render config required', 'invalid: render config required', []
    if config is None:
        return 'missing', 'missing', 'missing', []
    try:
        render_config.resolve_style(region_id)
        style = 'ok'
    except (OSError, ValueError, KeyError, TypeError) as error:
        rejected, separator, version = str(error).partition(': ')
        style = (f'unavailable style {version}' if separator and rejected == 'unavailable render style'
                 else _invalid(error))
    outside = []
    if region is not None:
        west, south, east, north = region['fishing_bounds']
        for window in config['previews']:
            lon, lat = window['center']
            if not (west <= lon <= east and south <= lat <= north):
                outside.append(window['id'])
    notes = ['outside fishing_bounds: ' + ', '.join(outside)] if outside else []
    return 'ok', style, 'ok', notes


def _row(root, region_id):
    folder = root / 'regions' / region_id
    region_status, region = _region(folder / 'region.json', region_id)
    coast = _coast(folder / 'coast.json', region_id)
    render, style, previews, notes = _render(region_id, region)
    checks = (region_status, coast, render, style, previews)
    ready = 'yes' if all(status == 'ok' for status in checks) else 'no'
    return dict(zip(COLUMNS, (region_id, *checks, ready)), notes=notes)


def _print_table(rows):
    lines = [COLUMNS, *([row[column] for column in COLUMNS] for row in rows)]
    widths = [max(map(len, column)) for column in zip(*lines)]
    for line, notes in zip(lines, [[], *(row['notes'] for row in rows)]):
        text = '  '.join(cell.ljust(width) for cell, width in zip(line, widths)).rstrip()
        print(text + ('  notes: ' + '; '.join(notes) if notes else ''))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--json', action='store_true', help='emit a JSON array instead of a table')
    parser.add_argument('regions', metavar='REGION', nargs='*')
    args = parser.parse_intermixed_args(argv)
    root = args.root.resolve()
    try:
        release = _release_regions(root)
    except FileNotFoundError:
        parser.error(f'{INDEX}: missing')
    except (OSError, ValueError) as error:
        parser.error(f'{INDEX}: {_invalid(error)}')

    rows = []
    # render_config's root argument is a style directory, not a repository.
    # Its normal repo_root() hook honors SKIPPERCAST_ROOT for both reads.
    with patch.dict(os.environ, {'SKIPPERCAST_ROOT': str(root)}):
        for region_id in args.regions or release:
            if region_id in release:
                rows.append(_row(root, region_id))
            else:
                rows.append(dict(zip(COLUMNS, (region_id, *('invalid: not a release region',) * 5,
                                               'not a release region')), notes=[]))
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        _print_table(rows)
    return int(any(row['ready'] != 'yes' for row in rows))


if __name__ == '__main__':
    raise SystemExit(main())
