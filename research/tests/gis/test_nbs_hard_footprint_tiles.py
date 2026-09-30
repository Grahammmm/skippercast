import json
import tempfile
import unittest

from shapely.geometry import box
from shapely import wkb

from research.scripts.inventory_nbs_hard_footprint_tiles import COASTS, gpkg_geometry, inventory
from research.scripts.audit_nbs_hard_footprint_tiles import validate
from research.lib.paths import ROOT


class HardFootprintTileTest(unittest.TestCase):
    def test_geopackage_binary_geometry(self):
        raw = b'GP' + bytes([0, 1]) + b'\0' * 4 + wkb.dumps(box(-123, 35, -122, 36))
        self.assertEqual(gpkg_geometry(raw).bounds, (-123.0, 35.0, -122.0, 36.0))
        with self.assertRaisesRegex(ValueError, 'GeoPackage'):
            gpkg_geometry(b'not a geopackage')

    def test_reviewed_california_inventory_is_non_target(self):
        root = ROOT
        scheme = root / 'var/modeling-tile-scheme-20260923.gpkg'
        if not scheme.exists():
            self.skipTest('Pinned NOAA scheme not cached')
        contexts = {coast: root / 'dist/data' / f'usgs-hard-context-{coast}.geojson'
                    for coast in COASTS}
        sectors = json.loads((root / 'catalog/coastal-sectors.json').read_text())
        report = inventory(scheme, contexts, sectors)
        self.assertEqual(report['tile_count'], 102)
        self.assertFalse(report['fishing_target'])
        self.assertFalse(report['exportable'])
        self.assertEqual(len({row['tile'] for row in report['tiles']}), 102)
        with tempfile.TemporaryDirectory() as directory:
            changed = dict(report)
            changed['scheme_sha256'] = '0' * 64
            with self.assertRaisesRegex(ValueError, 'scheme hash changed'):
                validate(changed, scheme)
        validate(report, scheme)


if __name__ == '__main__':
    unittest.main()
