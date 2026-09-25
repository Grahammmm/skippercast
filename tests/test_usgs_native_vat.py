"""Original value tables must agree with inspected native class pixels."""
from io import BytesIO
import json
from pathlib import Path
import sys
import unittest

import shapefile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from scripts.inspect_usgs_native_grids import parse_vat


def original_style_dbf():
    shp, shx, dbf = BytesIO(), BytesIO(), BytesIO()
    writer = shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.NULL)
    for name, kind, width in [('VALUE', 'N', 5), ('COUNT', 'N', 12),
                              ('SUBSTRATE', 'N', 2), ('SUBST_DESC', 'C', 60)]:
        writer.field(name, kind, width, 0 if kind == 'N' else 0)
    writer.null()
    writer.record(3, 4, 3, 'Rock and boulders, rugose')
    writer.close()
    return dbf.getvalue()


class UsgsNativeVatTests(unittest.TestCase):
    def test_original_table_proves_class_semantics_only_when_counts_match(self):
        raw = original_style_dbf()
        self.assertEqual(parse_vat(raw, {'3': 4})[0]['substrate_class'], 3)
        with self.assertRaisesRegex(ValueError, 'counts do not match'):
            parse_vat(raw, {'3': 5})

    def test_aptos_receipt_is_actual_grid_review_and_not_a_target(self):
        data = json.loads((ROOT / 'dist/data/usgs-offshore-aptos-native-audit.json').read_text())
        self.assertEqual(data['scope'], 'usgs-state-waters-native-grid-audit')
        self.assertEqual((data['inspected_count'], data['product_count']), (4, 4))
        self.assertFalse(data['fishing_target'])
        self.assertFalse(data['exportable'])
        two_meter = next(row for row in data['products'] if row['kind'] == 'seafloor_character'
                         and '2m' in row['archive_url'])
        self.assertEqual(two_meter['class_table_status'], 'verified')
        self.assertEqual(sum(row['count'] for row in two_meter['original_class_table']
                             if row['substrate_class'] == 3), 156741)
        self.assertEqual(sum(two_meter['class_counts'].values()), two_meter['valid_pixels'])
        self.assertEqual(two_meter['archive_sha256'],
                         '9fcab31d296bcf75c26c3aa937fe7fff190f0365299b6a287f76e93694dbcead')


if __name__ == '__main__':
    unittest.main()
