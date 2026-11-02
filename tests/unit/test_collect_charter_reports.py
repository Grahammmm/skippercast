"""RF0510-3: research/scripts/collect_charter_reports.py is importable and tolerant of one bad row."""
import datetime
import importlib.util
import json
import sys

import pytest

from tests._support import FIXTURES, ROOT

SCRIPT = ROOT / 'research' / 'scripts' / 'collect_charter_reports.py'
FIXTURE = (FIXTURES / 'charter-reports' / 'dock-totals-2026-09-20.html').read_text(encoding='utf-8')
URL = 'https://www.socalfishreports.com/dock_totals/boats.php?date=2026-09-20'


def load():
    spec = importlib.util.spec_from_file_location('collect_charter_reports_under_test', SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def page_for(day, base=FIXTURE):
    d = datetime.date.fromisoformat(day)
    return base.replace('September 20, 2026', f"{d:%B} {d.day}, {d.year}")


def fake_fetch(bad_days=()):
    def fetch(url):
        day = url.rsplit('=', 1)[1]
        return (b'\xff\xfe not utf-8 \xff' if day in bad_days else page_for(day).encode('utf-8')), 200
    return fetch


def test_import_parses_no_arguments_and_creates_no_folder(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['collect_charter_reports.py', '--bogus'])
    mod = load()
    assert callable(mod.main) and callable(mod.collect) and callable(mod.parse_page)
    assert list(tmp_path.iterdir()) == []


def test_parse_page_returns_morro_bay_and_avila_rows():
    rows = load().parse_page('2026-09-20', FIXTURE, URL)
    assert [(r['boat'], r['port']) for r in rows] == [
        ('Example Boat', 'Morro Bay'), ('Other Boat', 'Avila Beach'), ('Twin Port Boat', 'Morro Bay'),
        ('Example Boat', 'Morro Bay'), ('Example Boat', 'Morro Bay')]
    assert rows[0] == {
        'date': '2026-09-20', 'boat': 'Example Boat', 'port': 'Morro Bay', 'ground': 'Out Front',
        'species': ['lingcod', 'rockfish', 'halibut'], 'trip': '12 Anglers 3/4 Day Out Front',
        'reported_catch': '1,200 Rockfish, 3 Lingcod (up to 9 pounds), 2 Lingcod Released, 0 Halibut',
        'source_url': URL, 'vessel_source_url': 'https://www.socalfishreports.com/boats/test'}
    assert rows[1]['vessel_source_url'] == 'https://www.socalfishreports.com/boats/other'
    assert rows[2]['ground'] is None


def test_row_without_boat_link_is_kept_with_null_url_and_day_ok(tmp_path):
    mod = load()
    unlinked = FIXTURE.replace('<a href="/boats/other">', '<a>')
    assert unlinked != FIXTURE
    before = mod.parse_page('2026-09-20', FIXTURE, URL)

    def fetch(url):
        return unlinked.encode('utf-8'), 200
    result = mod.collect('2026-09-20', tmp_path, fetch=fetch)
    assert result['status'] == 'ok'
    rows = result['records']
    assert len(rows) == len(before) == 5
    assert rows[1]['boat'] == 'Other Boat' and rows[1]['vessel_source_url'] is None
    assert rows[1] == dict(before[1], vessel_source_url=None)
    assert [r for i, r in enumerate(rows) if i != 1] == [r for i, r in enumerate(before) if i != 1]


def test_page_with_wrong_date_is_failed_with_existing_error(tmp_path):
    def fetch(url):
        return FIXTURE.encode('utf-8'), 200
    result = load().collect('2026-09-21', tmp_path, fetch=fetch)
    assert result == {'date': '2026-09-21', 'status': 'failed',
                      'error': 'Returned page date does not match requested date'}


def test_invalid_utf8_cached_page_fails_only_that_date(tmp_path, capsys):
    load().main(['--start', '2026-09-20', '--end', '2026-09-22', '--output', str(tmp_path)],
                fetch=fake_fetch(bad_days={'2026-09-21'}))
    data = json.loads((tmp_path / 'trip-facts.json').read_text(encoding='utf-8'))
    status = {c['date']: c['status'] for c in data['coverage']}
    assert status == {'2026-09-20': 'ok', '2026-09-21': 'failed', '2026-09-22': 'ok'}
    failed = [c for c in data['coverage'] if c['status'] == 'failed'][0]
    assert failed['error'].startswith('UnicodeDecodeError')
    assert sorted({r['date'] for r in data['records']}) == ['2026-09-20', '2026-09-22']
    assert len(data['records']) == 10


def test_cached_page_is_read_as_utf8_not_locale(tmp_path):
    mod = load()
    accented = FIXTURE.replace('Out Front', 'Pt. Buchón')

    def fetch(url):
        return accented.encode('utf-8'), 200
    result = mod.collect('2026-09-20', tmp_path, fetch=fetch)
    assert result['status'] == 'ok' and result['records'][0]['ground'] == 'Pt. Buchón'


def test_main_writes_complete_file_and_no_tmp(tmp_path, capsys):
    load().main(['--start', '2026-09-20', '--end', '2026-09-21', '--output', str(tmp_path)], fetch=fake_fetch())
    data = json.loads((tmp_path / 'trip-facts.json').read_text(encoding='utf-8'))
    assert [c['status'] for c in data['coverage']] == ['ok', 'ok']
    assert len(data['records']) == 10
    assert not (tmp_path / 'trip-facts.json.tmp').exists()
    summary = json.loads(capsys.readouterr().out)
    assert summary['pages'] == 2 and summary['failed'] == [] and summary['local_trips'] == 10


def test_failed_final_replace_keeps_old_file_bytes(tmp_path, monkeypatch):
    mod = load()
    old = b'{"coverage": [], "records": ["previous"]}'
    (tmp_path / 'trip-facts.json').write_bytes(old)

    def boom(src, dst):
        raise OSError('replace refused')
    monkeypatch.setattr(mod.os, 'replace', boom)
    with pytest.raises(OSError, match='replace refused'):
        mod.main(['--start', '2026-09-20', '--end', '2026-09-21', '--output', str(tmp_path)], fetch=fake_fetch())
    assert (tmp_path / 'trip-facts.json').read_bytes() == old


def test_end_before_start_is_usage_error(tmp_path, capsys):
    with pytest.raises(SystemExit) as exc:
        load().main(['--start', '2026-09-21', '--end', '2026-09-20', '--output', str(tmp_path / 'out')])
    assert exc.value.code == 2
    assert 'End must be on or after start' in capsys.readouterr().err
    assert not (tmp_path / 'out').exists()
