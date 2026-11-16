"""A present but blank local catch cell is refused, never read as an empty catch."""
import datetime as dt
import unittest

from skippercast.pipeline import collect, parsers

URL = 'https://example.invalid/dock_totals/boats.php?date=2026-09-20'
PORTS = {'Town, CA': 'Town'}
DAY = '2026-09-20'


def row(boat, catch, landing='Town, CA'):
    return (f'<tr><td><b>{boat}</b> {landing}<a href="/boat/{boat}">x</a></td>'
            f'<td>12 Anglers Half Day <i>Reef</i></td><td>{catch}</td></tr>')


def page(*rows):
    return f'<html><h1>Fish Counts</h1><p>September 20, 2026</p><table>{"".join(rows)}</table></html>'


class InertClient:
    def __init__(self, now):
        self.requests = []


class BlankCatchTests(unittest.TestCase):
    def parse(self, body):
        return parsers.charter_reports(body, DAY, URL, ports=PORTS)

    def test_blank_cells_are_refused(self):
        for cell in ('', '  \t\n ', '<br>', '&nbsp;', '<b> </b>', '<span><i></i></span>'):
            with self.subTest(cell=cell), self.assertRaisesRegex(ValueError, 'Unrecognized local catch cell'):
                self.parse(page(row('Alpha', cell)))

    def test_explicit_zero_and_counts_are_preserved(self):
        for cell, catches in (('No fish', []), ('No catch', []),
                              ('0 Rockfish', [{'species': 'rockfish', 'label': 'Rockfish', 'count': 0,
                                               'disposition': 'reported'}]),
                              ('2 Lingcod', [{'species': 'lingcod', 'label': 'Lingcod', 'count': 2,
                                              'disposition': 'reported'}])):
            with self.subTest(cell=cell):
                reports = self.parse(page(row('Alpha', cell)))['reports']
                self.assertEqual([r['catches'] for r in reports], [catches])

    def test_valid_then_blank_trip_fails_whole_page(self):
        with self.assertRaisesRegex(ValueError, 'Unrecognized local catch cell'):
            self.parse(page(row('Alpha', '2 Lingcod'), row('Beta', '&nbsp;')))

    def test_blank_row_at_other_port_is_skipped(self):
        reports = self.parse(page(row('Gamma', '', landing='Elsewhere, CA'), row('Alpha', '2 Lingcod')))['reports']
        self.assertEqual([r['boat'] for r in reports], ['Alpha'])

    def test_source_fails_without_previous_data(self):
        body = page(row('Alpha', '<br>'))
        result = collect.source('s', 'S', 'landing-reports', URL, 48,
                                lambda c: self.parse(body), dt.datetime(2026, 9, 21, tzinfo=dt.timezone.utc),
                                client_factory=InertClient)
        self.assertEqual(result['status'], 'failed')
        self.assertIsNone(result['data'])
        self.assertIn('Unrecognized local catch cell', result['issue'])

    def test_source_retains_previous_data(self):
        previous = {'data': {'reports': ['old']}, 'last_success_at': '2026-09-20T00:00:00Z',
                    'data_retrieved_at': '2026-09-20T00:00:01Z'}
        body = page(row('Alpha', ''))
        result = collect.source('s', 'S', 'landing-reports', URL, 48,
                                lambda c: self.parse(body), dt.datetime(2026, 9, 21, tzinfo=dt.timezone.utc),
                                previous=previous, client_factory=InertClient)
        self.assertEqual(result['status'], 'retained')
        self.assertEqual(result['data'], previous['data'])
        self.assertEqual(result['last_success_at'], previous['last_success_at'])
        self.assertEqual(result['data_retrieved_at'], previous['data_retrieved_at'])


if __name__ == '__main__':
    unittest.main()
