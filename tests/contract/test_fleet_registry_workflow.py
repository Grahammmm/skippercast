"""Public fleet registry authorization and operator runbook contracts."""
import json
import re
import unittest

from tests._support import ROOT

RUNBOOK = ROOT / 'docs' / 'operations' / 'runbooks' / 'fleet-registry.md'


class FleetRegistryAuthorizationTests(unittest.TestCase):
    def test_registry_is_in_the_public_scheduler_and_route_scope(self):
        policy = json.loads((ROOT / 'deployments' / 'production.json').read_text())
        self.assertIn('fleet-registry.yml', policy['scheduler']['workflows'])
        self.assertIn("'fleet-registry.yml'", (ROOT / 'server' / 'routes' / 'fleet.ts').read_text())

class FleetRegistryRunbookTests(unittest.TestCase):
    def setUp(self):
        self.text = RUNBOOK.read_text(encoding='utf-8')

    def test_covers_first_run_reruns_and_staging_runs(self):
        for heading in ('## First run', '## Reruns', '## Staging runs', '## Applying charter-identity coverage'):
            self.assertIn(heading, self.text)
        for needle in ('gh workflow run fleet-registry.yml', '-f sink=staging', '-f sink=worker', '-f run_id=',
                       'FLEET_ENABLED', 'ENABLE_FLEET', 'https://github.com/Grahammmm/skippercast/settings/variables/actions',
                       'GOOGLE_PLACES_API_KEY', 'discover.json', 'state.json'):
            self.assertIn(needle, self.text)
        self.assertNotRegex(self.text, r'gh workflow run fleet-registry\.yml[^\n`]*--ref', 'the workflow runs only from main')

    def test_documents_the_private_confirmation_ledger_and_that_ready_is_the_owners_decision(self):
        for needle in ('## Recording an operator-confirmed identity (private)', 'confirm add', 'confirm withdraw',
                       'confirm list', 'confirmations/<sink>.json', 'operator-statement',
                       'uscg-documentation-matched-to-operator', 'cdfw-cpfv-licence-matched-to-operator',
                       'never published and never committed', 'ready threshold is an owner decision'):
            self.assertIn(needle, self.text)
        self.assertRegex(self.text, r'(?s)never writes `ready`.*?owner decision')
        self.assertIn('stale', self.text)
        from skippercast.fleet import coverage
        self.assertIn('ready threshold is an owner decision', coverage.__doc__ or '')

    def test_notes_the_receipt_and_the_open_issues(self):
        self.assertIn('regions/fort-bragg-point-arena/region.json', self.text)
        self.assertIn('research/receipts/h11730-fort-bragg-regional-camera-support.json', self.text)
        self.assertIn('python -m research.lib.receipts', self.text)
        issues = set(re.findall(r'https://github\.com/Grahammmm/skippercast/issues/(\d+)', self.text))
        self.assertGreaterEqual(len(issues), 2, 'offering retirement and the source_id/priority mismatch')


if __name__ == '__main__':
    unittest.main()
