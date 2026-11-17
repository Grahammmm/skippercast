"""GEFS ISO stamps describe the same instants as the manifest epochs (offline, synthetic)."""
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import patch

from skippercast.forecast import ensemble


def at(offset_minutes, *fields, micro=0):
    return datetime(*fields, microsecond=micro, tzinfo=timezone(timedelta(minutes=offset_minutes)))


class StampZoneTests(unittest.TestCase):
    def test_equivalent_aware_stamps_are_identical_utc_text(self):
        for moment in (at(0, 2026, 9, 27, 6), at(330, 2026, 9, 27, 11, 30), at(-420, 2026, 9, 26, 23)):
            self.assertEqual(ensemble.stamp(moment), '2026-09-27T06:00:00Z')

    def test_manifest_iso_fields_match_numeric_instants(self):
        cycle, built = at(330, 2026, 9, 27, 11, 30), at(-420, 2026, 9, 27, 3, 15)
        manifest = ensemble.manifest_for(cycle, [1], {}, {'a': []}, built, 5)
        self.assertEqual(manifest['cycle_iso'], '2026-09-27T06:00:00Z')
        self.assertEqual(manifest['built_at'], '2026-09-27T10:15:00Z')
        parse = lambda text: datetime.strptime(text, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc).timestamp()
        self.assertEqual(parse(manifest['cycle_iso']), manifest['cycle'])
        self.assertEqual(manifest['cycle'], manifest['meta']['last_run_initialisation_time'])
        for key in ('last_run_modification_time', 'last_run_availability_time'):
            self.assertEqual(parse(manifest['built_at']), manifest['meta'][key])

    def test_date_and_year_rollovers_are_normalized(self):
        self.assertEqual(ensemble.stamp(at(-570, 2026, 12, 31, 20, 45)), '2027-01-01T06:15:00Z')
        self.assertEqual(ensemble.stamp(at(840, 2027, 1, 1, 5)), '2026-12-31T15:00:00Z')

    def test_utc_naive_and_precision_controls(self):
        self.assertEqual(ensemble.stamp(at(0, 2026, 9, 27, 6, 0, 1, micro=999999)), '2026-09-27T06:00:01Z')
        self.assertEqual(ensemble.stamp(datetime(2026, 9, 27, 6, 30, 5)), '2026-09-27T06:30:05Z')
        fixed = datetime(2026, 9, 27, 7, 8, 9, tzinfo=timezone.utc)
        with patch.object(ensemble, 'datetime') as clock:
            clock.now.return_value = fixed
            self.assertEqual(ensemble.stamp(), '2026-09-27T07:08:09Z')


if __name__ == '__main__':
    unittest.main()
