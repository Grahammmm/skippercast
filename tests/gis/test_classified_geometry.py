"""Synthetic point contacts, holes and bounded native representation checks."""
from copy import deepcopy
import unittest
from unittest.mock import patch

from shapely.geometry import Polygon, box, mapping
from shapely import make_valid

from skippercast.seafloor import classified_geometry as cg
from skippercast.seafloor.screen import screen_candidates
from tests.gis.test_classified_habitat import candidate
from tests.gis.test_seafloor_screen import state, geo


def touching_hole():
    # Synthetic EPSG:3310 shape. Its triangular hole meets a shell at one point.
    x,y=50000,100000
    return Polygon([(x,y),(x+100,y),(x+100,y+100),(x,y+100)],
        [[(x,y+50),(x+25,y+100/3),(x+25,y+200/3),(x,y+50)]])


def inventory(native):
    geo,_=cg.represent(native)
    return ({'features':[{'geometry':mapping(geo),'properties':{'id':'synthetic'}}]},
            {'version':cg.VERSION,'crs':'EPSG:3310','features':[
                {'geometry':mapping(native),'properties':{'id':'synthetic'}}]})


class ClassifiedGeometryTests(unittest.TestCase):
    def test_valid_native_contact_hole_has_valid_faithful_representations(self):
        native=touching_hole()
        self.assertTrue(native.is_valid)
        self.assertFalse(cg.project(native,3310,4326).is_valid)
        with patch.object(cg,'make_valid',wraps=make_valid) as repair:
            geo,report=cg.represent(native)
        self.assertTrue(geo.is_valid)
        self.assertTrue(all(cg.operational(geo,crs).is_valid for crs in (3310,3857)))
        self.assertTrue(all(v['symmetric_difference_m2']<.002 for v in report.values()))
        self.assertTrue(repair.called)
        for call in repair.call_args_list:
            self.assertEqual(call.kwargs,{'method':'structure','keep_collapsed':False})
        # The native evidence and original hole are retained unchanged.
        self.assertEqual(len(native.interiors),1)
        self.assertFalse(cg.operational(geo,3310).covers(box(50010,100045,50015,100055)))

    def test_bound_rejects_hole_fill_translation_and_collapsed_or_invalid_native(self):
        native=touching_hole();geo,_=cg.represent(native)
        filled=cg.geographic(Polygon(native.exterior))
        with self.assertRaisesRegex(ValueError,'fidelity bound'):cg.fidelity(native,filled)
        from shapely.affinity import translate
        with self.assertRaisesRegex(ValueError,'fidelity bound'):cg.fidelity(native,translate(geo,xoff=.001))
        for bad in (Polygon([(0,0),(50,50),(0,50),(50,0),(0,0)]),box(0,0,0,0)):
            with self.assertRaisesRegex(ValueError,'Invalid classified polygon'):cg.represent(bad)
        # Even a valid result from a blanket repair is rejected if it fills the
        # native hole. Native comparison, rather than validity/area alone, gates it.
        with patch.object(cg,'make_valid',return_value=filled):
            with self.assertRaisesRegex(ValueError,'fidelity bound'):cg.represent(native)

    def test_pathological_hole_structure_retains_native_notch_linework_adds_area(self):
        shell=box(50000,100000,50100,100100)
        hole=box(50080,100040,50110,100060)
        native=shell.difference(hole)  # Valid synthetic notch; unchanged evidence.
        malformed=Polygon(shell.exterior,[hole.exterior])
        self.assertFalse(malformed.is_valid)
        raw=cg.project(malformed,3310,4326)
        faithful=cg.structure(raw)
        self.assertLess(cg.fidelity(native,faithful)['3310']['symmetric_difference_m2'],.002)
        linework=make_valid(raw)  # Default fills the portion outside the shell.
        with self.assertRaisesRegex(ValueError,'fidelity bound'):
            cg.fidelity(native,linework)

    def test_inventory_retains_ids_and_rejects_noncanonical_or_tampered_native(self):
        candidates,native=inventory(touching_hole())
        report=cg.verify_inventory(candidates,native)
        self.assertEqual(report['feature_count'],1)
        self.assertLess(report['union_symmetric_difference_m2'],.01)
        bad=deepcopy(candidates);bad['features'][0]['properties']['id']='split-id'
        with self.assertRaisesRegex(ValueError,'identity'):cg.verify_inventory(bad,native)
        bad=deepcopy(native);bad['features'][0]['geometry']=mapping(box(50000,100000,50100,100100))
        with self.assertRaisesRegex(ValueError,'canonical representation'):cg.verify_inventory(candidates,bad)
        bad=deepcopy(native);bad['crs']='EPSG:4326'
        with self.assertRaisesRegex(ValueError,'inventory'):cg.verify_inventory(candidates,bad)

    def test_current_restriction_screen_uses_original_native_boundary(self):
        c=candidate()
        # The display polygon passes this synthetic restriction. The unchanged
        # authoritative native boundary touches it, and therefore must be held.
        original=box(0,0,51,50)
        passed,held,_=screen_candidates({'features':[c]},state(geo(51,0)),
            native_geometries={c['properties']['id']:mapping(original)})
        self.assertFalse(passed['features'])
        self.assertIn('overlap-cdfw-mpa',held['features'][0]['properties']['hold_reasons'])
        passed,_,summary=screen_candidates({'features':[c]},state(),
            native_geometries={c['properties']['id']:mapping(original)})
        self.assertEqual(len(passed['features']),1)
        self.assertEqual(summary['classified_area_km2'],original.area/1e6)

    def test_native_inventory_union_bound_is_independent_of_per_feature_bound(self):
        candidates,native=inventory(touching_hole())
        with patch.object(cg,'MAX_UNION_DIFFERENCE_M2',0):
            with self.assertRaisesRegex(ValueError,'union'):cg.verify_inventory(candidates,native)
