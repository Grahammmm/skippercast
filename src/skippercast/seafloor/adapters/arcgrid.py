"""Original USGS ArcInfo GRID archives, read at native spacing without conversion.

Only an explicitly reviewed grid directory is extracted. Tar links, special
files, duplicate names and traversal are rejected before any extraction.
The original archive is the private recovery object; extracted members are
reproducible scratch with their own checksum receipt.
"""
from pathlib import Path, PurePosixPath
import hashlib
import shutil
from tarfile import open as open_tar

import rasterio

from skippercast.platform.contracts import atomic_json, read_json
from ..io import sha256

MAX_MEMBERS = 4096
MAX_EXTRACTED_BYTES = 2_000_000_000


def safe_name(name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
        raise ValueError('Unsafe ArcInfo archive member')
    return path.as_posix().rstrip('/')


def source_path(path, row):
    path = Path(path)
    if path.suffix.lower() != '.tgz':
        raise ValueError('ArcInfo adapter requires an original TGZ archive')
    member = safe_name(row['archive_member'])
    if member == 'unknown':
        raise ValueError('Select an exact reviewed ArcInfo grid directory')
    identity = hashlib.sha256(member.encode()).hexdigest()[:16]
    destination = path.parent/('grid-'+identity)
    receipt_path = destination.with_suffix('.json')
    archive_hash = sha256(path)
    if destination.is_symlink() or receipt_path.is_symlink():
        raise ValueError('Unsafe ArcInfo extracted path')
    if destination.exists() and receipt_path.exists():
        receipt = read_json(receipt_path)
        if receipt['archive_sha256'] != archive_hash or receipt['member'] != member:
            raise ValueError('Extracted ArcInfo source checksum mismatch')
        actual = {p.relative_to(destination).as_posix(): sha256(p)
                  for p in destination.rglob('*') if p.is_file() and not p.is_symlink()}
        if actual != receipt['files'] or any(p.is_symlink() for p in destination.rglob('*')):
            raise ValueError('Extracted ArcInfo member checksum mismatch')
        return destination
    temporary = destination.with_name(destination.name+'.part')
    if temporary.exists():
        shutil.rmtree(temporary)
    try:
        with open_tar(path, 'r:gz') as archive:
            selected, names, total = [], set(), 0
            for index, entry in enumerate(archive):
                if index >= MAX_MEMBERS:
                    raise ValueError('ArcInfo archive exceeds member bound')
                name = safe_name(entry.name)
                if name in names or not (entry.isfile() or entry.isdir()):
                    raise ValueError('Unsafe or duplicate ArcInfo archive entry')
                names.add(name)
                if entry.isfile():
                    if entry.size < 0:
                        raise ValueError('Invalid ArcInfo member size')
                    total += entry.size
                    if total > MAX_EXTRACTED_BYTES:
                        raise ValueError('ArcInfo extraction exceeds byte bound')
                    if name.startswith(member+'/'):
                        selected.append((entry, name[len(member)+1:]))
            if not {'hdr.adf', 'prj.adf'} <= {name for _, name in selected}:
                raise ValueError('Reviewed ArcInfo grid headers missing')
            temporary.mkdir(parents=True)
            files = {}
            for entry, name in selected:
                output = temporary/name
                output.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(entry) as stream, output.open('wb') as target:
                    shutil.copyfileobj(stream, target, length=1024*1024)
                if output.stat().st_size != entry.size:
                    raise ValueError('Incomplete ArcInfo extraction')
                files[name] = sha256(output)
        if destination.exists():
            raise ValueError('Unverified ArcInfo extraction already exists')
        temporary.rename(destination)
        atomic_json(receipt_path, {'archive_sha256': archive_hash, 'member': member, 'files': files})
        return destination
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def open_source(path, row):
    dataset = rasterio.open(source_path(path, row))
    if dataset.driver != 'AIG' or dataset.count != 1 or not dataset.crs:
        dataset.close()
        raise ValueError('Expected one georeferenced original ArcInfo elevation band')
    return dataset
