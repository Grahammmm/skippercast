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

context=module('build_usgs_statewide_context')
splitter=module('split_usgs_context')


class UsgsContextTests(unittest.TestCase):
    def test_legacy_and_modern_class_three_require_rock_evidence(self):
        legacy={'substrate_definitions':[{'definition':'Class 3, Rock and boulder, rugose'}], 'categorical_classes':[]}
        modern={'substrate_definitions':[],'categorical_classes':[{'code':'3','label':'hard and rugose boulder, bedrock seafloor'}]}
        soft={'substrate_definitions':[],'categorical_classes':[{'code':'3','label':'soft sediment'}]}
        self.assertTrue(context.hard_class_review(legacy))
        self.assertTrue(context.hard_class_review(modern))
        self.assertFalse(context.hard_class_review(soft))

    def test_mpa_snapshot_must_be_complete_and_recent(self):
        with self.assertRaises(ValueError):
            context.mpa_union({'sources':{'mpas':{'status':'ok','data_retrieved_at':datetime.now(timezone.utc).isoformat(),
                                                  'data':{'geojson':{'type':'FeatureCollection','features':[]}}}}})

    def test_shards_by_california_coast_without_dropping_features(self):
        feature={'type':'Feature','properties':{'id':'x'},'geometry':{'type':'Polygon','coordinates':[[[-123,40.5],[-122,40.5],[-122,40.6],[-123,40.6],[-123,40.5]]]}}
        result=splitter.split({'scope':'generalized-statewide-usgs-hard-bottom-context','features':[feature]},
                              {'regions':[{'id':'northern','latitude':[40,42]},{'id':'central','latitude':[34,40]}]})
        self.assertEqual(len(result['northern']['features']),1)
        self.assertEqual(result['central']['features'],[])


if __name__=='__main__':unittest.main()
