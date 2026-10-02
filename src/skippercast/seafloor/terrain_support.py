"""Source-bound positive terrain support, separate from depth and substrate.

The original CSUMB rough/smooth interpretation shares the depth survey. It can
restrict habitat calibration and extraction, but cannot prove substrate, fish
presence, independent corroboration or the absence of acquisition artifacts.
"""
from contextlib import contextmanager
from datetime import date
import hashlib
import json
from pathlib import Path, PurePosixPath


ROUGH_CODES = (-1, -31, -101, -201)
SMOOTH_CODES = (0, -30, -100, -200)


def validate_binding(row):
    binding = row.get('terrain_support')
    if binding is None:
        return
    if (row['kind'] != 'bathymetry' or row['format'] != 'arcgrid'
            or binding['depth_source_id'] != row['id']
            or binding['source_sha256'] != row['sha256']
            or binding['depth_archive_member'] != row['archive_member']
            or binding['depth_cog_sha256'] != row.get('adapter_review', {}).get('cog_sha256')):
        raise ValueError('Terrain support must bind the exact reviewed native depth product')
    if (binding['profile'] != 'csumb-native-rough-v1'
            or binding['rough_codes'] != list(ROUGH_CODES)
            or binding['smooth_codes'] != list(SMOOTH_CODES)):
        raise ValueError('Unreviewed terrain support legend')
    if date.fromisoformat(binding['reviewed_on']) > date.today():
        raise ValueError('Terrain support review cannot be dated in the future')
    if not binding['evidence'] or not set(binding['evidence']) <= set(row['evidence']):
        raise ValueError('Terrain support requires inventoried original-source evidence')
    for member in (binding['archive_member'], binding['depth_archive_member']):
        if (not member or PurePosixPath(member).is_absolute() or '..' in PurePosixPath(member).parts
                or '\\' in member or ':' in member):
            raise ValueError('Unsafe terrain support archive member')
    if binding['archive_member'].rstrip('/') == row['archive_member'].rstrip('/'):
        raise ValueError('Terrain support must select a separate categorical product')


def binding_digest(row):
    return hashlib.sha256(json.dumps(row['terrain_support'], sort_keys=True).encode()).hexdigest()


def feature_evidence(row):
    if not row.get('terrain_support'):
        return None
    binding = row['terrain_support']
    return {'profile': binding['profile'], 'binding_sha256': binding_digest(row),
            'depth_source_id': row['id'], 'source_sha256': binding['source_sha256'],
            'archive_member': binding['archive_member'], 'metadata_sha256': binding['metadata_sha256'],
            'same_survey_as_depth': True, 'independent_confirmation': False,
            'meaning': 'Producer-interpreted rough terrain; substrate and fish presence not established.',
            'evidence': list(binding['evidence'])}


def classify(values, valid):
    import numpy as np
    used = values[valid]
    if not np.isfinite(used).all() or not (used == np.floor(used)).all():
        raise ValueError('Terrain support codes must be finite integers')
    if not set(np.unique(used)) <= set(ROUGH_CODES + SMOOTH_CODES):
        raise ValueError('Unreviewed terrain support codes')
    return valid & np.isin(values, ROUGH_CODES)


@contextmanager
def native_reader(source, *, root):
    """Verify original bytes, exact native alignment and embedded metadata."""
    import rasterio
    from .adapters.arcgrid import source_path
    from .fetch import fetch_source
    from .io import sha256
    row = source['row']
    validate_binding(row)
    binding = row['terrain_support']
    if sha256(source['path']) != binding['depth_cog_sha256']:
        raise ValueError('Terrain support normalized depth checksum mismatch')
    archive, _ = fetch_source(row, Path(root)/'var/seafloor/cache')
    categorical = source_path(archive, {'archive_member': binding['archive_member']})
    if sha256(categorical/'metadata.xml') != binding['metadata_sha256']:
        raise ValueError('Terrain support original metadata checksum mismatch')
    with rasterio.open(source_path(archive, row)) as depth, rasterio.open(categorical) as support:
        if (depth.crs is None or depth.crs != support.crs or depth.transform != support.transform
                or depth.shape != support.shape or depth.count != 1 or support.count != 1
                or tuple(support.res) != (row['resolution_m'], row['resolution_m'])):
            raise ValueError('Terrain support does not exactly align with original native depth')
        if support.nodata is None or support.nodata in ROUGH_CODES + SMOOTH_CODES:
            raise ValueError('Terrain support requires an explicit original NoData mask')
        yield support


@contextmanager
def support_reader(source, shape, affine, *, root):
    """Read bounded support windows on the same nearest grid used for depth."""
    import numpy as np
    from rasterio.enums import Resampling
    from rasterio.vrt import WarpedVRT
    if not source['row'].get('terrain_support'):
        yield lambda window: np.ones((int(window.height), int(window.width)), dtype=bool)
        return
    with native_reader(source, root=root) as native:
        with WarpedVRT(native, crs='EPSG:3310', transform=affine, width=shape[1],
                       height=shape[0], resampling=Resampling.nearest) as vrt:
            def read(window):
                values = vrt.read(1, window=window, masked=True)
                return classify(values.data, ~np.ma.getmaskarray(values))
            yield read


def read_support(source, shape, affine, *, root):
    from rasterio.windows import Window
    with support_reader(source, shape, affine, root=root) as read:
        return read(Window(0, 0, shape[1], shape[0]))


def verify_sources(sources, *, root):
    """Binding evidence remains required on cache hits, not just fresh runs."""
    for source in sources:
        if source['row'].get('terrain_support'):
            with native_reader(source, root=root):
                pass
