"""Compile regional search footprints from reviewed habitat, never invented circles.
Run in the existing GIS environment after a survey release, before platform.build.
Runtime conditions and ocean frames remain dated and are evaluated in the browser.
"""
import hashlib,json
from pathlib import Path
from shapely.geometry import shape,mapping,box
from shapely.ops import unary_union
ROOT=Path(__file__).resolve().parents[1]
def read(p):return json.loads(p.read_text())
def build(root=ROOT):
 methods=read(root/'catalog/search-methods.json')
 for path in sorted((root/'regions').glob('*/region.json')):
  r=read(path)
  if r['status']=='draft':continue
  features=[];receipts=[];closure=[];rejected=[]
  for key in ('protected_areas','closures'):
   if r['assets'].get(key):closure += [shape(f['geometry']) for f in read(root/'dist'/r['assets'][key])['features']]
  excluded=unary_union(closure).buffer(.00002)
  extent=box(*r['fishing_bounds'])
  for key in ('survey_habitat','habitats','atlas'):
   if not r['assets'].get(key):continue
   src=root/'dist'/r['assets'][key];d=read(src)
   receipts.append({'path':r['assets'][key],'sha256':hashlib.sha256(src.read_bytes()).hexdigest()})
   rows=d.get('features',d.get('areas',[]))
   for row in rows:
    p=row.get('properties',row);g=row.get('geometry');kind=p.get('habitat_kind','rock' if key=='atlas' else 'sediment')
    if not g or p.get('military_access')=='unverified':continue
    ids=p.get('species_ids',p.get('species',['reef'] if key=='atlas' else None))
    ids=[s for s in r['species'] if (s in ids if ids is not None else kind in methods['species'][s]['habitat_kinds'])]
    if not ids:continue
    geom=shape(g)
    if not geom.is_valid:
     rejected.append({'id':p.get('id'),'reason':'Invalid source geometry; withheld pending repair and review'});continue
    # Intersection/difference only: do not expand habitat into unknown water.
    geom=geom.intersection(extent).difference(excluded)
    if geom.is_empty or geom.geom_type not in ('Polygon','MultiPolygon'):continue
    point=geom.representative_point()
    features.append({'type':'Feature','geometry':mapping(geom),'properties':{
     'id':p['id'],'name':p.get('name',p.get('label',p['id'])),'species':ids,'habitat_kind':kind,
     'latitude':point.y,'longitude':point.x,'bounds':list(geom.bounds),
     'source_url':p.get('source_url'),'source_date':p.get('source_date',p.get('survey_year')),
     'depth_qualified':key=='atlas' or key=='habitats','depth_note':p.get('depth_note','Only the published survey footprint is shown; confirm depth with sonar.'),
     'source_id':p.get('source_id'),'fish_confirmed':False,'exportable':False}})
  local=read(root/'catalog/ecology'/(r['intelligence']['ecology_profile']+'.json'))['profiles']
  profiles={}
  for k in r['species']:
   if k not in local:raise ValueError('Missing regional ecological profile '+k)
   profiles[k]={**methods['species'][k],**{field:local[k][field] for field in ('habitat','timing','regional_notes','condition_response','depth_guidance') if field in local[k]}}
  out={'schema_version':1,'region_id':r['id'],'method':methods['method'],'reviewed_at':methods['reviewed_at'],
       'profiles':profiles,'features':features,'input_receipts':receipts,'rejected':rejected,
       'coverage_note':'Source footprints, not complete species distribution. No habitat is invented where a regional dataset is absent.'}
  target=root/'dist/regions'/r['id']/'search-plans.json';temp=target.with_suffix('.json.tmp');temp.write_text(json.dumps(out,separators=(',',':'))+'\n');temp.replace(target)
  r['assets']['search_plans']='regions/'+r['id']+'/search-plans.json';path.write_text(json.dumps(r,indent=2)+'\n')
  print(r['id'],len(features),'footprints;',len(out['profiles']),'species methods')
if __name__=='__main__':build()
