"""GEFS member fields must sit on the land mask's cells, not merely have its dimensions (offline, synthetic GRIB)."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from skippercast.forecast import ensemble
from tests.unit.test_forecast_ensemble import CYCLE, HAS_ECCODES, FakeBucket, grib

STEPS = (0, 3, 6, 9)
NOW = datetime(2026, 9, 27, 5, tzinfo=timezone.utc)
SHIFT = {'longitude': {'lon1': 243.0, 'lon2': 245.0}, 'latitude': {'lat1': 41.0, 'lat2': 40.0}}
REGIONS = {'test-region': [(35.5, -121.5), (35.5, -120.0), (35.5, -118.0)]}


def displace(bucket, member, step, fields, axis):
    """Re-serve one member-step with the named fields' decoded axes moved; dimensions stay 5 x 9."""
    import numpy as np
    values = {'gust': np.full((5, 9), 10.0 + step), 'u10': np.full((5, 9), 3.0 + member), 'v10': np.full((5, 9), 4.0)}
    layout = (('gust', 'GUST', 'surface'), ('u10', 'UGRD', '10 m above ground'), ('v10', 'VGRD', '10 m above ground'))
    bucket.add(ensemble.gefs_url(CYCLE, member, step),
               [(var, level, f'{step} hour fcst', grib(values[name], **(SHIFT[axis] if name in fields else {})))
                for name, var, level in layout])


class BuilderCase(unittest.TestCase):
    def setUp(self):
        patcher = patch.multiple(ensemble, MEMBERS=3, STEPS=STEPS)
        patcher.start()
        self.addCleanup(patcher.stop)

    def build(self, output, bucket, previous=None, force=False):
        return ensemble.build(output, previous, force, now=NOW, regions=REGIONS, http=bucket,
                              exists=lambda url: True, log=lambda *_: None)


@unittest.skipUnless(HAS_ECCODES, 'Optional GRIB decoder not installed')
class AxisTests(BuilderCase):
    def test_same_shape_longitude_displacement_fails_before_publish(self):
        bucket = FakeBucket(3, STEPS)
        for member in range(3):
            for step in STEPS:
                displace(bucket, member, step, ('gust', 'u10', 'v10'), 'longitude')
        with tempfile.TemporaryDirectory() as tmp:
            control = self.build(Path(tmp, 'control'), FakeBucket(3, STEPS))
            failed = self.build(Path(tmp, 'out'), bucket)
            self.assertEqual((control['status'], control['state']), ('ok', 'built'))
            self.assertEqual((failed['status'], failed['kept_previous']), ('failed', False))
            self.assertIn('GEFS', failed['issue'])
            self.assertIn('longitude axis differs from the land mask', failed['issue'])
            self.assertFalse(Path(tmp, 'out/ncep_gefs025').exists())

    def test_latitude_and_each_field_are_checked(self):
        for axis in ('latitude', 'longitude'):
            for field in ('u10', 'v10', 'gust'):
                for member, step in ((0, 0), (1, 3), (2, 9)):  # first, middle and last jobs
                    with self.subTest(axis=axis, field=field, member=member, step=step):
                        bucket = FakeBucket(3, STEPS)
                        displace(bucket, member, step, (field,), axis)
                        with tempfile.TemporaryDirectory() as tmp:
                            failed = self.build(Path(tmp), bucket)
                            self.assertFalse(Path(tmp, 'ncep_gefs025').exists())
                        self.assertEqual((failed['status'], failed['kept_previous']), ('failed', False))
                        self.assertIn(f'GEFS {field} {axis} axis differs from the land mask', failed['issue'])


@unittest.skipUnless(HAS_ECCODES, 'Optional GRIB decoder not installed')
class DecodedSeamTests(unittest.TestCase):
    """Controlled decoded arrays through fetch_member_step: refusal comes before any value is returned."""

    def setUp(self):
        import numpy as np
        self.np = np
        self.bucket = FakeBucket(1, (0,))
        self.lats = np.linspace(35.0, 36.0, 5)
        self.lons = -122.0 + 0.25 * np.arange(9)

    def fetch(self, lats=None, lons=None, ref_lons=None):
        decoded = (self.np.full((5, 9), 7.0), self.lats if lats is None else lats, self.lons if lons is None else lons)
        with patch.object(ensemble, 'decode_one', return_value=decoded):
            return ensemble.fetch_member_step(CYCLE, 0, 0, [(2, 1)], (5, 9), reference_lats=self.lats,
                                              reference_lons=self.lons if ref_lons is None else ref_lons,
                                              http=self.bucket)

    def test_axes_require_index_alignment_and_finite_values(self):
        np = self.np
        nan_lons = self.lons.copy()
        nan_lons[3] = np.nan
        inf_lats = self.lats.copy()
        inf_lats[0] = np.inf
        cases = {
            'longitude order reversed': {'lons': self.lons[::-1]},
            'latitude order reversed': {'lats': self.lats[::-1]},
            'longitude length': {'lons': self.lons[:8]},
            'latitude length': {'lats': np.append(self.lats, 36.25)},
            'longitude NaN': {'lons': nan_lons},
            'latitude inf': {'lats': inf_lats},
            'longitude spacing': {'lons': -122.0 + 0.2501 * np.arange(9)},
            'latitude spacing': {'lats': np.linspace(35.0, 36.5, 5)},
            'two-dimensional axis': {'lons': self.lons.reshape(3, 3)},
        }
        for name, axes in cases.items():
            with self.subTest(name), self.assertRaisesRegex(ValueError, 'differs from the land mask|not finite'):
                self.fetch(**axes)
        values, receipts, missing = self.fetch()  # control: identical axes are accepted
        self.assertEqual((values['u10'], missing, len(receipts)), ([7.0], [], 3))

    def test_absolute_coordinate_tolerance(self):
        for offset in (0.0, 5e-7, -5e-7, 9e-7):
            with self.subTest(offset=offset):
                values, _, _ = self.fetch(lons=self.lons + offset, lats=self.lats + offset)
                self.assertEqual(values['u10'], [7.0])
        # 5e-4 degrees at longitude 120 sits inside numpy's default relative tolerance and must still refuse.
        for offset in (2e-6, 5e-4, 1e-3, 0.25):
            for axis in ('lons', 'lats'):
                with self.subTest(offset=offset, axis=axis), self.assertRaisesRegex(ValueError, 'differs from the land mask'):
                    self.fetch(**{axis: (self.lons if axis == 'lons' else self.lats) + offset})

    def test_longitude_representations_of_one_meridian_agree(self):
        np = self.np
        ref = np.array([179.75, 180.0, -179.75, -179.5, -179.25, -179.0, -178.75, -178.5, -178.25])
        field = ref.copy()
        field[1] = -180.0  # the same meridian, written the other way round
        self.assertEqual(self.fetch(lons=field, ref_lons=ref)[0]['u10'], [7.0])


@unittest.skipUnless(HAS_ECCODES, 'Optional GRIB decoder not installed')
class PublicationTests(BuilderCase):
    @staticmethod
    def tree(root):
        return {str(p.relative_to(root)): p.read_bytes() for p in sorted(Path(root).rglob('*')) if p.is_file()}

    def test_mismatched_grid_retains_previous_generation(self):
        bad = FakeBucket(3, STEPS)
        displace(bad, 1, 6, ('u10',), 'longitude')
        with tempfile.TemporaryDirectory() as tmp:
            previous, output = Path(tmp, 'published'), Path(tmp, 'out')
            self.assertEqual(self.build(previous, FakeBucket(3, STEPS))['state'], 'built')
            before = self.tree(previous)
            failed = self.build(output, bad, previous, force=True)
            self.assertEqual((failed['status'], failed['kept_previous']), ('failed', True))
            self.assertNotIn('state', failed)
            self.assertIn('differs from the land mask', failed['issue'])
            self.assertEqual(self.tree(output / 'ncep_gefs025'), self.tree(previous / 'ncep_gefs025'))
            self.assertEqual(self.tree(previous), before)
            self.assertFalse(Path(output, '.ncep_gefs025.staging').exists())
            again = self.build(output, FakeBucket(3, STEPS), previous, force=True)
            self.assertEqual((again['status'], again['state']), ('ok', 'built'))

    def test_matching_grid_preserves_samples_and_receipts(self):
        digests = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as tmp:
                status = self.build(Path(tmp), FakeBucket(3, STEPS, absent={(2, 6)}))
                manifest = json.loads(Path(tmp, 'ncep_gefs025/manifest.json').read_text())
                region = json.loads(Path(tmp, 'ncep_gefs025/regions/test-region.json').read_text())
            self.assertEqual((status['status'], status['state'], status['missing_member_steps']), ('ok', 'built', 1))
            self.assertEqual(manifest['upstream']['messages'], (3 * 4 - 1) * 3)
            self.assertEqual(manifest['upstream']['missing'], [{'member': 2, 'step': 6, 'fields': ['u10', 'v10', 'gust']}])
            exact = region['points'][0]
            self.assertEqual((exact['grid'], exact['distance_km']), ([35.5, -121.5], 0.0))
            self.assertEqual(exact['wind_speed_10m'][0][0], 5.0)       # 3 and 4 m/s components
            self.assertEqual(exact['wind_gusts_10m'][0][2], 16.0)      # 10 + step 6
            self.assertIsNone(exact['wind_speed_10m'][2][2])
            digests.append((manifest['upstream']['messages_sha256'], manifest['upstream']['bytes']))
        self.assertEqual(digests[0], digests[1])


if __name__ == '__main__':
    unittest.main()
