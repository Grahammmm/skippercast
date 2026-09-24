"""Scientific failure fixtures for the optional original-BAG compiler."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest

from skippercast.platform.bottom_targets import (bag_metadata, cells_qualified,
    fresh_closures, source_url_allowed, vr_transform, terrain_metrics, contained_outline, target_prefix)

try:
    import numpy as np
    from affine import Affine
    from shapely.geometry import box, Polygon
    HAVE_GIS = True
except ImportError:
    HAVE_GIS = False


def metadata(vertical='VERT_CS["MLLW",VERT_DATUM["MLLW",2000]]',uncertainty="productUncert",survey="H13323"):
    return f'''<root><CharacterString>PROJCS["NAD83 / UTM zone 11N"]</CharacterString>
    <CharacterString>{vertical}</CharacterString><CharacterString>{survey}</CharacterString>
    <BAG_VertUncertCode>{uncertainty}</BAG_VertUncertCode>
    <beginPosition>2019-10-04T00:00:00</beginPosition><endPosition>2019-10-21T00:00:00</endPosition></root>'''


class MetadataAndClosureTests(unittest.TestCase):
    def test_named_datum_and_uncertainty_retained(self):
        result=bag_metadata(metadata(),"H13323")
        self.assertEqual(result["vertical_datum"],"MLLW")
        self.assertEqual(result["uncertainty_type"],"productUncert")
        self.assertEqual(len(result["metadata_sha256"]),64)
        self.assertEqual(bag_metadata(metadata('VERT_CS["MLLW depth",VERT_DATUM["MLLW depth",2005]]'),"H13323")["vertical_datum"],"MLLW")

    def test_unknown_datum_and_misleading_title_held(self):
        for v in ['VERT_CS["unknown",VERT_DATUM["unknown",2000]]','VERT_CS["MLLW",VERT_DATUM["ellipsoid",2000]]',
                  'VERT_CS["MLLW depth",VERT_DATUM["MLLW ellipsoid",2000]]']:
            with self.subTest(v=v),self.assertRaises(ValueError):bag_metadata(metadata(v),"H13323")

    def test_identity_and_uncertainty_required(self):
        for xml in [metadata(survey="H13093"),metadata(uncertainty="unknown")]:
            with self.assertRaises(ValueError):bag_metadata(xml,"H13323")

    def test_dtd_rejected(self):
        with self.assertRaises(ValueError):bag_metadata('<!DOCTYPE root>'+metadata(),"H13323")

    def test_closure_freshness_identity_and_completeness(self):
        now=datetime(2026,9,22,18,tzinfo=timezone.utc)
        polygon={"geometry":{"type":"Polygon","coordinates":[[[-119,33],[-119,34],[-118,34],[-118,33],[-119,33]]]}}
        d={"region_id":"southern-california","checked_at":now.isoformat(),"features":[polygon]*8}
        fresh_closures(d,minimum_features=8,now=now)
        for change in [{"checked_at":(now-timedelta(hours=37)).isoformat()},
                       {"checked_at":(now+timedelta(minutes=1)).isoformat()},
                       {"region_id":"morro-bay"},{"features":[]}]:
            with self.subTest(change=change),self.assertRaises(ValueError):
                fresh_closures({**d,**change},minimum_features=8,now=now)

    def test_nonpolygon_or_incomplete_closure_geometry_held(self):
        now=datetime(2026,9,22,18,tzinfo=timezone.utc)
        for geometry in [{"type":"Point","coordinates":[-119,34]},
                         {"type":"Polygon","coordinates":[[[-119,33],[-119,34],[-118,34]]]},
                         {"type":"MultiPolygon","coordinates":[]}]:
            d={"region_id":"southern-california","checked_at":now.isoformat(),"features":[{"geometry":geometry}]*8}
            with self.assertRaises(ValueError):fresh_closures(d,minimum_features=8,now=now)

    def test_target_prefix_is_explicit_and_portable(self):
        self.assertEqual(target_prefix({"target_prefix":"MONTEREY-Q"}),"MONTEREY-Q")
        for p in [None,"../X","lowercase","-BAD","A"*33]:
            with self.assertRaises(ValueError):target_prefix({"target_prefix":p})

    def test_source_urls_are_bounded_to_original_archive(self):
        self.assertTrue(source_url_allowed('https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/H12001-H14000/H13323/BAG/a.bag'))
        for url in ['http://data.ngdc.noaa.gov/platforms/ocean/nos/coast/a.bag',
                    'https://data.ngdc.noaa.gov.evil.test/platforms/ocean/nos/coast/a.bag',
                    'https://user:pass@data.ngdc.noaa.gov/platforms/ocean/nos/coast/a.bag',
                    'https://data.ngdc.noaa.gov/other/a.bag']:
            self.assertFalse(source_url_allowed(url))


@unittest.skipUnless(HAVE_GIS,"Optional GIS scientific environment is not installed")
class NativeQualificationTests(unittest.TestCase):
    def test_depth_includes_reported_uncertainty_and_planning_margin(self):
        a=np.array([-58.0,-59.0,-60.0,-20.0])
        u=np.array([.5,.5,.1,.5])
        self.assertEqual(cells_qualified(a,u,2).tolist(),[True,False,False,True])

    def test_missing_uncertainty_gaps_shoals_and_coarse_cells_are_not_promoted(self):
        a=np.array([-30,np.nan,1000000,-3,-30,-30,-30])
        u=np.array([.4,.4,.4,.4,np.nan,0,1.1])
        self.assertEqual(cells_qualified(a,u,4).tolist(),[True,False,False,False,False,False,False])
        self.assertFalse(cells_qualified(np.array([-30]),np.array([.4]),8).any())

    def test_shape_mismatch_and_invalid_policy_fail(self):
        with self.assertRaises(ValueError):cells_qualified(np.array([-30]),np.array([.4,.5]),2)
        with self.assertRaises(ValueError):cells_qualified(np.array([-30]),np.array([.4]),2,planning_margin_m=-1)

    def test_native_supergrid_origin_and_south_to_north_index(self):
        meta={"resolution_x":1,"resolution_y":1,"sw_corner_x":.45585936,"sw_corner_y":.45585936,"dimensions_y":48}
        a=vr_transform(237795.2099995,3747866.0999995,47.911719,47.911719,406,580,meta)
        # Independently observed GDAL BAG:H13323...:supergrid:406:580 bounds.
        self.assertAlmostEqual(a.c,265583.96287886,places=6)
        self.assertAlmostEqual(a.f,3767366.21377286,places=6)
        self.assertEqual(a.e,-1)

    def test_plain_slope_is_not_misclassified_as_complex_rock(self):
        x,y=np.meshgrid(np.arange(20)*4,np.arange(20)*4)
        z=-30-.1*x-.05*y
        result=terrain_metrics(x.ravel(),y.ravel(),z.ravel(),np.full(x.size,4),hard_area_m2=50000)
        self.assertAlmostEqual(result["plane_residual_rms_m"],0,places=3)
        self.assertEqual(result["score_components"]["complexity"],0)
        self.assertEqual(result["grade_thresholds"],{"A":75,"B":55})
        self.assertIsNone(result["catch_probability"])

    def test_target_outline_cannot_bridge_hole_or_unmeasured_gap(self):
        p=Polygon([(0,0),(200,0),(200,200),(0,200)],holes=[[(80,80),(120,80),(120,120),(80,120)]])
        p=p.difference(box(0,60,90,70))
        out=contained_outline(p,100)
        self.assertTrue(p.covers(out))
        self.assertFalse(out.intersects(box(85,85,115,115)))
        self.assertFalse(out.intersects(box(20,62,80,68)))


class ProducedReleaseTests(unittest.TestCase):
    def test_manifest_if_present_has_explicit_limits_and_original_sources(self):
        root=Path(__file__).resolve().parents[1]/"dist/regions/southern-california/qualified-bottom"
        if not (root/"manifest.json").exists():self.skipTest("Original BAG release not yet compiled")
        q=json.loads((root/"quality.json").read_text());a=json.loads((root/"atlas.json").read_text())
        self.assertFalse(q["claims"]["catch_calibrated"])
        self.assertFalse(q["claims"]["boulder_size_measured"])
        self.assertEqual(set(s["id"] for s in q["sources"]),{"NOAA-H13093","NOAA-H13323"})
        self.assertGreater(len(a["targets"]),0)
        for t in a["targets"]:
            self.assertLessEqual(t["qualification"]["max_depth_including_uncertainty_and_margin_ft"],200)
            self.assertLessEqual(max(t["native_resolution_range_m"]),4)
            self.assertIsNone(t["rating"]["catch_probability"])
            self.assertEqual(t["rating"]["grade_thresholds"],{"A":75,"B":55})
            self.assertEqual(t["habitat_grade"],"A" if t["habitat_score"]>=75 else "B" if t["habitat_score"]>=55 else "C")
            self.assertEqual(t["vertical_datum"],"MLLW")


if __name__=="__main__":unittest.main()
