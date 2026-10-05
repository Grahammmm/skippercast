"""A small, forgiving HTML tree for the fleet page parsers (stdlib ``html.parser`` only).

Report sites and directories publish hand-written HTML with unclosed ``<p>``,
``<li>``, ``<td>`` and ``<dd>`` elements; this builder closes those implicitly,
ignores stray end tags and drops ``<script>``/``<style>`` content, so parsers can
select elements by tag and class instead of matching raw markup with regular
expressions.
"""
from __future__ import annotations

from html.parser import HTMLParser
import re
from typing import Callable, Iterator

VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track",
                  "wbr"})
# Starting one of these closes an open element of the same group (implicit end tags).
IMPLICIT = {"p": {"p"}, "li": {"li"}, "dt": {"dt", "dd"}, "dd": {"dt", "dd"}, "tr": {"tr", "td", "th"},
            "td": {"td", "th"}, "th": {"td", "th"}, "option": {"option"}}
SKIP = frozenset({"script", "style", "noscript", "template", "svg"})
_SPACE = re.compile(r"\s+")


class LayoutError(ValueError):
    """A page no longer has the structure its parser expects (raised instead of returning nothing)."""

    def __init__(self, url: str, detail: str):
        super().__init__(f"{detail}: {url}")
        self.url, self.detail = url, detail


class Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict[str, str] | None = None, parent: "Node | None" = None):
        self.tag = tag
        self.attrs = attrs or {}
        self.children: list[Node | str] = []
        self.parent = parent

    @property
    def classes(self) -> set[str]:
        return set((self.attrs.get("class") or "").split())

    def text(self) -> str:
        """The element's text with whitespace collapsed; ``<br>`` counts as a space."""
        parts: list[str] = []

        def walk(node: Node) -> None:
            for child in node.children:
                if isinstance(child, str):
                    parts.append(child)
                elif child.tag == "br":
                    parts.append(" ")
                else:
                    walk(child)
        walk(self)
        return _SPACE.sub(" ", "".join(parts)).strip()

    def iter(self) -> Iterator["Node"]:
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.iter()

    def find_all(self, tag: str | None = None, cls: str | None = None,
                 where: Callable[["Node"], bool] | None = None) -> list["Node"]:
        return [n for n in self.iter() if (tag is None or n.tag == tag) and (cls is None or cls in n.classes)
                and (where is None or where(n))]

    def find(self, tag: str | None = None, cls: str | None = None,
             where: Callable[["Node"], bool] | None = None) -> "Node | None":
        return next((n for n in self.iter() if (tag is None or n.tag == tag) and (cls is None or cls in n.classes)
                     and (where is None or where(n))), None)

    def element_children(self) -> list["Node"]:
        return [c for c in self.children if isinstance(c, Node)]


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#document")
        self.stack = [self.root]
        self.skipping = 0

    def handle_starttag(self, tag, attrs):
        if self.skipping:
            if tag in SKIP:
                self.skipping += 1
            return
        if tag in SKIP:
            self.skipping = 1
            return
        group = IMPLICIT.get(tag)
        if group:
            for depth in range(len(self.stack) - 1, 0, -1):
                open_tag = self.stack[depth].tag
                if open_tag in group:
                    del self.stack[depth:]
                    break
                if open_tag in ("table", "ul", "ol", "dl", "div", "tbody", "thead", "section", "article"):
                    break
        node = Node(tag, {k: v or "" for k, v in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        if self.skipping:
            return
        node = Node(tag, {k: v or "" for k, v in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)

    def handle_endtag(self, tag):
        if self.skipping:
            if tag in SKIP:
                self.skipping -= 1
            return
        for depth in range(len(self.stack) - 1, 0, -1):
            if self.stack[depth].tag == tag:
                del self.stack[depth:]
                return
        # a stray end tag closes nothing

    def handle_data(self, data):
        if not self.skipping and data:
            self.stack[-1].children.append(data)


def parse(markup: str) -> Node:
    builder = _Builder()
    builder.feed(markup)
    builder.close()
    return builder.root
