"""RF0450-7: the research page links only https://, relative and #fragment targets; heading ids are unique."""
import unittest

from research.lib.paths import ROOT
from research.scripts.build_research_page import render


def body(md):
    page = render(md)
    return page[page.index('<main id="content">') + len('<main id="content">'):page.index('</main>')]


class LinkSchemeTest(unittest.TestCase):
    def assert_text_only(self, md, text='x'):
        out = body(md)
        self.assertNotIn('<a', out, md)
        self.assertEqual(out, f'<p>{text}</p>', md)

    def test_script_and_data_schemes_render_text_only(self):
        # The unchanged link pattern ends a target at the first ')', so 'alert(1))' leaves one ')' as text.
        self.assert_text_only('[x](javascript:alert(1))', 'x)')
        self.assert_text_only('[x](JaVaScRiPt:alert(1))', 'x)')
        for md in ('[x](javascript:alert`1`)', '[x](data:text/html,hi)', '[x](vbscript:msgbox)',
                   '[x](DATA:image/svg+xml,hi)'):
            self.assert_text_only(md)

    def test_scheme_relative_and_plain_http_render_text_only(self):
        for md in ('[x](//evil.example/)', '[x](http://a.b)', '[x](HTTP://a.b)', '[x](ftp://a.b)',
                   '[x](\\\\evil.example/)', '[x](/\\evil.example/)'):
            self.assert_text_only(md)

    def test_whitespace_or_control_characters_render_text_only(self):
        for md in ('[x]( javascript:1)', '[x](javascript:1 )', '[x]( https://a.b)', '[x](https://a.b )',
                   '[x](java\tscript:1)', '[x](https://a.b/\x01)', '[x](a\x7fb.html)'):
            self.assert_text_only(md)

    def test_https_relative_and_fragment_targets_are_links(self):
        self.assertEqual(body('[x](https://a.b/c?d=1&e=2)'), '<p><a href="https://a.b/c?d=1&amp;e=2">x</a></p>')
        self.assertEqual(body('[x](HTTPS://a.b)'), '<p><a href="HTTPS://a.b">x</a></p>')
        self.assertEqual(body('[x](#top)'), '<p><a href="#top">x</a></p>')
        self.assertEqual(body('[x](sources.html)'), '<p><a href="sources.html">x</a></p>')
        self.assertEqual(body('[x](data-sources.md)'), '<p><a href="sources.html">x</a></p>')
        self.assertEqual(body('[x](/map)'), '<p><a href="/map">x</a></p>')

    def test_link_text_stays_escaped_when_target_refused(self):
        self.assertEqual(body('[<b>x</b>](javascript:1)'), '<p>&lt;b&gt;x&lt;/b&gt;</p>')
        self.assertEqual(body('[**x**](data:,1)'), '<p><strong>x</strong></p>')

    def test_refused_and_allowed_links_on_one_line(self):
        self.assertEqual(body('[a](javascript:1) and [b](https://a.b)'), '<p>a and <a href="https://a.b">b</a></p>')


class HeadingIdTest(unittest.TestCase):
    def test_repeated_headings_get_numbered_ids(self):
        out = body('## Notes\n\n## Notes\n\n### notes\n\n## Other')
        self.assertEqual(out.split('\n'), ['<h2 id="notes">Notes</h2>', '<h2 id="notes-2">Notes</h2>',
                                           '<h3 id="notes-3">notes</h3>', '<h2 id="other">Other</h2>'])

    def test_empty_slug_is_section_and_repeats_are_numbered(self):
        out = body('## ---\n\n## ***\n\n## Section')
        self.assertEqual(out.split('\n'), ['<h2 id="section">---</h2>', '<h2 id="section-2">***</h2>',
                                           '<h2 id="section-3">Section</h2>'])

    def test_numbered_id_never_collides_with_a_literal_heading_slug(self):
        out = body('## Notes 2\n\n## Notes\n\n## Notes')
        self.assertEqual(out.split('\n'), ['<h2 id="notes-2">Notes 2</h2>', '<h2 id="notes">Notes</h2>',
                                           '<h2 id="notes-3">Notes</h2>'])

    def test_counter_resets_between_renders(self):
        self.assertEqual(body('## Notes'), '<h2 id="notes">Notes</h2>')
        self.assertEqual(body('## Notes'), '<h2 id="notes">Notes</h2>')


class CommittedPageTest(unittest.TestCase):
    def test_render_of_the_real_document_is_the_committed_page(self):
        page = render((ROOT / 'docs/species-research.md').read_text()) + '\n'
        self.assertTrue(page == (ROOT / 'dist/species-research.html').read_text(), 'committed page changed')


if __name__ == '__main__':
    unittest.main()
