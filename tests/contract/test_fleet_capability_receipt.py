"""SC2207-09: the fleet-activity state receipt (committed flags and the latest fleet-health run).

Offline: reads committed files only. No gh, no git history, no fetch, no live clock, no latest-run lookup.
A failed, cancelled, skipped or pending run is a valid observation; nothing here requires green CI, and a
green run is never read as proof that the job ran, that AIS data is fresh or that a flag is on in production.
"""
import copy
import hashlib
import json
import re
import unittest
from pathlib import Path

from tests._support import ROOT

RECEIPTS = ROOT / 'research' / 'receipts'
RECEIPT = 'research/receipts/fleet-activity-state-2026-11-04.json'
PAGE = ROOT / 'docs' / 'coast-capabilities-status.md'
HISTORICAL_PIN = 'c3fe61e5c14543013511ffa5c1744655641ef657'
SHA40 = re.compile(r'^[0-9a-f]{40}$')
SHA64 = re.compile(r'^[0-9a-f]{64}$')
UTC = re.compile(r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$')
FIELDS = ('schema_version', 'scope', 'captured_at', 'repository_commit', 'repository', 'workflow_file', 'run_query',
          'run', 'committed_config', 'production_flags', 'production_reason', 'sources', 'limits')
RUN_FIELDS = ('databaseId', 'headSha', 'status', 'conclusion', 'createdAt', 'updatedAt', 'url', 'event', 'workflowName')
FLAGS = ('FLEET_ENABLED', 'FLEET_MAP_ENABLED')
WORKFLOW = '.github/workflows/fleet-health.yml'
QUERY = ('gh run list --repo Grahammmm/skippercast --workflow fleet-health.yml --limit 1 --json '
         'databaseId,headSha,status,conclusion,createdAt,updatedAt,url,event,workflowName')
SOURCE_IDS = ('config-vars-object', 'workflow-identity', 'workflow-triggers', 'workflow-gate', 'flag-allowlist',
              'deploy-passes-vars', 'page-status-rules', 'page-evidence-rule')
STATUSES = ('completed', 'in_progress', 'queued', 'waiting', 'pending', 'requested')
CONCLUSIONS = ('success', 'failure', 'cancelled', 'timed_out', 'skipped', 'neutral', 'startup_failure',
               'action_required', 'stale')


def load(path=RECEIPT):
    return json.loads((ROOT / path).read_text())


def strip_jsonc(text):
    """The text without // and /* */ comments, ignoring comment markers inside strings."""
    out, i, in_string = [], 0, False
    while i < len(text):
        char = text[i]
        if in_string:
            out.append(char)
            if char == '\\':
                out.append(text[i + 1])
                i += 1
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
            out.append(char)
        elif text.startswith('//', i):
            while i < len(text) and text[i] != '\n':
                i += 1
            continue
        elif text.startswith('/*', i):
            i = text.index('*/', i) + 2
            continue
        else:
            out.append(char)
        i += 1
    return ''.join(out)


def derive_flags(config_text):
    """{flag: {present, value}} read from the top-level vars object of the committed config text."""
    vars_object = json.loads(strip_jsonc(config_text)).get('vars', {})
    return {flag: ({'present': True, 'value': vars_object[flag]} if flag in vars_object
                   else {'present': False, 'value': None}) for flag in FLAGS}


def vars_range(config_text):
    """(first line, last line), 1-based, of the complete top-level vars object."""
    lines = config_text.split('\n')
    start = next(n for n, line in enumerate(lines) if line.startswith('  "vars": {'))
    end = next(n for n in range(start + 1, len(lines)) if lines[n].startswith('  }'))
    return start + 1, end + 1


def receipt_problems(receipt):
    """Every reason this receipt is not a faithful record; [] when it is faithful."""
    missing = [key for key in FIELDS if key not in receipt]
    if missing:
        return [f'missing fields {missing}']
    problems = []
    if receipt['schema_version'] != 2 or receipt['scope'] != 'fleet-activity-state':
        problems.append('wrong schema or scope')
    if not UTC.match(str(receipt['captured_at'])):
        problems.append('captured_at is not UTC')
    if not SHA40.match(str(receipt['repository_commit'])):
        problems.append('repository_commit is not a full sha')
    if receipt['repository'] != 'Grahammmm/skippercast' or receipt['workflow_file'] != WORKFLOW:
        problems.append('wrong repository or workflow file')
    query = receipt['run_query']
    if not isinstance(query, dict) or query.get('command') != QUERY or query.get('exit_code') != 0:
        problems.append('wrong run query or query did not exit 0')
    elif not UTC.match(str(query.get('clock_read_before_query_at'))):
        problems.append('query clock read is not UTC')
    problems += run_problems(receipt)
    problems += config_problems(receipt)
    if receipt['production_flags'] != {flag: 'UNVERIFIED' for flag in FLAGS}:
        problems.append('production flags must both stay UNVERIFIED')
    if not str(receipt['production_reason']).strip():
        problems.append('production_reason missing')
    if not isinstance(receipt['limits'], list) or not receipt['limits']:
        problems.append('limits missing')
    if 'mmsi' in json.dumps(receipt).lower():
        problems.append('vessel identifiers do not belong in this receipt')
    return problems


def run_problems(receipt):
    run = receipt['run']
    if not isinstance(run, dict) or sorted(run) != sorted(RUN_FIELDS):
        return ['run fields must be exactly the queried fields']
    problems = []
    if not isinstance(run['databaseId'], int) or isinstance(run['databaseId'], bool) or run['databaseId'] <= 0:
        problems.append('run id missing')
    if not SHA40.match(str(run['headSha'])):
        problems.append('run headSha is not a full sha')
    if run['url'] != f"https://github.com/Grahammmm/skippercast/actions/runs/{run['databaseId']}":
        problems.append('run url does not match the run id')
    if run['workflowName'] != 'Fleet AIS health':
        problems.append('not the fleet-health workflow run')
    if not str(run['event']).strip():
        problems.append('run event missing')
    if run['status'] not in STATUSES:
        problems.append('unknown run status')
    if run['status'] == 'completed' and run['conclusion'] not in CONCLUSIONS:
        problems.append('completed run needs a conclusion')
    if run['status'] != 'completed' and run['conclusion'] not in (None, ''):
        problems.append('pending run must keep an empty conclusion')
    times = [run['createdAt'], run['updatedAt'], receipt['captured_at']]
    if not all(UTC.match(str(value)) for value in times):
        problems.append('run and capture times must be UTC')
    elif not run['createdAt'] <= run['updatedAt'] <= receipt['captured_at']:
        problems.append('times out of order: created, updated, captured')
    return problems


def config_problems(receipt):
    config = receipt['committed_config']
    keys = ('path', 'commit', 'sha256', 'text', 'flags')
    if not isinstance(config, dict) or sorted(config) != sorted(keys):
        return ['committed_config fields']
    problems = []
    if config['path'] != 'wrangler.jsonc' or config['commit'] != receipt['repository_commit']:
        problems.append('config is not the file at the baseline commit')
    text = config['text']
    if not isinstance(text, str) or not SHA64.match(str(config['sha256'])) \
            or hashlib.sha256(text.encode('utf-8')).hexdigest() != config['sha256']:
        return problems + ['config text does not hash to sha256']
    try:
        derived = derive_flags(text)
    except (ValueError, StopIteration):
        return problems + ['config text is not readable JSONC']
    flags = config['flags']
    if not isinstance(flags, dict) or sorted(flags) != sorted(FLAGS):
        return problems + ['flags must be exactly the two fleet flags']
    for flag in FLAGS:
        if flags[flag] != derived[flag] or sorted(flags[flag]) != ['present', 'value']:
            problems.append(f'{flag} differs from the committed config')
        if flags[flag].get('present') is False and flags[flag].get('value') is not None:
            problems.append(f'{flag} absent but has a value')
    return problems + source_problems(receipt)


def source_problems(receipt):
    sources = receipt['sources']
    if not isinstance(sources, list) or [entry.get('id') for entry in sources] != list(SOURCE_IDS):
        return ['sources must be exactly the expected evidence entries']
    problems = []
    text = receipt['committed_config']['text']
    for entry in sources:
        label = entry['id']
        start, end = entry.get('start_line'), entry.get('end_line')
        if entry.get('commit') != receipt['repository_commit'] or not str(entry.get('path')).strip():
            problems.append(f'{label}: not bound to the baseline commit')
        if not all(isinstance(n, int) and not isinstance(n, bool) for n in (start, end)) or not 1 <= start <= end:
            problems.append(f'{label}: bad line range')
            continue
        excerpt = entry.get('excerpt')
        if not isinstance(excerpt, str) or not excerpt or len(excerpt.split('\n')) != end - start + 1:
            problems.append(f'{label}: excerpt does not fill its line range')
        elif entry['path'] == 'wrangler.jsonc' and excerpt != '\n'.join(text.split('\n')[start - 1:end]):
            problems.append(f'{label}: excerpt differs from the committed config lines')
    by_id = {entry['id']: entry for entry in sources if isinstance(entry, dict)}
    vars_entry = by_id['config-vars-object']
    if vars_entry.get('path') != 'wrangler.jsonc' or (vars_entry.get('start_line'), vars_entry.get('end_line')) != vars_range(text):
        problems.append('config-vars-object is not the complete vars object')
    if any(flag in str(vars_entry.get('excerpt')) for flag in FLAGS) != any(item['present'] for item in receipt['committed_config']['flags'].values()):
        problems.append('config-vars-object excerpt disagrees with the recorded flags')
    if by_id['workflow-identity'].get('excerpt') != f"name: {(receipt['run'] if isinstance(receipt['run'], dict) else {}).get('workflowName')}":
        problems.append('workflow-identity does not match the run workflow name')
    if "vars.ENABLE_FLEET == 'true'" not in str(by_id['workflow-gate'].get('excerpt')):
        problems.append('workflow-gate does not quote the ENABLE_FLEET gate')
    for id_, path in (('workflow-identity', WORKFLOW), ('workflow-triggers', WORKFLOW), ('workflow-gate', WORKFLOW),
                      ('flag-allowlist', 'scripts/wrangler_config.mjs'), ('deploy-passes-vars', '.github/workflows/deploy-cloudflare.yml'),
                      ('page-status-rules', 'docs/coast-capabilities-status.md'), ('page-evidence-rule', 'docs/coast-capabilities-status.md')):
        if by_id[id_].get('path') != path:
            problems.append(f'{id_}: wrong path')
    return problems


def fleet_row(page):
    rows = {line.split('|')[1].strip(): [cell.strip() for cell in line.split('|')[1:-1]]
            for line in page.splitlines() if line.startswith('| ') and line.count('|') >= 6}
    return rows['Fleet activity'], rows


def page_problems(page, receipt):
    """Every reason the page does not cite this receipt as a scoped Fleet addendum; [] when it does."""
    row, rows = fleet_row(page)
    text = ' '.join(row)
    problems = []
    first = page.splitlines()[0]
    if HISTORICAL_PIN not in first or 'every other row stays pinned' not in first or receipt['repository_commit'] not in first:
        problems.append('first line lost the historical pin or the scoped Fleet exception')
    if 'research/receipts/' + Path(RECEIPT).name not in row[1]:
        problems.append('evidence cell does not cite the receipt')
    if receipt['repository_commit'] not in row[1] or 'not at the historical pin' not in row[1]:
        problems.append('evidence cell does not name the baseline outside the historical pin')
    run = receipt['run']
    for value in (run['databaseId'], run['conclusion'], run['status'], run['event'], run['createdAt'], run['updatedAt'],
                  run['headSha'], receipt['committed_config']['sha256'], receipt['captured_at'][:10]):
        if str(value) not in row[1]:
            problems.append(f'evidence cell lacks {value}')
    if row[2] != 'PREVIEW':
        problems.append('status must stay PREVIEW')
    if 'UNVERIFIED' not in row[3] or 'no deploy record' not in row[3] or 'not as `false`' not in row[1]:
        problems.append('production values must stay UNVERIFIED and absence must not read as false')
    if 'does not show that the job ran' not in row[3] or 'publication hold' not in row[4]:
        problems.append('run limits or publication hold missing')
    if 'This is fleet intelligence, not charter grounds or bite evidence.' not in row[3]:
        problems.append('fleet-not-charter-or-bite distinction lost')
    if 'Fleet activity' not in rows or rows['Charter grounds'][2] != 'DESIGNED' or rows['Bite evidence'][2] != 'DESIGNED':
        problems.append('other rows changed status')
    if 'No row on this page is LIVE.' not in page or any(cells[2] == 'LIVE' for cells in rows.values()):
        problems.append('a row claims LIVE')
    return problems


class FleetReceiptTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = load()

    def copy(self):
        return copy.deepcopy(self.receipt)

    def test_committed_receipt_is_faithful(self):
        self.assertEqual(receipt_problems(self.receipt), [])
        self.assertTrue(UTC.match(self.receipt['captured_at']))
        self.assertTrue(self.receipt['captured_at'].startswith(Path(RECEIPT).stem[-10:]))
        self.assertEqual(self.receipt['production_flags'], {'FLEET_ENABLED': 'UNVERIFIED', 'FLEET_MAP_ENABLED': 'UNVERIFIED'})

    def test_committed_config_has_neither_flag_and_absent_is_not_false(self):
        flags = self.receipt['committed_config']['flags']
        for flag in FLAGS:
            self.assertEqual(flags[flag], {'present': False, 'value': None})
            self.assertNotIn(flag, self.receipt['committed_config']['text'])

    def test_missing_flag_differs_from_explicit_string_values(self):
        for value in ('false', 'true', True):
            wrong = self.copy()
            wrong['committed_config']['flags']['FLEET_ENABLED'] = {'present': True, 'value': value}
            self.assertTrue(receipt_problems(wrong), f'claimed {value!r} that the file does not hold')
        wrong = self.copy()
        wrong['committed_config']['flags']['FLEET_ENABLED'] = {'present': False, 'value': False}
        self.assertTrue(receipt_problems(wrong), 'absent must carry null, never false')
        wrong = self.copy()
        wrong['committed_config']['flags']['FLEET_MAP_ENABLED'] = {'present': True, 'value': None}
        self.assertTrue(receipt_problems(wrong))
        wrong = self.copy()
        del wrong['committed_config']['flags']['FLEET_MAP_ENABLED']
        self.assertTrue(receipt_problems(wrong))

    def test_a_config_that_holds_the_flag_is_recorded_with_its_exact_value(self):
        for value, literal in (('false', '"false"'), ('true', '"true"'), (True, 'true')):
            text = self.receipt['committed_config']['text'].replace(
                '"vars": {\n', f'"vars": {{\n    "FLEET_ENABLED": {literal},\n', 1)
            receipt = self.copy()
            receipt['committed_config'].update(text=text, sha256=hashlib.sha256(text.encode()).hexdigest())
            receipt['committed_config']['flags']['FLEET_ENABLED'] = {'present': True, 'value': value}
            start, end = vars_range(text)
            vars_entry = receipt['sources'][0]
            vars_entry.update(start_line=start, end_line=end, excerpt='\n'.join(text.split('\n')[start - 1:end]))
            self.assertEqual(receipt_problems(receipt), [], literal)
            self.assertEqual(derive_flags(text)['FLEET_ENABLED']['value'], value)
            self.assertEqual(receipt['production_flags']['FLEET_ENABLED'], 'UNVERIFIED', 'committed value never sets production')
            receipt['committed_config']['flags']['FLEET_ENABLED'] = {'present': False, 'value': None}
            self.assertTrue(receipt_problems(receipt), 'file holds the flag but the receipt says absent')

    def test_config_bytes_and_digest_must_agree(self):
        wrong = self.copy()
        wrong['committed_config']['text'] += '\n'
        self.assertTrue(receipt_problems(wrong), 'text edited without the digest')
        wrong = self.copy()
        wrong['committed_config']['sha256'] = '0' * 64
        self.assertTrue(receipt_problems(wrong))
        wrong = self.copy()
        wrong['committed_config']['sha256'] = wrong['committed_config']['sha256'].upper()
        self.assertTrue(receipt_problems(wrong))
        wrong = self.copy()
        text = json.dumps(json.loads(strip_jsonc(wrong['committed_config']['text'])), indent=2)
        wrong['committed_config'].update(text=text, sha256=hashlib.sha256(text.encode()).hexdigest())
        self.assertTrue(receipt_problems(wrong), 'a reformatted config no longer matches the cited lines')
        wrong = self.copy()
        wrong['committed_config']['commit'] = 'a' * 40
        self.assertTrue(receipt_problems(wrong), 'config must be the baseline commit')

    def test_run_conclusions_success_failure_cancelled_skipped_and_pending_are_all_valid(self):
        for status, conclusion in (('completed', 'success'), ('completed', 'failure'), ('completed', 'cancelled'),
                                   ('completed', 'skipped'), ('in_progress', None), ('queued', ''), ('pending', None)):
            receipt = self.copy()
            receipt['run'].update(status=status, conclusion=conclusion)
            self.assertEqual(receipt_problems(receipt), [], (status, conclusion))

    def test_run_identity_is_checked(self):
        for key in RUN_FIELDS:
            wrong = self.copy()
            del wrong['run'][key]
            self.assertTrue(receipt_problems(wrong), key)
        wrong = self.copy()
        wrong['run']['extra'] = 1
        self.assertTrue(receipt_problems(wrong), 'only the queried fields')
        for key, value in (('databaseId', 0), ('databaseId', None), ('databaseId', True), ('databaseId', '41788933654'),
                           ('headSha', 'abc123'), ('headSha', 'A' * 40), ('workflowName', 'Daily fishing evidence'),
                           ('url', 'https://github.com/Grahammmm/skippercast/actions/runs/1'),
                           ('status', 'done'), ('event', '')):
            wrong = self.copy()
            wrong['run'][key] = value
            self.assertTrue(receipt_problems(wrong), key)
        wrong = self.copy()
        wrong['workflow_file'] = '.github/workflows/daily-data.yml'
        self.assertTrue(receipt_problems(wrong))
        wrong = self.copy()
        wrong['run_query']['command'] = QUERY.replace('--limit 1', '--limit 1 --status success')
        self.assertTrue(receipt_problems(wrong), 'a filtered query is not the latest run')
        wrong = self.copy()
        wrong['run_query']['exit_code'] = 1
        self.assertTrue(receipt_problems(wrong))
        wrong = self.copy()
        wrong['run'].update(status='completed', conclusion=None)
        self.assertTrue(receipt_problems(wrong), 'a completed run needs a conclusion')
        wrong = self.copy()
        wrong['run'].update(status='in_progress', conclusion='success')
        self.assertTrue(receipt_problems(wrong), 'a pending run must not claim a conclusion')

    def test_times_are_utc_distinct_and_in_order(self):
        for path, value in ((('captured_at',), '2026-11-04 10:39:47'), (('run', 'createdAt'), '2026-11-04T06:57:21+00:00'),
                            (('run', 'updatedAt'), 'yesterday'), (('run_query', 'clock_read_before_query_at'), '10:39')):
            wrong = self.copy()
            target = wrong
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            self.assertTrue(receipt_problems(wrong), path)
        wrong = self.copy()
        wrong['run']['updatedAt'], wrong['run']['createdAt'] = wrong['run']['createdAt'], wrong['run']['updatedAt']
        self.assertTrue(receipt_problems(wrong), 'updated before created')
        wrong = self.copy()
        wrong['captured_at'] = wrong['run']['createdAt']
        self.assertTrue(receipt_problems(wrong), 'captured before the run finished updating')
        self.assertNotIn(self.receipt['captured_at'], (self.receipt['run']['createdAt'], self.receipt['run']['updatedAt']))

    def test_baseline_must_be_a_full_sha_and_independent_of_the_run_head(self):
        wrong = self.copy()
        wrong['repository_commit'] = wrong['repository_commit'][:12]
        self.assertTrue(receipt_problems(wrong))
        wrong = self.copy()
        wrong['repository_commit'] = 'b' * 40
        self.assertTrue(receipt_problems(wrong), 'config and sources are bound to the baseline commit')
        self.assertNotEqual(self.receipt['repository_commit'], self.receipt['run']['headSha'],
                            'the queried run did not use the inspected main')

    def test_production_flags_stay_unverified_whatever_the_run_says(self):
        for flag in FLAGS:
            for value in ('on', 'off', 'true', 'false', True, False, None):
                wrong = self.copy()
                wrong['production_flags'][flag] = value
                self.assertTrue(receipt_problems(wrong), (flag, value))
        wrong = self.copy()
        wrong['production_reason'] = ' '
        self.assertTrue(receipt_problems(wrong))

    def test_source_evidence_is_bound_to_lines_and_quotes(self):
        by_id = {entry['id']: i for i, entry in enumerate(self.receipt['sources'])}
        wrong = self.copy()
        wrong['sources'][by_id['config-vars-object']]['excerpt'] += '\n'
        self.assertTrue(receipt_problems(wrong), 'altered quote')
        wrong = self.copy()
        wrong['sources'][by_id['config-vars-object']]['start_line'] += 1
        self.assertTrue(receipt_problems(wrong), 'altered line range')
        wrong = self.copy()
        wrong['sources'][by_id['config-vars-object']]['end_line'] -= 1
        wrong['sources'][by_id['config-vars-object']]['excerpt'] = '\n'.join(
            wrong['sources'][by_id['config-vars-object']]['excerpt'].split('\n')[:-1])
        self.assertTrue(receipt_problems(wrong), 'a partial vars object cannot prove absence')
        wrong = self.copy()
        wrong['sources'][by_id['workflow-gate']]['excerpt'] = 'jobs:\n  check:\n    if: always()'
        self.assertTrue(receipt_problems(wrong))
        wrong = self.copy()
        wrong['sources'][by_id['workflow-identity']]['excerpt'] = 'name: Daily fishing evidence'
        self.assertTrue(receipt_problems(wrong))
        wrong = self.copy()
        wrong['sources'][by_id['flag-allowlist']]['commit'] = 'c' * 40
        self.assertTrue(receipt_problems(wrong))
        wrong = self.copy()
        wrong['sources'][by_id['flag-allowlist']]['path'] = 'scripts/other.mjs'
        self.assertTrue(receipt_problems(wrong))
        wrong = self.copy()
        del wrong['sources'][by_id['page-evidence-rule']]
        self.assertTrue(receipt_problems(wrong))

    def test_every_field_is_required_and_no_vessel_ids_leak(self):
        for key in FIELDS:
            wrong = self.copy()
            del wrong[key]
            self.assertTrue(receipt_problems(wrong), key)
        wrong = self.copy()
        wrong['limits'] = ['MMSI 367000000']
        self.assertTrue(receipt_problems(wrong))


class PageCitationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = PAGE.read_text()
        cls.receipt = load()

    def test_fleet_row_cites_the_receipt_baseline_and_run(self):
        self.assertEqual(page_problems(self.page, self.receipt), [])
        row, _ = fleet_row(self.page)
        self.assertEqual(row[2], 'PREVIEW')

    def test_missing_citation_status_upgrade_or_global_repin_fails(self):
        row, _ = fleet_row(self.page)
        cases = {
            'citation removed': self.page.replace(RECEIPT.split('/')[-1], 'something-else.json'),
            'status upgraded': self.page.replace('| PREVIEW | The layers are admin-only', '| LIVE | The layers are admin-only'),
            'run id altered': self.page.replace(str(self.receipt['run']['databaseId']), '1'),
            'baseline dropped': self.page.replace(self.receipt['repository_commit'], 'f' * 40),
            'global re-pin': self.page.replace(HISTORICAL_PIN, self.receipt['repository_commit'], 1),
            'exception dropped': self.page.replace('every other row stays pinned', 'every row is current'),
            'production no longer unverified': self.page.replace('no deploy record was captured', 'the flags are on'),
            'absent read as false': self.page.replace('not as `false`', 'as `false`'),
            'success read as healthy': self.page.replace('does not show that the job ran', 'shows the fleet is healthy'),
            'publication hold dropped': self.page.replace('stays under the publication hold', 'can go ahead'),
            'fleet distinction dropped': self.page.replace('not charter grounds or bite evidence', 'also charter grounds'),
        }
        for label, page in cases.items():
            self.assertNotEqual(page, self.page, label)
            self.assertTrue(page_problems(page, self.receipt), label)

    def test_other_rows_and_dependency_receipts_are_untouched(self):
        _, rows = fleet_row(self.page)
        self.assertEqual(rows['Charter grounds'][2], 'DESIGNED')
        self.assertEqual(rows['Bite evidence'][2], 'DESIGNED')
        self.assertIn('research/receipts/charter-grounds-test-2026-11-04.json', rows['Charter grounds'][1])
        self.assertIn('research/receipts/bite-evidence-health-2026-11-04.json', rows['Bite evidence'][1])
        self.assertNotIn('fleet-activity-state', ' '.join(rows['Coast map (regional chart and seabed views)']))
        self.assertIn(HISTORICAL_PIN, self.page.splitlines()[0])
        self.assertIn('did not exist at the historical pin', self.page)
        self.assertIn(self.receipt['repository_commit'], self.page.splitlines()[0])


class ManifestBindingTest(unittest.TestCase):
    def test_manifest_lists_the_receipt_with_its_bytes(self):
        recorded = json.loads((RECEIPTS / 'manifest.json').read_text())['files']
        self.assertEqual(recorded.get(Path(RECEIPT).name), hashlib.sha256((ROOT / RECEIPT).read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()
