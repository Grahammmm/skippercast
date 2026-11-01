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
    assert '- catches-2026-10-27: other\n' in summary  # NB-SC-05: failed ids carry a class
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
    expected = old_heredoc_summary(evidence, review)
    for ident, status in sources.items():  # NB-SC-05: only failed/retained lines gain a class
        if status in ('failed', 'retained'):
            expected = expected.replace(f'- {ident}\n', f'- {ident}: other\n')
    assert run(tmp_path)[1] == expected


def test_usage_error_exits_2(tmp_path, monkeypatch):
    monkeypatch.delenv('GITHUB_STEP_SUMMARY', raising=False)
    with pytest.raises(SystemExit) as stop:
        report.main(['--region', REGION, '--root', str(tmp_path)])
    assert stop.value.code == 2


# NB-SC-05: each failed/retained source logs one error class, never page text.

TYPES = {'HTTPStatusError': 'http', 'TransportError': 'transport', 'TLSVerificationError': 'transport',
         'TimeoutError': 'transport', 'ConnectionError': 'transport', 'ContractError': 'contract',
         'BodyTooLarge': 'contract', 'DisallowedHost': 'contract', 'ValueError': 'parse', 'KeyError': 'parse',
         'IndexError': 'parse', 'TypeError': 'parse', 'JSONDecodeError': 'parse',
         'UnicodeDecodeError': 'parse', 'RuntimeError': 'other', 'valueerror': 'other'}


@pytest.mark.parametrize('issue,cls', [(f'{name}: went wrong', cls) for name, cls in TYPES.items()] + [
    ('ValueError: Empty response', 'empty'), ('ValueError: Empty response body', 'parse'),
    ('ValueError: empty response', 'parse'), ('ContractError: Empty response', 'contract'),
    ('HTTPStatusError: HTTP 503 from www.example.gov', 'http 503'), ('HTTPStatusError: HTTP 404', 'http 404'),
    ('HTTPStatusError: 503 Service Unavailable', 'http 503'), ('HTTPStatusError: HTTP 5030', 'http'),
    ('HTTPStatusError: HTTP unavailable', 'http'), ('HTTPStatusError: <html>503</html>', 'http'),
    ('HTTPStatusError', 'http'),
    (None, 'other'), ('', 'other'), ('   ', 'other'), (42, 'other'), ('no colon here', 'other'),
])
def test_error_class_edges(issue, cls):
    assert report.error_class(issue) == cls


def write_issues(tmp_path, sources):
    """sources: ident -> (status, issue or None)."""
    evidence = write(tmp_path, {ident: status for ident, (status, _) in sources.items()})
    for ident, (_, issue) in sources.items():
        if issue is not None:
            evidence['sources'][ident]['issue'] = issue
    (tmp_path / 'rehearsal' / REGION / 'regions' / REGION / 'latest.json').write_text(json.dumps(evidence))


def test_class_lines_in_log_and_summary_in_issue_order(tmp_path, capsys):
    write_issues(tmp_path, {
        'tides': ('retained', 'TransportError: timed out'), 'harbor': ('ok', None), 'buoy': ('stale', 'ValueError: old'),
        'catches-2026-10-27': ('failed', 'ValueError: Empty response'),
        'regs': ('failed', 'HTTPStatusError: HTTP 503 from regs.example.gov'), 'gone': ('missing', None)})
    code, summary = run(tmp_path)
    out = capsys.readouterr().out
    assert code == REVIEW
    assert out == (f'{REGION} tides: transport\n{REGION} catches-2026-10-27: empty\n'
                   f'{REGION} regs: http 503\n')
    assert '- tides: transport\n- buoy\n- catches-2026-10-27: empty\n- regs: http 503\n- gone\n' in summary
    assert 'regs.example.gov' not in out + summary and 'timed out' not in out + summary


def test_retained_source_uses_its_own_issue(tmp_path, capsys):
    write_issues(tmp_path, {'harbor': ('retained', 'ContractError: x'), 'tides': ('failed', 'KeyError: x')})
    assert '- harbor: contract\n- tides: parse\n' in run(tmp_path)[1]
    assert capsys.readouterr().out == f'{REGION} harbor: contract\n{REGION} tides: parse\n'


def test_missing_and_stale_get_no_class_line(tmp_path, capsys):
    write_issues(tmp_path, {'harbor': ('missing', 'ValueError: x'), 'tides': ('stale', 'HTTPStatusError: HTTP 500')})
    code, summary = run(tmp_path)
    assert capsys.readouterr().out == ''
    assert code == 0 and '- harbor\n- tides\n' in summary and ': ' not in summary.split('clearance.\n')[1]


PAGE = '<html>Fish Counts 12 lingcod ... TOKEN=abc</html>'


@pytest.mark.parametrize('issue', [f'{name}: {PAGE}' for name in ('ValueError', 'HTTPStatusError', 'RuntimeError')]
                         + [PAGE.replace(' ... ', ': ')])
def test_page_text_never_printed(tmp_path, capsys, issue):
    write_issues(tmp_path, {'harbor': ('failed', issue)})
    _, summary = run(tmp_path)
    out = capsys.readouterr().out
    for text in (out, summary):
        assert not [word for word in ('html', 'Fish', 'TOKEN', 'lingcod', 'abc') if word in text]
