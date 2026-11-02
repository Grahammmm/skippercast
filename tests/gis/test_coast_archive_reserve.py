"""RF2310-9: archive_segment reserve_bytes is a whole byte count 0..10**15, refused first."""
import shutil
import sys

import pytest

from tests.gis.test_coast_segment_close import (  # noqa: F401  (fixtures)
    HEAD, _closed_template, archive_segment, close_common, closed, exclusive_synthetic_campaign, ledger_module,
)

pytestmark = pytest.mark.gis
MESSAGE = 'reserve_bytes must be a whole number of bytes from 0 to 10\\*\\*15'


def boom(*args, **kwargs):
    raise AssertionError('ran before the reserve check')


class NoBindings:
    @property
    def bindings(self):
        boom()


def archive(f, resolver, reserve):
    return archive_segment.archive(resolver, campaign_path=f.campaign_path, ledger=f.ledger,
                                   campaign_ledger=f.campaign_ledger, head=HEAD, reserve_bytes=reserve, close_id='close01')


@pytest.mark.parametrize('reserve', [-1, -200 * 10**9, True, False, 1.5, None, '0', 10**15 + 1])
def test_bad_reserve_refused_before_anything_runs(closed, monkeypatch, reserve):
    monkeypatch.setattr(shutil, 'disk_usage', boom)
    monkeypatch.setattr(archive_segment, 'write_retained', boom)
    monkeypatch.setattr(close_common.coast_ledger, 'append_index', boom)
    before = closed.ledger.read_bytes()
    for resolver in (NoBindings(), closed.resolver()):
        with pytest.raises(close_common.Refused, match=MESSAGE):
            archive(closed, resolver, reserve)
    assert closed.ledger.read_bytes() == before
    assert not any(closed.archive.iterdir())


def free(n):
    return lambda path: shutil._ntuple_diskusage(total=n, used=0, free=n)


def test_reserve_zero_closes_as_today(closed):
    result = archive(closed, closed.resolver(), 0)
    assert ledger_module.verify(closed.ledger)[-1]['kind'] == 'archived'
    assert result['manifest'] == ledger_module.verify(closed.ledger)[-1]['manifest']


def test_reserve_max_passes_the_check(closed, monkeypatch):
    monkeypatch.setattr(shutil, 'disk_usage', free(2 * 10**15))
    archive(closed, closed.resolver(), 10**15)
    assert ledger_module.verify(closed.ledger)[-1]['kind'] == 'archived'


@pytest.mark.parametrize('reserve', [1, 10**6, 10**15])
def test_reserve_above_free_space_still_insufficient(closed, monkeypatch, reserve):
    monkeypatch.setattr(shutil, 'disk_usage', free(0))
    with pytest.raises(close_common.Refused, match='insufficient archive capacity after reserve'):
        archive(closed, closed.resolver(), reserve)
    assert ledger_module.verify(closed.ledger)[-1]['kind'] == 'verdict'
    assert not any(closed.archive.iterdir())


class Loaded(Exception):
    pass


def run_cli(monkeypatch, tmp_path, *reserve):
    def load_json(path):
        raise Loaded(path)
    monkeypatch.setattr(archive_segment, 'load_json', load_json)
    files = {k: str(tmp_path / k) for k in ('roots', 'campaign', 'src', 'dest', 'ledger', 'campaign-ledger', 'header')}
    argv = ['archive_segment.py', '--allowed-root-id', 'queue:synthetic', '--close-id', 'close01', *reserve]
    for key, value in files.items():
        argv += ['--' + key, value]
    monkeypatch.setattr(sys, 'argv', argv)
    return archive_segment.main()


@pytest.mark.parametrize('text', ['-1', '-200000000000', 'abc', '1e3', '1.5', '', '1000000000000001'])
def test_cli_bad_reserve_exits_2_before_roots_load(monkeypatch, tmp_path, capsys, text):
    with pytest.raises(SystemExit) as exited:
        run_cli(monkeypatch, tmp_path, '--reserve-bytes', text)
    assert exited.value.code == 2
    assert 'reserve_bytes must be a whole number of bytes from 0 to 10**15' in capsys.readouterr().err


@pytest.mark.parametrize('reserve', [('--reserve-bytes', '0'), ('--reserve-bytes', '1000000000000000'), ()])
def test_cli_good_reserve_reaches_roots_load(monkeypatch, tmp_path, reserve):
    with pytest.raises(Loaded):
        run_cli(monkeypatch, tmp_path, *reserve)
