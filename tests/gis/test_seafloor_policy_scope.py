"""Offline source-policy-only regional selection and fallback tests."""
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from skippercast.seafloor import jobs
from skippercast.seafloor.jobs import (_policy_snapshot_valid, _push_policy_scope, regional_batch_rows,
                                       scoped_policy_change)


POLICY = 'catalog/classified-habitat-policy.json'
OTHER_INPUT = 'catalog/habitat-rules.json'


def policy(ident, reach_ids=None, neighbor_reaches=None, *, credit='USGS'):
    row = {'id': ident, 'credit': credit}
    if reach_ids is not None:
        row['reach_ids'] = reach_ids
    if neighbor_reaches is not None:
        row['neighbor_reaches'] = neighbor_reaches
    return row


def document(*rows):
    return {'schema_version': 1, 'profile': 'original-rugose-classified-area-v1',
            'sources': list(rows)}


def reviewed_policy(ident, reach_ids=None, neighbor_reaches=None, **changes):
    row = {'id': ident, 'depth_source_id': 'bathymetry-'+ident,
           'depth_source_sha256': 'a'*64, 'classification_source_id': 'class-'+ident,
           'classification_source_sha256': 'b'*64,
           'metadata_url': 'https://example.org/'+ident+'.xml',
           'metadata_sha256': 'c'*64, 'rugose_raw_codes': [3],
           'credit': 'Reviewed producer', 'release_license': 'public-domain-us-gov',
           'notice': 'Retain source limitations.', 'review_basis': 'Reviewed original metadata.',
           'reviewed_on': '2026-10-04'}
    if reach_ids is not None:
        row['reach_ids'] = reach_ids
    if neighbor_reaches is not None:
        row['neighbor_reaches'] = neighbor_reaches
    row.update(changes)
    return row


def inventory():
    return ([{'id': f'cambria-r0{i}', 'region': 'cambria-san-simeon', 'status': 'complete'}
             for i in range(1, 7)]
            + [{'id': 'morro-r01', 'region': 'morro-bay', 'status': 'complete'},
               {'id': 'morro-r02', 'region': 'morro-bay', 'status': 'complete'}])


class ClassifiedPolicyScopeTests(unittest.TestCase):
    def test_scoped_rollout_plans_only_affected_regions_but_all_processed_reaches(self):
        rows = inventory()
        seen=[]
        def fake_plan(_root,region,max_new,*,progress):
            seen.append((region,max_new))
            region_rows=[row for row in rows if row['region']==region]
            selected=[{'reach':row['id'],'region':region} for row in region_rows
                      if row['status']!='unassessed']
            return {'version':1,'scope':region,'physical_only':False,
                'survey_status_counts':{},'totals':{},'reaches':region_rows,
                'selected':selected,'new_reaches':[],
                'execution':{'next_action':'refresh'},'source_review_queue':[],
                'deferred_source_reviews':[],'source_review_warnings':[],
                'notice':'synthetic fixture'}
        scope={'regions':['cambria-san-simeon'],'reach_ids':['cambria-r02'],
               'changed_policy_ids':['point-estero']}
        with patch.object(jobs,'plan',side_effect=fake_plan):
            rollout=jobs._scoped_policy_plan('/unused',scope,{})
        self.assertEqual(seen,[('cambria-san-simeon',0)])
        self.assertEqual(len(rollout['selected']),6)
        self.assertTrue(all(row['region']=='cambria-san-simeon' for row in rollout['selected']))
        self.assertEqual(rollout['policy_scope'],scope)

    def test_push_scope_reads_exact_base_and_target_files(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'catalog').mkdir();(root/'dist/data').mkdir(parents=True)
            (root/'dist/data/seafloor-ledger.json').write_text(json.dumps({'reaches':inventory()}))
            legacy=document(reviewed_policy('legacy'))
            policy_path=root/POLICY
            policy_path.write_text(json.dumps(legacy))
            subprocess.run(['git','init','-q'],cwd=root,check=True)
            subprocess.run(['git','config','user.name','Offline Test'],cwd=root,check=True)
            subprocess.run(['git','config','user.email','offline@example.test'],cwd=root,check=True)
            subprocess.run(['git','add','.'],cwd=root,check=True)
            subprocess.run(['git','commit','-qm','base'],cwd=root,check=True)
            before=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
            policy_path.write_text(json.dumps(document(reviewed_policy('legacy'),
                reviewed_policy('new',['cambria-r02']))))
            subprocess.run(['git','add',POLICY],cwd=root,check=True)
            subprocess.run(['git','commit','-qm','scoped policy'],cwd=root,check=True)
            after=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
            event=root/'event.json';event.write_text(json.dumps({'before':before,'after':after}))
            with patch.dict(os.environ,{'GITHUB_EVENT_NAME':'push','GITHUB_EVENT_PATH':str(event)}):
                self.assertEqual(_push_policy_scope(root),{'mode':'scoped',
                    'reach_ids':['cambria-r02'],'regions':['cambria-san-simeon'],
                    'changed_policy_ids':['new']})

    def test_shallow_push_clone_deepens_exact_target_before_ancestry_check(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'source'; remote=root/'remote.git'; shallow=root/'shallow'
            source.mkdir()
            subprocess.run(['git','init','-q','-b','main'],cwd=source,check=True)
            subprocess.run(['git','config','user.name','Offline Test'],cwd=source,check=True)
            subprocess.run(['git','config','user.email','offline@example.test'],cwd=source,check=True)
            (source/'catalog').mkdir();(source/'dist/data').mkdir(parents=True)
            (source/'dist/data/seafloor-ledger.json').write_text(json.dumps({'reaches':inventory()}))
            policy_path=source/POLICY
            policy_path.write_text(json.dumps(document(reviewed_policy('legacy'))))
            subprocess.run(['git','add','.'],cwd=source,check=True)
            subprocess.run(['git','commit','-qm','base'],cwd=source,check=True)
            before=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
            (source/'intermediate.txt').write_text('one')
            subprocess.run(['git','add','.'],cwd=source,check=True)
            subprocess.run(['git','commit','-qm','intermediate one'],cwd=source,check=True)
            (source/'intermediate.txt').write_text('two')
            subprocess.run(['git','add','.'],cwd=source,check=True)
            subprocess.run(['git','commit','-qm','intermediate two'],cwd=source,check=True)
            subprocess.run(['git','rm','-q','intermediate.txt'],cwd=source,check=True)
            subprocess.run(['git','commit','-qm','restore unrelated tree'],cwd=source,check=True)
            policy_path.write_text(json.dumps(document(reviewed_policy('legacy'),
                reviewed_policy('new',['cambria-r02']))))
            (source/'CHANGELOG.md').write_text('Record the policy-only regional planning change.\n')
            subprocess.run(['git','add',POLICY],cwd=source,check=True)
            subprocess.run(['git','add','CHANGELOG.md'],cwd=source,check=True)
            subprocess.run(['git','commit','-qm','scoped policy'],cwd=source,check=True)
            after=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source,text=True).strip()
            subprocess.run(['git','init','-q','--bare',str(remote)],check=True)
            subprocess.run(['git','remote','add','origin',str(remote)],cwd=source,check=True)
            subprocess.run(['git','push','-q','origin','main'],cwd=source,check=True)
            subprocess.run(['git','clone','-q','--depth=1','--branch','main',
                remote.as_uri(),str(shallow)],check=True)
            event=shallow/'event.json';event.write_text(json.dumps({'before':before,'after':after}))
            self.assertEqual(subprocess.check_output(['git','rev-parse','--is-shallow-repository'],
                cwd=shallow,text=True).strip(),'true')
            # Reproduce the former depth-one base fetch: both commits exist,
            # but the target's shallow boundary prevents ancestry proof.
            subprocess.run(['git','fetch','--no-tags','--depth=1','origin',before],
                cwd=shallow,stdout=subprocess.DEVNULL,check=True)
            self.assertEqual(subprocess.run(['git','cat-file','-e',before+'^{commit}'],
                cwd=shallow,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode,0)
            self.assertNotEqual(subprocess.run(['git','merge-base','--is-ancestor',before,after],
                cwd=shallow,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode,0)
            with patch.dict(os.environ,{'GITHUB_EVENT_NAME':'push','GITHUB_EVENT_PATH':str(event)}):
                self.assertEqual(_push_policy_scope(shallow),{'mode':'scoped',
                    'reach_ids':['cambria-r02'],'regions':['cambria-san-simeon'],
                    'changed_policy_ids':['new']})
            self.assertEqual(subprocess.check_output(['git','rev-parse','--is-shallow-repository'],
                cwd=shallow,text=True).strip(),'false')

    def test_policy_snapshots_use_complete_production_validation(self):
        reaches=inventory()
        good=document(reviewed_policy('source',['cambria-r02']))
        self.assertTrue(_policy_snapshot_valid(good,reaches))
        with self.subTest('unsupported support mode'):
            bad=document(reviewed_policy('source',['cambria-r02'],support_mode='invented-v1'))
            self.assertFalse(_policy_snapshot_valid(bad,reaches))
        with self.subTest('invalid reviewed hash and rights'):
            bad=document(reviewed_policy('source',['cambria-r02'],
                depth_source_sha256='not-a-sha',release_license='unknown'))
            self.assertFalse(_policy_snapshot_valid(bad,reaches))
        with self.subTest('own neighbor overlap'):
            bad=document(reviewed_policy('source',['cambria-r02'],['cambria-r02']))
            self.assertFalse(_policy_snapshot_valid(bad,reaches))
        with self.subTest('duplicate depth identity'):
            bad=document(reviewed_policy('one',['cambria-r02']),
                         reviewed_policy('two',['cambria-r03'],depth_source_id='bathymetry-one'))
            self.assertFalse(_policy_snapshot_valid(bad,reaches))

    def test_push_with_cochanged_rules_falls_back_and_unavailable_base_never_scopes(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'catalog').mkdir();(root/'dist/data').mkdir(parents=True)
            (root/'dist/data/seafloor-ledger.json').write_text(json.dumps({'reaches':inventory()}))
            policy_path=root/POLICY
            policy_path.write_text(json.dumps(document()))
            (root/OTHER_INPUT).write_text('{"rules":[] }')
            subprocess.run(['git','init','-q'],cwd=root,check=True)
            subprocess.run(['git','config','user.name','Offline Test'],cwd=root,check=True)
            subprocess.run(['git','config','user.email','offline@example.test'],cwd=root,check=True)
            subprocess.run(['git','add','.'],cwd=root,check=True)
            subprocess.run(['git','commit','-qm','base'],cwd=root,check=True)
            before=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
            policy_path.write_text(json.dumps(document(policy('new',['cambria-r02']))))
            (root/OTHER_INPUT).write_text('{"rules":["changed"]}')
            subprocess.run(['git','add','.'],cwd=root,check=True)
            subprocess.run(['git','commit','-qm','cochange'],cwd=root,check=True)
            after=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
            event=root/'event.json';event.write_text(json.dumps({'before':before,'after':after}))
            with patch.dict(os.environ,{'GITHUB_EVENT_NAME':'push','GITHUB_EVENT_PATH':str(event)}):
                result=_push_policy_scope(root)
                self.assertEqual(result['mode'],'global-fallback')
                event.write_text(json.dumps({'before':'0'*40,'after':after}))
                result=_push_policy_scope(root)
                self.assertEqual(result['mode'],'global-fallback')

    def test_additive_scoped_row_ignores_unchanged_unscoped_history_and_keeps_region_closure(self):
        legacy = policy('legacy-unscoped')
        old = document(legacy)
        new = document(legacy, policy('point-estero', ['cambria-r02']))
        scope = scoped_policy_change(old, new, [POLICY], inventory())
        self.assertEqual(scope, {'reach_ids': ['cambria-r02'],
            'regions': ['cambria-san-simeon'], 'changed_policy_ids': ['point-estero']})
        rows = inventory()
        global_matrix = regional_batch_rows(rows, rows, {})
        scoped_matrix = regional_batch_rows(rows, [{'reach': 'cambria-r02',
            'region': 'cambria-san-simeon'}], {})
        self.assertEqual(len(global_matrix), 8)
        self.assertEqual([row['id'] for row in scoped_matrix],
                         [f'cambria-r0{i}' for i in range(1, 7)])

    def test_withdrawal_includes_old_scope_and_complete_region(self):
        old = document(policy('point-estero', ['cambria-r02']))
        new = document()
        scope = scoped_policy_change(old, new, [POLICY], inventory())
        self.assertEqual(scope['reach_ids'], ['cambria-r02'])
        self.assertEqual(scope['regions'], ['cambria-san-simeon'])
        self.assertEqual(len(regional_batch_rows(inventory(), [{'reach': 'cambria-r02',
            'region': 'cambria-san-simeon'}], {})), 6)

    def test_scope_move_and_neighbor_dependencies_include_old_and_new_regions(self):
        old = document(policy('source', ['cambria-r02'], ['cambria-r03']))
        new = document(policy('source', ['morro-r01'], ['morro-r02']))
        scope = scoped_policy_change(old, new, [POLICY], inventory())
        self.assertEqual(scope['reach_ids'], ['cambria-r02', 'cambria-r03', 'morro-r01', 'morro-r02'])
        self.assertEqual(scope['regions'], ['cambria-san-simeon', 'morro-bay'])
        selected = [{'reach': reach, 'region': region} for reach, region in (
            ('cambria-r02', 'cambria-san-simeon'), ('cambria-r03', 'cambria-san-simeon'),
            ('morro-r01', 'morro-bay'), ('morro-r02', 'morro-bay'))]
        self.assertEqual(len(regional_batch_rows(inventory(), selected, {})), 8)

    def test_order_change_scopes_changed_priorities(self):
        first = policy('first', ['cambria-r01'])
        second = policy('second', ['morro-r01'])
        scope = scoped_policy_change(document(first, second), document(second, first),
                                     [POLICY], inventory())
        self.assertEqual(scope['changed_policy_ids'], ['first', 'second'])
        self.assertEqual(scope['regions'], ['cambria-san-simeon', 'morro-bay'])
        legacy=policy('unchanged-unscoped')
        scoped = scoped_policy_change(document(first, second, legacy),
            document(second, first, legacy), [POLICY], inventory())
        self.assertEqual(scoped['changed_policy_ids'], ['first','second'])
        self.assertEqual(scoped['regions'], ['cambria-san-simeon','morro-bay'])

    def test_changed_unscoped_cochanged_missing_or_unresolved_inputs_fall_back(self):
        with self.subTest('changed unscoped'):
            self.assertIsNone(scoped_policy_change(document(policy('old')),
                document(policy('old', credit='changed')), [POLICY], inventory()))
        with self.subTest('changed top-level policy member'):
            old = document(policy('new', ['cambria-r02']))
            new = {**old, 'global_ruleset': 'changed'}
            self.assertIsNone(scoped_policy_change(old, new, [POLICY], inventory()))
        with self.subTest('cochanged rules'):
            self.assertIsNone(scoped_policy_change(document(), document(policy('new', ['cambria-r02'])),
                sorted([POLICY, OTHER_INPUT]), inventory()))
        with self.subTest('missing base'):
            self.assertIsNone(scoped_policy_change(None, document(policy('new', ['cambria-r02'])),
                [POLICY], inventory()))
        with self.subTest('unknown reach'):
            self.assertIsNone(scoped_policy_change(document(), document(policy('new', ['unknown-r01'])),
                [POLICY], inventory()))
        with self.subTest('unassessed reach'):
            rows = inventory()+[{'id':'new-r01','region':'new-coast','status':'unassessed'}]
            self.assertIsNone(scoped_policy_change(document(), document(policy('new', ['new-r01'])),
                [POLICY], rows))
        with self.subTest('unresolved neighbor list'):
            self.assertIsNone(scoped_policy_change(document(),
                document(policy('new', ['cambria-r02'], [])), [POLICY], inventory()))


if __name__ == '__main__':
    unittest.main()
