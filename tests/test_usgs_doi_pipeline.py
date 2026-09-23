import importlib.util
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest


SCRIPTS=Path(__file__).resolve().parents[1]/'scripts'
sys.path.insert(0,str(SCRIPTS))
def module(name):
    spec=importlib.util.spec_from_file_location(name,SCRIPTS/(name+'.py'))
    loaded=importlib.util.module_from_spec(spec);spec.loader.exec_module(loaded)
    return loaded

doi=module('discover_usgs_doi_releases')
metadata=module('audit_usgs_map_metadata')


class DoiPipelineTests(unittest.TestCase):
    def test_only_index_catalog_dois_are_discovered(self):
        raw=b'''<a href="https://doi.org/10.5066/P9ZSTUK1">California State Waters Map Series Data Catalog--Point Estero</a>
        <a href="https://doi.org/10.5066/P9HEZNRO">California State Waters Map Series Data Catalog--Morro Bay</a>
        <a href="https://example.net/10.5066/FAKE">California State Waters Map Series Data Catalog--Fake</a>'''
        self.assertEqual(set(doi.index_dois(raw)),{'P9ZSTUK1','P9HEZNRO'})

    def test_doi_release_only_accepts_matching_official_files(self):
        landing='https://cmgds.marine.usgs.gov/data-releases/datarelease/10.5066-P9ZSTUK1/'
        good='https://cmgds.marine.usgs.gov/data-releases/media/2022/10.5066-P9ZSTUK1/a/SeafloorCharacter.zip'
        other=good.replace('P9ZSTUK1','P9HEZNRO')
        self.assertTrue(doi.official(good,'P9ZSTUK1',landing))
        self.assertFalse(doi.official(other,'P9ZSTUK1',landing))
        self.assertFalse(doi.official('https://attacker.example/'+good,'P9ZSTUK1',landing))

    def test_modern_original_xml_categorical_hard_class(self):
        raw=b'''<metadata><idinfo><spdom><bounding><westbc>-121.1</westbc><eastbc>-121.0</eastbc><southbc>35.3</southbc><northbc>35.4</northbc></bounding></spdom></idinfo>
        <eainfo><detailed><attr><attrlabl>Value</attrlabl><attrdomv><edom><edomv>3</edomv><edomvd>hard and rugose boulder and bedrock seafloor</edomvd></edom></attrdomv></attr></detailed></eainfo></metadata>'''
        row=metadata.parse_metadata('https://cmgds.marine.usgs.gov/data-releases/media/2022/10.5066-P9ZSTUK1/a/SeafloorCharacter.xml',raw,now=datetime(2026,9,23,tzinfo=timezone.utc))
        self.assertEqual(row['categorical_classes'][0]['code'],'3')
        self.assertIn('boulder',row['categorical_classes'][0]['label'])


if __name__=='__main__':unittest.main()
