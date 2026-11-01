"""scripts/ops_report.py: client-error message/source text masks e-mails, separated phone numbers and URL queries."""
import unittest
from datetime import datetime, timezone

from scripts import ops_report

NOW = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)


def error_row(message, source='https://skippercast.example/assets/app.js', kind='error', build='b1'):
    return {'message': message, 'source': source, 'line': 3, 'kind': kind, 'build': build, 'reports': 2}


class MaskTests(unittest.TestCase):
    def test_url_query_and_fragment_dropped_and_email_masked(self):
        self.assertEqual(ops_report.mask('Failed https://a.test/x?token=1#f for bob@example.org'),
                         'Failed https://a.test/x for [email]')
        self.assertEqual(ops_report.mask('see http://a.test/p#frag'), 'see http://a.test/p')
        # Userinfo is not kept either, and is not mistaken for an e-mail address.
        self.assertEqual(ops_report.mask('https://amy:pw@a.test:8443/x?k=v'), 'https://a.test:8443/x')

    def test_unparsable_url_is_replaced(self):
        self.assertEqual(ops_report.mask('bad http://[::1/x?token=1 here'), 'bad [url] here')

    def test_separated_phone_numbers_masked_with_words_kept(self):
        cases = {
            'Call 805-555-0100.': 'Call [phone].',
            'office (805) 555-0100 today': 'office [phone] today',
            'ring +1 805.555.0100 now': 'ring [phone] now',
            'ring 1-805-555-0101 now': 'ring [phone] now',
            'or 805 555 0102, ok': 'or [phone], ok',
            '(805)555-0103': '[phone]',
        }
        for raw, masked in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(ops_report.mask(raw), masked)

    def test_other_numbers_unchanged(self):
        for raw in ('12:30', 'v1.2.3', '2026-10-31T12:30:00Z', 'line 42 col 7', '555-0100', '8055550100',
                    'id 9805-555-0100', 'id 805-555-01001', 'build 805.555.01', ''):
            with self.subTest(raw=raw):
                self.assertEqual(ops_report.mask(raw), raw)
        self.assertEqual(ops_report.mask(None), '')

    def test_email_shapes(self):
        self.assertEqual(ops_report.mask('from a.b+c@mail.example.org.'), 'from [email].')
        for raw in ('user@host', 'a @ b.org', '@example.org'):
            with self.subTest(raw=raw):
                self.assertEqual(ops_report.mask(raw), raw)

    def test_source_query_dropped_url_without_query_unchanged(self):
        self.assertEqual(ops_report.mask('https://skippercast.example/assets/app.js?v=abc'),
                         'https://skippercast.example/assets/app.js')
        self.assertEqual(ops_report.mask('https://skippercast.example/assets/app.js'),
                         'https://skippercast.example/assets/app.js')
        table = ops_report.table([error_row('m', 'https://skippercast.example/assets/app.js?v=abc')])
        self.assertIn('| `m` | `https://skippercast.example/assets/app.js` |', table)
        self.assertNotIn('v=abc', table)


class TableTests(unittest.TestCase):
    def test_backtick_and_pipe_still_one_safe_code_span(self):
        table = ops_report.table([error_row('a `b` | c bob@example.org ` https://a.test/x?q=`|`')])
        self.assertIn('| `a b \\| c [email]  https://a.test/x` |', table)
        row = table.splitlines()[2]
        self.assertEqual(row.count('`'), 4)
        self.assertNotIn('bob@', table)

    def test_non_browser_columns_untouched(self):
        row = error_row('m', kind='bob@example.org', build='805-555-0100')
        table = ops_report.table([row])
        self.assertIn('| `m` | `https://skippercast.example/assets/app.js` | 3 | bob@example.org | 805-555-0100 | 2 |', table)

    def test_rows_differing_only_after_masking_stay_separate(self):
        rows = [error_row('x amy@example.org'), error_row('x bob@example.org')]
        table = ops_report.table(rows)
        self.assertEqual(table.count('| `x [email]` |'), 2)

    def test_full_report_masks_and_leaks_nothing(self):
        rows = [error_row('Failed https://a.test/x?token=s3cr3t#f for bob@example.org, call (805) 555-0100',
                          'https://skippercast.example/assets/app.js?v=abc')]
        text = ops_report.report({'client_errors': rows}, now=NOW)
        self.assertIn('| `Failed https://a.test/x for [email], call [phone]` | '
                      '`https://skippercast.example/assets/app.js` | 3 | error | b1 | 2 |', text)
        for leak in ('bob@example.org', 'bob', 'token', 's3cr3t', '555-0100', 'v=abc', '#f'):
            with self.subTest(leak=leak):
                self.assertNotIn(leak, text)


if __name__ == '__main__':
    unittest.main()
