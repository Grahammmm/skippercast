"""A zero-exit join must pass the PMTiles v3 signature check before replacement."""
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from scripts import build_map_tiles


@pytest.mark.parametrize(
    ('joined_bytes', 'valid'),
    [
        pytest.param(b'NotTile\x03wrong-magic', False, id='wrong-magic'),
        pytest.param(b'PMTiles\x02wrong-version', False, id='wrong-version'),
        pytest.param(b'PMTiles\x03joined-archive', True, id='v3'),
    ],
)
def test_split_join_checks_signature_before_replacing(tmp_path, monkeypatch, joined_bytes, valid):
    output = tmp_path / 'region.pmtiles'
    previous = b'PMTiles\x03previous-archive'
    output.write_bytes(previous)

    def run_tile_tool(args, *, check, cwd=None, env=None):
        target = Path(args[args.index('-o') + 1])
        if args[0] == 'tippecanoe':
            assert cwd is not None
            (Path(cwd) / target).write_bytes(b'PMTiles\x03split-input')
        else:
            assert Path(args[0]).name == 'tile-join'
            for split in args[-2:]:
                assert Path(split).read_bytes() == b'PMTiles\x03split-input'
            target.write_bytes(joined_bytes)
        return CompletedProcess(args, 0)

    monkeypatch.setattr(build_map_tiles.subprocess, 'run', run_tile_tool)

    def build():
        return build_map_tiles.build_vector_archive(
            tmp_path / 'tippecanoe', {'reefs': [], 'cells': []}, output,
            title='Fixture', attribution='Fixture', description='Fixture', coarse_first=True,
        )

    # A successful tool exit used to let malformed joined bytes overwrite this archive.
    if valid:
        assert build() == output
        assert output.read_bytes() == joined_bytes
    else:
        with pytest.raises(ValueError, match='tile-join did not produce PMTiles v3'):
            build()
        assert output.read_bytes() == previous
    assert not output.with_suffix('.part').exists()
