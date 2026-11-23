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
STRING_LANGUAGES = ('en', 'es')
# Keep strings/templates and comments intact so embedded code-looking text is not a call.
TS_TOKEN = re.compile(r'''//[^\n]*|/\*[\s\S]*?\*/|"(?:\\[\s\S]|[^"\\])*"'''
                      r'''|'(?:\\[\s\S]|[^'\\])*'|`(?:\\[\s\S]|[^`\\])*`|[\w$]+|[^\s]''')
TS_GROUPS = {'(': ')', '[': ']', '{': '}'}
IDENTIFIER = re.compile(r'[A-Za-z_$][\w$]*')


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


def ts_value_end(tokens: list[str], start: int) -> int:
    """Find the next sibling property or enclosing delimiter after a value."""
    stack: list[str] = []
    for i in range(start, len(tokens)):
        token = tokens[i]
        if token in TS_GROUPS:
            stack.append(TS_GROUPS[token])
        elif stack and token == stack[-1]:
            stack.pop()
        elif not stack and token in (',', ';', '}', ')', ']', 'const', 'let', 'var'):
            return i
    return len(tokens)


def lookup_keys(tokens: list[str]) -> Iterator[str]:
    for i in range(len(tokens) - 3):
        name, opening, key, following = tokens[i:i + 4]
        if (name == 't' and (i == 0 or tokens[i - 1] != '.') and opening == '('
                and key.startswith(('"', "'")) and following in (',', ')')):
            yield key[1:-1]


Span = tuple[int, int]
MODULE: Span = (-1, 1 << 60)  # the whole file
Binding = tuple[Span, int, int]  # (scope, value start, value end) in token positions


def block_spans(tokens: list[str]) -> list[Span]:
    """Token spans of every {...} block (function bodies, blocks, object literals)."""
    spans: list[Span] = []
    opened: list[int] = []
    for i, token in enumerate(tokens):
        if token == '{':
            opened.append(i)
        elif token == '}' and opened:
            spans.append((opened.pop(), i))
    spans.extend((start, len(tokens)) for start in opened)  # unbalanced: runs to the end
    return spans


def scope_at(spans: list[Span], i: int) -> Span:
    inside = [span for span in spans if span[0] < i < span[1]]
    return min(inside, key=lambda span: span[1] - span[0], default=MODULE)


def local_bindings(tokens: list[str], spans: list[Span]) -> dict[str, list[Binding]]:
    """Map each local name to the values assigned to it, each tagged with its block scope."""
    declared: dict[str, list[Binding]] = {}
    assigned: list[tuple[str, int, int, int]] = []
    for i in range(len(tokens) - 1):
        name = tokens[i]
        if not IDENTIFIER.fullmatch(name):
            continue
        declaration = i > 0 and tokens[i - 1] in ('const', 'let', 'var')
        if tokens[i + 1] != '=' or (i + 2 < len(tokens) and tokens[i + 2] in ('=', '>')):
            if declaration:  # `let label;` still opens a local of that name
                declared.setdefault(name, []).append((scope_at(spans, i), i, i))
            continue  # not a binding: ==, === or an arrow function (x => ...)
        if i and tokens[i - 1] in ('.', '=', '!', '<', '>'):
            continue  # a member store or a comparison, not a local binding
        end = ts_value_end(tokens, i + 2)
        if declaration:
            declared.setdefault(name, []).append((scope_at(spans, i), i + 2, end))
        else:
            assigned.append((name, i, i + 2, end))
    bindings = {name: list(rows) for name, rows in declared.items()}
    for name, i, start, end in assigned:  # a bare `label = ...` updates the nearest declared local
        scopes = [row[0] for row in declared.get(name, []) if row[0][0] < i < row[0][1]]
        scope = min(scopes, key=lambda span: span[1] - span[0], default=MODULE)
        bindings.setdefault(name, []).append((scope, start, end))
    return bindings


def value_keys(tokens: list[str], start: int, end: int, bindings: dict[str, list[Binding]]) -> set[str]:
    """Literal t() keys in tokens[start:end], following each local name to what its scope assigned."""
    keys: set[str] = set()
    seen: set[Binding] = set()
    pending = [(start, end)]
    while pending:
        begin, stop = pending.pop()
        keys.update(lookup_keys(tokens[begin:stop]))
        for i in range(begin, stop):
            token = tokens[i]
            if (token not in bindings or (i > begin and tokens[i - 1] == '.')
                    or (i + 1 < stop and tokens[i + 1] in ('(', ':'))):
                continue
            visible = [row for row in bindings[token] if row[0][0] < i < row[0][1]]
            if not visible:
                continue
            innermost = min(row[0][1] - row[0][0] for row in visible)  # shadowing: nearest scope wins
            for row in visible:
                if row[0][1] - row[0][0] == innermost and row not in seen:
                    seen.add(row)
                    pending.append((row[1], row[2]))
    return keys


def drawn_string_keys(source: str) -> set[str]:
    """Follow literal t() calls in text-field values and their local GeoJSON fields.

    Saved spots use the second form: a translated fallback in properties.name,
    drawn by ['get', 'name'] in the same module. This is a source scan of those
    shapes, not general TypeScript dataflow (computed lookup keys are excluded).
    """
    tokens = [token for token in TS_TOKEN.findall(source) if not token.startswith(('//', '/*'))]
    bindings = local_bindings(tokens, block_spans(tokens))
    keys: set[str] = set()
    fields: set[str] = set()
    properties: list[int] = []
    for i in range(len(tokens) - 2):
        name, colon, start = tokens[i:i + 3]
        if colon != ':':
            continue
        if name in ('"text-field"', "'text-field'"):
            end = ts_value_end(tokens, i + 2)
            value = tokens[i + 2:end]
            keys.update(value_keys(tokens, i + 2, end, bindings))
            for opening, op, comma, field in zip(value, value[1:], value[2:], value[3:]):
                if opening == '[' and op in ('"get"', "'get'") and comma == ',' and field.startswith(('"', "'")):
                    fields.add(field[1:-1])
        elif name in ('properties', '"properties"', "'properties'") and start == '{':
            properties.append(i + 3)
    for i in properties:
        while i + 1 < len(tokens) and tokens[i] != '}':
            if tokens[i + 1] == ':':
                end = ts_value_end(tokens, i + 2)
                if tokens[i].strip('"\'') in fields:
                    keys.update(value_keys(tokens, i + 2, end, bindings))
            else:
                end = ts_value_end(tokens, i)
                if tokens[i] in fields:  # shorthand: {name} reads the local called name
                    keys.update(value_keys(tokens, i, end, bindings))
            if end == len(tokens) or tokens[end] != ',':
                break
            i = end + 1
    return keys


def catalogue_labels(root: Path) -> Iterator[tuple[dict, str | None]]:
    keys: set[str] = set()
    for path in files_in(root / 'web/map', '.ts'):
        try:
            source = path.read_text(encoding='utf-8')
        except (OSError, UnicodeError) as exc:
            raise InputError(f'{path}: {type(exc).__name__}: {exc}') from exc
        keys.update(drawn_string_keys(source))
    if not keys:
        return
    for lang in STRING_LANGUAGES:
        path = root / f'web/strings.{lang}.generated.json'
        table = object_at(read_json(path), path, 'string catalogue')
        for key in sorted(keys):
            location = {'file': display_path(path, root), 'key': key, 'lang': lang}
            if key not in table:
                yield location, None
                continue
            # The bundled English table wraps values; the Spanish overlay is flat.
            text = object_at(table[key], path, key).get(lang) if lang == 'en' else table[key]
            if not isinstance(text, str):
                raise InputError(f'{path}: expected translated text for {key}')
            yield location, text


def scan(root: Path, styles: list[Path], data: list[Path], fields: set[str], *, strings: bool = False) -> Iterator[dict]:
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

    if strings:
        for location, text in catalogue_labels(root):
            if text is None:
                yield {**location, 'kind': 'missing-key'}
            else:
                yield from matches(text, location)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2], help='repository root')
    parser.add_argument('--style', type=Path, nargs='+', action='extend', default=[],
                        help='style fragments instead of the fragments in style/index.json')
    parser.add_argument('--data', type=Path, nargs='+', action='extend', default=[],
                        help='GeoJSON inputs in addition to catalog/depth-contours/*.geojson')
    parser.add_argument('--field', nargs='+', action='extend', help='extra feature properties (default: label)')
    parser.add_argument('--strings', action='store_true', help='also check translated map feature labels')
    parser.add_argument('--json', action='store_true', help='print a JSON array of findings')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        findings = list(scan(root, [root / p for p in args.style], [root / p for p in args.data],
                             set(args.field or ['label']), strings=args.strings))
    except InputError as exc:
        print(f'label_lint: {exc}', file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(findings, indent=2, ensure_ascii=False))
    elif findings:
        for finding in findings:
            if 'key' in finding:
                origin = f"{finding['file']}: {finding['lang']} key {finding['key']!r}"
                if finding.get('kind') == 'missing-key':
                    print(f'{origin}: missing-key')
                else:
                    print(f"{origin}: {finding['text']!r} matches {finding['source_id']!r}")
                continue
            origin = (f"layer {finding['layer_id']!r}" if 'layer_id' in finding
                      else f"feature {finding['feature_index']}")
            print(f"{finding['file']}: {origin}, {finding['property']!r}: "
                  f"{finding['text']!r} matches {finding['source_id']!r}")
    else:
        print('No source names found in scanned labels.')
    return int(any('source_id' in finding for finding in findings))


if __name__ == '__main__':
    sys.exit(main())
