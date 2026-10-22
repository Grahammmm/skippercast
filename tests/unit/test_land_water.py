"""The land/water product for ranked places (CI6-01B; docs/land-water-method.md).

Every case is injected geometry near 35.4 N, offline and independent of the
committed region, except the last class, which rebuilds the committed Morro Bay
product from its committed shoreline. The node tests (tests/test_land_water.mjs)
classify points on the products this module writes to tests/fixtures/land-water/:

    PYTHONPATH=src:. python -m tests.unit.test_land_water --write

`FixturesTest` fails when those files differ from a rebuild, so they stay
generated output.
"""
import argparse
import json
from pathlib import Path
import re
import tempfile
import unittest

from skippercast.platform import land_water as lw
from tests._support import ROOT

FIXTURES = ROOT / 'tests/fixtures/land-water'
# The fixture region: about 3.6 km east-west by 4.4 km north-south, in zoom-12 tile column 671.
WEST, SOUTH, EAST, NORTH = -120.99, 35.40, -120.95, 35.44
K = lw.metres_per_unit((SOUTH + NORTH) / 2)


def at(x, y):
    """Metres east and north of the fixture region's south-west corner, as a published 5-decimal position."""
    return [round(WEST + x / K[0] / lw.UNIT, 5), round(SOUTH + y / K[1] / lw.UNIT, 5)]


def top():
    return (NORTH - SOUTH) * lw.UNIT * K[1]


def tile_key(lon, lat):
    x, y, *_ = lw.tile_of(lon, lat)
    return f'{lw.Z}/{x}/{y}'


def served_tiles(bounds=(WEST, SOUTH, EAST, NORTH)):
    w, s, e, n = bounds
    (x0, y0, *_), (x1, y1, *_) = lw.tile_of(w, n), lw.tile_of(e, s)
    return sorted(f'{lw.Z}/{x}/{y}' for x in range(x0, x1 + 1) for y in range(y0, y1 + 1))


def shoreline(lines, served=None, acc=4.31, raw=False):
    """A published-form CUSP collection with one feature per line (`lines` in metres unless raw)."""
    features = []
    for i, line in enumerate(lines):
        coords = line if raw else [at(*p) for p in line]
        first = coords[0] if coords and isinstance(coords[0], list) and all(isinstance(v, (int, float)) for v in coords[0]) else [WEST, SOUTH]
        features.append({'type': 'Feature', 'id': f'line-{i}', 'geometry': {'type': 'MultiLineString', 'coordinates': [coords]},
                         'properties': {'HOR_ACC': acc, 'source_tile': tile_key(*first), 'source_date': '2010-11-01', 'DAT_SET_CR': 'NOAA'}})
    return {'type': 'FeatureCollection', 'schema_version': 2, 'features': features,
            'provenance': {'region_id': 'fixture', 'bounds': [WEST, SOUTH, EAST, NORTH], 'display_quantisation_m': 1.96,
                           'tile_receipts': [{'tile': t} for t in (served if served is not None else served_tiles())]}}


REGION = {'id': 'fixture', 'bounds': [WEST, SOUTH, EAST, NORTH], 'land_water': {'land_corners': ['SE', 'NE']}}


def square(x, y, side):
    return [(x, y), (x + side, y), (x + side, y + side), (x, y + side), (x, y)]


def mainland(gap=None):
    """North bound to south bound with land to the east; a straight stretch at x = 2000 from y = 1200 to the south bound."""
    path = [(2000, top()), (2000, 2600), (2200, 2400), (2000, 1200), (2000, 0)]
    if gap is None:
        return [path]
    return [path[:-1] + [(2000, 1200 - 200 + gap / 2)], [(2000, 1200 - 200 - gap / 2), (2000, 0)]]


ISLAND, LAGOON = square(600, 1800, 300), square(2800, 1800, 300)
# Fixture cases for the node tests: name -> (lines, note).
CASES = {
    'coast': (mainland() + [ISLAND, LAGOON], 'mainland edge to edge (land east), a closed island ring, an enclosed water ring'),
    'gap': (mainland(gap=50) + [ISLAND], 'the mainland with a 50 m gap mid-tile, wider than the join limit'),
    'empty-line': (mainland() + [[]], 'an empty line'),
    'short-ring': (mainland() + [[(600, 1800), (800, 1800), (600, 1800)]], 'an "island" ring of three positions (a-b-a)'),
    'unclosed-island': (mainland() + [ISLAND[:-1]], 'an island ring left unclosed'),
    'non-numeric': (mainland(), 'a non-numeric coordinate'),
    'bowtie': (mainland() + [[(600, 1800), (800, 2000), (600, 2000), (800, 1800), (600, 1800)]], 'a 200 m bowtie island'),
}


def case_shoreline(name):
    lines, _ = CASES[name]
    shore = shoreline(lines)
    if name == 'non-numeric':
        shore['features'][0]['geometry']['coordinates'][0][2] = ['-120.97', 35.42]
    return shore


def build(name):
    return lw.build_product(case_shoreline(name), REGION, {'path': f'fixture/{name}', 'sha256': f'fixture-{name}'})


def write_fixtures():
    FIXTURES.mkdir(parents=True, exist_ok=True)
    for name, (_, note) in CASES.items():
        index, lines = build(name)
        index = {**index, 'fixture': note}
        (FIXTURES / f'{name}.json').write_bytes(lw._dump(index))
        target = FIXTURES / f'{name}.lines.json'
        if lines is None:
            target.unlink(missing_ok=True)
        else:
            target.write_bytes(lw._dump(lines))


def cells_of(runs):
    return ''.join(ch * int(n) for ch, n in re.findall(r'([wlm])(\d+)', runs))


def status(shore, region=REGION):
    index, _ = lw.build_product(shore, region)
    return index['status'], index['causes']


class BuilderTest(unittest.TestCase):
    def assertAvailable(self, shore, region=REGION):
        state, causes = status(shore, region)
        self.assertEqual((state, causes), ('available', []))

    def assertUnavailable(self, shore, cause, region=REGION):
        state, causes = status(shore, region)
        self.assertEqual(state, 'unavailable')
        self.assertIn(cause, causes[0])

    def test_coast_with_island_and_water_ring(self):
        index, lines = build('coast')
        self.assertEqual(index['status'], 'available')
        self.assertEqual(index['census']['parity_curves'], 3)
        self.assertEqual(len(lines['parity']), 3)
        self.assertEqual(sorted(index['tiles']), served_tiles())
        cells = ''.join(cells_of(runs) for runs in index['tiles'].values())
        self.assertEqual(len(cells), lw.GRID ** 2 * len(index['tiles']))
        self.assertEqual(set(cells), {'w', 'l', 'm'})

    def test_mid_tile_gaps_are_never_bridged(self):
        # The step-0 review's counterexample: a 50 m gap could hide a headland, so the product is unavailable.
        self.assertUnavailable(case_shoreline('gap'), 'gap not a tile seam')
        self.assertUnavailable(shoreline(mainland(gap=6)), 'gap not a tile seam')

    def test_seam_joins_need_every_condition(self):
        edge = lw.tile_lat(1616)
        a, b = (-12_100_000, edge), (-12_099_993, edge)  # 7 units of longitude, about 6.4 m, on a row edge
        north, south = {'tile': '12/671/1615', 'acc': 4.31}, {'tile': '12/671/1616', 'acc': 4.31}
        both = {'12/671/1615', '12/671/1616'}
        self.assertIsNone(lw.seam_problem(K, a, b, north, south, both))
        self.assertEqual(lw.seam_problem(K, a, b, north, south, {'12/671/1616'}), 'a tile was not served')
        self.assertIn('over 2 x HOR_ACC', lw.seam_problem(K, a, (a[0] + 22, edge), north, south, both))
        self.assertEqual(lw.seam_problem(K, (a[0], edge + 1), b, north, south, both), 'ends not on the shared tile edge')
        self.assertIn('not edge neighbours', lw.seam_problem(K, a, b, north, {'tile': '12/673/1616', 'acc': 4.31}, both))
        self.assertEqual(lw.seam_problem(K, a, b, north, {'tile': None, 'acc': 4.31}, both), 'no source tile')

    def test_seam_join_on_a_real_tile_edge(self):
        # The mainland split where it crosses a zoom-12 row edge, the two clips 6 m apart along that edge.
        _, row, *_ = lw.tile_of(WEST, SOUTH)
        edge_lat = lw.tile_lat(row) / lw.UNIT  # the north edge of the fixture's tile row
        bounds = [WEST, round(edge_lat - 0.02, 2), EAST, round(edge_lat + 0.02, 2)]
        region = {**REGION, 'bounds': bounds}
        lon = round(WEST + 2000 / K[0] / lw.UNIT, 5)
        north = [[lon, bounds[3]], [lon, edge_lat]]
        south = [[round(lon + 7 / lw.UNIT, 5), edge_lat], [round(lon + 7 / lw.UNIT, 5), bounds[1]]]
        shore = shoreline([north, south], served_tiles(bounds), raw=True)
        shore['provenance']['bounds'] = bounds
        shore['features'][0]['properties']['source_tile'] = tile_key(lon, edge_lat + 1e-4)
        shore['features'][1]['properties']['source_tile'] = tile_key(lon, edge_lat - 1e-4)
        self.assertAvailable(shore, region)
        index, _ = lw.build_product(shore, region)
        self.assertEqual(index['census']['seam_joins'], 1)
        shore['provenance']['tile_receipts'] = [{'tile': t} for t in served_tiles(bounds) if t != shore['features'][1]['properties']['source_tile']]
        self.assertUnavailable(shore, 'a tile was not served', region)

    def test_degenerate_curves_are_edge_only(self):
        self.assertEqual(lw.degenerate(K, [tuple(map(round, (p[0] * lw.UNIT, p[1] * lw.UNIT))) for p in (at(0, 0), at(56, 0), at(0, 0))]), 'collinear')
        ring = lambda pts: [tuple(round(v * lw.UNIT) for v in at(*p)) for p in pts + pts[:1]]
        self.assertEqual(lw.degenerate(K, ring([(0, 0), (10, 10), (0, 10), (10, 0)])), 'small')
        self.assertIsNone(lw.degenerate(K, ring([(0, 0), (200, 200), (0, 200), (200, 0)])))
        # A three-position "ring" is collinear: it is an edge line and never an island.
        self.assertAvailable(case_shoreline('short-ring'))
        self.assertEqual(build('short-ring')[0]['census']['parity_curves'], 1)

    def test_malformed_input_makes_the_product_unavailable(self):
        self.assertUnavailable(case_shoreline('empty-line'), 'malformed lines 1')
        self.assertUnavailable(case_shoreline('non-numeric'), 'malformed lines 1')
        self.assertUnavailable(case_shoreline('unclosed-island'), 'is not degenerate')
        self.assertUnavailable(shoreline(mainland() + [[(600, 1800)]]), 'malformed lines 1')
        self.assertUnavailable(shoreline(mainland() + [[(600, 1800), (600, 1800)]]), 'malformed lines 1')
        nan = shoreline(mainland())
        nan['features'][0]['geometry']['coordinates'][0][1] = [float('nan'), 35.42]
        self.assertUnavailable(nan, 'malformed lines 1')
        self.assertUnavailable({'type': 'Feature'}, 'not a FeatureCollection')
        self.assertUnavailable(shoreline([]), 'no shoreline lines')

    def test_defects_without_a_witness_fail_closed(self):
        self.assertUnavailable(case_shoreline('bowtie'), 'defects without a witness')
        loop = [(400, 400), (900, 400), (900, 900), (600, 900), (600, 1000), (700, 1000), (700, 850), (400, 850), (400, 400)]
        self.assertUnavailable(shoreline(mainland() + [loop]), 'defects without a witness')
        self.assertUnavailable(shoreline(mainland() + [square(400, 400, 300), square(550, 550, 300)]), 'defects without a witness')
        self.assertUnavailable(shoreline(mainland() + [[(1900, 600), (2100, 500), (2100, 700), (1900, 600)]]), 'defects without a witness')

    def test_witnessed_defects_are_removed(self):
        curl = [(400, 400), (900, 400), (900, 900), (640, 900), (640, 910), (650, 910), (650, 895), (400, 895), (400, 400)]
        spike = [(400, 400), (900, 400), (900, 650), (1000, 650), (900, 650), (900, 900), (400, 900), (400, 400)]
        for ring in (curl, spike):
            index, _ = lw.build_product(shoreline(mainland() + [ring]), REGION)
            self.assertEqual(index['status'], 'available', ring)
            self.assertTrue(index['census']['removed'])
        # A vertex resting on the coast without crossing it (today's eight tangent touches) is allowed.
        touch = [(2000, 600), (1800, 500), (1800, 700), (2000, 600)]
        index, _ = lw.build_product(shoreline(mainland() + [touch]), REGION)
        self.assertEqual((index['status'], set(index['census']['left'])), ('available', {'touch without crossing'}))  # one per segment pair

    def test_changed_mainland_is_the_one_classified(self):
        # The step-0 review's note: the parity curves must carry the mainland after removal, not the original.
        path = [(2000, top()), (2000, 2600), (1990, 2600), (1990, 2610), (2005, 2610), (2005, 2400), (2000, 0)]
        built = lw.assemble(shoreline([path]), REGION)
        original = lw.close_mainland([tuple(round(v * lw.UNIT) for v in at(*p)) for p in path], REGION, built['units'])
        self.assertEqual(built['counts']['removed'], {'inner sub-loop': 1})
        self.assertNotEqual(built['parity'][0], original)
        self.assertLess(len(built['parity'][0]), len(original))
        self.assertIn(built['parity'][0], [c for c in built['parity']])

    def test_topology_and_closure_failures(self):
        path = mainland()[0]
        branch = [path[:4], path[3:], [(2000, 1200), (2500, 1300)]]
        self.assertUnavailable(shoreline(branch), 'three or more lines')
        self.assertUnavailable(shoreline(mainland() + [[(1000, top()), (1000, 0)]]), 'bounds-to-bounds paths 2')
        self.assertUnavailable(shoreline([]), 'no shoreline lines')
        self.assertUnavailable(case_shoreline('coast'), 'declares no land corners', {**REGION, 'land_water': {}})
        self.assertUnavailable(case_shoreline('coast'), 'do not fit the declared land corners', {**REGION, 'land_water': {'land_corners': ['NW']}})
        self.assertUnavailable(case_shoreline('coast'), 'do not share a bounds edge', {**REGION, 'land_water': {'land_corners': ['SE', 'NW']}})
        self.assertUnavailable(shoreline(mainland(), acc=12), 'exceeds EDGE_M')
        far = shoreline(mainland())
        far['provenance']['bounds'] = [WEST, SOUTH, EAST + 0.01, NORTH]
        self.assertUnavailable(far, 'differ from the region bounds')

    def test_land_side_follows_the_declared_corners(self):
        index, lines = build('coast')
        rows = lw._rows([(a, b) for c in lw.assemble(case_shoreline('coast'), REGION)['parity'] for a, b in zip(c, c[1:])])
        east, west = at(3300, 3500), at(400, 600)
        self.assertTrue(lw.parity_at(rows, (east[0] * lw.UNIT, east[1] * lw.UNIT)))
        self.assertFalse(lw.parity_at(rows, (west[0] * lw.UNIT, west[1] * lw.UNIT)))
        flipped = lw.assemble(case_shoreline('coast'), {**REGION, 'land_water': {'land_corners': ['SW', 'NW']}})
        rows = lw._rows([(a, b) for c in flipped['parity'] for a, b in zip(c, c[1:])])
        self.assertFalse(lw.parity_at(rows, (east[0] * lw.UNIT, east[1] * lw.UNIT)))
        self.assertTrue(lw.parity_at(rows, (west[0] * lw.UNIT, west[1] * lw.UNIT)))

    def test_grid_cells_are_clean_only_beyond_the_band(self):
        index, _ = build('coast')
        built = lw.assemble(case_shoreline('coast'), REGION)
        edge = [(a, b) for line in built['edge'] for a, b in zip(line, line[1:])]
        for tile, runs in index['tiles'].items():
            cells = cells_of(runs)
            self.assertEqual(len(cells), lw.GRID ** 2)
            for r in range(lw.GRID):
                for c in range(lw.GRID):
                    if cells[r * lw.GRID + c] == 'm':
                        continue
                    box = lw.cell_box(tile, r, c)
                    k = lw.metres_per_unit((box[1] + box[3]) / 2 / lw.UNIT)
                    self.assertTrue(all(lw._segment_box_m(k, a, b, box) > lw.EDGE_M for a, b in edge), (tile, r, c))


class PublishTest(unittest.TestCase):
    def test_no_shoreline_writes_nothing_and_removes_stale_copies(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / lw.INDEX).write_text('{}')
            (out / lw.LINES).write_text('{}')
            self.assertIsNone(lw.publish_land_water(ROOT, REGION, out))
            self.assertFalse((out / lw.INDEX).exists() or (out / lw.LINES).exists())

    def test_unavailable_product_keeps_its_causes_and_no_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / 'shoreline.geojson').write_text(json.dumps(case_shoreline('gap')))
            (out / lw.LINES).write_text('{}')
            index = lw.publish_land_water(ROOT, REGION, out)
            self.assertEqual(index['status'], 'unavailable')
            self.assertFalse((out / lw.LINES).exists())
            self.assertEqual(json.loads((out / lw.INDEX).read_text())['causes'], index['causes'])


class FixturesTest(unittest.TestCase):
    def test_node_fixtures_are_rebuilt_output(self):
        for name, (_, note) in CASES.items():
            index, lines = build(name)
            self.assertEqual(json.loads((FIXTURES / f'{name}.json').read_text()), {**index, 'fixture': note}, name)
            target = FIXTURES / f'{name}.lines.json'
            self.assertEqual(json.loads(target.read_text()) if target.exists() else None, lines, name)


class CommittedProductTest(unittest.TestCase):
    """The committed Morro Bay product is the builder's output for the committed shoreline (step-0 numbers)."""

    def test_morro_bay(self):
        out = ROOT / 'dist/regions/morro-bay'
        region = json.loads((ROOT / 'regions/morro-bay/region.json').read_text())
        index = json.loads((out / lw.INDEX).read_text())
        self.assertEqual(index['status'], 'available')
        census = index['census']
        self.assertEqual((census['lines'], census['closed_lines'], census['open_lines']), (3773, 3593, 180))
        self.assertEqual((census['seam_joins'], census['edge_only_chains'], census['parity_curves'], census['parity_segments']), (1, 4, 196, 12740))
        self.assertEqual(census['left'], {'touch without crossing': 8})
        raw = (out / 'shoreline.geojson').read_bytes()
        rebuilt, lines = lw.build_product(json.loads(raw), region, index['derived_from'])
        self.assertEqual(rebuilt, index)
        self.assertEqual((out / lw.LINES).read_bytes(), lw._dump(lines))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Write the node fixtures (tests/fixtures/land-water/).')
    parser.add_argument('--write', action='store_true')
    if parser.parse_args().write:
        write_fixtures()
        print(f'wrote {FIXTURES}')
    else:
        unittest.main()
