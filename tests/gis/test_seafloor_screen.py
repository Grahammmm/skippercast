"""Offline whole-polygon legal-screen, expiry and source-change regressions."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import hashlib
from pathlib import Path
import tempfile
import unittest

from pyproj import Transformer, Geod
from shapely.geometry import box, mapping, Point, Polygon, MultiPolygon, shape
from shapely.ops import transform

from skippercast.seafloor.screen import load_snapshot, screen_candidates, input_identity, exclusion_polygon, VERSION
from skippercast.seafloor.screen_sources import security_layer
from skippercast.seafloor.io import sha256
from skippercast.platform.contracts import REPO, atomic_json

NOW = datetime(2026, 9, 28, tzinfo=timezone.utc)
TO_GEO = Transformer.from_crs(3310, 4326, always_xy=True).transform


def geo(x, y, size=50):
    return mapping(transform(TO_GEO, box(x, y, x+size, y+size)))


def candidate(geometry=None):
    return {'type': 'Feature', 'geometry': geometry or geo(0, 0), 'properties': {
        'id': 'fixture', 'tier': 1, 'hold_reasons': ['legal-screen-pending'],
        'terrain': {'grade': 'B'}, 'fit': {'lingcod': 3}, 'resolution_m': 2,
        'depth_min_ft': 90, 'depth_max_ft': 110, 'vertical_datum': 'unknown'}}


def state(exclusion=None):
    return {'version': VERSION, 'status': 'ready', 'reasons': [], 'snapshot': NOW.isoformat(),
            'snapshot_sha256': 'a'*64, 'scope': geo(-1000, -1000, 2000),
            'layers': [{'id': name, 'features': [{'geometry': exclusion or geo(300, 300)}]}
                       for name in ('cdfw-mpa', 'noaa-federal', 'security')]}


class ScreenTests(unittest.TestCase):
    def test_nested_source_components_union_without_removing_restricted_area(self):
        raw = MultiPolygon([box(-122, 35, -121, 36), box(-121.8, 35.2, -121.7, 35.3)])
        self.assertFalse(raw.is_valid)
        fixed = exclusion_polygon(mapping(raw))
        for part in raw.geoms:
            self.assertTrue(fixed.covers(part))
        self.assertEqual(fixed.area, 1)
        with self.assertRaisesRegex(ValueError, 'Invalid screen polygon'):
            exclusion_polygon(mapping(Polygon([(-122,35),(-121,36),(-122,36),(-121,35),(-122,35)])))

    def test_whole_polygon_overlap_not_only_centroid_and_boundary_touch(self):
        for exclusion in (geo(49, 0), geo(50, 0)):
            passed, held, summary = screen_candidates({'features': [candidate()]}, state(exclusion))
            self.assertEqual(passed['features'], [])
            self.assertIn('overlap-cdfw-mpa', held['features'][0]['properties']['hold_reasons'])
            self.assertEqual(summary['tier2_km2'], 0)

    def test_mpa_hole_is_preserved_and_pass_is_nominal_never_verified(self):
        ring = Polygon([(-100,-100),(150,-100),(150,150),(-100,150),(-100,-100)],
                       [[(-10,-10),(-10,60),(60,60),(60,-10),(-10,-10)]])
        s = state(mapping(transform(TO_GEO, ring)))
        passed, held, summary = screen_candidates({'features': [candidate()]}, s)
        self.assertFalse(held['features'])
        p = passed['features'][0]['properties']
        self.assertEqual(p['tier'], 2)
        self.assertTrue(p['exportable'])
        self.assertIn('unknown', p['label'])
        self.assertAlmostEqual(summary['tier2_km2'], .0025, places=8)
        # Duplicate polygons cannot double the footprint.
        _, _, twice = screen_candidates({'features': [candidate(), candidate()]}, s)
        self.assertEqual(summary['tier2_km2'], twice['tier2_km2'])

    def test_no_snapshot_unknown_grade_outside_scope_and_invalid_depth_hold(self):
        c = candidate()
        for change in ({'terrain': 'unknown'}, {'depth_max_ft': 301}, {'fit': {'lingcod': 'unknown'}}):
            altered = deepcopy(c); altered['properties'].update(change)
            passed, held, _ = screen_candidates({'features': [altered]}, state())
            self.assertFalse(passed['features']); self.assertTrue(held['features'])
        passed, held, _ = screen_candidates({'features': [candidate(geo(5000,5000))]}, state())
        self.assertIn('screen-outside-coverage', held['features'][0]['properties']['hold_reasons'])
        with tempfile.TemporaryDirectory() as directory:
            missing = load_snapshot(Path(directory), 'fixture', NOW)
        passed, held, _ = screen_candidates({'features': [c]}, missing)
        self.assertEqual(held['features'][0]['properties']['screen']['status'], 'held')

    def fixture(self, root):
        folder=root/'var/seafloor/screen'; folder.mkdir(parents=True)
        (root/'catalog').mkdir()
        atomic_json(root/'catalog/seafloor-screen.json', {'fixture': True})
        data={'version':VERSION,'checked_at':NOW.isoformat(),'reviewed_reaches':['fixture'],
              'scope':geo(-1000,-1000,2000),'policy_sha256':sha256(root/'catalog/seafloor-screen.json'),'layers':{}}
        for name in ('cdfw-mpa','noaa-federal','security'):
            p=folder/(name+'.json'); atomic_json(p,{'type':'FeatureCollection','features':[{'geometry':geo(300,300)}]})
            data['layers'][name]={'file':p.name,'sha256':sha256(p),'status':'ok','feature_count':1,
                'source_url':'https://example.gov/fixture','checked_at':NOW.isoformat(),
                'evidence':{'up_to_date_as_of':'2026-09-24'}}
        atomic_json(folder/'snapshot.json', data)
        return folder,data

    def test_expiry_future_dates_partial_inventory_failure_and_byte_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); folder,data=self.fixture(root)
            good=load_snapshot(root,'fixture',NOW)
            self.assertEqual(good['status'],'ready')
            expired=load_snapshot(root,'fixture',datetime(2026,11,5,tzinfo=timezone.utc))
            self.assertEqual(expired['status'],'held')
            self.assertNotEqual(input_identity(good),input_identity(expired))
            self.assertEqual(load_snapshot(root,'fixture',datetime(2026,9,1,tzinfo=timezone.utc))['status'],'held')
            self.assertIn('screen-scope-unreviewed',load_snapshot(root,'new-reach',NOW)['reasons'])
            atomic_json(folder/'refresh-failure.json',{'error':'timeout'})
            self.assertIn('screen-refresh-failed',load_snapshot(root,'fixture',NOW)['reasons'])
            (folder/'refresh-failure.json').unlink()
            (folder/'cdfw-mpa.json').write_text('{}')
            self.assertIn('screen-invalid',load_snapshot(root,'fixture',NOW)['reasons'])
            data['layers'].pop('security'); atomic_json(folder/'snapshot.json',data)
            self.assertIn('screen-invalid',load_snapshot(root,'fixture',NOW)['reasons'])

    def test_changed_policy_invalidates_snapshot_and_changed_law_requires_review(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); self.fixture(root)
            atomic_json(root/'catalog/seafloor-screen.json', {'changed':True})
            self.assertIn('screen-policy-changed',load_snapshot(root,'fixture',NOW)['reasons'])
        config={'security_zones':[{'section':'165.1155','reviewed_xml_sha256':'0'*64}]}
        def getter(url):
            if url.endswith('titles'):
                return b'{"titles":[{"number":33,"up_to_date_as_of":"2026-09-24"}]}'
            return b'<DIV8 N="165.1155">Changed law</DIV8>'
        with self.assertRaisesRegex(ValueError,'text changed'):
            security_layer(config,getter)

    def test_reviewed_security_circle_preserves_nad83_yards_and_margin(self):
        body=b'<DIV8 N="165.1155">Offline boundary fixture</DIV8>'
        lon,lat=-120.8563888889,35.2063888889
        zone={'id':'fixture','section':'165.1155','reviewed_xml_sha256':hashlib.sha256(body).hexdigest(),
              'geometry_method':'nad83-geodesic-circle','center_nad83':[lon,lat],'radius_m':1828.8}
        def getter(url):
            return (b'{"titles":[{"number":33,"up_to_date_as_of":"2026-09-24"}]}'
                    if url.endswith('titles') else body)
        layer,receipt=security_layer({'security_zones':[zone]},getter)
        self.assertEqual(receipt['up_to_date_as_of'],'2026-09-24')
        back=Transformer.from_crs(4326,4269,always_xy=True)
        distances=[Geod(ellps='GRS80').inv(lon,lat,*back.transform(*point))[2]
                   for point in shape(layer['features'][0]['geometry']).exterior.coords]
        self.assertAlmostEqual(min(distances),1829.8,places=4)
        self.assertAlmostEqual(max(distances),1829.8,places=4)

    def test_coastal_zone_envelope_covers_published_vertices_and_fails_on_change(self):
        body=('''<DIV8 N="334.1130"><P>(iv) Zone 4. Beginning at the mouth of the
            Santa Ynez River latitude 34°41′50″, longitude 120°36′20″; thence
            to latitude 34°41′50″, longitude 120°40′12″; thence to latitude
            34°35′12″; longitude 120°42′45″; thence latitude 34°34′32″,
            longitude 120°42′15″, thence to Point Arguello, latitude
            34°34′32″, longitude 120°39′03″.</P></DIV8>''').encode()
        config=json.loads((REPO/'catalog/seafloor-screen.json').read_text())
        zone=next(z for z in config['security_zones'] if z['id']=='vandenberg-zone-4').copy()
        zone['reviewed_xml_sha256']=hashlib.sha256(body).hexdigest()
        def getter(url):
            return (b'{"titles":[{"number":33,"up_to_date_as_of":"2026-09-28"}]}'
                    if url.endswith('titles') else body)
        layer,receipt=security_layer({'security_zones':[zone]},getter)
        boundary=shape(layer['features'][0]['geometry'])
        self.assertTrue(boundary.is_valid)
        self.assertEqual(layer['features'][0]['properties']['datum'],'unknown')
        self.assertEqual(layer['features'][0]['properties']['planning_margin_m'],250)
        for lat,lon in ((34+41/60+50/3600,-(120+36/60+20/3600)),
                        (34+35/60+12/3600,-(120+42/60+45/3600)),
                        (34+34/60+32/3600,-(120+39/60+3/3600))):
            self.assertTrue(boundary.covers(Point(lon,lat)))
        self.assertTrue(boundary.covers(Point(-120.51,34.64)))
        self.assertFalse(boundary.intersects(Point(-120.9,34.64)))
        self.assertEqual(receipt['sections'][0]['sha256'],zone['reviewed_xml_sha256'])
        regional={'version':VERSION,'status':'ready','reasons':[],
                  'snapshot':NOW.isoformat(),'snapshot_sha256':'a'*64,
                  'scope':mapping(box(-121.3,34.48,-120.5,35.65)),
                  'layers':[{'id':name,'features':layer['features'] if name=='security'
                             else [{'geometry':mapping(box(-122.5,35.8,-122.4,35.9))}]}
                            for name in ('cdfw-mpa','noaa-federal','security')]}
        inside=candidate(mapping(box(-120.651,34.639,-120.649,34.641)))
        outside=candidate(mapping(box(-120.901,34.639,-120.899,34.641)))
        passed,held,_=screen_candidates({'features':[inside,outside]},regional)
        self.assertEqual(len(passed['features']),1)
        self.assertEqual(len(held['features']),1)
        self.assertIn('overlap-security',held['features'][0]['properties']['hold_reasons'])
        changed=deepcopy(zone)
        changed['expected_pairs_dms'][2][5]=46
        with self.assertRaisesRegex(ValueError,'coordinates changed'):
            security_layer({'security_zones':[changed]},getter)


if __name__ == '__main__':
    unittest.main()
