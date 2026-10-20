"""Root-confined byte references and independently supplied review checks."""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

MAX_SOURCE_BYTES = 2 * 1024**3
MAX_JSON_BYTES = 2_000_000


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda: stream.read(1024**2), b''):
            h.update(part)
    return h.hexdigest()


def confined(root, relative, *, existing=True):
    root = Path(root).resolve()
    p = Path(relative)
    if p.is_absolute() or not p.parts or '..' in p.parts:
        raise ValueError('artifact path must be root-relative')
    candidate = root / p
    for parent in [candidate, *candidate.parents]:
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError('artifact symlinks refused')
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError('artifact escapes root')
    if existing and not resolved.is_file():
        raise ValueError('artifact is not a regular file')
    return resolved


def ref(root, path, contract, *, cap=MAX_SOURCE_BYTES):
    path = Path(path)
    if path.is_absolute():
        # Accept the caller's declared root spelling as well as its canonical
        # spelling (for example macOS /var and /private/var). Do not resolve the
        # artifact itself: confined must still see traversal and child symlinks.
        declared_root = Path(root).absolute()
        try:
            path = path.relative_to(declared_root)
        except ValueError:
            path = path.relative_to(declared_root.resolve())
    path = confined(root, path)
    size = path.stat().st_size
    if size > cap:
        raise ValueError('artifact byte cap exceeded')
    return dict(path=path.relative_to(Path(root).resolve()).as_posix(), sha256=sha(path), bytes=size, contract=contract)


def resolve(root, artifact, *, contract=None, cap=MAX_SOURCE_BYTES):
    if not isinstance(artifact, dict) or (contract and artifact.get('contract') != contract):
        raise ValueError('artifact contract mismatch')
    path = confined(root, artifact['path'])
    if type(artifact.get('bytes')) is not int or not 0 <= artifact['bytes'] <= cap:
        raise ValueError('artifact byte size invalid')
    if path.stat().st_size != artifact['bytes'] or sha(path) != artifact.get('sha256'):
        raise ValueError('artifact bytes/hash changed')
    return path


def load(root, value, *, contract=None):
    if isinstance(value, dict) and 'path' in value and 'sha256' in value:
        path = resolve(root, value, contract=contract, cap=MAX_JSON_BYTES)
        return json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError('manifest must be an object or byte reference')
    return value


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, sort_keys=True, separators=(',', ':'), allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def epoch(now):
    if isinstance(now, datetime):
        if now.tzinfo is None:
            raise ValueError('aware clock required')
        return now.timestamp()
    if isinstance(now, str):
        return epoch(datetime.fromisoformat(now.replace('Z', '+00:00')))
    number = float(now)
    if not math.isfinite(number):
        raise ValueError('finite clock required')
    return number


def review_holds(root, review, facts_digest, *, now, minimum_valid_until=None, schema='coastal-private-input-review-v2'):
    if review is None:
        return ['independent_review_missing']
    resolve(root, review, contract=schema, cap=MAX_JSON_BYTES)
    document = load(root, review, contract=schema)
    holds = []
    if (document.get('schema') != schema or document.get('independent') is not True
            or not document.get('reviewer_id') or document['reviewer_id'].startswith('coastal.')
            or document.get('facts_digest') != facts_digest):
        holds.append('independent_review_binding_invalid')
    try:
        if not epoch(document['checked_at']) <= epoch(now) < epoch(document['valid_until']):
            holds.append('review_expired_or_future')
        if minimum_valid_until is not None and epoch(document['valid_until']) <= epoch(minimum_valid_until):
            holds.append('review_insufficient_validity')
    except (KeyError, ValueError, TypeError):
        holds.append('review_time_invalid')
    if document.get('decision') not in ('qualified_private_terrain', 'accept'):
        holds.append('review_not_accepted')
    added = document.get('holds_added')
    if not isinstance(added, list) or any(not isinstance(x, str) or not x for x in added):
        holds.append('review_holds_invalid')
    else:
        holds.extend(added)
    return sorted(set(holds))


TIFF_SIGNATURES = (b'II*\x00', b'MM\x00*', b'II+\x00', b'MM\x00+')
HDF5_SIGNATURE = b'\x89HDF\r\n\x1a\n'
# netCDF classic, 64-bit offset and CDF-5. None of them can reference another file.
NETCDF_CLASSIC_SIGNATURES = (b'CDF\x01', b'CDF\x02', b'CDF\x05')


def _local_hdf5_tree(h5py, start, label):
    """Refuse soft/external links and virtual/external-storage datasets below ``start``."""
    visited, pending, total = set(), [start], 0
    while pending:
        group = pending.pop()
        address = h5py.h5o.get_info(group.id).addr
        if address in visited:
            continue
        visited.add(address)
        for name in group:
            total += 1
            if total > 1024:
                raise ValueError(f'{label} container link bound exceeded')
            if not isinstance(group.get(name, getlink=True), h5py.HardLink):
                raise ValueError(f'{label} external/soft links refused before GDAL')
            item = group[name]
            if isinstance(item, h5py.Group):
                pending.append(item)
            elif isinstance(item, h5py.Dataset):
                if item.is_virtual or item.external:
                    raise ValueError(f'{label} virtual/external-storage datasets refused before GDAL')
            else:
                raise ValueError(f'{label} container object unsupported')


NETCDF_STEM_SIDECARS = ('.aux', '.aux.xml', '.msk', '.ovr', '.rrd')


def _no_netcdf_sidecars(path):
    """Refuse every GDAL-probed sidecar of a netCDF source before GDAL opens it.

    PAM (.aux.xml), masks (.msk), overviews (.ovr/.rrd) and auxiliary files
    (.aux) can override georeferencing or nodata, or point GDAL at further
    datasets (a mask can be a VRT referencing a file outside the queue). The
    bridge lane binds no netCDF sidecar lineage, so any name GDAL derives from
    the filename (``crm.nc.*``) or the stem (``crm.aux``...) is refused,
    case-insensitively and whether a file, directory or (dangling) symlink.
    """
    filename, stem = path.name.lower(), path.stem.lower()
    stem_forms = {stem+extension for extension in NETCDF_STEM_SIDECARS}
    for sibling in path.parent.iterdir():
        name = sibling.name.lower()
        if name != filename and (name.startswith(filename+'.') or name in stem_forms):
            raise ValueError('netCDF sidecar refused before GDAL')


def native_container(path):
    """Classify a local source by its bytes: 'tiff', 'bag', 'netcdf' or None.

    A netCDF-4 file is HDF5 without a ``BAG_root``; the classification never
    decides admission, which stays with ``validate_native_source``.
    """
    with Path(path).open('rb') as stream:
        magic = stream.read(8)
    if magic[:4] in TIFF_SIGNATURES:
        return 'tiff'
    if magic[:4] in NETCDF_CLASSIC_SIGNATURES:
        return 'netcdf'
    if magic != HDF5_SIGNATURE:
        return None
    import h5py
    with h5py.File(path, 'r') as source:
        return 'netcdf' if source.get('BAG_root', getlink=True) is None else 'bag'


def validate_native_source(root, artifact, *, netcdf=False):
    """Inspect permitted containers before GDAL can follow any source links.

    ``netcdf=True`` additionally admits a local netCDF container (classic, or
    netCDF-4 whose whole HDF5 tree is local) for the bridge-lane reader only.
    """
    path = resolve(root, artifact)
    with path.open('rb') as stream:
        magic = stream.read(8)
    if magic[:4] in TIFF_SIGNATURES:
        for auxiliary in (Path(str(path)+'.aux.xml'),Path(str(path)+'.ovr'),Path(str(path)+'.msk'),path.with_suffix('.aux')):
            if auxiliary.exists() or auxiliary.is_symlink():
                ref(root,auxiliary,'native-raster-auxiliary-v1')
        return path
    if netcdf and magic[:4] in NETCDF_CLASSIC_SIGNATURES:
        _no_netcdf_sidecars(path)
        return path
    if magic != HDF5_SIGNATURE:
        raise ValueError('native container signature unsupported; VRT/network readers refused')
    import h5py
    with h5py.File(path, 'r') as source:
        link = source.get('BAG_root', getlink=True)
        if netcdf and link is None:
            _local_hdf5_tree(h5py, source, 'netCDF-4')
            _no_netcdf_sidecars(path)
            return path
        if not isinstance(link, h5py.HardLink):
            raise ValueError('BAG_root must be a local hard link')
        root_group = source['BAG_root']
        if not isinstance(root_group, h5py.Group):
            raise ValueError('BAG_root must be a local group')
        _local_hdf5_tree(h5py, root_group, 'BAG')
        for name in ('elevation', 'uncertainty', 'metadata'):
            if name not in root_group or not isinstance(root_group[name], h5py.Dataset):
                raise ValueError('BAG required local datasets missing')
        if root_group['metadata'].size > 1_000_000:
            raise ValueError('BAG metadata byte bound exceeded')
    return path


def validate_derived_geotiff(root, artifact, *, contract=None, cap=MAX_SOURCE_BYTES):
    """Require self-contained TIFF bytes before opening a derived artifact.

    Derived output contracts carry no sidecar lineage. PAM, masks, overviews,
    world files and related metadata must therefore be absent, including case
    variants; a caller cannot introduce an unbound secondary GDAL source.
    """
    path = resolve(root, artifact, contract=contract, cap=cap)
    with path.open('rb') as stream:
        if stream.read(4) not in (b'II*\x00', b'MM\x00*', b'II+\x00', b'MM\x00+'):
            raise ValueError('derived artifact requires a self-contained GeoTIFF; VRT/BAG refused')
    stem, filename = path.stem.lower(), path.name.lower()
    forbidden = {filename+extension for extension in ('.aux.xml','.msk','.ovr','.rrd')}
    forbidden.update(stem+extension for extension in
                     ('.aux','.aux.xml','.tfw','.tifw','.tiffw','.tfwx','.wld','.tab','.rpb','.imd','.rpc'))
    for sibling in path.parent.iterdir():
        if sibling.name.lower() in forbidden:
            raise ValueError('unbound derived GeoTIFF sidecar refused before GDAL')
    return path
