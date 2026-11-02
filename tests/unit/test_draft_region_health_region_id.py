"""draft-region-health report: --region must be a plain region id, else exit 2 before any read or write (RF0310-13)."""
import json
from pathlib import Path

import pytest

from tests.unit.test_draft_region_health_report import report

PLAIN = '--region must be a plain region id'
BAD = ['../evil', 'a\nb', '.hidden', 'Monterey', 'a b', '', 'a' * 65, 'a/b', 'central-coast\n', '_x', '-x']


def plant(folder):
    folder.mkdir(parents=True)
    evidence = {'health': {'sources_ok': 1, 'sources_total': 1, 'issues': [], 'critical_available': True},
                'sources': {'harbor': {'status': 'ok'}}}
    (folder / 'latest.json').write_text(json.dumps(evidence))
    (folder / 'regulations-health.json').write_text(json.dumps({'review_required': []}))


def run(tmp_path, region, summary=True):
    argv = [f'--region={region}', '--root', str(tmp_path / 'rehearsal')]
    argv += ['--summary', str(tmp_path / 'summary.md')] if summary else []
    try:
        return report.main(argv)
    except SystemExit as stop:
        return stop.code


def test_traversal_refused_before_any_read_or_write(tmp_path, monkeypatch):
    plant(tmp_path / 'evil' / 'evil')  # where rehearsal/../evil/regions/../evil points
    (tmp_path / 'summary.md').write_bytes(b'earlier step\n')

    def no_read(*args, **kwargs):
        raise AssertionError('read under --root')
    monkeypatch.setattr(Path, 'read_text', no_read)
    monkeypatch.setattr(Path, 'is_file', no_read)
    assert run(tmp_path, '../evil') == 2
    assert (tmp_path / 'summary.md').read_bytes() == b'earlier step\n'


@pytest.mark.parametrize('region', BAD)
def test_non_plain_region_is_usage_error_without_echo(tmp_path, capsys, region):
    if region == 'Monterey':  # a valid receipt where the upper-case id would point
        plant(tmp_path / 'rehearsal' / region / 'regions' / region)
    assert run(tmp_path, region) == 2
    assert not (tmp_path / 'summary.md').exists()
    err = capsys.readouterr().err
    assert PLAIN in err
    if region:
        assert region not in err


@pytest.mark.parametrize('region', ['central-coast', 'sf_bay', 'a' * 64, '9'])
def test_plain_region_behaves_as_before(tmp_path, region):
    plant(tmp_path / 'rehearsal' / region / 'regions' / region)
    assert run(tmp_path, region) == 0
    assert (tmp_path / 'summary.md').read_text().startswith(f'## {region} draft rehearsal\n')


@pytest.mark.parametrize('region', ['central-coast', 'sf_bay'])
def test_plain_region_without_receipt_keeps_message(tmp_path, region):
    assert run(tmp_path, region) == 'Draft collector produced no regional receipt'


def test_missing_summary_still_reported_first(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv('GITHUB_STEP_SUMMARY', raising=False)
    assert run(tmp_path, '../evil', summary=False) == 2
    err = capsys.readouterr().err
    assert '--summary or GITHUB_STEP_SUMMARY is required' in err
    assert PLAIN not in err
