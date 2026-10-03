"""Route reviewed source formats without invalidating legacy native COG keys."""
from skippercast.platform.contracts import REPO, bbox


def ingest(row, bounds, *, root=REPO, fetch=False, local=None):
    bbox(list(bounds))
    if row.get('format') == 'measured-multibeam-grid':
        from .adapters.multibeam_grid import ingest as ingest_grid
        return ingest_grid(row, bounds, root=root, local=local)
    from .ingest import ingest as ingest_native
    return ingest_native(row, bounds, root=root, fetch=fetch, local=local)
