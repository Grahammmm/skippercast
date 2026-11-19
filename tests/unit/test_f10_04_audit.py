"""Offline release admission controls for closure clearance around full footprints."""
import unittest

from skippercast.platform.qualified_scope import _utm11
from tests.unit.test_sp1703_qualified_coverage import RASTERS, SyntheticRelease, polygon, view


class ClosureClearanceTests(unittest.TestCase):
    def test_reviewed_projection_matches_independent_metric_reference(self):
        # Synthetic points, evaluated offline with PROJ (EPSG:4326 -> EPSG:26911).
        for point, expected in (
            ((-125, 25), (-308977.616577, 2788920.369111)),
            ((-119, 34), (315290.168867, 3763959.139495)),
            ((-110, 49), (1011818.952628, 5451106.950079)),
        ):
            with self.subTest(point=point):
                for actual, reference in zip(_utm11(*point), expected):
                    self.assertAlmostEqual(actual, reference, delta=.001)

    def test_disjoint_footprint_inside_buffer_cannot_use_claimed_clearance(self):
        # A later polygon component approaches the side of a closure. The target
        # center and first component are far away, and no vertices touch.
        self.check_clearance(gap_deg=.00001, ready=False)

    def test_disjoint_footprint_beyond_buffer_is_admitted(self):
        self.check_clearance(gap_deg=.001, ready=True)

    def check_clearance(self, gap_deg, ready):
        release = SyntheticRelease(self, [view(RASTERS['healthy'])])
        area = release.atlas['areas'][0]
        for record in (area, release.atlas['targets'][0]):
            record['recorded_validation']['closure_clearance_m'] = 100
        path = 'dist/' + release.region['assets']['closures']
        receipt = next(r for r in release.quality['closure_receipts'] if r['path'] == path)
        # Synthetic coordinates only. At 34 N the two gaps are ~0.9 m and
        # ~92 m, respectively; the reviewed policy requires 75 m.
        closure = polygon(-119.41, 33.999, -119.4, 34.001)
        receipt['sha256'] = release.write(path, {
            'region_id': release.rid, 'type': 'FeatureCollection',
            'checked_at': receipt['checked_at'], 'source_url': receipt['source_url'],
            'features': [{'type': 'Feature', 'geometry': closure}],
        })['sha256']
        nearby = polygon(-119.4 + gap_deg, 33.99, -119.38, 34.01)
        area['geometry'] = {'type': 'MultiPolygon', 'coordinates': [
            area['geometry']['coordinates'], nearby['coordinates'],
        ]}
        release.publish()
        if ready:
            result = release.validate()
            assert result is not None
            self.assertTrue(result['ready'])
            self.assertFalse(result['current_legal_clearance'])
            self.assertTrue(result['runtime_closure_screen_required'])
        else:
            with self.assertRaisesRegex(ValueError, 'below the reviewed closure clearance'):
                release.validate()
