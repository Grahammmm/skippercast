"""draft-region-health report: past-day catches-* failures go to the coverage gate (NB-SC-04)."""
import importlib.util
import json

import pytest

from tests._support import ROOT

_spec = importlib.util.spec_from_file_location('draft_region_health_report',
                                               ROOT / 'scripts/draft_region_health_report.py')
report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(report)

REGION = 'bodega-point-reyes'
REVIEW = 'Draft evidence needs review before regional promotion'
EXTRA = 'Past-day landing reports that failed: 1 (left to the 5-of-7 coverage gate).\n'


def write(tmp_path, sources, critical=True, review=()):
    root = tmp_path / 'rehearsal' / REGION / 'regions' / REGION
    root.mkdir(parents=True)
    issues = [ident for ident, status in sources.items() if status != 'ok']
    evidence = {'health': {'sources_ok': len(sources) - len(issues), 'sources_total': len(sources),
                           'issues': issues, 'critical_available': critical},
                'sources': {ident: {'status': status} for ident, status in sources.items()}}
    (root / 'latest.json').write_text(json.dumps(evidence))
    (root / 'regulations-health.json').write_text(json.dumps({'review_required': list(review)}))
    return evidence


def run(tmp_path):
    summary = tmp_path / 'summary.md'
    try:
        code = report.main(['--region', REGION, '--root', str(tmp_path / 'rehearsal'), '--summary', str(summary)])
    except SystemExit as stop:
        code = stop.code
    return code, summary.read_text() if summary.exists() else ''


def old_heredoc_summary(evidence, review):
    """The workflow heredoc's summary before NB-SC-04, verbatim."""
    health = evidence['health']
    source_failures = [ident for ident in health['issues']
                       if evidence['sources'][ident]['status'] in ('failed', 'retained')]
    text = f"## {REGION} draft rehearsal\n"
    text += f"{health['sources_ok']}/{health['sources_total']} sources healthy; legal source changes or failures: {len(review)}; source fetch failures: {len(source_failures)}.\n"
    text += 'This is unpublished source evidence, not fishing permission or site clearance.\n'
    for issue in health['issues']:
        text += f'- {issue}\n'
    return text


def test_only_past_day_report_failed_is_healthy(tmp_path):
    write(tmp_path, {'harbor': 'ok', 'catches-2026-10-27': 'failed', 'catches-2026-10-28': 'ok'})
    code, summary = run(tmp_path)
    assert code == 0
    assert '- catches-2026-10-27\n' in summary
    assert EXTRA in summary
    assert 'source fetch failures: 0.' in summary


@pytest.mark.parametrize('status', ['failed', 'retained'])
def test_other_source_fetch_failure_still_red(tmp_path, status):
    write(tmp_path, {'harbor': status, 'catches-2026-10-27': 'ok'})
    assert run(tmp_path)[0] == REVIEW


def test_past_day_failure_still_counted_with_other_failure(tmp_path):
    write(tmp_path, {'harbor': 'failed', 'catches-2026-10-27': 'failed'})
    code, summary = run(tmp_path)
    assert code == REVIEW
    assert 'source fetch failures: 1.' in summary and EXTRA in summary


def test_coverage_gate_still_red_with_past_day_failure(tmp_path):
    write(tmp_path, {'harbor': 'ok', 'catches-2026-10-27': 'failed'}, critical=False)
    code, summary = run(tmp_path)
    assert code == REVIEW
    assert EXTRA in summary


def test_legal_review_without_fetch_failures_is_red(tmp_path):
    write(tmp_path, {'harbor': 'ok'}, review=['ca-ccr-title-14'])
    assert run(tmp_path)[0] == REVIEW


def test_catches_prefix_must_lead_the_id(tmp_path):
    write(tmp_path, {'harbor-catches-2026-10-27': 'failed'})
    assert run(tmp_path)[0] == REVIEW


def test_missing_receipt_is_red(tmp_path):
    (tmp_path / 'rehearsal').mkdir()
    code, summary = run(tmp_path)
    assert code == 'Draft collector produced no regional receipt'
    assert summary == ''


def test_issue_missing_from_sources_is_named(tmp_path):
    evidence = write(tmp_path, {'harbor': 'ok'})
    evidence['health']['issues'] = ['ghost-feed']
    (tmp_path / 'rehearsal' / REGION / 'regions' / REGION / 'latest.json').write_text(json.dumps(evidence))
    code, _ = run(tmp_path)
    assert isinstance(code, str) and 'ghost-feed' in code


@pytest.mark.parametrize('sources,review', [
    ({'harbor': 'ok', 'tides': 'stale'}, []),
    ({'harbor': 'failed', 'tides': 'retained', 'catches-2026-10-28': 'ok'}, ['ca-ccr-title-14']),
])
def test_summary_identical_to_old_heredoc_without_exclusions(tmp_path, sources, review):
    evidence = write(tmp_path, sources, review=review)
    assert run(tmp_path)[1] == old_heredoc_summary(evidence, review)


def test_usage_error_exits_2(tmp_path, monkeypatch):
    monkeypatch.delenv('GITHUB_STEP_SUMMARY', raising=False)
    with pytest.raises(SystemExit) as stop:
        report.main(['--region', REGION, '--root', str(tmp_path)])
    assert stop.value.code == 2
