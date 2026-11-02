"""draft-region-health report: unreadable or misshaped evidence is named (exit 1), never a traceback (RF2310-2)."""
import json

import pytest

from tests.unit.test_draft_region_health_report import REGION, old_heredoc_summary, run, write

UNREADABLE = 'Draft evidence unreadable: '
HEADING = f'## {REGION} draft rehearsal\n'


def folder(tmp_path):
    return tmp_path / 'rehearsal' / REGION / 'regions' / REGION


def assert_named(tmp_path, message):
    code, summary = run(tmp_path)
    assert code == UNREADABLE + message
    assert summary == f'{HEADING}{UNREADABLE}{message}\n'


def test_missing_regulations_health_is_named(tmp_path):
    write(tmp_path, {'harbor': 'ok'})
    (folder(tmp_path) / 'regulations-health.json').unlink()
    assert_named(tmp_path, 'regulations-health.json: unreadable JSON')


@pytest.mark.parametrize('name', ['latest.json', 'regulations-health.json'])
@pytest.mark.parametrize('body', [b'{"health": {"issues": [', b'\xff\xfe{}', b'[' * 100000, b''])
def test_unreadable_json_is_named(tmp_path, name, body):
    write(tmp_path, {'harbor': 'ok'})
    (folder(tmp_path) / name).write_bytes(body)
    assert_named(tmp_path, f'{name}: unreadable JSON')


def test_receipt_is_a_directory_is_named(tmp_path):
    write(tmp_path, {'harbor': 'ok'})
    (folder(tmp_path) / 'regulations-health.json').unlink()
    (folder(tmp_path) / 'regulations-health.json').mkdir()
    assert_named(tmp_path, 'regulations-health.json: unreadable JSON')


def mutate(evidence, rules, case):
    health, sources = evidence['health'], evidence['sources']
    if case == 'health':
        del evidence['health']
    elif case == 'health.issues':
        health['issues'] = 'harbor'
    elif case == 'health.issues.item':
        health['issues'] = [{'id': 'harbor'}]
    elif case in ('health.sources_ok', 'health.sources_total'):
        health[case.split('.')[1]] = True if case.endswith('ok') else '2'
    elif case == 'health.critical_available':
        health['critical_available'] = 'yes'
    elif case == 'sources':
        evidence['sources'] = ['harbor']
    elif case == 'sources.harbor':
        sources['harbor'] = ['failed']
    elif case == 'sources.harbor.status':
        sources['harbor']['status'] = None
    elif case == 'review_required':
        del rules['review_required']
    elif case == 'review_required.type':
        rules['review_required'] = 'ca-ccr-title-14'


@pytest.mark.parametrize('case,message', [
    ('health', 'latest.json: health missing or wrong type'),
    ('health.issues', 'latest.json: health.issues missing or wrong type'),
    ('health.issues.item', 'latest.json: health.issues missing or wrong type'),
    ('health.sources_ok', 'latest.json: health.sources_ok missing or wrong type'),
    ('health.sources_total', 'latest.json: health.sources_total missing or wrong type'),
    ('health.critical_available', 'latest.json: health.critical_available missing or wrong type'),
    ('sources', 'latest.json: sources missing or wrong type'),
    ('sources.harbor', 'latest.json: sources.harbor missing or wrong type'),
    ('sources.harbor.status', 'latest.json: sources.harbor.status missing or wrong type'),
    ('review_required', 'regulations-health.json: review_required missing or wrong type'),
    ('review_required.type', 'regulations-health.json: review_required missing or wrong type'),
])
def test_misshaped_key_is_named(tmp_path, case, message):
    evidence = write(tmp_path, {'harbor': 'failed', 'tides': 'ok'})
    rules = {'review_required': []}
    mutate(evidence, rules, case)
    (folder(tmp_path) / 'latest.json').write_text(json.dumps(evidence))
    (folder(tmp_path) / 'regulations-health.json').write_text(json.dumps(rules))
    assert_named(tmp_path, message)


@pytest.mark.parametrize('document,message', [
    ([], 'latest.json: health missing or wrong type'), ('text', 'latest.json: health missing or wrong type'),
    (None, 'latest.json: health missing or wrong type')])
def test_non_object_receipt_is_named(tmp_path, document, message):
    write(tmp_path, {'harbor': 'ok'})
    (folder(tmp_path) / 'latest.json').write_text(json.dumps(document))
    assert_named(tmp_path, message)


def test_non_object_rules_is_named(tmp_path):
    write(tmp_path, {'harbor': 'ok'})
    (folder(tmp_path) / 'regulations-health.json').write_text('[]')
    assert_named(tmp_path, 'regulations-health.json: review_required missing or wrong type')


def test_missing_status_names_key_not_page_text(tmp_path, capsys):
    page = '<html>Fish Counts 12 lingcod TOKEN=abc</html>'
    evidence = write(tmp_path, {'harbor': 'failed'})
    evidence['sources']['harbor'] = {'issue': f'HTTPStatusError: {page}'}
    (folder(tmp_path) / 'latest.json').write_text(json.dumps(evidence))
    assert_named(tmp_path, 'latest.json: sources.harbor.status missing or wrong type')
    code, summary = run(tmp_path)
    for text in (code, summary, capsys.readouterr().out):
        assert not [word for word in ('html', 'Fish', 'TOKEN', 'lingcod', 'abc') if word in text]


def test_healthy_summary_unchanged(tmp_path):
    evidence = write(tmp_path, {'harbor': 'ok', 'tides': 'stale'})
    code, summary = run(tmp_path)
    assert code == 0
    assert summary == old_heredoc_summary(evidence, [])
