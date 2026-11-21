"""draft-region-health report: failed or retained sources missing from health.issues are unreadable (RF1940-8)."""
import json

import pytest

from tests.unit.test_draft_region_health_inputs import HEADING, assert_named, folder
from tests.unit.test_draft_region_health_report import REGION, REVIEW, run, write

OMITTED = 'latest.json: health.issues omits failed or retained sources'


def unlist(tmp_path, *idents):
    path = folder(tmp_path) / 'latest.json'
    evidence = json.loads(path.read_text())
    evidence['health']['issues'] = [i for i in evidence['health']['issues'] if i not in idents]
    path.write_text(json.dumps(evidence))


@pytest.mark.parametrize('status', ['failed', 'retained'])
def test_omitted_failed_or_retained_source_is_unreadable(tmp_path, status):
    write(tmp_path, {'harbor': 'ok', 'tides': status})
    unlist(tmp_path, 'tides')
    assert_named(tmp_path, OMITTED)


def test_partially_omitted_failures_also_refuse(tmp_path):
    secret = 'bad\nkey <script>'
    write(tmp_path, {'a': 'failed', 'b': 'retained', secret: 'failed'})
    unlist(tmp_path, secret, 'b')
    code, summary = run(tmp_path)
    assert code == 'Draft evidence unreadable: ' + OMITTED
    assert summary == f'{HEADING}Draft evidence unreadable: {OMITTED}\n'
    assert 'script' not in summary


def test_omitted_catches_failure_is_inconsistent_not_healthy(tmp_path):
    write(tmp_path, {'harbor': 'ok', 'catches-2026-10-27': 'failed'})
    unlist(tmp_path, 'catches-2026-10-27')
    assert_named(tmp_path, OMITTED)


def test_listed_catches_failure_is_still_healthy(tmp_path):
    write(tmp_path, {'harbor': 'ok', 'catches-2026-10-27': 'failed'})
    assert run(tmp_path)[0] == 0


def test_existing_shape_errors_precede_membership_check(tmp_path):
    write(tmp_path, {'harbor': 'failed'})
    path = folder(tmp_path) / 'latest.json'
    evidence = json.loads(path.read_text())
    evidence['health']['issues'] = 'harbor'
    path.write_text(json.dumps(evidence))
    assert_named(tmp_path, 'latest.json: health.issues missing or wrong type')


def test_complete_and_nonfailure_controls_are_unchanged(tmp_path):
    write(tmp_path, {'harbor': 'ok', 'tides': 'stale', 'wx': 'missing'})
    unlist(tmp_path, 'tides', 'wx')
    assert run(tmp_path)[0] == 0
    write(tmp_path / 'e', {})
    assert_named(tmp_path / 'e', 'latest.json: sources must not be empty')
    write(tmp_path / 'f', {'harbor': 'failed'})
    assert run(tmp_path / 'f')[0] == REVIEW
