"""Synthetic DL-6R-W acceptance; local runs use real loopback Chromium."""
from contextlib import redirect_stdout
from io import StringIO
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import rasterio
from rasterio.transform import from_bounds, from_origin
from rasterio.warp import transform_bounds
from shapely.geometry import box, mapping

from scripts.relief import region as cli, run_region
from skippercast.relief import contours, envelope, mosaic, package, qa, receipts, select, shots
from tests._support import FIXTURES, ROOT
from tests.gis.test_relief_qa import shot_png, write_json


def stub_node_capture(command, **kwargs):
    """CI only: stand in for Node, not for the shots stage or its receipt."""
    release, out = Path(command[2]), Path(command[4])
    doc = package.decode_document(release.read_bytes())
    lo, hi = doc['minzoom'], doc['maxzoom']
    cameras = sorted({z for z in (lo, 10, 13, 15, hi) if lo <= z <= hi})
    rows = []
    for z in cameras:
        for device, (width, height) in qa.DEVICES.items():
            for theme in qa.THEMES:
                png, notice = shot_png(width, height, len(rows))
                path = f'shots/{theme}-{device}-z{z}.png'
                (out / 'shots').mkdir(parents=True, exist_ok=True)
                (out / path).write_bytes(png)
                rows.append(dict(path=path, zoom=z, theme=theme, device=device, viewport=[width, height],
                                 sha256=receipts.sha256_bytes(png), navigation_visible=True, notice_box=notice))
    w, s, e, n = doc['bounds']
    write_json(out / 'shots.json', {'renderer': 'mb08-chart', 'release_sha256': receipts.sha256_file(release),
                                    'cameras': cameras, 'shots': rows, 'center': [(w + e) / 2, (s + n) / 2]})


def test_guarded_tiny_release_through_envelope(tmp_path, monkeypatch):
    # CI-ARTICLE-1: the real CLI chain must bind inventory, contours and attested capture to
    # one release. The old argv could not reach QA; passing the package generation as a shot
    # generation or hashing a different release also fails this test.
    root = tmp_path.resolve()
    region = receipts.Region(root / 'out', 'tiny')
    tiny = runpy.run_path(str(FIXTURES / 'relief/tiny/tiny_region.py'))
    tiny_grid = tiny['write_grids'](region.dir / 'raw')['projected_1m.tif']
    # Expand the shared invented depths onto the actual 10 m mosaic lattice. The 24 m
    # original is subpixel at the overview cameras and native paint there can lack 10 m
    # land evidence. This footprint keeps the browser control legible without changing QA.
    grid = region.dir / 'raw' / 'aligned-10m.tif'
    with rasterio.open(tiny_grid) as src:
        x, _, _, y = transform_bounds(src.crs, 'EPSG:3310', *src.bounds)
        samples = np.repeat(np.repeat(src.read(1), 5, axis=0), 5, axis=1)
    transform = from_origin(round(x / 10) * 10, round(y / 10) * 10, 10, 10)
    with rasterio.open(grid, 'w', driver='GTiff', width=samples.shape[1], height=samples.shape[0],
                       count=1, dtype='float32', nodata=-9999, crs='EPSG:3310', transform=transform) as dst:
        dst.write(samples, 1)
        w, s, e, n = transform_bounds(dst.crs, 'EPSG:4326', *dst.bounds)
    bounds = [round(w - .0002, 7), round(s - .0002, 7), round(e + .0002, 7), round(n + .0002, 7)]
    fixture = root / 'config'
    contract = {'id': 'tiny', 'bounds': bounds, 'source_bindings': {'bathymetry': ['tiny-grid']}}
    config = fixture / 'regions/tiny/region.json'
    write_json(config, contract)
    source = dict(id='tiny-grid', name='Tiny synthetic fixture', provider='Fixture survey', needs=['bathymetry'],
                  review_status='approved', survey_year=2020, vertical_datum='unstated',
                  documentation_url='https://example.org/survey', rights={'public_display': 'allowed',
                  'license': 'public-domain', 'attribution': 'Fixture survey'})
    write_json(fixture / 'catalog/sources.json', {'sources': [source]})
    schema = fixture / 'catalog/relief/pointer.schema.json'
    schema.parent.mkdir()
    shutil.copyfile(ROOT / 'catalog/relief/pointer.schema.json', schema)
    write_json(root / 'PROVENANCE-LABELS.json', {'source_rows': []})
    write_json(region.dir / 'census.json', {'summary': {'region': 'tiny'}, 'files': [
        dict(id='tiny-grid', path=str(grid), kind='elevation', units='m', admissible_now=True,
             sha256=receipts.sha256_file(grid))]})
    coarse = root / 'coarse.tif'
    with rasterio.open(coarse, 'w', driver='GTiff', width=8, height=8, count=1, dtype='float32', crs='EPSG:3310',
                       transform=from_bounds(*transform_bounds('EPSG:4326', 'EPSG:3310', *bounds), 8, 8)) as dst:
        dst.write(np.full((8, 8), -10, dtype='float32'), 1)
    water = root / 'water.geojson'
    write_json(water, {'type': 'FeatureCollection', 'features': [
        {'type': 'Feature', 'geometry': mapping(box(*bounds)), 'properties': {}}]})

    # Supply the fictional region/rights registry, without changing the checkout or any
    # receipt logic. Keep the real producer and the real git checkout for its code hashes.
    monkeypatch.chdir(root)
    monkeypatch.delenv('SC_RELIEF_PROVENANCE', raising=False)
    monkeypatch.setattr(select, 'REPO', fixture)
    monkeypatch.setattr(contours, 'producer', lambda producer=contours.producer(): producer)
    for module in (contours, package, qa, envelope):
        monkeypatch.setattr(module, 'repo_root', lambda: fixture)
    monkeypatch.setattr(contours, 'load_region', lambda *_: contract)
    monkeypatch.setattr(contours, 'load_catalogs', lambda *_: ({}, {'tiny-grid': source}))

    # The same host fact injection used by the existing adapter test: execute the real
    # mosaic tool with its real argv, but give the reserve check synthetic free space.
    tool = mosaic.run_tool

    def run_tool(script, *args, **kwargs):
        if script != mosaic.SCRIPT:
            return tool(script, *args, **kwargs)
        argv = [str(ROOT / script), *map(str, args)]
        assert argv[argv.index('--reserve-gib') + 1] == '250'
        with monkeypatch.context() as patch:
            patch.setattr(sys, 'argv', argv)
            patch.setattr(shutil, 'disk_usage', lambda _: SimpleNamespace(free=2**40))
            runpy.run_path(argv[0], run_name='__main__')

    monkeypatch.setattr(mosaic, 'run_tool', run_tool)
    ci = os.environ.get('GITHUB_ACTIONS') == 'true'
    if ci:
        monkeypatch.setattr(shots, 'capture', stub_node_capture)
    proc = root / 'proc'
    (proc / 'pressure').mkdir(parents=True)
    (proc / 'pressure/cpu').write_text('some avg60=1.00\n')
    cfg = run_region.Config(proc_root=str(proc), slot_dir=root / 'slots',
                            stop_files=(root / 'LOCAL-STOP', root / 'UNITFEED-STOP'),
                            free_bytes=lambda _: 2**40, is_mount=lambda _: True,
                            basemap_roots=(FIXTURES,))
    real_run = subprocess.run
    qa_command = []

    def dispatch(command, *, capture_output=False, **kwargs):
        if command[:len(cfg.prefix) + 2] != [*cfg.prefix, cfg.python, str(cfg.region_py)]:
            return real_run(command, capture_output=capture_output, **kwargs)
        # Dispatch the runner's exact CLI argv in this fixture process so its synthetic
        # catalog and host facts apply. Region/slot locks must already be held at every call.
        assert run_region.lock_is_held(region.out_root, region.id)
        assert run_region.slots_held(cfg) == 1
        argv = command[len(cfg.prefix) + 2:]
        if argv[0] == 'qa':
            qa_command[:] = argv
        if capture_output:
            out = StringIO()
            with redirect_stdout(out):
                code = cli.main(argv)
            return subprocess.CompletedProcess(command, code, out.getvalue().encode(), b'')
        return subprocess.CompletedProcess(command, cli.main(argv))

    monkeypatch.setattr(subprocess, 'run', dispatch)
    basemap = FIXTURES / 'basemap/tiny.pmtiles'
    assert run_region.main(['tiny', '--through', 'envelope', '--out', str(region.out_root),
                            '--norm', str(root / 'norm'), '--region-config', str(config),
                            '--coarse', str(coarse), '--water', str(water), '--coarse-source', 'tiny-grid',
                            '--basemap', str(basemap)], cfg) == 0
    packaged, captured = (receipts.check(region, stage) for stage in ('package', 'shots'))
    assert packaged.done and captured.done and packaged.receipt is not None and captured.receipt is not None
    generation, shot_generation = packaged.receipt['generation'], captured.receipt['generation']
    assert shot_generation != generation
    rel = f'release/{generation}/release.json'
    release = region.dir / rel
    digest = receipts.sha256_file(release)
    shot_doc = package.decode_document((region.dir / f'shots/{shot_generation}/shots.json').read_bytes())
    report_path = region.dir / f'qa/{generation}/qa.json'
    report = package.decode_document(report_path.read_bytes())
    assert report['status'] == 'PASS' and report['release_sha256'] == shot_doc['release_sha256'] == digest
    envelope_doc = package.decode_document((region.dir / f'review/{generation}/envelope.json').read_bytes())
    assert envelope_doc['release'] == {'path': rel, 'sha256': digest}
    assert envelope_doc['qa']['sha256'] == receipts.sha256_file(report_path)
    assert all(not row['path'].startswith('layers/contours/') for row in envelope_doc['layers'])
    print(f"tiny envelope PASS: {len(shot_doc['shots'])} {'stubbed CI' if ci else 'real Chromium'} shots")

    # Use the very argv captured from the runner. A wrong expected release hash must fail
    # QA; byte drift after package must independently stop both consumers.
    envelope_command = ['envelope', '--region', 'tiny', '--out', str(region.out_root), '--generation', generation]
    wrong_hash = qa_command.copy()
    wrong_hash[wrong_hash.index('--release-sha256') + 1] = '0' * 64
    assert cli.main(wrong_hash) == 1
    assert 'release does not match' in receipts.check(region, 'qa').reason
    assert cli.main(envelope_command) == 3
    release.write_bytes(release.read_bytes() + b'\n')
    assert cli.main(qa_command) == cli.main(envelope_command) == 3
    assert 'output changed' in receipts.check(region, 'package').reason
