"""Route reviewed source formats without invalidating legacy native COG keys."""
import fcntl
import hashlib
from pathlib import Path

from skippercast.platform.contracts import REPO, bbox


def ingest(row, bounds, *, root=REPO, fetch=False, local=None):
    bbox(list(bounds))
    # Locks live beside, not inside, the content-addressed cache so a refused
    # import leaves the cache tree untouched. Keep the lock inode after closing:
    # deleting it can split waiters across two inodes. Hold it through receipt
    # installation in every adapter.
    locks = Path(root) / 'var/seafloor/import-locks'
    locks.mkdir(parents=True, exist_ok=True)
    source_key = hashlib.sha256(row['url'].encode()).hexdigest()
    with (locks / (source_key + '.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
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
