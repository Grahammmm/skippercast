"""Draft health receipts must match the request and their source rows (F20-11)."""
import json
import subprocess
import sys

import pytest

from tests._support import ROOT

REGION = 'fixture-coast'
CATCHES = [f'catches-2026-10-{day}' for day in range(21, 28)]


def run_report(tmp_path, evidence, rules):
    rehearsal = tmp_path / 'rehearsal'
    folder = rehearsal / REGION / 'regions' / REGION
    folder.mkdir(parents=True)
    (folder / 'latest.json').write_text(json.dumps(evidence))
    (folder / 'regulations-health.json').write_text(json.dumps(rules))
    summary = tmp_path / 'summary.md'
    result = subprocess.run(
        [sys.executable, str(ROOT / 'scripts/draft_region_health_report.py'),
         '--region', REGION, '--root', str(rehearsal), '--summary', str(summary)],
        text=True, capture_output=True, timeout=10,
    )
    return result, summary.read_text()


@pytest.fixture
def receipts():
    sources = {'buoy-fixture': {'status': 'ok'}}
    sources.update({ident: {'status': 'ok'} for ident in CATCHES[:5]})
    sources[CATCHES[5]] = {'status': 'failed'}
    sources[CATCHES[6]] = {'status': 'retained'}
    evidence = {'region_id': REGION, 'sources': sources, 'health': {
        'sources_total': 8, 'sources_ok': 6, 'critical_available': True, 'issues': CATCHES[5:],
        'recent_report_days_ok': 5,
    }}
    return evidence, {'region_id': REGION, 'review_required': []}


def test_five_of_seven_landing_reports_still_pass(tmp_path, receipts):
    result, summary = run_report(tmp_path, *receipts)
    assert result.returncode == 0, result.stderr
    assert '6/8 sources healthy' in summary and 'source fetch failures: 0.' in summary
    assert 'Past-day landing reports that failed: 2' in summary
    assert 'not fishing permission or site clearance' in summary


@pytest.mark.parametrize('case,field', [
    ('audit-control', 'latest.json: region_id'),
    ('foreign-feed', 'latest.json: region_id'),
    ('foreign-legal', 'regulations-health.json: region_id'),
    ('missing-feed-id', 'latest.json: region_id'),
    ('missing-legal-id', 'regulations-health.json: region_id'),
    ('empty', 'latest.json: sources'),
    ('wrong-total', 'latest.json: health.sources_total'),
    ('inflated-ok', 'latest.json: health.sources_ok'),
    ('negative-ok', 'latest.json: health.sources_ok'),
    ('unknown-status', 'latest.json: sources status'),
    ('critical-with-no-ok', 'latest.json: health.critical_available'),
])
def test_refuses_inconsistent_receipt(tmp_path, receipts, case, field):
    evidence, rules = receipts
    health = evidence['health']
    foreign = 'wrong-coast'
    if case in ('audit-control', 'empty'):
        evidence['sources'].clear()
        health.update(sources_total=0, sources_ok=0, issues=[])
    if case in ('audit-control', 'foreign-feed'):
        evidence['region_id'] = foreign
    if case in ('audit-control', 'foreign-legal'):
        rules['region_id'] = foreign
    if case == 'missing-feed-id':
        del evidence['region_id']
    if case == 'missing-legal-id':
        del rules['region_id']
    if case == 'wrong-total':
        health['sources_total'] = 7  # Plausible alone, but eight source rows exist.
    if case == 'inflated-ok':
        health['sources_ok'] = 8  # Two source rows are not ok.
    if case == 'negative-ok':
        health['sources_ok'] = -1
    if case == 'unknown-status':
        evidence['sources'][CATCHES[5]]['status'] = 'unsupported-status'
    if case == 'critical-with-no-ok':
        evidence['sources'] = {'buoy-fixture': {'status': 'stale'}}
        health.update(sources_ok=0, sources_total=1, issues=['buoy-fixture'])
    result, summary = run_report(tmp_path, evidence, rules)
    assert result.returncode == 1
    assert f'Draft evidence unreadable: {field}' in result.stderr and field in summary
    assert foreign not in result.stderr + summary
    assert 'unsupported-status' not in result.stderr + summary
