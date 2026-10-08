"""The NOAA CUSP shoreline import and its platform-build gate (FE-10, design § 11)."""
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from scripts import import_cusp_shoreline as cusp
from skippercast.platform.shoreline import check_shoreline, publish_shoreline
from tests._support import ROOT, NOW


def varint(n):
    out = bytearray()
    while True:
        out.append((n & 0x7F) | (0x80 if n > 0x7F else 0))
        n >>= 7
        if not n:
            return bytes(out)


def field(number, payload):
    if isinstance(payload, int):
        return varint(number << 3) + varint(payload)
    return varint(number << 3 | 2) + varint(len(payload)) + payload


def packed(values):
    return b''.join(varint(v) for v in values)


def zigzag(n):
    return (n << 1) ^ (n >> 31)


def tile(features):
    """A synthetic one-layer MVT: features are (properties, [(x, y), ...]) lines in tile units."""
    keys, values, body = [], [], b''
    for properties, points in features:
        tags = []
        for key, value in properties.items():
            if key not in keys:
                keys.append(key)
            if value not in values:
                values.append(value)
            tags += [keys.index(key), values.index(value)]
        geometry, (x, y) = [9, zigzag(points[0][0]), zigzag(points[0][1])], points[0]
        geometry.append(2 | (len(points) - 1) << 3)
        for px, py in points[1:]:
            geometry += [zigzag(px - x), zigzag(py - y)]
            x, y = px, py
        body += field(2, field(2, packed(tags)) + field(3, 2) + field(4, packed(geometry)))
    layer = (field(15, 2) + field(1, b'tiles') + body + b''.join(field(3, k.encode()) for k in keys)
             + b''.join(field(4, field(1, v.encode())) for v in values) + field(5, 4096))
    return gzip.compress(field(3, layer))


NOAA = {'SRC_DATE': '20100509', 'HOR_ACC': '4.31', 'DAT_SET_CR': 'NOAA', 'ATTRIBUTE': 'Natural.Mean High Water'}
BOX = [-120.9, 35.3, -120.8, 35.4]


class DecodeAndClipTests(unittest.TestCase):
    def test_a_gzipped_tile_decodes_to_properties_and_lines(self):
        (layer,) = cusp.decode_tile(tile([(NOAA, [(10, 20), (30, 40), (25, 45)])]))
        self.assertEqual((layer['name'], layer['extent']), ('tiles', 4096))
        (feature,) = layer['features']
        self.assertEqual(feature['properties'], NOAA)
        self.assertEqual(cusp.lines(feature['geometry']), [[(10, 20), (30, 40), (25, 45)]])

    def test_clip_splits_a_line_that_leaves_and_returns(self):
        pieces = cusp.clip([(0.5, 0.5), (2.0, 0.5), (0.5, 0.8)], [0, 0, 1, 1])
        self.assertEqual(pieces, [[[0.5, 0.5], [1.0, 0.5]], [[1.0, 0.7], [0.5, 0.8]]])
        self.assertEqual(cusp.clip([(0.1, 0.1), (0.2, 0.2)], [0, 0, 1, 1]), [[[0.1, 0.1], [0.2, 0.2]]])
        self.assertEqual(cusp.clip([(2, 2), (3, 3)], [0, 0, 1, 1]), [])

    def test_source_dates_are_iso_or_refused(self):
        self.assertEqual(cusp.source_date('19940228'), '1994-02-28')
        self.assertIsNone(cusp.source_date('19941345'))
        self.assertIsNone(cusp.source_date(None))


class ExtractTests(unittest.TestCase):
    def test_extract_keeps_dated_noaa_lines_and_records_the_rest(self):
        z, x, y = cusp.tiles_for(BOX)[0]
        body = tile([(NOAA, [(100, 100), (4000, 4000)]),
                     ({**NOAA, 'DAT_SET_CR': 'County'}, [(100, 100), (200, 200)]),
                     ({**NOAA, 'SRC_DATE': 'unknown'}, [(100, 100), (200, 200)])])
        collection = cusp.extract('test-region', BOX, get=lambda t: body if t == (z, x, y) else None, now=NOW)
        provenance = collection['provenance']
        (feature,) = collection['features']
        self.assertEqual(feature['properties']['source_date'], '2010-05-09')
        self.assertEqual(feature['properties']['HOR_ACC'], '4.31')
        self.assertEqual(provenance['held_creators'], {'County': 1})
        self.assertEqual(provenance['undated_features_dropped'], 1)
        self.assertEqual(len(provenance['unavailable_tiles']), provenance['requested_tiles'] - 1)
        self.assertEqual(provenance['tile_receipts'][0]['bytes'], len(body))
        self.assertAlmostEqual(provenance['display_quantisation_m'], 1.95, delta=0.05)
        for lon, lat in feature['geometry']['coordinates']:
            self.assertTrue(BOX[0] <= lon <= BOX[2] and BOX[1] <= lat <= BOX[3])
        check_shoreline(collection, {'id': 'test-region', 'bounds': BOX})


class PlatformGateTests(unittest.TestCase):
    def test_committed_imports_pass_the_gate_and_ship_unchanged(self):
        imports = sorted((ROOT / 'catalog/shoreline').glob('*.geojson'))
        self.assertTrue(imports, 'the Morro Bay import is the reference extract')
        for path in imports:
            region = json.loads((ROOT / 'regions' / path.stem / 'region.json').read_text())
            check_shoreline(json.loads(path.read_text()), region)
            self.assertEqual((ROOT / 'dist/regions' / path.stem / 'shoreline.geojson').read_bytes(), path.read_bytes())
            manifest = json.loads((ROOT / 'dist/regions' / path.stem / 'manifest.json').read_text())
            self.assertNotIn('shoreline', manifest['assets'])  # v1 offline packs save every manifest asset
            self.assertNotIn('shoreline', region['assets'])

    def test_undated_or_outside_features_are_refused(self):
        region = {'id': 'test-region', 'bounds': BOX}
        good = {'type': 'Feature', 'id': 'a', 'properties': {'source_date': '2010-05-09', 'DAT_SET_CR': 'NOAA'},
                'geometry': {'type': 'LineString', 'coordinates': [[-120.85, 35.35], [-120.84, 35.36]]}}
        collection = lambda *features: {'type': 'FeatureCollection', 'features': list(features), 'provenance': {
            'region_id': 'test-region', 'source_id': 'noaa-cusp-shoreline', 'features': len(features)}}
        check_shoreline(collection(good), region)
        for bad in ({**good, 'properties': {'DAT_SET_CR': 'NOAA'}},
                    {**good, 'properties': {**good['properties'], 'DAT_SET_CR': 'County'}},
                    {**good, 'geometry': {'type': 'LineString', 'coordinates': [[-121.5, 35.35], [-120.84, 35.36]]}}):
            with self.assertRaises(ValueError):
                check_shoreline(collection(bad), region)

    def test_a_region_without_an_import_publishes_none_and_drops_a_stale_copy(self):
        root, output = Path(tempfile.mkdtemp()), Path(tempfile.mkdtemp())
        (output / 'shoreline.geojson').write_text('{}')
        self.assertIsNone(publish_shoreline(root, {'id': 'test-region', 'bounds': BOX}, output))
        self.assertFalse((output / 'shoreline.geojson').exists())


if __name__ == '__main__':
    unittest.main()
