"""SC1952-11: the charter-grounds test receipt and the bite-evidence health receipt.

Offline: reads committed files only. No gh, no fetch, no clock-freshness threshold, no remote branch lookup.
A pending or failed latest run and a degraded health file are valid observations; nothing here requires green CI.
"""
import copy
import hashlib
import json
import re
import unittest
from pathlib import Path

from tests._support import ROOT

RECEIPTS = ROOT / 'research' / 'receipts'
CHARTER_RECEIPT = 'research/receipts/charter-grounds-test-2026-11-04.json'
BITE_RECEIPT = 'research/receipts/bite-evidence-health-2026-11-04.json'
PAGE = ROOT / 'docs' / 'coast-capabilities-status.md'
BASELINE = '4bcc2be4620f2915e18eff4cd6f7b378ad9162dc'
SHA40 = re.compile(r'^[0-9a-f]{40}$')
SHA64 = re.compile(r'^[0-9a-f]{64}$')
UTC = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
DAY = re.compile(r'^\d{4}-\d{2}-\d{2}$')
COUNTS = ('tests', 'pass', 'fail', 'cancelled', 'skipped', 'todo')
RUN_FIELDS = ('databaseId', 'headSha', 'status', 'conclusion', 'createdAt', 'updatedAt', 'url', 'event', 'workflowName')
CHARTER_FIELDS = ('schema_version', 'scope', 'ran_at', 'commit', 'command', 'node_version', 'exit_code', *COUNTS,
                  'result', 'files', 'coverage')
BITE_FIELDS = ('schema_version', 'scope', 'captured_at', 'repository_commit', 'workflow_file', 'run_query', 'run',
               'data_commit', 'health_path', 'health_sha256', 'generated_at', 'health_json')
COVERAGE_FIELDS = ('audit_date', 'from', 'through', 'dates_checked', 'dates_available')
WORKFLOW = '.github/workflows/daily-data.yml'


def load(path):
    return json.loads((ROOT / path).read_text())


def charter_problems(receipt, source_bytes):
    """Every reason this charter receipt is not a faithful record; [] when it is faithful."""
    problems = []
    missing = [key for key in CHARTER_FIELDS if key not in receipt]
    if missing:
        return [f'missing fields {missing}']
    if receipt['schema_version'] != 2 or receipt['scope'] != 'charter-grounds-test':
        problems.append('wrong schema or scope')
    if not UTC.match(str(receipt['ran_at'])):
        problems.append('ran_at is not UTC')
    if not SHA40.match(str(receipt['commit'])):
        problems.append('commit is not a full sha')
    if receipt['command'] != 'node --test tests/test_charters.mjs':
        problems.append('wrong command')
    counts = [receipt[key] for key in COUNTS]
    if not all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in counts):
        problems.append('counts must be non-negative integers')
    else:
        tests, passed, failed, cancelled, skipped, todo = counts
        if passed + failed + cancelled + skipped + todo != tests:
            problems.append('counts do not add up to tests')
        clean = receipt['exit_code'] == 0 and tests > 0 and passed == tests and not (failed or cancelled or skipped or todo)
        if receipt['result'] == 'pass' and not clean:
            problems.append('result pass but run not clean')
        if receipt['result'] not in ('pass', 'fail'):
            problems.append('result must be pass or fail')
        if receipt['result'] == 'fail' and clean:
            problems.append('result fail but run clean')
    files = receipt['files']
    if (not isinstance(files, list) or len(files) != 1 or files[0].get('path') != 'dist/data/charter-grounds.json'
            or files[0].get('sha256') != hashlib.sha256(source_bytes).hexdigest()):
        problems.append('file hash does not bind the bundled charter-grounds.json')
    source = json.loads(source_bytes)
    coverage = receipt['coverage']
    if not isinstance(coverage, dict) or sorted(coverage) != sorted(COVERAGE_FIELDS):
        problems.append('coverage fields')
    else:
        stated = dict(source['coverage'])
        stated['audit_date'] = source['audit_date']
        if any(coverage[key] != stated.get(key) for key in COVERAGE_FIELDS):
            problems.append('coverage differs from the dataset stated dates')
        if not all(DAY.match(str(coverage[key])) for key in ('audit_date', 'from', 'through')):
            problems.append('coverage dates must be YYYY-MM-DD')
    return problems


def bite_problems(receipt):
    """Every reason this bite-evidence receipt is not a faithful record; [] when it is faithful."""
    missing = [key for key in BITE_FIELDS if key not in receipt]
    if missing:
        return [f'missing fields {missing}']
    problems = []
    if receipt['schema_version'] != 2 or receipt['scope'] != 'bite-evidence-health':
        problems.append('wrong schema or scope')
    if not UTC.match(str(receipt['captured_at'])):
        problems.append('captured_at is not UTC')
    for key in ('repository_commit', 'data_commit'):
        if not SHA40.match(str(receipt[key])):
            problems.append(f'{key} is not a full sha')
    if receipt['workflow_file'] != WORKFLOW:
        problems.append('wrong workflow file')
    run = receipt['run']
    if not isinstance(run, dict) or any(key not in run for key in RUN_FIELDS):
        return problems + ['run fields missing']
    if not isinstance(run['databaseId'], int) or isinstance(run['databaseId'], bool) or run['databaseId'] <= 0:
        problems.append('run id missing')
    if not SHA40.match(str(run['headSha'])):
        problems.append('run headSha is not a full sha')
    if run['workflowName'] != 'Daily fishing evidence' or f"/actions/runs/{run['databaseId']}" not in str(run['url']):
        problems.append('not the daily-data workflow run')
    if run['status'] not in ('completed', 'in_progress', 'queued', 'waiting', 'pending', 'requested'):
        problems.append('unknown run status')
    if run['status'] == 'completed' and run['conclusion'] not in (
            'success', 'failure', 'cancelled', 'timed_out', 'skipped', 'neutral', 'startup_failure', 'action_required', 'stale'):
        problems.append('completed run needs a conclusion')
    if run['status'] != 'completed' and run['conclusion'] not in (None, ''):
        problems.append('pending run must keep an empty conclusion')
    health_bytes = str(receipt['health_json']).encode('utf-8')
    if hashlib.sha256(health_bytes).hexdigest() != receipt['health_sha256'] or not SHA64.match(str(receipt['health_sha256'])):
        problems.append('health_json does not hash to health_sha256')
    try:
        parsed = json.loads(receipt['health_json'])
    except ValueError:
        return problems + ['health_json is not valid JSON']
    if not isinstance(parsed, dict) or parsed.get('generated_at') != receipt['generated_at'] or not UTC.match(str(receipt['generated_at'])):
        problems.append('generated_at differs from the health file')
    if receipt['health_path'] != 'health.json':
        problems.append('wrong health path')
    return problems


class CharterReceiptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = (ROOT / 'dist' / 'data' / 'charter-grounds.json').read_bytes()
        cls.receipt = load(CHARTER_RECEIPT)

    def copy(self):
        return copy.deepcopy(self.receipt)

    def test_committed_receipt_is_faithful(self):
        self.assertEqual(charter_problems(self.receipt, self.source), [])
        self.assertEqual(self.receipt['commit'], BASELINE)
        self.assertEqual(self.receipt['coverage']['from'], '2026-04-01')
        self.assertEqual(self.receipt['coverage']['through'], '2026-09-20')

    def test_wrong_hash_or_date_fails(self):
        wrong = self.copy()
        wrong['files'][0]['sha256'] = '0' * 64
        self.assertTrue(charter_problems(wrong, self.source))
        wrong = self.copy()
        wrong['coverage']['through'] = '2026-11-04'  # rebased to capture time
        self.assertTrue(charter_problems(wrong, self.source))
        self.assertTrue(charter_problems(self.receipt, self.source + b' '))

    def test_bad_counts_and_false_pass_fail(self):
        for key, value in (('pass', 5), ('fail', -1), ('tests', 7), ('skipped', 1.0), ('todo', True)):
            wrong = self.copy()
            wrong[key] = value
            self.assertTrue(charter_problems(wrong, self.source), key)
        failing = self.copy()
        failing.update({'pass': 5, 'fail': 1, 'exit_code': 1})
        self.assertTrue(charter_problems(failing, self.source), 'pass claimed with a failure')
        failing['result'] = 'fail'
        self.assertEqual(charter_problems(failing, self.source), [], 'a truthful failure is recordable')
        skipping = self.copy()
        skipping.update({'pass': 5, 'skipped': 1})
        self.assertTrue(charter_problems(skipping, self.source), 'pass claimed with a skip')

    def test_missing_field_fails(self):
        for key in CHARTER_FIELDS:
            wrong = self.copy()
            del wrong[key]
            self.assertTrue(charter_problems(wrong, self.source), key)
        wrong = self.copy()
        del wrong['coverage']['dates_checked']
        self.assertTrue(charter_problems(wrong, self.source))

    def test_no_boat_or_schedule_data_in_receipt(self):
        text = json.dumps(self.receipt)
        for word in ('boat', 'vessel', 'schedule', 'trips', 'report_url'):
            self.assertNotIn(word, text.lower())


class BiteReceiptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = load(BITE_RECEIPT)

    def copy(self):
        return copy.deepcopy(self.receipt)

    def test_committed_receipt_is_faithful(self):
        self.assertEqual(bite_problems(self.receipt), [])
        self.assertEqual(self.receipt['repository_commit'], BASELINE)
        self.assertTrue(self.receipt['health_json'].endswith('\n'), 'exact bytes keep the final newline')

    def test_run_conclusions_success_failure_and_pending_are_all_valid(self):
        for status, conclusion in (('completed', 'success'), ('completed', 'failure'), ('completed', 'cancelled'),
                                   ('in_progress', None), ('queued', '')):
            receipt = self.copy()
            receipt['run'].update(status=status, conclusion=conclusion)
            self.assertEqual(bite_problems(receipt), [], (status, conclusion))

    def test_run_identity_is_checked(self):
        for key in RUN_FIELDS:
            wrong = self.copy()
            del wrong['run'][key]
            self.assertTrue(bite_problems(wrong), key)
        for key, value in (('databaseId', 0), ('databaseId', None), ('headSha', 'abc123'),
                           ('workflowName', 'Live conditions'), ('url', 'https://github.com/Grahammmm/skippercast/actions/runs/1')):
            wrong = self.copy()
            wrong['run'][key] = value
            self.assertTrue(bite_problems(wrong), key)
        wrong = self.copy()
        wrong['workflow_file'] = '.github/workflows/live-conditions.yml'
        self.assertTrue(bite_problems(wrong))
        wrong = self.copy()
        wrong['run'].update(status='completed', conclusion=None)
        self.assertTrue(bite_problems(wrong), 'a completed run needs a conclusion')
        wrong = self.copy()
        wrong['run'].update(status='in_progress', conclusion='success')
        self.assertTrue(bite_problems(wrong), 'a pending run must not claim a conclusion')

    def test_health_bytes_hash_and_generated_at(self):
        wrong = self.copy()
        wrong['health_json'] = wrong['health_json'].rstrip('\n')
        self.assertTrue(bite_problems(wrong), 'altered bytes (final newline dropped)')
        wrong = self.copy()
        wrong['generated_at'] = '2026-11-04T09:00:00Z'
        self.assertTrue(bite_problems(wrong), 'generated_at differs from the file')
        wrong = self.copy()
        wrong['health_json'] = '{not json\n'
        wrong['health_sha256'] = hashlib.sha256(wrong['health_json'].encode()).hexdigest()
        self.assertTrue(bite_problems(wrong), 'invalid JSON with a matching hash')
        wrong = self.copy()
        wrong['health_sha256'] = wrong['health_sha256'].upper()
        self.assertTrue(bite_problems(wrong))

    def test_degraded_health_is_recordable_and_data_commit_is_independent(self):
        receipt = self.copy()
        health = json.loads(receipt['health_json'])
        health['status'] = 'degraded'
        receipt['health_json'] = json.dumps(health) + '\n'
        receipt['health_sha256'] = hashlib.sha256(receipt['health_json'].encode()).hexdigest()
        self.assertEqual(bite_problems(receipt), [])
        self.assertNotEqual(receipt['data_commit'], receipt['run']['headSha'])
        wrong = self.copy()
        wrong['data_commit'] = wrong['data_commit'][:12]
        self.assertTrue(bite_problems(wrong))

    def test_missing_field_fails(self):
        for key in BITE_FIELDS:
            wrong = self.copy()
            del wrong[key]
            self.assertTrue(bite_problems(wrong), key)


class PageCitationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = PAGE.read_text()
        cls.rows = {line.split('|')[1].strip(): [cell.strip() for cell in line.split('|')[1:-1]]
                    for line in cls.page.splitlines() if line.startswith('| ') and line.count('|') >= 6}

    def test_both_rows_cite_their_receipt_and_the_named_baseline(self):
        charter = ' '.join(self.rows['Charter grounds'])
        bite = ' '.join(self.rows['Bite evidence'])
        self.assertIn(CHARTER_RECEIPT, charter)
        self.assertIn(BITE_RECEIPT, bite)
        for row in (charter, bite):
            self.assertIn(BASELINE, row)
            self.assertIn('not at the historical pin', row)

    def test_rows_quote_the_receipt_values(self):
        charter, bite = load(CHARTER_RECEIPT), load(BITE_RECEIPT)
        row = ' '.join(self.rows['Charter grounds'])
        for value in (charter['files'][0]['sha256'], charter['coverage']['from'], charter['coverage']['through']):
            self.assertIn(value, row)
        row = ' '.join(self.rows['Bite evidence'])
        for value in (str(bite['run']['databaseId']), bite['run']['conclusion'], bite['health_sha256'],
                      bite['generated_at'], bite['data_commit']):
            self.assertIn(value, row)

    def test_statuses_and_limits_are_unchanged(self):
        self.assertEqual(self.rows['Charter grounds'][2], 'DESIGNED')
        self.assertEqual(self.rows['Bite evidence'][2], 'DESIGNED')
        self.assertIn('No row on this page is LIVE.', self.page)
        self.assertNotRegex(self.page, r'\|\s*LIVE\s*\|\s*[^|]*\|\s*$')
        self.assertIn('Report locations are named places, not positions', self.rows['Charter grounds'][3])
        self.assertIn('`catch_probability` and `bite_score` stay null', self.rows['Bite evidence'][3])
        self.assertIn('c3fe61e5c14543013511ffa5c1744655641ef657', self.page.splitlines()[0])
        self.assertIn('every other row stays pinned', self.page.splitlines()[0])
        self.assertIn('did not exist at the historical pin', self.page)


class ManifestBindingTest(unittest.TestCase):
    def test_manifest_lists_both_receipts_with_their_bytes(self):
        recorded = json.loads((RECEIPTS / 'manifest.json').read_text())['files']
        for path in (CHARTER_RECEIPT, BITE_RECEIPT):
            name = Path(path).name
            self.assertEqual(recorded.get(name), hashlib.sha256((ROOT / path).read_bytes()).hexdigest(), name)


if __name__ == '__main__':
    unittest.main()
