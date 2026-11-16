"""Shore re-read dossier checker: SHA256 and commit tokens must match whole (no trailing LF). Offline, synthetic."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from tests.contract.test_shore_reread_dossier import checker, dossier

GOOD64 = 'a' * 64
GOOD40 = 'a' * 40
SUFFIXES = ['\n', '\r\n', '\r', ' ', '\t', 'a', 'g']
COMMIT_MSG = 'inspectedGitSha must be a 40-hex commit'


def run_main(text):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / 'r.json'
        path.write_text(text, encoding='utf-8')
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = checker.main([str(path)])
        after = path.read_text(encoding='utf-8')
        return code, out.getvalue(), err.getvalue(), after == text


class Sha256Token(unittest.TestCase):
    def test_exact_token_accepted(self):
        self.assertTrue(checker._ok_hash(GOOD64))

    def test_malformed_tokens_refused(self):
        bad = [GOOD64 + s for s in SUFFIXES] + [' ' + GOOD64, '\n' + GOOD64, 'a' * 63, 'a' * 65, 'A' * 64, 'g' * 64, '', None, 5]
        for v in bad:
            with self.subTest(v=v):
                self.assertFalse(checker._ok_hash(v))


class CommitToken(unittest.TestCase):
    def test_exact_commit_accepted(self):
        self.assertEqual(checker.check(dossier()), [])

    def test_malformed_commits_refused(self):
        bad = [GOOD40 + s for s in SUFFIXES] + [' ' + GOOD40, '\n' + GOOD40, 'a' * 39, 'a' * 41, 'A' * 40, 'g' * 40, '', None]
        for v in bad:
            with self.subTest(v=v):
                doc = dossier()
                doc['inspectedGitSha'] = v
                self.assertIn(COMMIT_MSG, checker.check(doc))


class Sha256Consumers(unittest.TestCase):
    def assert_refused(self, mutate, needle):
        doc = dossier()
        mutate(doc)
        self.assertTrue(any(needle in f for f in checker.check(doc)), needle)

    def test_each_consumer_refuses_trailing_lf(self):
        lf = GOOD64 + '\n'

        def baseline(d):
            d['baselines'][0]['sha256'] = lf

        def private(d):
            d['privateFiles'][0]['sha256'] = lf

        def acquired(d):
            d['sources'][0]['sha256'] = lf

        def ref(d):
            d['sources'][0]['baselineRefs'][0]['sha256'] = lf

        def selected(d):
            for r in d['runs']:
                r['source']['selectedGeometry']['old']['sha256'] = lf
                r['source']['selectedGeometry']['new']['sha256'] = lf

        def m2(d):
            d['m2EsteroBluffs']['selectionState'] = 'proposed'
            d['m2EsteroBluffs']['candidates'] = [{'objectId': 2255, 'esi': '1A', 'esiLegend': [{'code': '1A', 'legend': 'x'}],
                                                  'coordinatesSha256': lf, 'vertices': 20}]

        for fn, needle in [(baseline, 'baselines: each needs'), (private, 'privateFiles: relative'),
                           (acquired, 'acquired needs sha256'), (ref, 'baseline reference needs'),
                           (selected, 'needs old and new vertex sha256'), (m2, 'needs object id, ESI code')]:
            with self.subTest(fn=fn.__name__):
                self.assert_refused(fn, needle)


class CommandLine(unittest.TestCase):
    def test_valid_control(self):
        code, out, _, _ = run_main(json.dumps(dossier()))
        self.assertEqual((code, out.startswith('OK')), (0, True))

    def test_trailing_lf_commit_fails_cli(self):
        doc = dossier()
        doc['inspectedGitSha'] = GOOD40 + '\n'
        code, out, err, unchanged = run_main(json.dumps(doc))
        self.assertEqual(code, 1)
        self.assertIn('FAIL ' + COMMIT_MSG, out)
        self.assertFalse(out.startswith('OK'))
        self.assertNotIn('Traceback', err)
        self.assertTrue(unchanged)

    def test_trailing_lf_sha256_fails_cli(self):
        doc = dossier()
        doc['baselines'][0]['sha256'] = GOOD64 + '\n'
        code, out, err, unchanged = run_main(json.dumps(doc))
        self.assertEqual(code, 1)
        self.assertIn('FAIL baselines: each needs', out)
        self.assertNotIn('Traceback', err)
        self.assertTrue(unchanged)


if __name__ == '__main__':
    unittest.main()
