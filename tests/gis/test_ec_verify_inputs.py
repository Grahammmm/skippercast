"""RF1520-7: scripts/ec_verify.py refuses unreadable JSON inputs and a --max-pixels outside 1..1e9 (exit 2, no traceback)."""
import json
import pathlib

import numpy as np
import pytest

pytestmark = pytest.mark.gis
pytest.importorskip('rasterio')
from tests.gis import test_ec_verify as ev  # noqa: E402  (the script module and its tiny synthetic GeoTIFF helpers)

EC = ev.EC


@pytest.fixture
def grid(tmp_path):
    """A 4x4 corrected/provenance pair with a valid ec-apply-v1 receipt, catalog entries and an agreeing B survey."""
    a = np.tile(-20.0 - 0.5 * np.arange(4), (4, 1)).astype('float32')
    ev._a_dir(tmp_path, a, np.full(a.shape, 10, 'uint8'))
    ev._tif(tmp_path / 'b.tif', ev.survey(a, 0.3))
    return tmp_path


def _refused(tmp_path, capsys, extra=()):
    code = ev._run(tmp_path, 'out', [(tmp_path / 'b.tif', 'usgs-b', 'MLLW')], extra=extra)[0]
    err = capsys.readouterr().err
    assert code == 2 and 'Traceback' not in err and not (tmp_path / 'out').exists()
    return err.strip()


@pytest.mark.parametrize('content', [
    None,  # missing
    b'{"schema": "ec-apply-v1", "source_id": "us',  # truncated
    b'{"source_id": "\xff\xfe"}',  # invalid UTF-8
    b'[]',  # a JSON list, not an object
    b'[' * 100000,  # too deep for the JSON parser
    b'"ec-apply-v1"', b'null', b''], ids=['missing', 'truncated', 'utf8', 'list', 'deep', 'string', 'null', 'empty'])
def test_unreadable_apply_receipt_is_refused(grid, capsys, content):
    receipt = grid / 'a' / 'EC-APPLY.json'
    receipt.unlink()
    if content is not None:
        receipt.write_bytes(content)
    assert _refused(grid, capsys) == 'verify refused: apply receipt: unreadable JSON object'


@pytest.mark.parametrize('content, message', [
    (None, 'catalog entries: unreadable JSON object'),  # missing
    (b'["usgs-a", "usgs-b"]', 'catalog entries: unreadable JSON object'),
    (b'{"usgs-a": {"id": "usgs-a"', 'catalog entries: unreadable JSON object'),  # invalid JSON
    (b'{"x": \xff}', 'catalog entries: unreadable JSON object'),  # invalid UTF-8
    (b'[' * 100000, 'catalog entries: unreadable JSON object'),
    (b'{"x": 1}', 'catalog entries must map source ids to objects'),
    (b'{"usgs-a": {"id": "usgs-a"}, "usgs-b": ["geotiff"]}', 'catalog entries must map source ids to objects'),
    (b'{"usgs-a": {"id": "usgs-a"}, "usgs-b": null}', 'catalog entries must map source ids to objects')],
    ids=['missing', 'list', 'invalid', 'utf8', 'deep', 'int-value', 'list-value', 'null-value'])
def test_unreadable_or_malformed_catalog_entries_are_refused(grid, capsys, content, message):
    entries = grid / 'entries.json'
    entries.unlink()
    if content is not None:
        entries.write_bytes(content)
    assert _refused(grid, capsys) == f'verify refused: {message}'


def test_catalog_entry_checks_keep_their_order(grid, capsys):
    """A well-formed map still reaches the missing-entry refusal; a bad receipt is refused before entries are read."""
    (grid / 'entries.json').write_text(json.dumps({'usgs-a': {'id': 'usgs-a', 'adapter': 'geotiff'}}))
    assert _refused(grid, capsys) == 'verify refused: catalog entry missing: usgs-b'
    (grid / 'entries.json').write_text('[]')
    (grid / 'a' / 'EC-APPLY.json').write_text('[]')
    assert _refused(grid, capsys) == 'verify refused: apply receipt: unreadable JSON object'


@pytest.mark.parametrize('value', ['0', '-1', '1000000001', 'abc', '', '1e9', '1.5', ' ', '+0'])
def test_bad_max_pixels_exits_2_before_any_file_is_read(grid, capsys, monkeypatch, value):
    def fail(*args, **kwargs):
        raise AssertionError('read_text called')
    monkeypatch.setattr(pathlib.Path, 'read_text', fail)
    monkeypatch.setattr(pathlib.Path, 'read_bytes', fail)
    with pytest.raises(SystemExit) as exc:
        ev._run(grid, 'out', [(grid / 'b.tif', 'usgs-b', 'MLLW')], extra=['--max-pixels', value])
    err = capsys.readouterr().err
    assert exc.value.code == 2 and 'must be a whole number from 1 to 1000000000' in err and 'Traceback' not in err
    assert not (grid / 'out').exists()


def test_max_pixels_bounds_and_default_keep_existing_behaviour(grid, capsys):
    assert _refused(grid, capsys, extra=['--max-pixels', '1']) == 'verify refused: pixel cap: A'
    assert _refused(grid, capsys, extra=['--max-pixels', '15']) == 'verify refused: pixel cap: A'  # 4x4 = 16 cells
    for out, extra in (('upper', ['--max-pixels', '1000000000']), ('exact', ['--max-pixels', '16']), ('default', [])):
        receipt, prov, _ = ev._run(grid, out, [(grid / 'b.tif', 'usgs-b', 'MLLW')], extra=extra)
        assert receipt['disposition'] == 'VERIFY' and (prov == 30).all(), out
        assert receipt['pairs'][0]['verified_cells'] == 16, out
