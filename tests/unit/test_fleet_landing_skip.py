"""Landing parser: excluded containers close only by their own tag (RF0010-6). Synthetic HTML, no server."""
import unittest

from skippercast.fleet.adapters.landing_pages import parse_html

VISIBLE = '<a href="/boats/visible">Visible Example</a>'
HIDDEN = '<a href="/boats/hidden">Hidden Example</a>'


def hrefs(markup):
    return [n.attrs["href"] for n in parse_html(markup).find_all("a")]


class SkipCloseTests(unittest.TestCase):
    def test_balanced_template_hides_link(self):
        self.assertEqual(hrefs(f"<template>{HIDDEN}</template>{VISIBLE}"), ["/boats/visible"])

    def test_unmatched_excluded_close_cannot_publish_hidden_boat(self):
        root = parse_html(f"<template></noscript>{HIDDEN}</template>{VISIBLE}")
        self.assertEqual([n.attrs["href"] for n in root.find_all("a")], ["/boats/visible"])
        self.assertEqual(root.text(), "Visible Example")

    def test_ancestor_close_unwinds_unclosed_descendants(self):
        root = parse_html(f"<template><noscript>{HIDDEN}</template>{VISIBLE}")
        self.assertEqual(root.text(), "Visible Example")
        self.assertEqual(hrefs(f"<template><noscript></template>{VISIBLE}"), ["/boats/visible"])

    def test_nested_same_name_closes_nearest(self):
        self.assertEqual(hrefs(f"<template><template></template>{HIDDEN}</template>{VISIBLE}"), ["/boats/visible"])

    def test_ordinary_and_repeated_closers_do_not_release_scope(self):
        markup = f"<div><template></div></span></noscript></noscript>{HIDDEN}</template>{VISIBLE}</div>"
        root = parse_html(markup)
        self.assertEqual(hrefs(markup), ["/boats/visible"])
        link = root.find("a")
        self.assertIsNotNone(link)
        self.assertEqual(link.parent.tag, "div")  # type: ignore[union-attr]

    def test_selfclosing_excluded_tags_are_scope_neutral(self):
        self.assertEqual(hrefs(f"<template><template/>{HIDDEN}</template>{VISIBLE}"), ["/boats/visible"])
        self.assertEqual(hrefs(f"<script/>{VISIBLE}"), ["/boats/visible"])
        self.assertEqual(parse_html("<p>a<br/>b</p>").text(), "a b")

    def test_unclosed_excluded_hides_remainder(self):
        self.assertEqual(hrefs(f"{VISIBLE}<template>{HIDDEN}"), ["/boats/visible"])

    def test_raw_text_markup_stays_text_and_suppressed(self):
        self.assertEqual(hrefs(f"<script>'</template>'{HIDDEN}</script>{VISIBLE}"), ["/boats/visible"])
        self.assertEqual(parse_html("<style>a{}</style>ok").text(), "ok")


if __name__ == "__main__":
    unittest.main()
