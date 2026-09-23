import hashlib
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import unittest
import zipfile

import numpy as np
import rasterio
from rasterio.transform import from_origin

from scripts.qualify_regular_bag_hard import hard_mask_on_bag, excluded_report_hazards, excluded_federal_gea_cells


class OriginalGridScreenTest(unittest.TestCase):
    def test_federal_gea_exclusion_requires_current_complete_geometry(self):
        polygon = {'type': 'Polygon', 'coordinates': [[[-123.002, 37.998], [-122.998, 37.998],
                                                      [-122.998, 38.002], [-123.002, 38.002], [-123.002, 37.998]]]}
        far = {'type': 'Polygon', 'coordinates': [[[-120, 34], [-119.9, 34],
                                                  [-119.9, 34.1], [-120, 34.1], [-120, 34]]]}
        features = [{'geometry': polygon if i == 0 else far,
                     'properties': {'area_type': 'GEA' if i < 10 else 'YRCA',
                                    'source_layer': 'GEA_Cordell_Bank_20260623' if i == 0 else str(i)}}
                    for i in range(25)]
        snapshot = {'scope': 'noaa-west-coast-groundfish-conservation-areas', 'status': 'ok',
                    'retrieved_at': datetime.now(timezone.utc).isoformat(), 'features': features}
        from pyproj import Transformer
        x, y = Transformer.from_crs(4326, 26910, always_xy=True).transform(-123, 38)
        transform = from_origin(x - 500, y + 500, 5, 5)
        kwargs = {'shape_': (200, 200), 'transform_': transform, 'crs': 'EPSG:26910',
                  'geographic_bounds': (-123.01, 37.99, -122.99, 38.01)}
        mask = excluded_federal_gea_cells(snapshot, **kwargs)
        self.assertTrue(mask[100, 100])
        snapshot['retrieved_at'] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        with self.assertRaisesRegex(ValueError, 'stale'):
            excluded_federal_gea_cells(snapshot, **kwargs)

    def test_original_class_3_is_inset_and_not_confused_with_other_classes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            tif = root / 'character.tif'
            data = np.full((16, 16), 11, dtype='uint8')
            data[3:13, 3:13] = 13
            data[6, 6] = 12
            with rasterio.open(tif, 'w', driver='GTiff', width=16, height=16, count=1,
                               dtype='uint8', crs='EPSG:26910', transform=from_origin(0, 32, 2, 2),
                               nodata=0) as raster:
                raster.write(data, 1)
            url = 'https://pubs.usgs.gov/ds/781/Test/data/SeafloorCharacter_Test.zip'
            archive = root / ('Test-seafloor_character-' + hashlib.sha256(url.encode()).hexdigest()[:16] + '.zip')
            with zipfile.ZipFile(archive, 'w') as bundle:
                bundle.write(tif, 'character.tif')
            row = {'status': 'ok', 'kind': 'seafloor_character', 'block_id': 'Test',
                   'archive_url': url, 'archive_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                   'metadata_url': 'https://pubs.usgs.gov/test.xml', 'metadata_sha256': 'reviewed'}
            metadata = {'records': [{'status': 'ok', 'block_id': 'Test', 'kind': 'seafloor_character',
                                     'metadata_url': row['metadata_url'], 'xml_sha256': 'reviewed',
                                     'substrate_definitions': [{'definition': 'Class 3: rock and boulder, rugose'}]}]}
            mask, receipts = hard_mask_on_bag([row], root, metadata, shape_=(16, 16),
                                               transform_=from_origin(0, 32, 2, 2), crs='EPSG:26910')
            self.assertTrue(mask[9, 9])
            self.assertFalse(mask[3, 3])
            self.assertFalse(mask[6, 6])
            self.assertEqual(receipts[0]['archive_sha256'], row['archive_sha256'])

    def test_historical_hazard_requires_pinned_report_and_masks_center(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            report = root / 'H1.pdf'
            report.write_bytes(b'%PDF-reviewed')
            review = {'scope': 'historical-noaa-survey-hazard-review', 'surveys': [{
                'survey_id': 'H1', 'report_url': 'https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H1.pdf',
                'report_sha256': hashlib.sha256(report.read_bytes()).hexdigest(),
                'hazards': [{'longitude': -123, 'latitude': 38, 'review_exclusion_radius_m': 150}]}]}
            mask, _ = excluded_report_hazards('H1', review, root, shape_=(200, 200),
                                               transform_=from_origin(499800, 4206500, 4, 4), crs='EPSG:26910')
            from pyproj import Transformer
            x, y = Transformer.from_crs(4326, 26910, always_xy=True).transform(-123, 38)
            row = int((4206500 - y) // 4)
            col = int((x - 499800) // 4)
            self.assertTrue(mask[row, col])
            review['surveys'][0]['report_sha256'] = 'changed'
            with self.assertRaisesRegex(ValueError, 'missing or changed'):
                excluded_report_hazards('H1', review, root, shape_=(200, 200),
                                        transform_=from_origin(499800, 4206500, 4, 4), crs='EPSG:26910')

    def test_cross_survey_hazard_requires_supporting_original_report(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            primary = root / 'H1.pdf'
            primary.write_bytes(b'%PDF-primary')
            supporting = root / 'H2.pdf'
            supporting.write_bytes(b'%PDF-supporting')
            review = {'scope': 'historical-noaa-survey-hazard-review', 'surveys': [{
                'survey_id': 'H1', 'report_url': 'https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H1.pdf',
                'report_sha256': hashlib.sha256(primary.read_bytes()).hexdigest(),
                'supporting_reports': [{
                    'survey_id': 'H2', 'url': 'https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H2.pdf',
                    'sha256': hashlib.sha256(supporting.read_bytes()).hexdigest()}],
                'hazards': [{'longitude': -123, 'latitude': 38, 'review_exclusion_radius_m': 150}]}]}
            supporting.unlink()
            with self.assertRaisesRegex(ValueError, 'Supporting NOAA descriptive report is missing or changed'):
                excluded_report_hazards('H1', review, root, shape_=(200, 200),
                                        transform_=from_origin(499800, 4206500, 4, 4), crs='EPSG:26910')


if __name__ == '__main__':
    unittest.main()
