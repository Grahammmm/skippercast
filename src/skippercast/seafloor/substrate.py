"""Reviewed original categorical grids. Unknown coverage is never called sand.

Bindings review categorical semantics separately from bathymetry qualification.
They pin a manifest product and metadata digest; a held/withdrawn product is not
read. Nearest-neighbor projection preserves classes and producer no-data masks.
"""
from pathlib import Path
from contextlib import contextmanager
import re

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.vrt import WarpedVRT

from .adapters.usgs_geotiff import source_path
from .fetch import fetch_source
from skippercast.platform.contracts import public_url


def resolve_bindings(rules, manifest):
    rows = {row['id']: row for row in manifest['surveys']}
    result = {}
    for binding in rules['substrate_bindings']:
        row = rows[binding['source_id']]
        if row['status'] in {'hold', 'withdrawn'}:
            continue
        if (row['kind'] != 'substrate' or row['format'] != 'usgs-geotiff'
                or row['sha256'] != binding['source_sha256']
                or row['license'] != 'public-domain-us-gov'
                or binding['review_status'] != 'reviewed'
                or not re.fullmatch('[a-f0-9]{64}', binding['metadata_sha256'])):
            raise ValueError('Substrate binding lacks matching original-source review')
        public_url(binding['metadata_url'])
        if any(category['normalized_code'] not in (1, 2, 3) for category in binding['classes'].values()):
            raise ValueError('Unreviewed normalized substrate class')
        for depth_id in binding['depth_source_ids']:
            if depth_id in result:
                raise ValueError('Ambiguous substrate binding for depth product')
            result[depth_id] = {'binding': binding, 'row': row}
    return result


def classify(values, valid, binding):
    """Return 0 unknown, 1 soft, 2 flat coarse/bedrock, 3 hard rugose."""
    result = np.zeros(values.shape, dtype='uint8')
    if not np.isfinite(values[valid]).all() or not (values[valid] == np.floor(values[valid])).all():
        raise ValueError('Unreviewed substrate codes must be finite integers')
    known = set(binding['classes'])
    actual = {str(int(x)) for x in np.unique(values[valid])}
    if not actual <= known:
        raise ValueError(f'Unreviewed substrate codes: {sorted(actual-known)}')
    for code, category in binding['classes'].items():
        result[valid & (values == int(code))] = category['normalized_code']
    return result


@contextmanager
def class_reader(binding, shape, affine, *, root):
    """Open a verified categorical source once; read bounded nearest tiles."""
    if binding is None:
        yield lambda window: np.zeros((int(window.height), int(window.width)), dtype='uint8')
        return
    row = binding['row']
    archive, _ = fetch_source(row, Path(root)/'var/seafloor/cache')
    with rasterio.open(source_path(archive, row)) as source:
        if not np.isclose(max(source.res), row['resolution_m']):
            raise ValueError('Substrate resolution changed')
        with WarpedVRT(source, crs='EPSG:3310', transform=affine,
                width=shape[1], height=shape[0], resampling=Resampling.nearest) as vrt:
            def read(window):
                values = vrt.read(1, window=window, masked=True)
                return classify(values.data, ~np.ma.getmaskarray(values), binding['binding'])
            yield read


def read_classes(binding, shape, affine, *, root):
    from rasterio.windows import Window
    with class_reader(binding, shape, affine, root=root) as read:
        return read(Window(0, 0, shape[1], shape[0]))


def verify_sources(bindings, *, root, fetch=False):
    """Recheck source bytes even when the reach computation is a cache hit."""
    for entry in bindings.values():
        fetch_source(entry['row'], Path(root)/'var/seafloor/cache', fetch=fetch)
