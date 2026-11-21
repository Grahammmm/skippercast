"""SCA-404: low measured cost cannot prove required CI work executed."""
import contextlib
import io
import json

from scripts import pytest_report


RUN = {
    'databaseId': 1, 'createdAt': '2026-11-01T10:00:00Z', 'updatedAt': '2026-11-01T10:05:00Z',
    'status': 'completed', 'conclusion': 'success',
    'jobs': [{'name': 'check', 'status': 'completed', 'conclusion': 'success',
              'startedAt': '2026-11-01T10:00:10Z', 'completedAt': '2026-11-01T10:04:00Z'}],
}
SKIPPED = {'name': 'optional', 'conclusion': 'skipped'}


def test_all_skipped_receipt_holds_even_under_budget():
    # A success run containing only a skipped job previously authorized admission.
    run = RUN | {'jobs': [SKIPPED]}
    for required in (None, {'optional'}, {'check'}):
        text, ok = pytest_report.ci_budget([run], required)
        assert not ok
        assert '| **Total** | **5.00** | **0.00** | HOLD |' in text


def test_applicable_job_set_must_be_supplied_and_complete():
    # Executing one cheap job is not evidence that another required job ran.
    for required in (None, set(), {''}, {'check', 'missing'}):
        assert not pytest_report.ci_budget([RUN], required)[1]
    assert pytest_report.ci_budget([RUN], {'check'})[1]


def test_optional_skip_passes_but_required_skip_does_not():
    run = RUN | {'jobs': RUN['jobs'] + [SKIPPED]}
    text, ok = pytest_report.ci_budget([run], {'check'})
    assert ok and '| 1/optional | — | 0.00 | skipped |' in text
    assert not pytest_report.ci_budget([run], {'check', 'optional'})[1]
    # Duplicate names must not allow a successful job to mask a skipped required one.
    assert not pytest_report.ci_budget([run | {'jobs': RUN['jobs'] + [SKIPPED | {'name': 'check'}]}], {'check'})[1]


def test_cli_requires_explicit_job_set_and_accepts_optional_skip(tmp_path):
    path = tmp_path / 'runs.json'
    path.write_text(json.dumps([RUN | {'jobs': RUN['jobs'] + [SKIPPED]}]))
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert pytest_report.main(['--ci-runs', str(path)]) == 1
        assert pytest_report.main(['--ci-runs', str(path), '--required-job', 'check']) == 0
    assert '| HOLD |' in output.getvalue() and '| PASS |' in output.getvalue()
