"""RF0620-8: compile_coasts checks each local target advisory field by field and names coast, index and field."""
import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from skippercast.platform.coasts import _check_advisories, compile_coasts
from skippercast.platform.contracts import REPO

CATALOG = ('coasts.json', 'targets.json', 'species.json', 'data-needs.json', 'sources.json')
PREFIX = 'Invalid local coastal target advisory: san-francisco '
KEEP = object()  # compile_copy: leave the catalog's advisories as they are


class LocalTargetAdvisoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = json.loads((REPO / 'catalog/coasts.json').read_text())
        cls.sf = next(r for r in cls.directory['regions'] if r['id'] == 'san-francisco')
        cls.advisory = cls.sf['local_target_advisories'][0]

    def compile_copy(self, advisories=KEEP, drop=False):
        """Compile a temp-root copy whose san-francisco advisories are replaced (or the key dropped)."""
        directory = copy.deepcopy(self.directory)
        region = next(r for r in directory['regions'] if r['id'] == 'san-francisco')
        if drop:
            region.pop('local_target_advisories')
        elif advisories is not KEEP:
            region['local_target_advisories'] = advisories
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / 'catalog').mkdir()
        for name in CATALOG:
            shutil.copy(REPO / 'catalog' / name, root / 'catalog' / name)
        (root / 'catalog/coasts.json').write_text(json.dumps(directory))
        for ident in {p for r in directory['regions'] for p in r['packages']}:
            (root / 'regions' / ident).mkdir(parents=True)
            shutil.copy(REPO / 'regions' / ident / 'region.json', root / 'regions' / ident / 'region.json')
        self.out = root / 'dist/data/coasts.json'
        return compile_coasts(root)

    def edited(self, **fields):
        advisory = {**self.advisory, **fields}
        return {k: v for k, v in advisory.items() if v is not ...}

    def refused(self, advisories, message):
        with self.assertRaises(ValueError) as caught:
            self.compile_copy(advisories)
        self.assertEqual(str(caught.exception), message)
        self.assertFalse(self.out.exists(), 'nothing is written on a refusal')
        self.assertFalse(self.out.parent.exists(), 'nothing is written on a refusal')

    def test_latitude_must_be_a_number_strictly_inside_the_band(self):
        lo, hi = self.sf['latitude']
        for bad in ('38.03', True, False, None, lo, hi, hi + 1, lo - 1, 10 ** 400, [38.1], ...):
            with self.subTest(bad=bad):
                self.refused([self.edited(north_of_latitude=bad)], PREFIX + '#0 north_of_latitude')
        for bad in (float('nan'), float('inf'), float('-inf')):  # read_json refuses these, so the check is called directly
            with self.subTest(bad=bad), self.assertRaises(ValueError) as caught:
                _check_advisories({**self.sf, 'local_target_advisories': [self.edited(north_of_latitude=bad)]})
            self.assertEqual(str(caught.exception), PREFIX + '#0 north_of_latitude')
        self.assertEqual(self.compile_copy([self.edited(north_of_latitude=38)])['regions'][2]['local_target_advisories'][0]['north_of_latitude'], 38)

    def test_through_must_be_a_real_calendar_date(self):
        for bad in ('end of season', '2026-02-30', '2026-13-01', '2026-1-31', '20261031', '2026-10-31T00:00',
                    ' 2026-10-31', '2026-10-31\n', '٢٠٢٦-١٠-٣١', '0000-01-01', '', 20261031, None, ...):
            with self.subTest(bad=bad):
                self.refused([self.edited(through=bad)], PREFIX + '#0 through')
        for good in ('2026-10-31', '2024-02-29'):
            with self.subTest(good=good):
                self.assertEqual(self.compile_copy([self.edited(through=good)])['regions'][2]['local_target_advisories'][0]['through'], good)

    def test_each_note_must_be_non_empty_text(self):
        for field in ('north_note', 'south_note', 'expired_note'):
            for bad in (5, '  ', '', None, ['note'], {'text': 'x'}, True, ...):
                with self.subTest(field=field, bad=bad):
                    self.refused([self.edited(**{field: bad})], PREFIX + '#0 ' + field)

    def test_source_url_present_text_and_public_https(self):
        for bad in (..., None, 5, ['https://wildlife.ca.gov/']):
            with self.subTest(bad=bad):
                self.refused([self.edited(source_url=bad)], PREFIX + '#0 source_url')
        for url in ('http://wildlife.ca.gov/Fishing', ''):
            with self.subTest(url=url):
                self.refused([self.edited(source_url=url)], f'Expected a public HTTPS URL: {url}')

    def test_target_must_be_a_coast_target_and_appear_once(self):
        for bad in ('lingcod-nowhere', None, ['salmon'], ...):
            with self.subTest(bad=bad):
                self.refused([self.edited(target=bad)], PREFIX + '#0 target')
        self.refused([self.advisory, self.edited(north_of_latitude=37.5)], PREFIX + '#1 target (repeated)')
        self.refused([self.advisory, self.edited(through='2027-01-01'), self.advisory], PREFIX + '#1 target (repeated)')

    def test_advisories_must_be_a_list_of_objects(self):
        for bad in ({}, {'salmon': self.advisory}, None, 'salmon', 5):
            with self.subTest(bad=bad):
                self.refused(bad, PREFIX + 'local_target_advisories')
        for bad in ('salmon', None, 5, [self.advisory]):
            with self.subTest(item=bad):
                self.refused([self.advisory, bad], PREFIX + '#1 advisory')

    def test_first_bad_field_is_named_in_the_listed_order(self):
        worst = self.edited(target='nope', north_of_latitude='x', through='soon', north_note=5, source_url='http://x.example')
        self.refused([worst], PREFIX + '#0 target')
        self.refused([self.edited(north_of_latitude='x', through='soon', source_url='http://x.example')], PREFIX + '#0 north_of_latitude')
        self.refused([self.edited(through='soon', south_note='', source_url='http://x.example')], PREFIX + '#0 through')
        self.refused([self.edited(expired_note=' ', source_url='http://x.example')], PREFIX + '#0 expired_note')
        self.refused([self.advisory, self.edited(source_url='http://x.example')], 'Expected a public HTTPS URL: http://x.example')

    def test_valid_copy_compiles_like_the_repo_catalog(self):
        self.assertEqual(self.compile_copy(), compile_coasts())
        self.assertTrue(self.out.is_file())
        self.assertEqual(self.compile_copy([]), {**compile_coasts(), 'regions': [
            {**r, 'local_target_advisories': []} if r['id'] == 'san-francisco' else r for r in compile_coasts()['regions']]})
        dropped = self.compile_copy(drop=True)
        self.assertNotIn('local_target_advisories', dropped['regions'][2])


if __name__ == '__main__':
    unittest.main()
