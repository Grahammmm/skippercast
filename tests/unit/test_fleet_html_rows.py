"""Omitted cell/row end tags: a new <tr> closes the whole prior row (offline, synthetic)."""
from __future__ import annotations

import unittest

from skippercast.fleet.adapters._html import parse
from skippercast.fleet.adapters.teck_reports import parse_boat_page


def _rows(markup: str):
    root = parse(markup)
    return root, root.find_all("tr")


class RowSiblingTests(unittest.TestCase):
    def test_omitted_cell_and_row_ends_are_siblings(self):
        root, rows = _rows("<table><tr><td>Boat<td>Example<tr><td>Max Load<td>24</table>")
        table = root.find("table")
        self.assertEqual([r.text() for r in rows], ["BoatExample", "Max Load24"])
        self.assertTrue(all(r.parent is table for r in rows))
        self.assertEqual(len(table.element_children()), 2)

    def test_header_data_mix_matches_explicit_tree(self):
        root, rows = _rows("<table><tr><th>head<td>one<td>two<tr><th>next<th>end</table>")
        self.assertEqual([r.text() for r in rows], ["headonetwo", "nextend"])
        self.assertEqual([[c.tag for c in r.element_children()] for r in rows], [["th", "td", "td"], ["th", "th"]])
        self.assertTrue(all(c.parent is r for r in rows for c in r.element_children()))

    def test_inline_descendants_unwind_with_the_row(self):
        root, rows = _rows("<table><tr><td><b>Boat<span>x<td>Example<tr><td>Next</table>")
        self.assertEqual(rows[1].text(), "Next")
        self.assertIs(rows[1].parent, root.find("table"))

    def test_closed_cells_omitted_rows_control(self):
        _, rows = _rows("<table><tr><td>a</td><td>b</td><tr><td>c</td><td>d</td></table>")
        self.assertEqual([r.text() for r in rows], ["ab", "cd"])
        _, explicit = _rows("<table><tr><td>a</td></tr><tr><td>c</td></tr></table>")
        self.assertEqual([r.text() for r in explicit], ["a", "c"])

    def test_nested_table_scope_is_not_outer_row(self):
        root, rows = _rows("<table><tr><td>out<table><tr><td>i1<tr><td>i2</table><td>after<tr><td>next</table>")
        outer = root.find("table")
        inner = outer.find("table")
        inner_rows = [r for r in rows if r.parent is inner]
        self.assertEqual([r.text() for r in inner_rows], ["i1", "i2"])
        outer_rows = [r for r in rows if r.parent is outer]
        self.assertEqual([r.text() for r in outer_rows], ["outi1i2after", "next"])

    def test_table_section_scope_and_malformed_fallback(self):
        root, rows = _rows("<table><tbody><tr><td>a<td>b<tr><td>c</tbody></table>")
        self.assertEqual([r.text() for r in rows], ["ab", "c"])
        self.assertTrue(all(r.parent is root.find("tbody") for r in rows))
        _, rows = _rows("<td>a<tr>b")  # no open row: nearest cell closes as before
        self.assertEqual(rows[0].parent.tag, "#document")

    def test_many_rows_do_not_create_artificial_recursion(self):
        head = "<h2>Boat Information</h2><table>"
        other = "".join(f"<tr><td>Other{i}<td>v{i}" for i in range(1100))
        omitted = head + "<tr><td>Boat<td>Example" + other + "</table>"
        explicit = head + "<tr><td>Boat</td><td>Example</td></tr>" + "".join(
            f"<tr><td>Other{i}</td><td>v{i}</td></tr>" for i in range(1100)) + "</table>"
        self.assertEqual(parse_boat_page(omitted, "https://example.invalid/b.php"),
                         parse_boat_page(explicit, "https://example.invalid/b.php"))
        root, rows = _rows(omitted)
        self.assertEqual(len(rows), 1101)
        table = root.find("table")
        self.assertTrue(all(r.parent is table for r in rows))
        self.assertFalse(any(c.tag == "tr" for r in rows for c in r.element_children()))


if __name__ == "__main__":
    unittest.main()
