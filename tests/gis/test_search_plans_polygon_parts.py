"""Mixed clipped footprints keep their polygon parts (RF1940-7)."""
import importlib.util,json
import pytest
from tests._support import ROOT
shapely_geometry=pytest.importorskip('shapely.geometry')
box=shapely_geometry.box
shape=shapely_geometry.shape
SCRIPT=ROOT/'scripts/build_search_plans.py'
def load():
    spec=importlib.util.spec_from_file_location('bsp_polygon_parts',SCRIPT);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
def mp(*boxes):
    return {'type':'MultiPolygon','coordinates':[[list(map(list,box(*b).exterior.coords))] for b in boxes]}
def run(tmp_path,geom,closure=None):
    def w(rel,doc):
        p=tmp_path/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(doc))
    w('catalog/search-methods.json',{'method':'m','reviewed_at':'2026-11-01','species':{'rockfish':{'habitat_kinds':['rock']}}})
    w('catalog/ecology/eco.json',{'profiles':{'rockfish':{'habitat':'reef'}}})
    assets={'survey_habitat':'regions/a/habitat.json'}
    if closure:
        assets['closures']='regions/a/closures.json'
        w('dist/regions/a/closures.json',{'type':'FeatureCollection','features':[{'type':'Feature','geometry':closure,'properties':{}}]})
    w('regions/a/region.json',{'id':'a','status':'published','fishing_bounds':[0,0,1,1],'species':['rockfish'],'ecology_profile':'eco','assets':assets})
    w('dist/regions/a/habitat.json',{'type':'FeatureCollection','features':[{'type':'Feature','geometry':geom,'properties':{'id':'h1','habitat_kind':'rock'}}]})
    return load().plan(tmp_path)[0][3]['features']
def test_mixed_clip_retains_interior_polygon(tmp_path):
    f=run(tmp_path,mp((.1,.1,.4,.4),(1,.6,1.2,.8)))
    assert len(f)==1 and f[0]['properties']['id']=='h1'
    g=shape(f[0]['geometry'])
    assert g.geom_type=='Polygon' and g.equals(box(.1,.1,.4,.4)) and abs(g.area-.09)<1e-12
def test_multiple_polygon_parts_survive_mixed_clip(tmp_path):
    f=run(tmp_path,mp((.1,.1,.2,.2),(.5,.5,.6,.6),(1,.6,1.2,.8)))
    assert len(f)==1
    g=shape(f[0]['geometry']);p=f[0]['properties']
    assert g.geom_type=='MultiPolygon' and len(g.geoms)==2 and abs(g.area-.02)<1e-12
    assert p['bounds']==pytest.approx([.1,.1,.6,.6])
    assert g.contains(shapely_geometry.Point(p['longitude'],p['latitude']))
@pytest.mark.parametrize('b',[(1,.2,1.3,.4),(1,1,1.2,1.2),(2,2,3,3)])
def test_boundary_only_clip_remains_absent(tmp_path,b):
    assert run(tmp_path,mp(b))==[]
def test_ordinary_polygon_and_exclusions_are_unchanged(tmp_path):
    f=run(tmp_path,mp((.1,.1,.4,.4)),closure=box(.3,.0,.5,1).__geo_interface__)
    g=shape(f[0]['geometry'])
    assert f[0]['properties']['species']==['rockfish'] and f[0]['properties']['fish_confirmed'] is False
    assert g.geom_type=='Polygon' and g.disjoint(box(.3,0,.5,1)) and g.bounds[2]<.3
def test_invalid_source_geometry_still_rejected(tmp_path):
    bow={'type':'Polygon','coordinates':[[[.1,.1],[.4,.4],[.4,.1],[.1,.4],[.1,.1]]]}
    assert run(tmp_path,bow)==[]
