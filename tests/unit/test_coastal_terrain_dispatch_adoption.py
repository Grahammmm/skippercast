import sys,json,tempfile,unittest
from pathlib import Path
from contextlib import nullcontext
from unittest.mock import MagicMock,patch

import skippercast.coastal.coordinator.store as mod
from skippercast.coastal.coordinator.store import Store
class FinishProof(unittest.TestCase):
 def _finish(self,mutation=None):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);job={'job_id':'job:synthetic','stage':'render','segment_id':'seg:3310:0:0:5000','code_sha':'a'*64,'deps_sha':'b'*64,'params_sha':'c'*64,'input_manifest_sha':'d'*64,'lease_token':'token','params':{'terrain_root':str(root)},'input_manifest':{'contract':'coastal-terrain-only-input-v1','path':'input.json'},'budget':{'wall_s':120,'bytes':1024,'requests':0}}
   geography={'segment_id':job['segment_id'],'region':'synthetic-geographic-region'}
   stored={'state':'running','record_json':json.dumps(job),'attempts':1,'max_attempts':1,'result_sha':None,'stage':'render'}
   st=Store.__new__(Store);st.root=root;st.clock=lambda:100.;st.policy={'max_attempts':1};st.db=MagicMock()
   def execute(sql,*args):
    cursor=MagicMock()
    if 'FROM segments' in sql:cursor.fetchone.return_value=[json.dumps(geography)]
    else:cursor.fetchone.return_value=([stored['record_json']] if sql.startswith('SELECT record_json') else stored)
    return cursor
   st.db.execute.side_effect=execute;st.transaction=lambda:nullcontext();st._lease=MagicMock(return_value=stored);st.event=MagicMock();st._progress=MagicMock();st.charge=MagicMock();st.budget_for=MagicMock()
   result=dict(job,schema='coastal-stage-result-v1',state='done',holds=[],artifacts=[{'path':'render.json','contract':'coastal-terrain-only-render-v1','sha256':'e'*64,'bytes':1}],usage={'wall_s':1,'bytes':0,'requests':0},provenance={'libs':{'python':'synthetic'},'synthetic':False})
   result['artifact']=result['artifacts'][0];result['terrain_only_context_digest']='f'*64
   manifest={'schema':'coastal-terrain-only-input-v1','segment_id':job['segment_id'],'scope':'private-terrain-only'}
   rendered={'schema':'coastal-terrain-only-render-v1','ready':True,'publication_prohibited':True,'source_accessed':False,'imagery_used':False,'artifacts':[]}
   from skippercast.coastal.handoff.common import ref
   for name in ['mesh.json','preview.png']:(root/name).write_bytes(b'synthetic')
   rendered['artifacts']=[ref(root,root/name,'synthetic-test-artifact') for name in ['mesh.json','preview.png']]
   if mutation:mutation(result,manifest,rendered)
   for name,data in [('result.json',result),('input.json',manifest),('render.json',rendered)]: (root/name).write_text(json.dumps(data))
   def verify(root_,reference,*args,**kwargs):return root/reference['path']
   from skippercast.coastal.render import terrain_only
   with patch.object(mod,'verify_ref',side_effect=verify),patch.object(terrain_only,'verify',return_value={'ready':True}),patch.object(terrain_only,'context',return_value='f'*64),patch.object(terrain_only,'preview',return_value=rendered):
    self.assertTrue(st.finish(job['job_id'],'token',{'path':'result.json','sha256':'e'*64,'bytes':1},settle_budget=True))
   self.assertEqual(st.budget_for.call_args.args[0],geography['region'])
 def test_decoded_job_preserves_geographic_region_for_settlement(self):self._finish()
 def test_private_publication_guard(self):
  with self.assertRaisesRegex(ValueError,'private|terrain-only'):self._finish(lambda r,m,o:o.update(publication_prohibited=False))
 def test_context_digest_guard(self):
  with self.assertRaisesRegex(ValueError,'context mismatch'):self._finish(lambda r,m,o:r.update(terrain_only_context_digest='0'*64))
 def test_unknown_render_schema_guard(self):
  with self.assertRaisesRegex(ValueError,'terrain-only'):self._finish(lambda r,m,o:o.update(schema='unknown'))
 def test_output_root_guard(self):
  with self.assertRaises(ValueError):self._finish(lambda r,m,o:o['artifacts'][0].update(path='../escape.json'))
 def test_wrong_segment_refused_without_geometry_or_queue(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);doc={'schema':'coastal-terrain-only-input-v1','segment_id':'seg:3310:5000:0:5000'};(root/'input.json').write_text(json.dumps(doc))
   from skippercast.coastal.handoff.common import ref
   st=Store.__new__(Store);st.root=root;st.clock=lambda:100.;st.db=MagicMock();st.db.execute.return_value.fetchone.return_value=[json.dumps({'segment_id':'seg:3310:0:0:5000'})]
   ok,holds=st._evidence_gate({'stage':'render','segment_id':'seg:3310:0:0:5000','input_manifest':ref(root,root/'input.json','coastal-terrain-only-input-v1'),'params':{}})
   self.assertFalse(ok);self.assertIn('segment_mismatch',holds)
 def test_actual_reference_hash_guard(self):
  with tempfile.TemporaryDirectory() as tmp:
   from skippercast.coastal.coordinator.stages import verify_ref
   from skippercast.coastal.handoff.common import ref
   root=Path(tmp);p=root/'artifact.json';p.write_text('{}');r=ref(root,p,'synthetic');p.write_text('{ }')
   with self.assertRaises(ValueError):verify_ref(root,r)
 def test_actual_reference_root_guard(self):
  with tempfile.TemporaryDirectory() as tmp:
   from skippercast.coastal.coordinator.stages import verify_ref
   with self.assertRaises(ValueError):verify_ref(Path(tmp),{'path':'../escape','sha256':'a'*64,'bytes':1})
if __name__=='__main__':unittest.main()
