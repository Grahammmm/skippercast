import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location('map_metadata', SCRIPTS / 'audit_usgs_map_metadata.py')
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


class UsgsMetadataTests(unittest.TestCase):
    def test_original_xml_bounds_and_substrate_description(self):
        raw=b'''<metadata><idinfo><citation><citeinfo><title>Map block</title><pubdate>2014</pubdate></citeinfo></citation><spdom><bounding><westbc>-122.5</westbc><eastbc>-122.4</eastbc><northbc>37.4</northbc><southbc>37.2</southbc></bounding></spdom></idinfo><eainfo><detailed><attr><attrlabl>SUBSTRATE</attrlabl><attrdef>Class 3: rock and boulder</attrdef></attr></detailed></eainfo></metadata>'''
        row=mod.parse_metadata('https://pubs.usgs.gov/ds/781/X/metadata/SeafloorCharacter_X.xml',raw,now=datetime(2026,9,23,tzinfo=timezone.utc))
        self.assertEqual(row['bounds']['southbc'],37.2)
        self.assertIn('rock and boulder',row['substrate_definitions'][0]['definition'])

    def test_missing_bounds_is_not_approved(self):
        with self.assertRaises(ValueError):
            mod.parse_metadata('https://pubs.usgs.gov/ds/781/X/metadata/Bathymetry_X.xml',b'<metadata/>',now=datetime.now(timezone.utc))

    def test_structured_vertical_datum_is_separate_from_text_mentions(self):
        bounds=b'<bounding><westbc>-122.5</westbc><eastbc>-122.4</eastbc><southbc>37.2</southbc><northbc>37.4</northbc></bounding>'
        structured=b'<metadata>'+bounds+b'<vertdef><altsys><altdatum>North American Vertical Datum of 1988</altdatum></altsys></vertdef><abstract>Input MLLW soundings were converted.</abstract></metadata>'
        row=mod.parse_metadata('https://pubs.usgs.gov/ds/781/X/metadata/Bathymetry_X.xml',structured,now=datetime.now(timezone.utc))
        self.assertEqual(row['native_vertical_datum_code'],'NAVD88')
        self.assertEqual(row['vertical_datum_evidence'],'structured-xml')
        self.assertIn('MLLW',row['vertical_datum_mentions'])
        unstructured=b'<metadata>'+bounds+b'<abstract>NAVD88 bathymetry</abstract></metadata>'
        row=mod.parse_metadata('https://pubs.usgs.gov/ds/781/X/metadata/Bathymetry_X.xml',unstructured,now=datetime.now(timezone.utc))
        self.assertIsNone(row['native_vertical_datum_code'])
        self.assertEqual(row['vertical_datum_evidence'],'unverified-text-mentions')


if __name__=='__main__':unittest.main()
