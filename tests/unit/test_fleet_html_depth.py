"""Explicitly deep (but fully closed) fleet HTML must traverse without Python recursion (RF0010-7).

Synthetic, offline markup only; the process recursion limit is never changed.
"""
import unittest

from skippercast.fleet.adapters._html import Node, parse
from skippercast.fleet.adapters.directories import parse_ggfa
from skippercast.fleet.adapters.teck_reports import parse_directory

DEPTH = 1200
DIRECTORY = "https://reports.example.org/charter_boats/index.php"
ASSOCIATION = "https://association.example.org/"
CORE = 'left<br>right<span class="target"> deep </span>'
CARD = ("<div class='boat-card'><div class='boat-card-top'>"
        "<a href='/charter_boats/synthetic.php'>Synthetic Example</a></div></div>")
GGFA = "<h3>Example Port</h3><b><i>Synthetic Example</i></b>"


def wrap(markup: str, depth: int = DEPTH) -> str:
    return "<div>" * depth + markup + "</div>" * depth


class DeepTraversalTests(unittest.TestCase):
    def test_explicit_deep_text_matches_shallow(self):
        deep = parse(wrap(CORE))
        self.assertEqual(parse(CORE).text(), "left right deep")
        self.assertEqual(deep.text(), "left right deep")
        inner = deep
        for _ in range(DEPTH):
            inner = inner.element_children()[0]
        self.assertEqual(inner.text(), "left right deep")

    def test_preorder_identity_and_receiver_exclusion(self):
        root = Node("#document")
        a, b, c, d = (Node(t, parent=root) for t in "abcd")
        a.children = ["x", c, "y"]
        c.parent = a
        root.children = ["lead", a, "mid", b, d, "tail"]
        self.assertEqual([id(n) for n in root.iter()], [id(a), id(c), id(b), id(d)])
        self.assertEqual([n.tag for n in a.iter()], ["c"])
        self.assertEqual(list(d.iter()), [])
        deep = parse(wrap(CORE + "<p id='after'>sibling</p>"))
        tags = [n.tag for n in deep.iter()]
        self.assertEqual(tags[:DEPTH], ["div"] * DEPTH)
        self.assertEqual(tags[DEPTH:], ["br", "span", "p"])
        self.assertEqual(deep.find(cls="target").text(), "deep")
        self.assertEqual([n.text() for n in deep.find_all("p")], ["sibling"])
        self.assertEqual(deep.find("p").attrs["id"], "after")

    def test_lazy_iterator_keeps_normal_yield_order(self):
        root = parse("<div><b>one</b><i>two</i></div><u>three</u>")
        iterator = root.iter()
        self.assertIs(next(iterator), root.children[0])
        # Mutation after the generator started is observed in normal child-iterator fashion.
        late = Node("late", parent=root.children[0])
        root.children[0].children.append(late)
        self.assertEqual([n.tag for n in iterator], ["b", "i", "late", "u"])
        # Creating (not advancing) a generator does not walk the tree.
        fresh = root.iter()
        root.children.append(Node("added", parent=root))
        self.assertEqual([n.tag for n in fresh][-1], "added")

    def test_br_and_whitespace_are_byte_compatible(self):
        self.assertEqual(parse("<b>a</b><i>b</i>").text(), "ab")
        self.assertEqual(parse("a<br>b").text(), "a b")
        self.assertEqual(parse("  a &amp;\n\t b &nbsp; c ").text(), "a & b c")
        self.assertEqual(parse("<div> <span> </span> </div>").text(), "")
        self.assertEqual(Node("x").text(), "")
        br = Node("br")
        br.children = ["hidden", Node("span")]
        br.children[1].children = ["also hidden"]
        holder = Node("p")
        holder.children = ["a", br, "b"]
        self.assertEqual(holder.text(), "a b")
        self.assertEqual([n.tag for n in holder.iter()], ["br", "span"])

    def test_real_directory_deep_wrapper_is_transparent(self):
        shallow = parse_directory(CARD, DIRECTORY)
        deep = parse_directory(wrap(CARD), DIRECTORY)
        self.assertEqual(deep, shallow)
        self.assertEqual([(e.name, e.url) for e in deep.entries],
                         [("Synthetic Example", "https://reports.example.org/charter_boats/synthetic.php")])
        self.assertEqual((deep.page, deep.pages, deep.next_url), (1, 1, None))

    def test_real_association_deep_wrapper_is_transparent(self):
        shallow = parse_ggfa(GGFA, ASSOCIATION)
        deep = parse_ggfa(wrap(GGFA), ASSOCIATION)
        self.assertEqual(deep, shallow)
        self.assertEqual([(s.name, s.port) for s in deep], [("Synthetic Example", "Example Port")])


if __name__ == "__main__":
    unittest.main()
