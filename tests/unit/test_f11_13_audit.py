"""Synthetic controls for concurrent seafloor cache writers (F11-13)."""
import fcntl
import hashlib
import importlib
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest

from skippercast.seafloor import source_ingest
from skippercast.seafloor.fetch import fetch_source


@pytest.mark.parametrize('outcome', ['identical', 'disagreement', 'interruption'])
def test_overlapping_original_streams_keep_verified_pair(tmp_path, outcome):
    # The first writer's cleanup or rename used to act on the second writer's .part.
    payload = b'synthetic source'
    digest = hashlib.sha256(payload).hexdigest()
    row = dict(url='https://pubs.usgs.gov/synthetic.tif', sha256=digest, bytes=len(payload))
    started, finish = Event(), Event()

    def download(_url, output, *, first=False, **_options):
        body = b'x' * len(payload) if first and outcome == 'disagreement' else payload
        output.write(body)
        output.flush()
        if first:
            started.set()
            assert finish.wait(10)
            if outcome == 'interruption':
                raise InterruptedError('synthetic stream interrupted')
        return SimpleNamespace(receipt=SimpleNamespace(sha256=hashlib.sha256(body).hexdigest(),
                                                       bytes=len(body)))

    def paused(url, output, **options):
        return download(url, output, first=True, **options)

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(fetch_source, row, tmp_path, fetch=True,
                              session=SimpleNamespace(download=paused))
        try:
            assert started.wait(10)
            path, downloaded = fetch_source(row, tmp_path, fetch=True,
                                            session=SimpleNamespace(download=download))
            assert downloaded and path == tmp_path / digest / 'source.tif'
            receipt = path.with_suffix('.json')
            committed = path.read_bytes(), receipt.read_bytes()
        finally:
            finish.set()
        if outcome == 'identical':
            assert pending.result(timeout=10) == (path, True)
        elif outcome == 'disagreement':
            with pytest.raises(ValueError, match='Original source checksum mismatch'):
                pending.result(timeout=10)
        else:
            with pytest.raises(InterruptedError, match='synthetic stream interrupted'):
                pending.result(timeout=10)

    assert committed[0] == payload and json.loads(committed[1]) == row
    assert (path.read_bytes(), receipt.read_bytes()) == committed
    assert set(tmp_path.rglob('*')) == {path.parent, path, receipt}
    assert fetch_source(row, tmp_path) == (path, False)


@pytest.mark.gis
def test_routed_normalizers_commit_once_and_preserve_prior_pair(tmp_path, monkeypatch):
    # Pause a real COG writer, then have a second import contend for its source.
    # Without the router lock it can overwrite or remove the shared working TIFF.
    import numpy as np
    import rasterio
    from pyproj import Transformer
    from rasterio.transform import from_origin

    native = importlib.import_module('skippercast.seafloor.ingest')
    source = tmp_path / 'synthetic.tif'
    with rasterio.open(source, 'w', driver='GTiff', width=2, height=2, count=1,
                       dtype='int16', crs='EPSG:32631', transform=from_origin(500000, 40, 2, 2)) as dst:
        dst.write(np.full((2, 2), -10, dtype='int16'), 1)
    row = dict(id='synthetic', url='https://pubs.usgs.gov/synthetic.tif', kind='bathymetry',
               format='usgs-geotiff', sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
               bytes=source.stat().st_size, resolution_m=2, vertical_datum='unknown',
               archive_member='unknown')
    geo = Transformer.from_crs(32631, 4326, always_xy=True)
    bounds = (*geo.transform(499998, 34), *geo.transform(500006, 42))
    copying, contended, finish = Event(), Event(), Event()
    real_copy, real_flock = native.raster_copy, fcntl.flock
    copies = []

    def paused_copy(*args, **kwargs):
        copies.append(args[0])
        if len(copies) == 1:
            copying.set()
            assert finish.wait(10)
        else:
            contended.set()
        return real_copy(*args, **kwargs)

    def observe_flock(fd, operation):
        if operation == fcntl.LOCK_EX and copying.is_set() and not finish.is_set():
            with pytest.raises(BlockingIOError):
                real_flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            contended.set()
        return real_flock(fd, operation)

    with ThreadPoolExecutor(max_workers=2) as pool, monkeypatch.context() as patch:
        patch.setattr(native, 'raster_copy', paused_copy)
        patch.setattr(fcntl, 'flock', observe_flock)
        first = pool.submit(source_ingest.ingest, row, bounds, root=tmp_path, local=source)
        try:
            assert copying.wait(10)
            second = pool.submit(source_ingest.ingest, row, bounds, root=tmp_path, local=source)
            assert contended.wait(10)
            assert len(copies) == 1
        finally:
            finish.set()
        saved, downloaded, reused = first.result(timeout=10)
        assert not downloaded and not reused
        assert second.result(timeout=10) == (saved, False, True)

    bucket = tmp_path / 'var/seafloor/cache' / row['sha256']
    original = {bucket / 'source.tif', bucket / 'source.json'}
    receipt, = set(bucket.glob('*.json')) - original
    cog = receipt.with_suffix('.tif')
    committed = {path: path.read_bytes() for path in original | {cog, receipt}}
    assert saved['valid_pixels_in_requested_bounds'] == 4
    assert json.loads(committed[receipt]) == saved
    assert hashlib.sha256(committed[cog]).hexdigest() == saved['cog_sha256']

    def interrupted_copy(*_args, **_kwargs):
        raise InterruptedError('synthetic normalization interrupted')

    different_bounds = (*geo.transform(499997, 34), *geo.transform(500006, 42))
    with monkeypatch.context() as patch:
        patch.setattr(native, 'raster_copy', interrupted_copy)
        with pytest.raises(InterruptedError, match='synthetic normalization interrupted'):
            source_ingest.ingest(row, different_bounds, root=tmp_path)
    assert set(bucket.iterdir()) == committed.keys()
    assert {path: path.read_bytes() for path in committed} == committed
    assert source_ingest.ingest(row, bounds, root=tmp_path) == (saved, False, True)
