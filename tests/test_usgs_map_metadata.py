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


if __name__=='__main__':unittest.main()
