"""The map's light startup copies (#617): the atlas marks, the search-plan index and the overview shoreline."""
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest

from skippercast.platform.shoreline import OVERVIEW_MIN_RING_M, OVERVIEW_TOLERANCE_M, feature_lines, overview_shoreline, simplify
from skippercast.platform.startup_forms import ATLAS_MARKS, PLAN_INDEX, SHORELINE_OVERVIEW, publish_startup_forms
from tests._support import ROOT

MB = ROOT / 'dist/regions/morro-bay'


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class CommittedCopies(unittest.TestCase):
    """The committed Morro Bay copies match their originals (the platform build rewrites them; CI diffs the result)."""

    def test_atlas_marks_keep_every_target_and_drop_only_geometry(self):
        atlas, marks = read(ROOT / 'dist/data/atlas.json'), read(MB / ATLAS_MARKS)
        self.assertEqual(marks['derived_from'], {'path': 'data/atlas.json', 'sha256': sha(ROOT / 'dist/data/atlas.json')})
        self.assertEqual(marks['targets'], atlas['targets'])
        self.assertEqual(marks['sources'], atlas['sources'])
        self.assertEqual(marks['source_validation_date'], atlas['source_validation_date'])
        self.assertNotIn('areas', marks)
        self.assertNotIn('drifts', marks)

    def test_plan_index_keeps_every_profile(self):
        plans, index = read(MB / 'search-plans.json'), read(MB / PLAN_INDEX)
        self.assertEqual(index['derived_from']['sha256'], sha(MB / 'search-plans.json'))
        self.assertEqual((index['region_id'], index['profiles']), (plans['region_id'], plans['profiles']))
        self.assertNotIn('features', index)

    def test_overview_shoreline_keeps_features_and_their_source_fields(self):
        full, overview = read(MB / 'shoreline.geojson'), read(MB / SHORELINE_OVERVIEW)
        self.assertEqual(overview['derived_from']['sha256'], sha(MB / 'shoreline.geojson'))
        by_id = {f['id']: f for f in full['features']}
        self.assertTrue(overview['features'])
        for feature in overview['features']:
            self.assertEqual(feature['properties'], by_id[feature['id']]['properties'])
            vertices = {tuple(p) for line in feature_lines(by_id[feature['id']]['geometry']) for p in line}
            self.assertTrue(all(tuple(p) in vertices for line in feature_lines(feature['geometry']) for p in line),
                            'an overview vertex is always one of the published vertices')
        self.assertLess(len(json.dumps(overview)), len(json.dumps(full)) / 3)


class Overview(unittest.TestCase):
    SCALE = (111_320 * math.cos(math.radians(35.4)), 110_540)

    def test_simplify_stays_within_the_tolerance(self):
        line = [[-121.0 + i * 1e-4, 35.4 + 2e-5 * math.sin(i)] for i in range(200)]
        kept = simplify(line, OVERVIEW_TOLERANCE_M, self.SCALE)
        self.assertLess(len(kept), len(line))
        self.assertEqual((kept[0], kept[-1]), (line[0], line[-1]))
        kx, ky = self.SCALE
        for p in line:  # every original vertex lies within the tolerance of the kept polyline
            best = min(self._distance(p, a, b, kx, ky) for a, b in zip(kept, kept[1:]))
            self.assertLessEqual(best, OVERVIEW_TOLERANCE_M + 1e-6)

    @staticmethod
    def _distance(p, a, b, kx, ky):
        px, py, ax, ay, bx, by = p[0] * kx, p[1] * ky, a[0] * kx, a[1] * ky, b[0] * kx, b[1] * ky
        dx, dy = bx - ax, by - ay
        t = max(0, min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        return math.hypot(px - ax - t * dx, py - ay - t * dy)

    def test_single_rocks_are_left_out_and_empty_features_dropped(self):
        rock = [[-121.0, 35.4], [-121.0001, 35.4], [-121.0001, 35.4001], [-121.0, 35.4]]  # about 11 m across
        coast = [[-121.0, 35.40], [-121.0, 35.41], [-121.01, 35.42]]
        published = {'type': 'FeatureCollection', 'schema_version': 2, 'provenance': {'bounds': [-122, 35, -120, 36], 'features': 2},
                     'features': [{'type': 'Feature', 'id': 'a', 'properties': {'k': 1}, 'geometry': {'type': 'MultiLineString', 'coordinates': [rock, coast]}},
                                  {'type': 'Feature', 'id': 'b', 'properties': {'k': 2}, 'geometry': {'type': 'MultiLineString', 'coordinates': [rock]}}]}
        out = overview_shoreline(published, {'path': 'x', 'sha256': '0' * 64})
        self.assertGreater(OVERVIEW_MIN_RING_M, 11)
        self.assertEqual([f['id'] for f in out['features']], ['a'])
        self.assertEqual(out['features'][0]['geometry']['coordinates'], [coast])
        self.assertEqual(out['provenance']['features'], 1)


class Publish(unittest.TestCase):
    def test_a_region_without_originals_publishes_no_copies_and_removes_stale_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, output = Path(tmp), Path(tmp) / 'dist/regions/r'
            output.mkdir(parents=True)
            for name in (ATLAS_MARKS, PLAN_INDEX, SHORELINE_OVERVIEW):
                (output / name).write_text('{}')
            region = {'id': 'r', 'assets': {'atlas': 'regions/r/atlas.json', 'search_plans': None}}
            self.assertEqual(publish_startup_forms(root, region, output), [])
            self.assertEqual(sorted(p.name for p in output.iterdir()), [])

    def test_copies_are_written_beside_the_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, output = Path(tmp), Path(tmp) / 'dist/regions/r'
            output.mkdir(parents=True)
            (output / 'atlas.json').write_text(json.dumps({'schema_version': 1, 'targets': [{'id': 't'}], 'areas': [{'id': 'a'}], 'drifts': [], 'sources': []}))
            region = {'id': 'r', 'assets': {'atlas': 'regions/r/atlas.json'}}
            self.assertEqual(publish_startup_forms(root, region, output), ['regions/r/atlas-marks.json'])
            marks = read(output / ATLAS_MARKS)
            self.assertEqual((marks['targets'], marks['startup_form']), ([{'id': 't'}], 'atlas-marks'))
            self.assertNotIn('areas', marks)


if __name__ == '__main__':
    unittest.main()
