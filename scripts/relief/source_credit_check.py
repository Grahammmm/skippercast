"""Check rendered Sources credits against reviewed relief inputs in a local tree.

Use ``check(root)`` from the repository checkout. This reads the register and
existing HTML; it neither rebuilds the page nor verifies a deployed release.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
import re
from typing import Literal

from scripts import build_sources_register as register


CreditStatus = Literal['present', 'no-reviewed-pointer', 'missing-credit', 'unresolvable-display-tuple']


@dataclass(frozen=True)
class CreditCheck:
    region: str
    layer: str
    source_id: str | None
    status: CreditStatus


# These are the Sources renderer's structural seams, not serialized HTML
# snippets: h3 live group -> h4 region anchor -> h5 layer -> sibling ul.
_VOID = frozenset('area base br col embed hr img input link meta param source track wbr'.split())


@dataclass
class _Element:
    tag: str
    attrs: dict[str, str | None] = field(default_factory=dict)
    children: list[_Element | str] = field(default_factory=list)

    @property
    def visible(self):
        # Be conservative when inline declarations hide a subtree: even an
        # overridden display:none must not be used as proof of public credit.
        style = self.attrs.get('style') or ''
        # CSS comments can appear between declaration tokens, including after
        # the value. Remove them before checking for hidden display declarations.
        style = re.sub(r'/\*.*?\*/', '', style, flags=re.S)
        hidden_display = re.search(r'(?:^|;)\s*display\s*:\s*none\s*(?:!\s*important\s*)?(?:;|$)', style, re.I)
        return ('hidden' not in self.attrs and not hidden_display
                and self.tag not in {'script', 'style', 'template'})


class _Markup(HTMLParser):
    def __init__(self, page):
        super().__init__()
        self.stack = [_Element('document')]
        self.feed(page)
        self.close()

    def handle_starttag(self, tag, attrs):
        element = _Element(tag, dict(attrs))
        self.stack[-1].children.append(element)
        if tag not in _VOID:
            self.stack.append(element)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _space(text):
    return ' '.join(text.split())


def _text(node):
    if isinstance(node, str):
        return node
    return ''.join(map(_text, node.children)) if node.visible else ''


def _elements(node):
    return (child for child in node.children if isinstance(child, _Element) and child.visible)


def _sections(node):
    for child in _elements(node):
        if child.tag == 'section' and child.attrs.get('id') == 'data-sources':
            yield child
        else:
            yield from _sections(child)


def _entry_tuple(item):
    # The generated item starts with a strong source name, then uses <br>
    # for facts and credit. The optional terminal link isn't attribution.
    lines = [[]]
    for node in item.children:
        if isinstance(node, _Element):
            if not node.visible:
                continue
            if node.tag == 'br':
                lines.append([])
                continue
        lines[-1].append(node)
    first = next((node for node in lines[0] if isinstance(node, _Element)), None)
    if first is None or first.tag != 'strong':
        return None
    credits = []
    for line in lines[1:]:
        while line and isinstance(line[-1], str) and not line[-1].strip():
            line.pop()
        if line and isinstance(line[-1], _Element) and line[-1].tag == 'a':
            text = _space(''.join(map(_text, line[:-1])))
            text = text.removesuffix(' ·')
        else:
            text = _space(''.join(map(_text, line)))
        if text.startswith('Credit: '):
            credits.append(text.removeprefix('Credit: '))
    return (_space(_text(first)), credits[0]) if len(credits) == 1 else None


def _page_credits(page):
    credits = defaultdict(set)
    sections = list(_sections(_Markup(page).stack[0]))
    if len(sections) != 1:
        return credits
    live, anchor, layer = False, None, None
    for child in _elements(sections[0]):
        tag, ident = child.tag, child.attrs.get('id')
        if tag in {'h1', 'h2', 'h3'}:
            live, anchor, layer = tag == 'h3' and ident == 'data-sources-live', None, None
        elif live and tag == 'h4':
            anchor, layer = ident, None
        elif live and anchor and tag == 'h5':
            layer = _space(_text(child))
        elif layer:
            if tag == 'ul':
                credits[anchor, layer].update(
                    pair for item in _elements(child) if item.tag == 'li'
                    if (pair := _entry_tuple(item)) is not None
                )
            # Consume only the layer's own list, never the next unrelated one.
            layer = None
    return credits


def check(root: Path | str) -> tuple[CreditCheck, ...]:
    """Report outcomes per source and per registered region without a pointer.

    Depth contours are checked independently, including in contour-only regions.
    A missing page supplies no credit evidence. Invalid register inputs (e.g.
    invalid pointers or unknown source IDs) retain the register's own error.
    """
    root = Path(root)
    data = register.collect(root)
    layers = (register.DEPTH_SHADING, register.DEPTH_CONTOURS)
    expected = [(region['id'], layer, source_id)
                for region in data['regions'] for layer in layers
                for source_id in region['layers'].get(layer, {})]
    results = [CreditCheck(region['id'], register.DEPTH_SHADING, None, 'no-reviewed-pointer')
               for region in data['regions'] if not region['layers'].get(register.DEPTH_SHADING)]
    if not expected:
        return tuple(results)

    # Even repetitions of a tuple in the HTML carry no ID. A different
    # displayable catalogue ID with the same tuple makes that evidence ambiguous.
    tuples = {}
    ids_by_tuple = defaultdict(set)
    for source_id, row in data['sources'].items():
        name = _space(row['name'])
        attribution = _space(row['rights'].get('attribution') or '')
        if name and attribution and register.listed(row, live=True):
            pair = name, attribution
            tuples[source_id] = pair
            ids_by_tuple[pair].add(source_id)

    try:
        page = (root / register.PAGE).read_text(encoding='utf-8')
    except FileNotFoundError:
        page = ''
    credits = _page_credits(page)
    for region, layer, source_id in expected:
        pair = tuples.get(source_id)
        status: CreditStatus
        if pair is None or len(ids_by_tuple[pair]) != 1:
            status = 'unresolvable-display-tuple'
        elif pair not in credits.get((f'region-{region}', layer), ()):
            status = 'missing-credit'
        else:
            status = 'present'
        results.append(CreditCheck(region, layer, source_id, status))
    return tuple(results)
