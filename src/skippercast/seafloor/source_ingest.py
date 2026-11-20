"""Route reviewed source formats without invalidating legacy native COG keys."""
import contextlib
import fcntl
import hashlib
from pathlib import Path

from skippercast.platform.contracts import REPO, bbox


@contextlib.contextmanager
def _import_lock(root, row):
    """Serialize importers that share a cache bucket, whatever URL named the source.

    Every original, working TIFF and normalized output lives in
    ``cache/<source sha256>/``, so the reviewed source SHA is the shared
    identity: two reviewed URLs for the same bytes (or two rows, bounds or
    adapters over them) must not run at once. A draft row whose SHA is still
    ``unknown`` cannot name its bucket before download, so it takes the gate
    exclusively and runs alone; known-SHA imports hold it shared and run in
    parallel with each other. Locks live beside, not inside, the cache so a
    refused import leaves the cache tree untouched. Lock inodes are kept after
    closing: deleting one can split waiters across two inodes. Always take the
    gate before the bucket lock so ordering cannot deadlock.
    """
    locks = Path(root) / 'var/seafloor/import-locks'
    locks.mkdir(parents=True, exist_ok=True)
    sha = row.get('sha256')
    known = isinstance(sha, str) and len(sha) == 64 and set(sha) <= set('0123456789abcdef')
    with contextlib.ExitStack() as stack:
        gate = stack.enter_context((locks / 'unknown-source.gate').open('a'))
        fcntl.flock(gate, fcntl.LOCK_SH if known else fcntl.LOCK_EX)
        if known:
            bucket = stack.enter_context((locks / (hashlib.sha256(sha.encode()).hexdigest() + '.lock')).open('a'))
            fcntl.flock(bucket, fcntl.LOCK_EX)
        yield


def ingest(row, bounds, *, root=REPO, fetch=False, local=None):
    bbox(list(bounds))
    # Hold the lock through receipt installation in every adapter.
    with _import_lock(root, row):
        return _ingest(row, bounds, root=root, fetch=fetch, local=local)


def _ingest(row, bounds, *, root, fetch, local):
    if row.get('format') == 'measured-multibeam-grid':
        from .adapters.multibeam_grid import ingest as ingest_grid
        return ingest_grid(row, bounds, root=root, local=local)
    if row.get('format') == 'geographic-geotiff':
        from .reproject_geographic import ingest as ingest_geographic
        return ingest_geographic(row, bounds, root=root, fetch=fetch, local=local)
    from .ingest import ingest as ingest_native
    if row.get('format') == 'usgs-geotiff' and row.get('kind') == 'bathymetry':
        from .adapters import usgs_geotiff
        from .fetch import fetch_source
        from .sample_units import require_unpacked_metre_elevation

        source, downloaded = fetch_source(row, Path(root) / 'var/seafloor/cache', fetch=fetch, local=local)
        # Inspect the same verified original (and selected ZIP member) before
        # native ingest can reuse a normalized COG. Accepted keys stay unchanged.
        with usgs_geotiff.open_source(source, row) as dataset:
            require_unpacked_metre_elevation(dataset)
        # fetch_source stores originals under their verified SHA, even for a
        # draft with an unknown SHA. Bind the native call to that cached copy.
        verified = dict(row, sha256=source.parent.name, bytes=source.stat().st_size)
        saved, _, reused = ingest_native(verified, bounds, root=root)
        return saved, downloaded, reused
    return ingest_native(row, bounds, root=root, fetch=fetch, local=local)
