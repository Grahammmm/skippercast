#!/usr/bin/env python3
"""Check release bounds and catalog state in this checkout, not deployed tiles."""

from __future__ import annotations

import argparse
import json
import re
import sys
from itertools import combinations
from pathlib import Path
from typing import TypedDict

ROOT = Path(__file__).resolve().parents[2]
ISLANDS = ('channel-islands-north', 'outer-islands-borderland')
Bounds = tuple[float, float, float, float]  # west, south, east, north


class Regions(TypedDict):
    south: float
    north: float
    release: dict[str, Bounds]
    islands: dict[str, Bounds]


def load_regions(root: Path) -> Regions:
    """Take membership from the packaged index and geometry from source configs."""
    def bounds(region_id: str) -> Bounds:
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', region_id):
            raise ValueError(f'invalid region id: {region_id!r}')
        path = root / 'regions' / region_id / 'region.json'
        west, south, east, north = json.loads(path.read_text(encoding='utf-8'))['bounds']
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise ValueError(f'invalid bounds for {region_id}')
        return west, south, east, north

    index = json.loads((root / 'dist/regions/index.json').read_text(encoding='utf-8'))
    return {
        'south': bounds('san-diego')[1],
        'north': bounds('crescent-city')[3],
        'release': {entry['id']: bounds(entry['id']) for entry in index['regions']},
        'islands': {region_id: bounds(region_id) for region_id in ISLANDS},
    }


def coverage(regions: Regions) -> dict:
    """Report gaps and pairwise latitude overlaps within the anchor window.

    Only positive-width intervals count: touching edges are not gaps or
    overlaps. Island containment uses all four bounds, including shared edges;
    if several release regions qualify, report the lexically first ID.
    """
    south, north = regions['south'], regions['north']
    if not south < north:
        raise ValueError('south anchor must be below north anchor')

    release = regions['release']
    spans = []
    for region_id, (_, low, _, high) in release.items():
        start, end = max(south, low), min(north, high)
        if start < end:
            spans.append((start, end, region_id))
    spans.sort()

    gaps = []
    covered_to = south
    for start, end, _ in spans:
        if start > covered_to:
            gaps.append([covered_to, start])
        covered_to = max(covered_to, end)
    if covered_to < north:
        gaps.append([covered_to, north])

    overlaps = []
    for (start_a, end_a, id_a), (start_b, end_b, id_b) in combinations(spans, 2):
        start, end = max(start_a, start_b), min(end_a, end_b)
        if start < end:
            overlaps.append({'regions': [id_a, id_b], 'latitudes': [start, end]})

    islands_inside = {}
    ordered_release = sorted(release.items())
    for island_id, (west, low, east, high) in sorted(regions['islands'].items()):
        islands_inside[island_id] = next((
            region_id for region_id, (w, s, e, n) in ordered_release
            if w <= west and s <= low and east <= e and high <= n
        ), None)

    return {
        'gaps': gaps,
        'overlaps': overlaps,
        'islands_inside': islands_inside,
        'ok': not gaps and all(region_id is not None for region_id in islands_inside.values()),
    }


def _decode_object(data: bytes) -> dict:
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError(f'duplicate JSON member {key!r}')
            obj[key] = value
        return obj

    obj = json.loads(data.decode('utf-8'), object_pairs_hook=unique)
    if not isinstance(obj, dict):
        raise ValueError('expected a JSON object')
    # Reject nonfinite numbers (including overflow) and unpaired surrogates.
    json.dumps(obj, allow_nan=False, ensure_ascii=False).encode('utf-8')
    return obj


_SCHEMA_KEYS = frozenset('''$schema $defs title $ref type const enum allOf anyOf oneOf
    required properties patternProperties additionalProperties unevaluatedProperties
    minProperties minItems maxItems prefixItems items minLength maxLength pattern
    minimum maximum exclusiveMinimum'''.split())


def _json_equal(left, right) -> bool:
    # JSON booleans are not numbers; Python would equate False with 0.
    return isinstance(left, bool) == isinstance(right, bool) and left == right


def _pointer_matches(pointer: dict, schema: dict) -> bool:
    """Evaluate the checked-in pointer schema's subset with no runtime extras.

    This is not a general JSON Schema validator. Reject unsupported keywords
    and resolve only local definitions, never URLs.
    """
    types = {'object': dict, 'array': list, 'string': str, 'boolean': bool, 'null': type(None)}

    def evaluate(value, rule):
        # None means invalid; otherwise return evaluated property names so the
        # root's unevaluatedProperties sees both pointer and metadata fields.
        if rule.keys() - _SCHEMA_KEYS:
            raise ValueError('unsupported relief pointer schema keyword')
        if any(type(rule.get(key, True)) is not bool
               for key in ('additionalProperties', 'unevaluatedProperties')):
            raise ValueError('expected a boolean relief pointer property constraint')
        evaluated = set()
        kind = rule.get('type')
        number = type(value) in (int, float)
        if kind == 'number':
            if not number:
                return None
        elif kind == 'integer':
            if not number or (isinstance(value, float) and not value.is_integer()):
                return None
        elif kind is not None and not isinstance(value, types[kind]):
            return None
        if 'const' in rule and not _json_equal(value, rule['const']):
            return None
        if 'enum' in rule and not any(_json_equal(value, item) for item in rule['enum']):
            return None
        if '$ref' in rule:
            ref = rule['$ref']
            if not ref.startswith('#/$defs/'):
                raise ValueError('expected a local relief pointer schema reference')
            keys = evaluate(value, schema['$defs'][ref.removeprefix('#/$defs/')])
            if keys is None:
                return None
            evaluated.update(keys)
        for keyword in ('allOf', 'anyOf', 'oneOf'):
            if keyword not in rule:
                continue
            branches = rule[keyword]
            matches = [keys for branch in branches if (keys := evaluate(value, branch)) is not None]
            if (keyword == 'allOf' and len(matches) != len(branches)
                    or keyword == 'anyOf' and not matches
                    or keyword == 'oneOf' and len(matches) != 1):
                return None
            evaluated.update(*matches)
        if isinstance(value, dict):
            if len(value) < rule.get('minProperties', 0) or set(rule.get('required', ())) - value.keys():
                return None
            properties = rule.get('properties', {})
            patterns = rule.get('patternProperties', {})
            local = set()
            for key, item in value.items():
                rules = [properties[key]] if key in properties else []
                rules.extend(sub for pattern, sub in patterns.items() if re.search(pattern, key))
                if any(evaluate(item, sub) is None for sub in rules):
                    return None
                if rules:
                    local.add(key)
            if rule.get('additionalProperties') is False and value.keys() - local:
                return None
            evaluated.update(local)
            if rule.get('unevaluatedProperties') is False and value.keys() - evaluated:
                return None
        if isinstance(value, list):
            if not rule.get('minItems', 0) <= len(value) <= rule.get('maxItems', len(value)):
                return None
            prefix = rule.get('prefixItems', [])
            if any(evaluate(item, sub) is None for item, sub in zip(value, prefix)):
                return None
            if 'items' in rule and any(evaluate(item, rule['items']) is None for item in value[len(prefix):]):
                return None
        if isinstance(value, str) and (
            not rule.get('minLength', 0) <= len(value) <= rule.get('maxLength', len(value))
            or 'pattern' in rule and not re.search(rule['pattern'], value)
        ):
            return None
        if number and (
            value < rule.get('minimum', value) or value > rule.get('maximum', value)
            or 'exclusiveMinimum' in rule and value <= rule['exclusiveMinimum']
        ):
            return None
        return evaluated

    return evaluate(pointer, schema) is not None


def _relief_state(path: Path, region_id: str, schema: dict) -> str:
    try:
        pointer = _decode_object(path.read_bytes())
    except FileNotFoundError:
        return 'none'
    except (OSError, ValueError, RecursionError):
        return 'invalid'
    return (pointer['generation'][:12]
            if _pointer_matches(pointer, schema) and pointer['region'] == region_id else 'invalid')


def region_rows(root: Path, regions: Regions) -> list[dict[str, str]]:
    """Project catalog state for every release ID, independent of bounds coverage."""
    relief_dir = root / 'catalog/relief'
    contours_dir = root / 'catalog/depth-contours'
    schema = _decode_object((relief_dir / 'pointer.schema.json').read_bytes())
    return [
        {
            'id': region_id,
            'relief': _relief_state(relief_dir / f'{region_id}.json', region_id, schema),
            'contours': 'present' if (contours_dir / f'{region_id}.geojson').is_file() else 'none',
        }
        for region_id in sorted(regions['release'])
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    formats = parser.add_mutually_exclusive_group()
    formats.add_argument('--json', action='store_true', help='print machine-readable JSON')
    formats.add_argument('--markdown', action='store_true', help='print the catalog state table in Markdown')
    args = parser.parse_args(argv)
    try:
        regions = load_regions(ROOT)
        report = coverage(regions)
        if args.json or args.markdown:
            report['regions'] = region_rows(ROOT, regions)
    except (OSError, ValueError, KeyError, TypeError, re.error, RecursionError) as exc:
        print(f'Coast coverage could not be checked: {exc}', file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2))
    elif args.markdown:
        print('| Region | Relief | Contours |')
        print('| --- | --- | --- |')
        for row in report['regions']:
            print(f'| {row["id"]} | {row["relief"]} | {row["contours"]} |')
    else:
        print('Check      | Region(s) / island           | Result')
        for low, high in report['gaps']:
            print(f'Gap        | -                            | {low} to {high} N')
        for row in report['overlaps']:
            low, high = row['latitudes']
            print(f'Overlap    | {" / ".join(row["regions"])} | {low} to {high} N')
        for island, container in report['islands_inside'].items():
            print(f'Island     | {island} | {container or "outside"}')
        print(f'Configured coast coverage: {"OK" if report["ok"] else "NOT OK"}')
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
