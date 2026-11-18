"""CLI boundary tests for a synthetic, single-beam native gap receipt."""
import hashlib
import json
import os
import stat
import sys

import pytest

from research.scripts import triage_multibeam_beams as beams


pytestmark = pytest.mark.gis  # The reserved unit file exercises the real GIS path.


@pytest.fixture
def one_hit(tmp_path, monkeypatch):
    from pyproj import Transformer

    root = tmp_path.resolve()
    monkeypatch.setattr(beams, '__file__', str(root / 'research/scripts/triage_multibeam_beams.py'))
    monkeypatch.chdir(root)
    private = root / 'var/seafloor/source-review'
    private.mkdir(parents=True)
    table = root / 'fixture.tsv'
    raw = b'0.125 0.25 42 0 1 1 1\n'  # Invented point, not any surveyed location.
    table.write_bytes(raw)
    receipt = root / 'fixture-receipt.json'
    receipt.write_text(json.dumps({
        'columns': beams.COLUMNS,
        'binary_sha256': 'a' * 64,
        'command': ['mblist', '-F57', '-Ifixture.mb57', '-MA', '-OXYzFMN#'],
        'good_nominal_shallow_rows': 1,
        'shallow_sha256': hashlib.sha256(raw).hexdigest(),
    }))
    x, y = Transformer.from_crs(4326, 3310, always_xy=True).transform(0.125, 0.25)
    snapshot: dict[str, str] = dict.fromkeys((
        'cells_sha256', 'physical_input_hash', 'checkpoint_sha256',
        'native_support_inputs_sha256', 'native_support_sha256', 'retained_run_sha256',
    ), 'b' * 64)
    snapshot['reach'] = 'synthetic'
    query = root / 'fixture-query.json'
    query.write_text(json.dumps({'coverage_snapshot': snapshot, 'groups': [{
        'id': 'synthetic-gap-0001', 'query_geometry': {'spatialReference': {'wkid': 3310},
        'rings': [[[x-1, y-1], [x-1, y+1], [x+1, y+1], [x+1, y-1], [x-1, y-1]]]},
    }]}))

    def run(output):
        monkeypatch.setattr(sys, 'argv', [
            'triage_multibeam_beams', '--beam-table', str(table), '--beam-receipt', str(receipt),
            '--native-gap-query', str(query), '--native-gap-query-sha256',
            hashlib.sha256(query.read_bytes()).hexdigest(), '--output', str(output),
        ])
        beams.main()

    return root, private, snapshot, run


def test_one_hit_is_exact_in_private_receipt_and_count_only_on_stdout(one_hit, capsys):
    root, private, snapshot, run = one_hit
    output = private / 'beam-triage.json'
    run(output.relative_to(root))
    result = json.loads(output.read_text())
    assert result['gap_beam_bounds_wgs84'] == [0.125, 0.25, 0.125, 0.25]
    assert result['coverage_snapshot'] == snapshot
    assert result['by_gap_group'] == {'synthetic-gap-0001': 1}
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {
        'schema_version': 1,
        'evaluated_beam_rows': 1,
        'good_nominal_shallow_rows': 1,
        'rejected_flag_rows': 0,
        'rejected_depth_rows': 0,
        'good_shallow_rows_in_gaps': 1,
    }
    assert captured.err == ''
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert list(private.iterdir()) == [output]


@pytest.mark.parametrize('kind', ['public', 'traversal', 'directory-link', 'leaf-link', 'hard-link'])
def test_refuses_public_or_aliased_output_without_writing(one_hit, kind, capsys):
    root, private, _, run = one_hit
    public = root / 'dist'
    public.mkdir()
    sentinel = public / 'existing.json'
    sentinel.write_bytes(b'unchanged\n')
    output = private / 'beam-triage.json'
    if kind == 'public':
        output = public / output.name
    elif kind == 'traversal':
        output = private / '../../../dist' / output.name
    elif kind == 'directory-link':
        private.rmdir()
        private.symlink_to(public, target_is_directory=True)
    elif kind == 'leaf-link':
        output.symlink_to(sentinel)
    else:
        os.link(sentinel, output)

    before = sorted(root.rglob('*'))
    with pytest.raises(SystemExit) as refused:
        run(output)
    assert refused.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ''
    assert 'private' in captured.err
    assert sorted(root.rglob('*')) == before
    assert sentinel.read_bytes() == b'unchanged\n'
    if kind in ('directory-link', 'leaf-link'):
        assert (private if kind == 'directory-link' else output).is_symlink()
    if kind == 'hard-link':
        assert output.samefile(sentinel)
