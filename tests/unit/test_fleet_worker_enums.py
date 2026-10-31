"""Fleet activity kinds: the Python pipeline and the Worker agree (#608, RF0805-2).

A rename on one side failed every scheduled fleet-ais upload in production (#607). This test reads the
Worker's TypeScript as text (no node) and fails offline, naming both sides, when kinds, labels or basis differ.
"""
from pathlib import Path
import re
import tempfile
import unittest

from skippercast.fleet.ais.classify import FISHING_KINDS, KINDS
from skippercast.fleet.ais.events import EVENT_KINDS
from skippercast.fleet.ais.segment import BASIS
from tests._support import ROOT

FLEET = ROOT / 'server' / 'fleet'
_LITERAL = re.compile(r"\s*(?:'[^'\\]*'\s*,\s*)*(?:'[^'\\]*'\s*,?\s*)?")


def _source(path):
    """The file text with `//` line comments removed (a URL's `://` is kept)."""
    return re.sub(r"(^|[\s,\[])//[^\n]*", r"\1", Path(path).read_text(encoding='utf-8'), flags=re.M)


def ts_array(path, name):
    """The single-quoted strings of `name: [...]` or `name = [...]`, in order; anything else is refused."""
    text = _source(path)
    found = re.search(rf"(?<![\w.$]){re.escape(name)}\s*[:=](?![=>])\s*", text)
    if not found:
        raise AssertionError(f"{Path(path).name}: {name} not found")
    if not text.startswith('[', found.end()) or ']' not in text[found.end():]:
        raise AssertionError(f"{Path(path).name}: {name} is not a literal string array")
    body = text[found.end() + 1:text.index(']', found.end())]
    if not _LITERAL.fullmatch(body):
        raise AssertionError(f"{Path(path).name}: {name} is not a literal string array: [{body}]")
    return tuple(re.findall(r"'([^'\\]*)'", body))


def ts_string(path, name):
    found = re.search(rf"export const {re.escape(name)}\s*=\s*'([^'\\]*)'\s*;", _source(path))
    if not found:
        raise AssertionError(f"{Path(path).name}: {name} not found")
    return found.group(1)


def same(ts_name, ts, py_name, py):
    if tuple(ts) != tuple(py):
        raise AssertionError(f"Worker {ts_name} {tuple(ts)!r} != Python {py_name} {tuple(py)!r}")


class WorkerEnumParityTest(unittest.TestCase):
    def test_python_kinds_match_the_worker(self):
        same('activity.ts ENUMS.segment', ts_array(FLEET / 'activity.ts', 'segment'), 'KINDS', KINDS)
        same('activity.ts ENUMS.event', ts_array(FLEET / 'activity.ts', 'event'), 'EVENT_KINDS', EVENT_KINDS)
        same('Python EVENT_KINDS', EVENT_KINDS, 'FISHING_KINDS', FISHING_KINDS)
        same('map.ts FISHING_KINDS', ts_array(FLEET / 'map.ts', 'FISHING_KINDS'), 'FISHING_KINDS', FISHING_KINDS)
        same('admin/labels.ts LABELS', ts_array(FLEET / 'admin' / 'labels.ts', 'LABELS'), 'KINDS less uncertain/gap',
             tuple(k for k in KINDS if k not in ('uncertain', 'gap')))
        for path in (FLEET / 'activity.ts', FLEET / 'map.ts', FLEET / 'admin' / 'labels.ts'):
            self.assertEqual(ts_string(path, 'BASIS'), BASIS, path.name)


class HelperEdgeTest(unittest.TestCase):
    def ts(self, text):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        path = Path(self.tmp.name) / 'activity.ts'
        path.write_text(text, encoding='utf-8')
        return path

    def test_a_rename_on_the_worker_side_fails_naming_both_sides(self):
        text = (FLEET / 'activity.ts').read_text(encoding='utf-8')
        start = text.index('  event: [')
        line = text[start:text.index('\n', start)]
        path = self.ts(text.replace(line, line.replace("'troll-slow'", "'troll-slow-2'")))
        with self.assertRaises(AssertionError) as caught:
            same('ENUMS.event', ts_array(path, 'event'), 'EVENT_KINDS', EVENT_KINDS)
        for side in (EVENT_KINDS, ('drift-anchor', 'troll-slow-2', 'troll-pelagic')):
            self.assertIn(repr(side), str(caught.exception))

    def test_missing_key_and_non_literal_arrays_are_refused(self):
        self.assertRaisesRegex(AssertionError, 'event not found', ts_array, self.ts("const E = {segment: ['a']};"), 'event')
        self.assertRaisesRegex(AssertionError, 'not a literal', ts_array, self.ts("const E = {event: KINDS};"), 'event')
        self.assertRaisesRegex(AssertionError, 'not a literal', ts_array, self.ts("const E = {event: [...BASE, 'x']};"), 'event')
        self.assertRaisesRegex(AssertionError, 'BASIS not found', ts_string, self.ts("export const BASIS = X;"), 'BASIS')

    def test_comments_line_breaks_and_as_const_parse_in_order(self):
        path = self.ts("const E = {\n  event: ['a', // note 'q', see https://x.test\n    'b',\n  ],\n};\nexport const K = ['c', 'd'] as const;\n")
        self.assertEqual(ts_array(path, 'event'), ('a', 'b'))
        self.assertEqual(ts_array(path, 'K'), ('c', 'd'))
