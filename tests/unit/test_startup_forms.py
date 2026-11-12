"""The map's light startup copies (#617): the atlas marks, the search-plan index, the overview shoreline and (SC1938-06) the regulations."""
import hashlib
import json
import math
from pathlib import Path
import tempfile
import unittest

from skippercast.platform.shoreline import OVERVIEW_MIN_RING_M, OVERVIEW_TOLERANCE_M, feature_lines, overview_shoreline, simplify
from skippercast.platform.startup_forms import ATLAS_MARKS, PLAN_INDEX, POSTER, REGS_STARTUP, SHORELINE_OVERVIEW, poster_svg, publish_startup_forms, regs_startup
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

    def test_poster_is_the_overview_as_one_path_and_names_its_checksum(self):
        text, overview = (MB / POSTER).read_text(), read(MB / SHORELINE_OVERVIEW)
        self.assertEqual(text, poster_svg(overview, {'path': 'x', 'sha256': sha(MB / SHORELINE_OVERVIEW)}))
        self.assertIn(f'data-sha256="{sha(MB / SHORELINE_OVERVIEW)}"', text)
        self.assertEqual(text.count('<path '), 1)
        self.assertRegex(text, r'<path d="[Ml0-9 \-]+"/>')


def committed_regions():
    """(region.json, dist-relative registry path) of every committed region that names a registry."""
    found = []
    for path in sorted((ROOT / 'dist/regions').glob('*/region.json')):
        region = read(path)
        if region.get('jurisdiction_id') and region['assets'].get('regulations'):
            found.append(region)
    return found


def registry_with(**extra):
    """A small valid registry: two species (one cites two sources), one source nobody cites, one area notice."""
    check = {'status': 'unchanged', 'source_status': 'ok', 'data_retrieved_at': '2026-09-25T08:00:00Z'}
    return {'schema_version': 1, 'revision': 'r', 'reviewed_at': '2026-09-25T08:00:00Z', 'valid_from': '2026-01-01', 'valid_through': '2026-12-31',
            'check_interval_hours': 24, 'max_age_hours': 36, 'jurisdiction_id': 'j', 'rules_review_status': 'reviewed', 'common_notes': ['n'],
            'area': 'a', 'scope': 's', 'authority_hosts': ['h'], 'official_map_url': 'u', 'review_record': 'rr',
            'sources': {k: {'name': k, 'url': f'https://x/{k}'} for k in ('a', 'b', 'c', 'unused')},
            'checks': {k: dict(check) for k in ('a', 'b', 'c', 'unused')},
            'species': {'lingcod': {'name': 'Lingcod', 'source_ids': ['a', 'b']}, 'rockfish': {'name': 'Rockfish', 'source_ids': ['a']},
                        'salmon': {'name': 'Salmon', 'source_ids': ['c'], 'primary_source_id': 'c'}},
            'area_notices': [{'id': 'n1', 'name': 'N', 'note': 'x', 'source_ids': ['unused']}], **extra}


class RegulationsCopy(unittest.TestCase):
    """The map's legality line reads regions/<id>/regulations-startup.json before the whole shared registry."""

    def test_every_committed_copy_is_the_regions_cut_of_its_registry_and_names_its_checksum(self):
        regions = committed_regions()
        self.assertGreaterEqual(len(regions), 10)
        for region in regions:
            with self.subTest(region=region['id']):
                path, copy_path = ROOT / 'dist' / region['assets']['regulations'], ROOT / f"dist/regions/{region['id']}/{REGS_STARTUP}"
                copy = read(copy_path)
                self.assertEqual(copy['derived_from'], {'path': region['assets']['regulations'], 'sha256': sha(path)})
                self.assertEqual(copy, regs_startup(read(path), copy['derived_from'], region), 'the build is deterministic: the committed copy is what it writes')
                self.assertEqual(copy['jurisdiction_id'], region['jurisdiction_id'])
                self.assertLess(copy_path.stat().st_size, path.stat().st_size)
                self.assertNotIn('area_notices', copy)

    def test_morro_bay_copy_is_well_under_the_whole_registry(self):
        whole, copy = (ROOT / 'dist/data/regulations.json').stat().st_size, (MB / REGS_STARTUP).stat().st_size
        self.assertLess(copy, whole * 0.6)

    def test_only_the_regions_species_and_the_sources_and_checks_they_cite_are_kept(self):
        region = {'id': 'r', 'species': ['reef', 'salmon']}
        copy = regs_startup(registry_with(), {'path': 'p', 'sha256': 'x'}, region)
        self.assertEqual(sorted(copy['species']), ['lingcod', 'rockfish', 'salmon'], '`reef` stands for lingcod and rockfish')
        self.assertEqual(sorted(copy['sources']), ['a', 'b', 'c'])
        self.assertEqual(sorted(copy['checks']), ['a', 'b', 'c'])
        self.assertEqual(copy['species']['lingcod'], registry_with()['species']['lingcod'], 'a species record is copied whole')
        self.assertEqual(copy['sources']['a'], registry_with()['sources']['a'])
        self.assertEqual(copy['derived_from'], {'path': 'p', 'sha256': 'x'})
        for key in ('schema_version', 'reviewed_at', 'max_age_hours', 'check_interval_hours', 'jurisdiction_id', 'rules_review_status', 'valid_from', 'valid_through', 'common_notes'):
            self.assertEqual(copy[key], registry_with()[key], key)
        for key in ('area', 'scope', 'authority_hosts', 'official_map_url', 'review_record', 'area_notices'):
            self.assertNotIn(key, copy)
        narrow = regs_startup(registry_with(), {'path': 'p', 'sha256': 'x'}, {'id': 'r', 'species': ['salmon']})
        self.assertEqual((sorted(narrow['species']), sorted(narrow['sources'])), (['salmon'], ['c']))

    def test_a_registry_whose_area_notice_cites_no_reviewed_source_is_refused(self):
        region = {'id': 'r', 'species': ['salmon']}
        for notice in ({'id': 'n', 'name': 'N', 'note': 'x', 'source_ids': ['missing']}, {'id': 'n', 'name': 'N', 'note': 'x', 'source_ids': []},
                       {'id': 'n', 'name': 'N', 'source_ids': ['a']}, {'id': 'n', 'name': 'N', 'note': 'x'}):
            with self.subTest(notice=notice), self.assertRaises(ValueError):
                regs_startup(registry_with(area_notices=[notice]), {'path': 'p', 'sha256': 'x'}, region)
        regs_startup(registry_with(area_notices=[]), {'path': 'p', 'sha256': 'x'}, region)

    def test_published_beside_the_package_from_assets_regulations_and_removed_when_there_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, output = Path(tmp), Path(tmp) / 'dist/regions/r'
            output.mkdir(parents=True)
            (Path(tmp) / 'dist/data').mkdir(parents=True)
            registry = registry_with()
            (Path(tmp) / 'dist/data/regulations.json').write_text(json.dumps(registry))
            region = {'id': 'r', 'species': ['salmon'], 'assets': {'regulations': 'data/regulations.json'}}
            self.assertEqual(publish_startup_forms(root, region, output), ['regions/r/regulations-startup.json'])
            copy = read(output / REGS_STARTUP)
            self.assertEqual(copy['derived_from'], {'path': 'data/regulations.json', 'sha256': sha(Path(tmp) / 'dist/data/regulations.json')})
            self.assertEqual(sorted(copy['species']), ['salmon'])
            for assets in ({'regulations': None}, {}, {'regulations': 'data/gone.json'}):
                with self.subTest(assets=assets):
                    (output / REGS_STARTUP).write_text('{}')
                    self.assertEqual(publish_startup_forms(root, {**region, 'assets': assets}, output), [])
                    self.assertFalse((output / REGS_STARTUP).exists(), 'a stale copy is removed')


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
            for name in (ATLAS_MARKS, PLAN_INDEX, SHORELINE_OVERVIEW, POSTER, REGS_STARTUP):
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
