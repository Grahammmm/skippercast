"""Golden-slice regression coverage; no held inputs, browser, network, or real map jobs."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio

from scripts import build_bathy_tiles as tiler
from scripts.relief import golden_slice as golden
from tests._support import ROOT


def read_json(path):
    return json.loads(path.read_text())


@pytest.fixture(scope='module')
def slice_work(tmp_path_factory):
    work = tmp_path_factory.mktemp('golden')
    completed = subprocess.run([sys.executable, 'scripts/relief/golden_slice.py', '--work', str(work)],
                               cwd=ROOT, text=True, capture_output=True, timeout=60)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert read_json(work / 'golden-summary.json')['slice'] == 'synthetic'
    return work


def test_preview_absent_can_skip_but_merged_unwired_is_red(slice_work, tmp_path, monkeypatch, capsys):
    # A merged preview must not get the old unconditional SKIPPED, even on a cached run.
    def run():
        monkeypatch.setattr(sys, 'argv', ['golden_slice.py', '--work', str(slice_work)])
        return golden.main()

    original_module = golden.real_module
    preview = tmp_path / 'preview.py'
    monkeypatch.setattr(golden, 'real_module', lambda stage: preview if stage == 'preview' else original_module(stage))
    assert run() == 0
    assert 'stages executed this run: 0; already done (no work): 8' in capsys.readouterr().out
    preview.write_text('def render(path):\n    path.write_text("local preview")\n')
    assert run() == 1
    assert 'UNWIRED' in capsys.readouterr().out

    # The real adapter path calls the module, rather than just printing REAL. The tiny
    # module stands in for the not-yet-merged E2E-11 interface; no browser is simulated.
    def adapter(work, out, final, slice_name):
        import runpy
        runpy.run_path(str(preview))['render'](out / 'preview.txt')

    monkeypatch.setitem(golden.REAL_ADAPTERS, 'preview', adapter)
    golden.execute_stage('preview', slice_work, tmp_path, tmp_path, 'synthetic')
    assert (tmp_path / 'preview.txt').read_text() == 'local preview'


def test_catalogue_admits_exact_noaa_and_ncmp_rows_only_when_all_rights_allow(slice_work, tmp_path, monkeypatch):
    # Covers wrong/missing exact bindings and bypassing either publication veto even when approved.
    ids = ['noaa-morro-bay-topobathy-2022-9630', 'usace-ncmp-ca-8482']
    main = {row['id']: row for row in read_json(ROOT / 'catalog/sources.json')['sources']}
    rows = [dict(main[sid], review_status='approved', publication_allowed=True,
                 rights={'commercial_use': 'allowed', 'public_display': 'allowed'}) for sid in ids]
    catalog = tmp_path / 'catalog/sources.json'
    catalog.parent.mkdir()
    monkeypatch.setattr(golden, 'REPO', tmp_path)

    def selected():
        catalog.write_text(json.dumps({'sources': rows}))
        golden.st_select(slice_work, tmp_path, tmp_path, 'synthetic')
        return {s['id'] for s in read_json(tmp_path / 'sources.public.json')['sources']}

    noaa = {'r01-mrr22-089', 'r01-mrr22-090', 'r01-mrr22-093', 'r01-mrr22-094'}
    ncmp = {'r02-ncmp15-10sfe9416'}
    assert selected() == noaa | ncmp
    rows[0]['rights']['public_display'] = 'private'
    assert selected() == ncmp
    rows[0]['rights']['public_display'] = 'allowed'
    rows[1]['publication_allowed'] = False
    assert selected() == noaa
    rows[1].pop('publication_allowed')
    assert selected() == noaa


def test_tie_probe_can_flip_when_the_real_tiler_winner_changes(slice_work, tmp_path, monkeypatch):
    # The original source-text probe returned UNKNOWN on sort changes. Keep real raster
    # warps, and change only native priority to demonstrate a behavioral FLIPPED result.
    observed = read_json(slice_work / 'qa/tiebreak.json')
    load = tiler.load_native_manifest
    winner = observed['mosaic_id']
    key = lambda s: s['id'] == winner  # noqa: E731
    monkeypatch.setattr(tiler, 'load_native_manifest', lambda path: sorted(load(path), key=key, reverse=True))
    assert golden.tiebreak_probe(slice_work, tmp_path / 'tie.json')['agrees'] is False
    monkeypatch.setattr(tiler, 'load_native_manifest', lambda path: sorted(load(path), key=key))
    flipped = golden.tiebreak_probe(slice_work, tmp_path / 'tie.json')
    assert flipped['agrees'] is True
    gap = next(g for g in golden.gap_checks(slice_work) if g[0] == 'E2E-04/06')
    assert gap[2:] == (observed['agrees'], observed['detail'])
    (tmp_path / 'qa').mkdir()
    (tmp_path / 'qa/tiebreak.json').write_text(json.dumps(flipped))
    assert next(g for g in golden.gap_checks(tmp_path) if g[0] == 'E2E-04/06')[2] is True


def test_high_zoom_needs_cell_evidence_not_nominal_spacing(slice_work):
    # A numeric shallow cell with a zero support flag is valid background but not native
    # measured input. The interpolated NCMP and other unsupported 1 m grids stay estimated.
    inventory = read_json(slice_work / 'inventory/inventory.json')
    assert len(inventory['sources']) == 6 and not inventory['csmp_zips_held']
    assert all(Path(s['path']).parent == slice_work / 'fixture' for s in inventory['sources'])
    sources = read_json(slice_work / 'select/selection.json')['sources']
    estimated = {s['id'] for s in sources if s['label'] == 'estimated' and s['max_zoom'] is None}
    assert {'r01-mrr22-093', 'r01-mrr22-094', 'r02-ncmp15-10sfe9416', 'r09-bluetopo-bh4585bw'} <= estimated
    native = read_json(slice_work / 'select/native.private.json')
    assert {s['source_file'] for s in native} == {'mrr22-089.tif', 'mrr22-090.tif'}
    for source in native:
        with rasterio.open(slice_work / 'fixture' / source['source_file']) as raw, rasterio.open(source['path']) as grid:
            depth, support = raw.read()
            assert np.count_nonzero((depth != golden.NODATA) & (support == 0)) > 0
            np.testing.assert_array_equal(grid.read(1), np.where(support == 1, depth, golden.NODATA))
    qa = read_json(slice_work / 'qa/qa.json')['z16plus']
    assert 0 < qa['painted_outside_support'] < qa['painted']  # Legacy background can still paint outside native support.


@pytest.mark.parametrize(('cgroup', 'pgrep', 'reason'), [
    ('0::/user.slice/memcap.scope', None, 'requires a localmapq mapjob- systemd service'),
    ('0::/user.slice/mapjob-morro-bay.tiles.a1.service', 0, 'competing mosaic, tiler or run_bounded.py'),
    ('0::/user.slice/mapjob-morro-bay.tiles.a1.service', 2, 'pgrep failed'),
])
def test_heavy_refuses_before_stage_or_work_io(tmp_path, monkeypatch, cgroup, pgrep, reason):
    # Outside the unit, don't scan; inside, both a real competitor result and a probe
    # error fail closed. A hidden --run-stage must not bypass the same admission check.
    cgroup_file = tmp_path / 'cgroup'
    cgroup_file.write_text(cgroup + '\n')
    monkeypatch.setattr(golden, 'CGROUP', cgroup_file)
    work = tmp_path / 'must-not-exist'
    calls = []

    def probe(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, pgrep, '123\n' if pgrep == 0 else '', '')

    monkeypatch.setattr(golden.subprocess, 'run', probe)
    monkeypatch.setattr(sys, 'argv', ['golden_slice.py', '--slice', 'morro-bay', '--work', str(work),
                                     '--run-stage', 'inventory'])
    with pytest.raises(SystemExit, match=reason):
        golden.main()
    assert not work.exists()
    assert len(calls) == (pgrep is not None)
    if calls:
        assert calls[0][:2] == ['pgrep', '-f']
        assert all(name in calls[0][-1] for name in ('coast_mosaic', 'build_bathy_tiles', 'run_bounded'))
