import unittest
from research.scripts.diagnose_cadence import analyse

def run(i, minute, event='schedule', status='completed'):
    return {'id':i,'event':event,'status':status,'created_at':f'2026-10-15T{minute//60:02d}:{minute%60:02d}:00Z'}
def job(i,start,end,conclusion='success'):
    return {'run_id':i,'jobs':[{'started_at':f'2026-10-15T{start//60:02d}:{start%60:02d}:00Z','completed_at':f'2026-10-15T{end//60:02d}:{end%60:02d}:00Z','conclusion':conclusion}]}
class EvidenceTests(unittest.TestCase):
    def test_sparse_creation_is_not_runner_queue(self):
        x=analyse([run(1,0),run(2,120)],[job(1,0,1),job(2,120,121)])
        self.assertEqual(x['max_creation_gap_minutes'],120)
        self.assertEqual(x['max_job_start_delay_seconds'],0)
        self.assertTrue(x['trigger_delivery_cause'].startswith('unknown'))
    def test_created_runs_can_wait_without_creation_gap(self):
        x=analyse([run(1,0),run(2,30)],[job(1,20,21),job(2,50,51)])
        self.assertEqual(x['max_creation_gap_minutes'],30)
        self.assertEqual(x['max_job_start_delay_seconds'],1200)
    def test_manual_success_does_not_fill_natural_gap(self):
        x=analyse([run(1,0),run(2,30,'workflow_dispatch'),run(3,120)],[job(1,0,1),job(2,30,31),job(3,120,121)])
        self.assertEqual(x['scheduled_runs'],2)
        self.assertEqual(x['max_creation_gap_minutes'],120)
    def test_skipped_and_long_execution_are_separate(self):
        x=analyse([run(1,0),run(2,30)],[job(1,0,90),{'run_id':2,'jobs':[{'conclusion':'skipped'}]}])
        self.assertEqual(x['max_job_duration_seconds'],5400)
        self.assertEqual(x['skipped_jobs'],1)
    def test_pending_and_unknown_are_not_success(self):
        x=analyse([run(1,0,status='queued'),run(2,30)],[])
        self.assertEqual(x['created_pending_without_jobs'],1)
        self.assertEqual(x['completed_runs_without_job_evidence'],1)
        self.assertIsNone(x['max_job_start_delay_seconds'])
    def test_single_run_cannot_establish_cadence(self):
        self.assertIsNone(analyse([run(1,0)],[job(1,0,1)])['median_creation_gap_minutes'])
    def test_timezone_is_required(self):
        r=run(1,0);r['created_at']='2026-10-15T00:00:00'
        with self.assertRaises(ValueError):analyse([r],[])
if __name__=='__main__':unittest.main()
