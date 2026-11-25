#!/usr/bin/env python3
"""Check MapLibre label inputs for data-source names without drawing a map."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path

SOURCE_FIELDS = ('id', 'name', 'label', 'provider', 'attribution')


class InputError(ValueError):
    """An input could not be loaded as the expected document."""


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InputError(f'{path}: {type(exc).__name__}: {exc}') from exc


def object_at(value, path: Path, where: str) -> dict:
    if not isinstance(value, dict):
        raise InputError(f'{path}: expected an object for {where}')
    return value


def rows_at(document: dict, key: str, path: Path) -> Iterator[dict]:
    rows = document.get(key)
    if not isinstance(rows, list):
        raise InputError(f'{path}: expected an array for {key}')
    for i, row in enumerate(rows):
        yield object_at(row, path, f'{key}[{i}]')


def files_in(directory: Path, suffix: str) -> list[Path]:
    try:
        return sorted(path for path in directory.iterdir() if path.suffix == suffix)
    except FileNotFoundError:
        return []  # A repo need not have relief pointers or contour data yet.
    except OSError as exc:
        raise InputError(f'{directory}: {type(exc).__name__}: {exc}') from exc


def default_styles(root: Path) -> Iterator[Path]:
    index = root / 'style/index.json'
    document = object_at(read_json(index), index, 'style index')
    versions = object_at(document.get('layers'), index, 'layers')
    for version, row in versions.items():
        fragment = object_at(row, index, version).get('fragment')
        if not isinstance(fragment, str) or not fragment:
            raise InputError(f'{index}: expected a fragment path for {version}')
        yield index.parent / fragment


def source_patterns(root: Path) -> dict[str, re.Pattern]:
    catalog = root / 'catalog/sources.json'
    pointers = files_in(root / 'catalog/relief', '.json')
    names: dict[str, set[str]] = {}
    for path in [catalog, *(p for p in pointers if p.name != 'pointer.schema.json')]:
        document = object_at(read_json(path), path, 'source document')
        for row in rows_at(document, 'sources', path):
            source_id = row.get('id')
            if not isinstance(source_id, str) or not source_id:
                raise InputError(f'{path}: expected a source id')
            rights = row.get('rights')
            terms = [row.get(field) for field in SOURCE_FIELDS]
            if isinstance(rights, dict):
                terms.append(rights.get('attribution'))
            names.setdefault(source_id, set()).update(
                re.escape(term.casefold()) for term in terms if isinstance(term, str) and len(term) >= 4
            )
    return {
        source_id: re.compile(r'(?<!\w)(?:' + '|'.join(sorted(terms)) + r')(?!\w)')
        for source_id, terms in sorted(names.items()) if terms
    }


def text_parts(value, *, literal: bool = False) -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield 'text', value
    elif isinstance(value, list):
        if not literal and value and isinstance(value[0], str):
            # MapLibre's expression operator and the get key are syntax, not ink.
            operator, *args = value
            if operator == 'get' and args and isinstance(args[0], str):
                yield 'field', args[0]
                args = args[1:]
            for i, arg in enumerate(args):
                match_labels = operator == 'match' and i % 2 == 1 and i < len(args) - 1
                yield from text_parts(arg, literal=operator == 'literal' or match_labels)
        else:
            for item in value:
                yield from text_parts(item, literal=literal)
    elif isinstance(value, dict):
        for item in value.values():
            yield from text_parts(item, literal=literal)


def display_path(path: Path, root: Path) -> str:
    return str(path.relative_to(root) if path.is_relative_to(root) else path)


def scan(root: Path, styles: list[Path], data: list[Path], fields: set[str]) -> Iterator[dict]:
    patterns = source_patterns(root)

    def matches(text: str, location: dict) -> Iterator[dict]:
        folded = text.casefold()
        for source_id, pattern in patterns.items():
            if pattern.search(folded):
                yield {**location, 'text': text, 'source_id': source_id}

    for path in dict.fromkeys(styles or default_styles(root)):
        document = object_at(read_json(path), path, 'style')
        for layer in rows_at(document, 'layers', path):
            layout = object_at(layer.get('layout', {}), path, 'layer layout')
            if 'text-field' not in layout:
                continue
            layer_id = layer.get('id')
            if not isinstance(layer_id, str) or not layer_id:
                raise InputError(f'{path}: expected a layer id for text-field')
            location = {'file': display_path(path, root), 'layer_id': layer_id, 'property': 'text-field'}
            for kind, value in text_parts(layout['text-field']):
                if kind == 'field':
                    fields.add(value)
                else:
                    yield from matches(value, location)

    data_paths = files_in(root / 'catalog/depth-contours', '.geojson') + data
    for path in dict.fromkeys(data_paths):
        document = object_at(read_json(path), path, 'GeoJSON')
        file = display_path(path, root)
        for i, feature in enumerate(rows_at(document, 'features', path)):
            properties = feature.get('properties')
            if properties is None:  # GeoJSON permits null feature properties.
                continue
            properties = object_at(properties, path, f'features[{i}].properties')
            for field in sorted(fields):
                value = properties.get(field)
                if isinstance(value, str):
                    yield from matches(value, {'file': file, 'feature_index': i, 'property': field})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2], help='repository root')
    parser.add_argument('--style', type=Path, nargs='+', action='extend', default=[],
                        help='style fragments instead of the fragments in style/index.json')
    parser.add_argument('--data', type=Path, nargs='+', action='extend', default=[],
                        help='GeoJSON inputs in addition to catalog/depth-contours/*.geojson')
    parser.add_argument('--field', nargs='+', action='extend', help='extra feature properties (default: label)')
    parser.add_argument('--json', action='store_true', help='print a JSON array of findings')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        findings = list(scan(root, [root / p for p in args.style], [root / p for p in args.data],
                             set(args.field or ['label'])))
    except InputError as exc:
        print(f'label_lint: {exc}', file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(findings, indent=2, ensure_ascii=False))
    elif findings:
        for finding in findings:
            origin = (f"layer {finding['layer_id']!r}" if 'layer_id' in finding
                      else f"feature {finding['feature_index']}")
            print(f"{finding['file']}: {origin}, {finding['property']!r}: "
                  f"{finding['text']!r} matches {finding['source_id']!r}")
    else:
        print('No source names found in scanned labels.')
    return int(bool(findings))


if __name__ == '__main__':
    sys.exit(main())
