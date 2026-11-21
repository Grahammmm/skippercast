"""Synthetic DL-6R-W acceptance; local runs use real loopback Chromium."""
from contextlib import redirect_stdout
import gzip
from io import StringIO
import math
import os
from pathlib import Path
import runpy
import shutil
import struct
import subprocess
import sys
from types import SimpleNamespace

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_bounds, from_origin
from rasterio.warp import transform, transform_bounds
from shapely.geometry import box, mapping

from scripts.relief import region as cli, run_region
from skippercast.relief import contours, envelope, mosaic, package, pmtiles_v3, qa, receipts, select, shots
from tests._support import FIXTURES, ROOT
from tests.gis.test_relief_qa import shot_png, write_json


def stub_node_capture(command, *, blank_chart, **kwargs):
    """CI only: stand in for Node, not for the shots stage or its receipt."""
    release, out = Path(command[2]), Path(command[4])
    doc = package.decode_document(release.read_bytes())
    lo, hi = doc['minzoom'], doc['maxzoom']
    cameras = sorted({z for z in (lo, 10, 13, 15, hi) if lo <= z <= hi})
    rows = []
    for z in cameras:
        for device, (width, height) in qa.DEVICES.items():
            for theme in qa.THEMES:
                blank = blank_chart and (theme, device, z) == ('light', 'desktop', hi)
                png, notice = shot_png(width, height, len(rows), canvas=not blank)
                path = f'shots/{theme}-{device}-z{z}.png'
                (out / 'shots').mkdir(parents=True, exist_ok=True)
                (out / path).write_bytes(png)
                rows.append(dict(path=path, zoom=z, theme=theme, device=device, viewport=[width, height],
                                 sha256=receipts.sha256_bytes(png), navigation_visible=True, notice_box=notice))
    w, s, e, n = doc['bounds']
    write_json(out / 'shots.json', {'renderer': 'mb08-chart', 'release_sha256': receipts.sha256_file(release),
                                    'cameras': cameras, 'shots': rows, 'center': [(w + e) / 2, (s + n) / 2]})


def tile_basemap(path, xy, bounds):
    """Invent diagonal coastlines across the camera tiles; no fetched tiles or glyphs."""
    def packed(*values):
        out = bytearray()
        for value in values:
            pmtiles_v3._varint(out, value)
        return bytes(out)

    def field(tag, value):
        return packed(tag * 8 + 2, len(value)) + value

    payload, entries = bytearray(), []
    for z in (11, 12, 13):
        # Vector tiles are 512px; the Chart subtracts one from its display zoom.
        # Move the shore at each level so the oracle sees distinct PNGs.
        shore = 680 + 450 * (z - 11)
        geometry = packed(9, 0, 0, 26, 2 * shore, 0, 2 * 1800, 8192, 2 * (shore + 1800) - 1, 0, 15)
        feature = packed(24, 3) + field(4, geometry)  # Polygon, clockwise outer ring
        tile = field(3, field(1, b'earth') + field(2, feature) + packed(40, 4096, 120, 2))
        cell = 2 * qa.WEB_HALF / (1 << z)
        x, y = math.floor((xy[0] + qa.WEB_HALF) / cell), math.floor((qa.WEB_HALF - xy[1]) / cell)
        for i in range(x - 2, x + 3):
            for j in range(y - 2, y + 3):
                entries.append((pmtiles_v3._tile_id(z, i, j), len(payload), len(tile), 1))
        payload.extend(tile)
    directory = pmtiles_v3._directory(sorted(entries))
    meta = gzip.compress(receipts.canonical({'vector_layers': [{'id': 'earth', 'fields': {}}]}), mtime=0)
    data = 127 + len(directory) + len(meta)
    w, s, e, n = bounds
    header = (b'PMTiles\x03' + struct.pack('<11Q', 127, len(directory), 127 + len(directory), len(meta),
                                           data, 0, data, len(payload), len(entries), len(entries), 3)
              + bytes([0, 2, 1, 1, 11, 13])  # gzip directory/metadata, uncompressed MVT
              + struct.pack('<4iB2i', *(round(v * 1e7) for v in bounds), 11,
                            round((w + e) * 5e6), round((s + n) * 5e6)))
    path.write_bytes(header + directory + meta + payload)


def fixture_grid(region, blank_chart):
    tiny = runpy.run_path(str(FIXTURES / 'relief/tiny/tiny_region.py'))
    original = tiny['write_grids'](region.dir / 'raw')['projected_1m.tif']
    with rasterio.open(original) as src:
        w, s, e, n = transform_bounds(src.crs, 'EPSG:4326', *src.bounds)
    if blank_chart:
        bounds = [round(v, 7) for v in (w - .0002, s - .0002, e + .0002, n + .0002)]
        return original, bounds, bounds, FIXTURES / 'basemap/tiny.pmtiles'

    # An inset centred on a z12 PNG pixel is too narrow to contain a coarser
    # pixel centre, but contains z12 and z13 paint. This keeps the widest
    # camera's continuous 10 m mosaic small enough for routine survey CI.
    lon, lat = (w + e) / 2, (s + n) / 2
    xs, ys = transform('EPSG:4326', 'EPSG:3857', [lon], [lat])
    cell = 2 * qa.WEB_HALF / (256 << 12)
    xy = tuple((math.floor((v + qa.WEB_HALF) / cell) + .5) * cell - qa.WEB_HALF for v in (xs[0], ys[0]))

    def extent(dx, dy):
        x, y = xy
        return [round(v, 7) for v in transform_bounds('EPSG:3857', 'EPSG:4326', x - dx, y - dy, x + dx, y + dy)]

    bounds, mosaic_bounds = extent(12, 12), extent(25000, 18000)
    w, s, e, n = transform_bounds('EPSG:4326', 'EPSG:3310', *mosaic_bounds, densify_pts=101)
    left, top = math.floor(w / 10) * 10 - 20, math.ceil(n / 10) * 10 + 20
    width, height = math.ceil((e - left) / 10) + 2, math.ceil((top - s) / 10) + 2
    grid = original.with_name('continuous-10m.tif')
    with rasterio.open(grid, 'w', driver='GTiff', width=width, height=height, count=1,
                       dtype='float32', nodata=-9999, crs='EPSG:3310', compress='deflate',
                       transform=from_origin(left, top, 10, 10)) as dst:
        depths = np.linspace(-27, -5, width, dtype='float32')
        dst.write(np.broadcast_to(depths, (height, width)), 1)
    basemap = region.out_root.parent / 'continuous-basemap.pmtiles'
    tile_basemap(basemap, xy, mosaic_bounds)
    return grid, bounds, mosaic_bounds, basemap


@pytest.mark.parametrize('blank_chart', [False, True], ids=['continuous-mosaic', 'original-24x24-refuses'])
def test_guarded_tiny_release_through_envelope(tmp_path, monkeypatch, blank_chart):
    # CI-ARTICLE-1: the real CLI chain must bind inventory, contours and attested capture to
    # one release. The old argv could not reach QA; passing the package generation as a shot
    # generation or hashing a different release also fails this test.
    # CI-ARTICLE-1: a receipt-bound capture with an inked notice but no visible
    # Chart content must stop at QA (not reach envelope); losing the PNG oracle
    # or treating capture exit 0 as sufficient would accept the 24x24 control.
    root = tmp_path.resolve()
    region = receipts.Region(root / 'out', 'tiny')
    grid, bounds, mosaic_bounds, basemap = fixture_grid(region, blank_chart)
    fixture = root / 'config'
    contract = {'id': 'tiny', 'bounds': bounds, 'source_bindings': {'bathymetry': ['tiny-grid']}}
    config = fixture / 'regions/tiny/region.json'
    write_json(config, contract)
    source = dict(id='tiny-grid', name='Tiny synthetic fixture', provider='Fixture survey', needs=['bathymetry'],
                  review_status='approved', survey_year=2020, vertical_datum='unstated',
                  documentation_url='https://example.org/survey', rights={'public_display': 'allowed',
                  'license': 'public-domain', 'attribution': 'Fixture survey'})
    write_json(fixture / 'catalog/sources.json', {'sources': [source]})
    mosaic_repo, mosaic_config = fixture, config
    if not blank_chart:
        mosaic_repo = fixture / 'mosaic'
        mosaic_config = mosaic_repo / config.relative_to(fixture)
        write_json(mosaic_config, dict(contract, bounds=mosaic_bounds))
        write_json(mosaic_repo / 'catalog/sources.json', {'sources': [source]})
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
    for module in (package, qa, envelope):
        monkeypatch.setattr(module, 'repo_root', lambda: fixture)
    monkeypatch.setattr(contours, 'repo_root', lambda: mosaic_repo)
    monkeypatch.setattr(contours, 'load_region', lambda *_: dict(contract, bounds=mosaic_bounds))
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
        monkeypatch.setattr(shots, 'capture', lambda cmd, **kw: stub_node_capture(cmd, blank_chart=blank_chart, **kw))
    proc = root / 'proc'
    (proc / 'pressure').mkdir(parents=True)
    (proc / 'pressure/cpu').write_text('some avg60=1.00\n')
    cfg = run_region.Config(proc_root=str(proc), slot_dir=root / 'slots',
                            stop_files=(root / 'LOCAL-STOP', root / 'UNITFEED-STOP'),
                            free_bytes=lambda _: 2**40, is_mount=lambda _: True,
                            basemap_roots=(FIXTURES, root))
    real_run = subprocess.run
    qa_command = []
    baseline_release = []

    def dispatch(command, *, capture_output=False, **kwargs):
        if command[:len(cfg.prefix) + 2] != [*cfg.prefix, cfg.python, str(cfg.region_py)]:
            return real_run(command, capture_output=capture_output, **kwargs)
        # Dispatch the runner's exact CLI argv in this fixture process so its synthetic
        # catalog and host facts apply. Region/slot locks must already be held at every call.
        assert run_region.lock_is_held(region.out_root, region.id)
        assert run_region.slots_held(cfg) == 1
        argv = command[len(cfg.prefix) + 2:]
        if argv[0] == 'mosaic' and not blank_chart:
            # Fixture-only geometry: coast_mosaic sizes its evidence grid from
            # its config. Give it the wide config while select/tiles/zone/QA
            # keep the inset. Both input files are independently receipt-bound.
            at = argv.index('--region-config') + 1
            assert argv[at] == str(config)
            argv[at] = str(mosaic_config)
        if argv[0] == 'qa':
            qa_command[:] = argv
        if argv[0] == 'nearshore_vectors' and not blank_chart:
            # Build package both before and after vectors, evicting the receipt
            # so a cache hit cannot mask accidental release dependence.
            package_argv = ['package', *argv[1:5], '--manifest', str(region.dir / 'inventory/manifest.json')]
            for producer in ('tiles:public', 'digests', 'zone:public', 'inventory', 'contours'):
                package_argv.extend(('--upstream', producer))
            assert cli.main(package_argv) == 0
            prior = receipts.check(region, 'package').receipt
            assert prior is not None
            baseline_release.append((region.dir / f'release/{prior["generation"]}/release.json').read_bytes())
            region.receipt_path('package').unlink()
        if argv[0] == 'package' and baseline_release:
            region.receipt_path('inventory').unlink()
            assert cli.main(['inventory', *argv[1:5]]) == 0
        if capture_output:
            out = StringIO()
            with redirect_stdout(out):
                code = cli.main(argv)
            return subprocess.CompletedProcess(command, code, out.getvalue().encode(), b'')
        return subprocess.CompletedProcess(command, cli.main(argv))

    monkeypatch.setattr(subprocess, 'run', dispatch)
    code = run_region.main(['tiny', '--through', 'envelope', '--out', str(region.out_root),
                            '--norm', str(root / 'norm'), '--region-config', str(config),
                            '--coarse', str(coarse), '--water', str(water), '--coarse-source', 'tiny-grid',
                            '--basemap', str(basemap)], cfg)
    packaged, captured = (receipts.check(region, stage) for stage in ('package', 'shots'))
    assert packaged.done and captured.done and packaged.receipt is not None and captured.receipt is not None
    generation, shot_generation = packaged.receipt['generation'], captured.receipt['generation']
    assert shot_generation != generation
    rel = f'release/{generation}/release.json'
    release = region.dir / rel
    digest = receipts.sha256_file(release)
    shot_doc = package.decode_document((region.dir / f'shots/{shot_generation}/shots.json').read_bytes())
    assert shot_doc['release_sha256'] == digest
    envelope_path = region.dir / f'review/{generation}/envelope.json'
    if blank_chart:
        assert code == 1 and 'capture shows no rendered Chart content' in receipts.check(region, 'qa').reason
        assert not envelope_path.exists()
        print(f'tiny 24x24 control: QA exit 1, rendered-content refusal; {len(shot_doc["shots"])} shots')
        return
    assert code == 0
    assert [release.read_bytes()] == baseline_release
    release_doc = package.decode_document(release.read_bytes())
    assert release_doc['bounds'] == bounds
    manifest = package.decode_document((region.dir / 'inventory/manifest.json').read_bytes())
    assert all(not p.startswith('layers/public/nearshore/') for p in manifest['layer_paths'])
    assert all(not row['path'].startswith('layers/public/nearshore/') for row in release_doc['layers'])
    vectors = receipts.check(region, 'nearshore_vectors', 'public')
    assert vectors.done and vectors.receipt is not None and len(vectors.receipt['outputs']) == 4
    qa_receipt = receipts.check(region, 'qa').receipt
    assert qa_receipt is not None
    assert {'stage': 'nearshore_vectors', 'scope': 'public', 'generation': vectors.receipt['generation']} in qa_receipt['upstream']
    assert shot_doc['cameras'] == [12, 13]
    # Chart zoom and the 512 px base tile yield this Mercator scale. Prove the
    # union of both devices' widest frames fits inside continuous evidence.
    w, h = (max(size[i] for size in qa.DEVICES.values()) for i in range(2))
    xs, ys = transform('EPSG:4326', 'EPSG:3857', [shot_doc['center'][0]], [shot_doc['center'][1]])
    pixel = 2 * qa.WEB_HALF / (256 << min(shot_doc['cameras']))
    with rasterio.open(region.dir / 'mosaic/public/elevation.tif') as evidence:
        frame = transform_bounds('EPSG:3857', evidence.crs, xs[0] - w * pixel / 2, ys[0] - h * pixel / 2,
                                 xs[0] + w * pixel / 2, ys[0] + h * pixel / 2)
        assert box(*evidence.bounds).contains(box(*frame)) and evidence.read_masks(1).all()
    report_path = region.dir / f'qa/{generation}/qa.json'
    report = package.decode_document(report_path.read_bytes())
    assert report['status'] == 'PASS' and report['release_sha256'] == shot_doc['release_sha256'] == digest
    envelope_doc = package.decode_document(envelope_path.read_bytes())
    assert envelope_doc['release'] == {'path': rel, 'sha256': digest}
    assert envelope_doc['qa']['sha256'] == receipts.sha256_file(report_path)
    assert all(not row['path'].startswith('layers/contours/') for row in envelope_doc['layers'])
    print(f"tiny envelope PASS: {len(shot_doc['shots'])} {'stubbed CI' if ci else 'real Chromium'} shots; "
          f"land-evidence misses {report['metrics']['painted_without_land_evidence']}/{report['metrics']['painted_pixels']}")

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
