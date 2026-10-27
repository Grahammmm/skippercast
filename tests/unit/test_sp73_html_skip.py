"""Synthetic complete-module HTML skip-state contracts (SP73 A1-A4).

No import-time guards or global patches: ordinary repository discovery is inert.
The acceptance launcher installs its process-local offline guards before import.
"""
import json
import unittest

from skippercast.fleet.adapters._html import SKIP, parse
from tests._support import FIXTURES

CASES = json.loads((FIXTURES / 'sp73_html_skip' / 'cases.json').read_text(encoding='utf-8'))


class SkipTests(unittest.TestCase):
    def check_case(self, case):
        # Capture the actual result/exception before checking the semantic contract.
        # Only the named text leak (not any exception) qualifies as baseline evidence.
        try:
            tree = parse(case['html'])
            observed = {'text': tree.text(), 'exception': None}
        except Exception as error:
            tree = None
            observed = {'text': None, 'exception': type(error).__name__}
        print('OBSERVATION ' + json.dumps({'case': case['id'], **observed}, sort_keys=True))
        self.assertIsNone(observed['exception'], 'parser exception is not the declared text leak')
        self.assertEqual(observed['text'], case['text'], 'SKIP_TEXT_CONTRACT:' + case['id'])
        self.assertNotIn('hidden', tree.text())
        self.assertIsNone(tree.find(cls='hidden'))
        self.assertEqual(tree.find_all(cls='hidden'), [])
        self.assertIsNone(tree.find(where=lambda node: 'hidden' in node.text()))
        self.assertEqual(tree.find_all(where=lambda node: 'hidden' in node.text()), [])
        for tag in SKIP:
            self.assertIsNone(tree.find(tag))
            self.assertEqual(tree.find_all(tag), [])
        for selection in case.get('selections', []):
            nodes = tree.find_all(selection['tag'])
            self.assertEqual([node.text() for node in nodes], selection['texts'])
            self.assertEqual([node.parent.tag for node in nodes], selection['parents'])
            if 'classes' in selection:
                self.assertEqual([node.classes for node in nodes], [set(x) for x in selection['classes']])
        if case['id'] in {'primary_unmatched_svg', 'healthy_balanced_template', 'unmatched_noscript'}:
            self.assertEqual([node.text() for node in tree.find_all('p', cls='visible')], ['before', 'after'])
            self.assertEqual(tree.find('p', cls='visible').text(), 'before')


def _case_method(case):
    def test(self):
        self.check_case(case)
    test.__name__ = 'test_' + case['id']
    return test


# One separately named assertion case per fixture, including the exact baseline pair.
for _case in CASES:
    _name = 'test_' + _case['id']
    if hasattr(SkipTests, _name):
        raise ValueError('duplicate synthetic case: ' + _name)
    setattr(SkipTests, _name, _case_method(_case))


if __name__ == '__main__':
    unittest.main()
