"""Compile regional search footprints from reviewed habitat, never invented circles.
Run in the existing GIS environment after a survey release, before platform.build.
Runtime conditions and ocean frames remain dated and are evaluated in the browser.
"""
import hashlib,json,os,sys
from pathlib import Path
from shapely.geometry import shape,mapping,box
from shapely.ops import unary_union
ROOT=Path(__file__).resolve().parents[1]
class PlanInputError(Exception):pass
def read(p):return json.loads(p.read_text())
def plan(root=ROOT):
 """Compute every published region's output in memory; any input problem raises one PlanInputError, nothing written."""
 def rd(p):
  try:return read(p)
  except FileNotFoundError:raise PlanInputError(f'{p.relative_to(root)} missing') from None
  except (OSError,ValueError) as e:raise PlanInputError(f'{p.relative_to(root)} unreadable ({type(e).__name__})') from None
 methods=rd(root/'catalog/search-methods.json');seen={}
 def one(path):
  r=rd(path);seen['id']=r.get('id') if isinstance(r,dict) else None
  if r['status']=='draft':return None
  features=[];receipts=[];closure=[];rejected=[]
  for key in ('protected_areas','closures'):
   if r['assets'].get(key):closure += [shape(f['geometry']) for f in rd(root/'dist'/r['assets'][key])['features']]
  excluded=unary_union(closure).buffer(.00002)
  extent=box(*r['fishing_bounds'])
  for key in ('survey_habitat','habitats','atlas'):
   if not r['assets'].get(key):continue
   src=root/'dist'/r['assets'][key];d=rd(src)
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
  ecology_id=r.get('ecology_profile') or r.get('intelligence',{}).get('ecology_profile')
  if not ecology_id:raise ValueError('Published regional search plans need a reviewed ecology profile')
  local=rd(root/'catalog/ecology'/(ecology_id+'.json'))['profiles']
  profiles={}
  for k in r['species']:
   if k not in local:raise ValueError('Missing regional ecological profile '+k)
   profiles[k]={**methods['species'][k],**{field:local[k][field] for field in ('habitat','timing','regional_notes','condition_response','depth_guidance') if field in local[k]}}
  out={'schema_version':1,'region_id':r['id'],'method':methods['method'],'reviewed_at':methods['reviewed_at'],
       'profiles':profiles,'features':features,'input_receipts':receipts,'rejected':rejected,
       'coverage_note':'Source footprints, not complete species distribution. No habitat is invented where a regional dataset is absent.'}
  if r.get('search_plans_note'):out['datum_correction_note']=r['search_plans_note']
  target=root/'dist/regions'/r['id']/'search-plans.json'
  plans='regions/'+r['id']+'/search-plans.json'
  # Rewrite the hand-maintained region file only when its content changes, so
  # its bytes (and the hashes other reviews pin) stay stable across rebuilds.
  changed=r['assets'].get('search_plans')!=plans
  if changed:r['assets']['search_plans']=plans
  return path,r,target,out,changed
 done=[]
 for path in sorted((root/'regions').glob('*/region.json')):
  seen['id']=None
  try:item=one(path)
  except (PlanInputError,ValueError) as e:raise PlanInputError(f"{seen['id'] or path.parent.name}: {e}") from None
  except (OSError,KeyError,TypeError) as e:raise PlanInputError(f"{seen['id'] or path.parent.name}: {path.relative_to(root)} unreadable ({type(e).__name__})") from None
  if item:done.append(item)
 return done
def put(target,text):temp=target.with_name(target.name+'.tmp');temp.write_text(text);os.replace(temp,target)
def build(root=ROOT):
 done=plan(root)
 for path,r,target,out,changed in done:put(target,json.dumps(out,separators=(',',':'))+'\n')
 for path,r,target,out,changed in done:
  if changed:put(path,json.dumps(r,indent=2,ensure_ascii=False)+'\n')
 for path,r,target,out,changed in done:print(r['id'],len(out['features']),'footprints;',len(out['profiles']),'species methods')
if __name__=='__main__':
 try:build()
 except PlanInputError as e:print(f'search plans not built: {e}',file=sys.stderr);sys.exit(1)
