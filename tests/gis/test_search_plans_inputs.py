"""build_search_plans computes every published region before any write (RF0250-11)."""
import importlib.util,json,os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest import mock
from tests._support import ROOT
try:
 from shapely.geometry import shape
except ImportError:shape=None
SCRIPT=ROOT/'scripts/build_search_plans.py'
def load():
 spec=importlib.util.spec_from_file_location('build_search_plans_under_test',SCRIPT);mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod
SQUARE={'type':'Polygon','coordinates':[[[0.1,0.1],[0.4,0.1],[0.4,0.4],[0.1,0.4],[0.1,0.1]]]}


@unittest.skipIf(shape is None,'Optional native GIS tools unavailable')
class SearchPlanInputs(unittest.TestCase):
 def setUp(self):
  self.mod=load();self.root=Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,self.root)
  self.write('catalog/search-methods.json',{'method':'m','reviewed_at':'2026-11-01','species':{'rockfish':{'habitat_kinds':['rock']}}})
  self.write('catalog/ecology/eco.json',{'profiles':{'rockfish':{'habitat':'reef'}}})
  for rid in ('a','b'):self.region(rid)
 def write(self,rel,doc):
  p=self.root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(doc if isinstance(doc,str) else json.dumps(doc));return p
 def region(self,rid,status='published',**extra):
  doc={'id':rid,'status':status,'fishing_bounds':[0,0,1,1],'species':['rockfish'],'ecology_profile':'eco',
       'assets':{'survey_habitat':f'regions/{rid}/habitat.json'},**extra}
  self.write(f'regions/{rid}/region.json',json.dumps(doc,indent=2)+'\n')
  self.write(f'dist/regions/{rid}/habitat.json',{'type':'FeatureCollection','features':[
   {'type':'Feature','geometry':SQUARE,'properties':{'id':rid+'-1','habitat_kind':'rock'}}]})
 def snapshot(self):
  return {str(p.relative_to(self.root)):p.read_bytes() for p in sorted(self.root.rglob('*')) if p.is_file()}
 def assert_refused(self,*needles):
  before=self.snapshot()
  with self.assertRaises(self.mod.PlanInputError) as ctx:self.mod.build(self.root)
  msg=str(ctx.exception);self.assertTrue(msg.startswith('b: '),msg)
  for n in needles:self.assertIn(n,msg)
  self.assertEqual(self.snapshot(),before);self.assertFalse((self.root/'dist/regions/a/search-plans.json').exists())
  return msg
 def test_missing_asset_named_with_region_nothing_written(self):
  (self.root/'dist/regions/b/habitat.json').unlink()
  self.assert_refused('dist/regions/b/habitat.json missing')
 def test_invalid_json_asset_unreadable(self):
  self.write('dist/regions/b/habitat.json','{not json')
  self.assert_refused('dist/regions/b/habitat.json unreadable (JSONDecodeError)')
 def test_missing_ecology_profile_keeps_existing_message(self):
  r=json.loads((self.root/'regions/b/region.json').read_text());del r['ecology_profile'];self.write('regions/b/region.json',r)
  self.assert_refused('Published regional search plans need a reviewed ecology profile')
 def test_species_missing_from_profile(self):
  r=json.loads((self.root/'regions/b/region.json').read_text());r['species']=['rockfish','lingcod']
  self.write('regions/b/region.json',r)
  self.write('catalog/search-methods.json',{'method':'m','reviewed_at':'2026-11-01','species':{'rockfish':{'habitat_kinds':['rock']},'lingcod':{'habitat_kinds':['rock']}}})
  self.assert_refused('Missing regional ecological profile lingcod')
 def test_unreadable_region_file_named_by_folder(self):
  self.write('regions/b/region.json','[')
  self.assert_refused('regions/b/region.json unreadable (JSONDecodeError)')
 def test_draft_with_broken_assets_is_skipped(self):
  self.region('c',status='draft');(self.root/'dist/regions/c/habitat.json').unlink()
  self.mod.build(self.root)
  self.assertFalse((self.root/'dist/regions/c/search-plans.json').exists())
  for rid in ('a','b'):self.assertTrue((self.root/f'dist/regions/{rid}/search-plans.json').exists())
 def test_good_tree_written_stable_and_no_temp_left(self):
  self.mod.build(self.root);first=self.snapshot()
  for rid in ('a','b'):
   out=json.loads((self.root/f'dist/regions/{rid}/search-plans.json').read_text())
   self.assertEqual((out['region_id'],len(out['features']),list(out['profiles'])),(rid,1,['rockfish']))
   r=json.loads((self.root/f'regions/{rid}/region.json').read_text())
   self.assertEqual(r['assets']['search_plans'],f'regions/{rid}/search-plans.json')
  stat=(self.root/'regions/a/region.json').stat().st_mtime_ns
  self.mod.build(self.root);self.assertEqual(self.snapshot(),first)
  self.assertEqual((self.root/'regions/a/region.json').stat().st_mtime_ns,stat)
  self.assertEqual(list(self.root.rglob('*.tmp')),[])
 def test_write_phase_failure_propagates_first_target_complete(self):
  real=os.replace;calls=[]
  def flaky(src,dst):
   calls.append(dst)
   if len(calls)==2:raise OSError('disk full')
   return real(src,dst)
  with mock.patch.object(self.mod.os,'replace',side_effect=flaky):
   with self.assertRaises(OSError):self.mod.build(self.root)
  self.assertEqual(Path(calls[1]),self.root/'dist/regions/b/search-plans.json')
  self.assertEqual(json.loads((self.root/'dist/regions/a/search-plans.json').read_text())['region_id'],'a')
  self.assertFalse((self.root/'dist/regions/b/search-plans.json').exists())
 def test_cli_broken_tree_one_stderr_line_exit_1(self):
  self.write('scripts/build_search_plans.py',SCRIPT.read_text());(self.root/'dist/regions/b/habitat.json').unlink()
  before=self.snapshot()
  run=subprocess.run([sys.executable,str(self.root/'scripts/build_search_plans.py')],capture_output=True,text=True,cwd=self.root)
  self.assertEqual(run.returncode,1);self.assertEqual(run.stdout,'')
  lines=run.stderr.splitlines();self.assertEqual(len(lines),1,run.stderr)
  self.assertTrue(lines[0].startswith('search plans not built: b: '),lines[0])
  self.assertEqual(self.snapshot(),before)
if __name__=='__main__':unittest.main()
