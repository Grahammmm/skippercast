"""verify_inventory refuses a malformed inventory or candidate document by name.

Contract: a damaged native inventory or candidate collection is a refused
release input (named ValueError), never a bare KeyError/TypeError that reads as a
code defect, and never a non-list `features` that verifies with nothing checked.
"""
from copy import deepcopy
import unittest

from shapely.geometry import box, mapping

from skippercast.seafloor import classified_geometry as cg

INVENTORY_ERROR = 'Unreviewed classified native geometry inventory'
CANDIDATE_ERROR = 'Classified representation identity mismatch'


def valid_pair():
    """One synthetic 100 m EPSG:3310 square, represented by the module itself."""
    native = box(50000, 100000, 50100, 100100)
    geo, _ = cg.represent(native)
    candidates = {'features': [{'geometry': mapping(geo), 'properties': {'id': 'square'}}]}
    inventory = {'version': cg.VERSION, 'crs': 'EPSG:3310',
                 'features': [{'geometry': mapping(native), 'properties': {'id': 'square'}}]}
    return candidates, inventory


class InventoryRefusalTests(unittest.TestCase):
    def refused(self, candidates, inventory, message):
        with self.assertRaisesRegex(ValueError, message):
            cg.verify_inventory(candidates, inventory)

    def test_valid_one_polygon_inventory_still_verifies_with_the_same_report(self):
        # Unaffected control: the new guards must not refuse a well-formed pair.
        candidates, inventory = valid_pair()
        report = cg.verify_inventory(candidates, inventory)
        self.assertEqual(report['version'], cg.VERSION)
        self.assertEqual(report['feature_count'], 1)
        self.assertAlmostEqual(report['native_union_area_m2'], 10000.0, places=6)
        self.assertLessEqual(report['union_symmetric_difference_m2'], cg.MAX_UNION_DIFFERENCE_M2)
        self.assertLessEqual(report['max_symmetric_difference_m2'], cg.MAX_FEATURE_DIFFERENCE_M2)
        self.assertEqual(report['operational_crs'], ['EPSG:3310', 'EPSG:3857'])
        self.assertEqual(report['max_feature_difference_m2'], .002)
        self.assertEqual(report['max_union_difference_m2'], .01)
        self.assertEqual(set(report), {
            'version', 'runtime', 'feature_count', 'native_union_area_m2',
            'union_symmetric_difference_m2', 'max_symmetric_difference_m2', 'operational_crs',
            'max_feature_difference_m2', 'max_union_difference_m2'})

    def test_empty_valid_inventory_is_unchanged(self):
        # Guards against over-refusing: an honest empty list is not a damaged document.
        report = cg.verify_inventory({'features': []},
                                     {'version': cg.VERSION, 'crs': 'EPSG:3310', 'features': []})
        self.assertEqual(report['feature_count'], 0)

    def test_existing_named_refusals_are_unchanged(self):
        candidates, inventory = valid_pair()
        for key, value in (('crs', 'EPSG:4326'), ('version', 'other')):
            with self.subTest(key):
                self.refused(candidates, {**inventory, key: value}, INVENTORY_ERROR)
        renamed = deepcopy(candidates)
        renamed['features'][0]['properties']['id'] = 'other'
        self.refused(renamed, inventory, CANDIDATE_ERROR)
        claim = deepcopy(candidates)
        claim['features'][0]['properties']['area_ha'] = 2
        self.refused(claim, inventory, 'native area claim changed')

    def test_malformed_inventory_document_is_refused_by_name(self):
        # Bug caught: bare KeyError/TypeError, or a non-list `features` (e.g. 'x', None, a dict)
        # treated as an empty sequence so the release verifies with nothing checked.
        candidates, inventory = valid_pair()
        feature = inventory['features'][0]
        cases = {
            'inventory None': None,
            'inventory list': [],
            'inventory string': 'x',
            'no features': {'crs': 'EPSG:3310', 'version': cg.VERSION},
            'features string': {**inventory, 'features': 'x'},
            'features None': {**inventory, 'features': None},
            'features dict': {**inventory, 'features': {'0': feature}},
            'features tuple': {**inventory, 'features': (feature,)},
            'feature None': {**inventory, 'features': [None]},
            'feature string': {**inventory, 'features': ['square']},
            'no properties': {**inventory, 'features': [{'geometry': feature['geometry']}]},
            'properties None': {**inventory, 'features': [{**feature, 'properties': None}]},
            'properties list': {**inventory, 'features': [{**feature, 'properties': ['square']}]},
            'no id': {**inventory, 'features': [{**feature, 'properties': {}}]},
            'unhashable id': {**inventory, 'features': [{**feature, 'properties': {'id': ['a']}}]},
            'no geometry': {**inventory, 'features': [{'properties': {'id': 'square'}}]},
        }
        for name, bad in cases.items():
            with self.subTest(name):
                self.refused(candidates, bad, INVENTORY_ERROR)

    def test_malformed_candidate_document_is_refused_by_name(self):
        # Bug caught: a null/featureless candidate collection or a damaged candidate feature
        # surfacing as TypeError/KeyError, or `features: 'x'` verifying as no candidates.
        candidates, inventory = valid_pair()
        feature = candidates['features'][0]
        cases = {
            'candidates None': None,
            'candidates list': [],
            'candidates string': 'x',
            'no features': {},
            'features string': {'features': 'x'},
            'features None': {'features': None},
            'features dict': {'features': {'0': feature}},
            'feature None': {'features': [None]},
            'feature string': {'features': ['square']},
            'no properties': {'features': [{'geometry': feature['geometry']}]},
            'properties None': {'features': [{**feature, 'properties': None}]},
            'no id': {'features': [{**feature, 'properties': {}}]},
            'unhashable id': {'features': [{**feature, 'properties': {'id': ['a']}}]},
            'no geometry': {'features': [{'properties': {'id': 'square'}}]},
        }
        for name, bad in cases.items():
            with self.subTest(name):
                self.refused(bad, inventory, CANDIDATE_ERROR)

    def test_non_list_features_never_verify_as_empty_on_a_valid_counterpart(self):
        # Bug caught: an empty valid inventory paired with candidates whose `features` is a
        # string (or the reverse) passing because iteration over it yields nothing useful.
        empty = {'version': cg.VERSION, 'crs': 'EPSG:3310', 'features': []}
        self.refused({'features': 'x'}, empty, CANDIDATE_ERROR)
        self.refused({'features': ''}, empty, CANDIDATE_ERROR)
        self.refused({'features': []}, {**empty, 'features': ''}, INVENTORY_ERROR)


if __name__ == '__main__':
    unittest.main()
