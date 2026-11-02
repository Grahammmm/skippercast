"""build_map_tiles.py: unknown layer refused before any build; checked .part + rename write (RF0420-1). No tippecanoe."""
import contextlib
from pathlib import Path
from unittest import mock

import pytest

from scripts import build_map_tiles as bmt

NAME = 'morro-bay-reef-outlines'
OLD = b'PMTiles\x03old-archive'


def fake_tippecanoe(data):
    def run(args, **kwargs):
        (Path(kwargs['cwd']) / args[args.index('-o') + 1]).write_bytes(data)
    return run


@pytest.fixture
def tiles(tmp_path):
    folder = tmp_path / 'dist' / 'tiles'
    folder.mkdir(parents=True)
    (folder / f'{NAME}.pmtiles').write_bytes(OLD)
    layer = (lambda: iter([]), 'title', 'attribution', 'description')
    with mock.patch.object(bmt, 'ROOT', tmp_path), mock.patch.object(bmt, 'TILES', folder), \
            mock.patch.dict(bmt.LAYERS, {NAME: layer}):
        yield folder


def run_build(data, **patches):
    with mock.patch.object(bmt.subprocess, 'run', side_effect=fake_tippecanoe(data)) as run:
        with mock.patch.multiple(bmt.shutil, **patches) if patches else contextlib.nullcontext():
            bmt.build('/opt/bin/tippecanoe', NAME)
    return run


@pytest.mark.parametrize('argv', [['nope'], [NAME, 'nope'], ['nope', 'socal-survey-habitat']])
def test_unknown_layer_exits_2_before_any_tool_lookup_or_build(argv, capsys):
    with mock.patch.object(bmt.subprocess, 'run') as run, mock.patch.object(bmt.shutil, 'which') as which, \
            mock.patch.object(bmt, 'build') as build:
        assert bmt.main(argv) == 2
    run.assert_not_called()
    which.assert_not_called()
    build.assert_not_called()
    err = capsys.readouterr().err
    assert err.strip() == ('build_map_tiles: unknown layer nope; '
                           'known: morro-bay-reef-outlines, socal-survey-habitat')


def test_unknown_layer_reported_without_tippecanoe(monkeypatch, capsys):
    monkeypatch.delenv('TIPPECANOE', raising=False)
    with mock.patch.object(bmt.shutil, 'which', return_value=None):
        assert bmt.main(['Morro-Bay-Reef-Outlines']) == 2
    assert 'unknown layer Morro-Bay-Reef-Outlines;' in capsys.readouterr().err


def test_no_tool_with_valid_names_keeps_todays_message(monkeypatch):
    monkeypatch.delenv('TIPPECANOE', raising=False)
    with mock.patch.object(bmt.shutil, 'which', return_value=None), mock.patch.object(bmt, 'build') as build:
        with pytest.raises(SystemExit) as stop:
            bmt.main([NAME])
    assert str(stop.value.code).startswith('tippecanoe not found; set TIPPECANOE')
    build.assert_not_called()


def test_valid_names_build_each_in_order(monkeypatch):
    monkeypatch.setenv('TIPPECANOE', '/opt/bin/tippecanoe')
    with mock.patch.object(bmt, 'build') as build:
        bmt.main([NAME, 'socal-survey-habitat'])
    assert [c.args for c in build.call_args_list] == [('/opt/bin/tippecanoe', NAME),
                                                      ('/opt/bin/tippecanoe', 'socal-survey-habitat')]


@pytest.mark.parametrize('data', [b'NOTPMTIL-archive', b'PMTiles\x02-v2', b'PMTi', b''])
def test_non_pmtiles_v3_output_refused_and_old_archive_kept(tiles, data):
    with pytest.raises(ValueError, match='Builder did not produce PMTiles v3'):
        run_build(data)
    assert (tiles / f'{NAME}.pmtiles').read_bytes() == OLD
    assert sorted(p.name for p in tiles.iterdir()) == [f'{NAME}.pmtiles']


def test_valid_output_replaces_archive_with_no_part_left(tiles, capsys):
    new = b'PMTiles\x03new-archive-bytes'
    run = run_build(new)
    args = run.call_args.args[0]
    assert args[:2] == ['tippecanoe', '--quiet'] and args[args.index('-l') + 1] == 'reefs'
    assert args[-1] == 'layer.geojson'
    assert (tiles / f'{NAME}.pmtiles').read_bytes() == new
    assert sorted(p.name for p in tiles.iterdir()) == [f'{NAME}.pmtiles']
    assert f'dist/tiles/{NAME}.pmtiles:' in capsys.readouterr().out


def test_copy_failure_propagates_old_archive_kept_no_part(tiles):
    def half_copy(src, dst):
        Path(dst).write_bytes(b'PMTiles\x03half')
        raise OSError('disk full')
    with pytest.raises(OSError, match='disk full'):
        run_build(b'PMTiles\x03new-archive-bytes', copyfile=half_copy)
    assert (tiles / f'{NAME}.pmtiles').read_bytes() == OLD
    assert sorted(p.name for p in tiles.iterdir()) == [f'{NAME}.pmtiles']


def test_failed_rename_removes_part_and_keeps_old_archive(tiles):
    with mock.patch.object(Path, 'replace', side_effect=OSError('rename refused')):
        with pytest.raises(OSError, match='rename refused'):
            run_build(b'PMTiles\x03new-archive-bytes')
    assert (tiles / f'{NAME}.pmtiles').read_bytes() == OLD
    assert sorted(p.name for p in tiles.iterdir()) == [f'{NAME}.pmtiles']
