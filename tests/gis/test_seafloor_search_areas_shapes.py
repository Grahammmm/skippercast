"""Misshaped search-area properties fail closed; tier is the integer 1 (RF0620-9)."""
from copy import deepcopy
import unittest

from skippercast.seafloor.search_areas import assessment, published_contract
from skippercast.seafloor.screen import screen_candidates
from tests.gis.test_seafloor_screen import state
from tests.gis.test_seafloor_search_areas import rough_patch


def admitted():
    passed, held, _ = screen_candidates({'features': [rough_patch()]}, state())
    assert not held['features']
    return passed['features'][0]['properties']


class MisshapedPropertiesTests(unittest.TestCase):
    def setUp(self):
        self.p = admitted()

    def changed(self, **values):
        p = deepcopy(self.p)
        p.update(values)
        return p

    def test_non_dict_properties_are_no_assessment(self):
        for bad in (None, [], 'x', 1, ['terrain']):
            self.assertIsNone(assessment(bad))

    def test_non_dict_properties_are_not_admitted(self):
        for bad in (None, [], 'x', 1, ['screen']):
            self.assertFalse(published_contract(bad))

    def test_valid_feature_still_admitted(self):
        self.assertTrue(published_contract(self.p))
        self.assertIs(type(self.p['tier']), int)
        self.assertEqual(self.p['screen']['status'], 'pass')

    def test_non_dict_screen_is_not_admitted(self):
        for screen in ('pass', ['pass'], None, 1, True):
            self.assertFalse(published_contract(self.changed(screen=screen)), screen)

    def test_screen_absent_or_not_pass_is_not_admitted(self):
        p = deepcopy(self.p)
        del p['screen']
        self.assertFalse(published_contract(p))
        self.assertFalse(published_contract(self.changed(screen={})))
        self.assertFalse(published_contract(self.changed(screen={'status': 'held'})))

    def test_tier_must_be_the_integer_one(self):
        for tier in (True, 1.0, '1', 2, 0, None, [1]):
            self.assertFalse(published_contract(self.changed(tier=tier)), repr(tier))
        p = deepcopy(self.p)
        del p['tier']
        self.assertFalse(published_contract(p))
        self.assertTrue(published_contract(self.changed(tier=1)))

    def test_hold_reasons_rule_unchanged(self):
        self.assertTrue(published_contract(self.changed(hold_reasons=[])))
        self.assertFalse(published_contract(self.changed(hold_reasons=['rights'])))

    def test_misshaped_input_not_mutated(self):
        p = self.changed(screen='pass', tier=True)
        before = deepcopy(p)
        self.assertFalse(published_contract(p))
        self.assertEqual(p, before)


if __name__ == '__main__':
    unittest.main()
