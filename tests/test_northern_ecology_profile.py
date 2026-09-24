"""Northern ecology can be reviewed before live ocean-intelligence bindings."""
import copy
import unittest

from skippercast.platform.contracts import REPO, load_catalogs, load_region, validate_region


class NorthernEcologyProfileTests(unittest.TestCase):
    def test_three_draft_regions_have_scoped_species_dossiers(self):
        for ident in ('crescent-city', 'fort-bragg-point-arena', 'bodega-point-reyes'):
            with self.subTest(region=ident):
                region = load_region(ident)
                self.assertEqual(region['ecology_profile'], 'california-northern')
                self.assertNotIn('intelligence', region)
                validate_region(region, *load_catalogs(REPO), root=REPO)

    def test_profile_cannot_transfer_outside_reviewed_geography(self):
        region = copy.deepcopy(load_region('crescent-city'))
        region['fishing_bounds'] = [-124.6, 41.6, -124.1, 42.2]
        with self.assertRaisesRegex(ValueError, 'Ecology dossier does not cover'):
            validate_region(region, *load_catalogs(REPO), root=REPO)


if __name__ == '__main__':
    unittest.main()
