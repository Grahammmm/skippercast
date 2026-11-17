import unittest

from skippercast.pipeline.parsers import page_watch, watch_content, watch_content_v4


def page(attrs, label="Reviewed document"):
    return f"<html><body><main><h1>Fishing rules</h1><a {attrs}>{label}</a></main></body></html>"


def links(body):
    return watch_content_v4(body).split("DOCUMENT LINKS\n", 1)[1]


class WatchAnchorHrefTest(unittest.TestCase):
    def test_real_href_change_survives_earlier_data_href(self):
        one = page('data-href="/ui-placeholder" href="https://example.test/one.pdf"')
        two = page('data-href="/ui-placeholder" href="https://example.test/two.pdf"')
        self.assertEqual(links(one), "https://example.test/one.pdf")
        self.assertNotEqual(page_watch(one, ["rules"])["content_sha256"],
                            page_watch(two, ["rules"])["content_sha256"])

    def test_data_only_change_does_not_change_document_links(self):
        one = page('data-href="/a" href="https://example.test/same.pdf"')
        two = page('data-href="/b" href="https://example.test/same.pdf"')
        self.assertEqual(watch_content_v4(one), watch_content_v4(two))
        self.assertEqual(page_watch(one, ["rules"]), page_watch(two, ["rules"]))

    def test_href_text_inside_other_attribute_is_not_a_link(self):
        shadow = page("""data-note='see href="/fake.pdf"' href="https://example.test/real.pdf\"""")
        self.assertEqual(links(shadow), "https://example.test/real.pdf")
        self.assertEqual(links(page('data-href="/only.pdf"')), "")

    def test_ordinary_anchor_entities_scope_and_legacy_controls(self):
        body = ("<!-- <a href='/gone.pdf'>x</a> --><script>var a='<a href=\"/js.pdf\">';</script>"
                "<main><a HREF='https://example.test/a.pdf?x=1&amp;y=2'>A</a>"
                "<a href=\"https://example.test/b.pdf\">B</a>"
                "<a href=\"mailto:a@example.test\">m</a><a href=\"#top\">t</a>"
                "<a href=\"javascript:void(0)\">j</a></main><footer><a href=\"/foot\">f</a></footer>")
        self.assertEqual(links(body), "https://example.test/a.pdf?x=1&y=2\nhttps://example.test/b.pdf")
        v3 = watch_content('<a href="/x.pdf">X</a><a data-href="/y.pdf" href="/z.pdf">Z</a>')
        self.assertTrue(v3.endswith("DOCUMENT LINKS\n/x.pdf\n/y.pdf\n/z.pdf"))


if __name__ == "__main__":
    unittest.main()
