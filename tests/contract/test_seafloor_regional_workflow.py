"""Regional publisher isolation and retry identity must survive workflow edits."""
import unittest
from tests._support import ROOT
from tests.contract.test_trip_check_loop import jobs


class RegionalWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.jobs = jobs((ROOT/'.github/workflows/seafloor.yml').read_text())

    def test_publication_is_region_bounded_and_bookkeeping_never_publishes(self):
        pub = self.jobs['publish']
        self.assertIn('fail-fast: false', pub)
        self.assertIn('region: ${{ fromJSON(needs.prepare.outputs.regions) }}', pub)
        self.assertIn('--region "$REGION"', pub)
        self.assertNotIn('create-pull-request@', pub)
        ledger = self.jobs['ledger']
        self.assertIn('if: always()', ledger)
        self.assertIn('--ledger-only', ledger)
        self.assertNotIn('tippecanoe', ledger)
        self.assertIn("os.environ['PUBLICATION_RESULT'] != 'success'", ledger)

    def test_failed_job_retry_preserves_original_prepare_batch(self):
        self.assertIn('batch: ${{ steps.plan.outputs.batch }}', self.jobs['prepare'])
        for name in ('reaches', 'publish', 'ledger'):
            self.assertIn('SEAFLOOR_BATCH: ${{ needs.prepare.outputs.batch }}', self.jobs[name])
            self.assertNotIn('GITHUB_RUN_ATTEMPT', self.jobs[name])
