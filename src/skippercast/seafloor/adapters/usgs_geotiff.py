"""USGS native GeoTIFF and explicitly selected ZIP member, without resampling."""
from pathlib import Path, PurePosixPath
import shutil
from zipfile import ZipFile

import rasterio

from skippercast.platform.contracts import atomic_json, read_json
from ..io import sha256


def source_path(path, row):
    path = Path(path)
    if path.suffix.lower() != '.zip':
        return path
    member = row['archive_member']
    with ZipFile(path) as archive:
        members = [i for i in archive.infolist() if i.filename.lower().endswith(('.tif', '.tiff'))
                   and not i.filename.startswith('__MACOSX/')]
        if member == 'unknown':
            if len(members) != 1:
                raise ValueError('Select an exact GeoTIFF archive member; multiple resolutions cannot be guessed')
            member = members[0].filename
        if PurePosixPath(member).is_absolute() or '..' in PurePosixPath(member).parts:
            raise ValueError('Unsafe archive member')
        info = archive.getinfo(member)
        if not 0 < info.file_size <= 2_000_000_000:
            raise ValueError('GeoTIFF archive member exceeds extraction bound')
        destination = path.parent / ('member-' + sha256_text(member)[:16] + '.tif')
        receipt = destination.with_suffix('.json')
        if destination.exists() and receipt.exists():
            saved = read_json(receipt)
            if (saved['archive_sha256'] != sha256(path) or saved['member'] != member
                    or sha256(destination) != saved['sha256']):
                raise ValueError('Extracted source checksum mismatch')
            return destination
        temporary = destination.with_suffix('.part')
        try:
            with archive.open(member) as source, temporary.open('wb') as output:
                shutil.copyfileobj(source, output, length=1024*1024)
            if temporary.stat().st_size != info.file_size:
                raise ValueError('Incomplete GeoTIFF extraction')
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        atomic_json(receipt, {'archive_sha256': sha256(path), 'member': member, 'sha256': sha256(destination)})
        return destination


def sha256_text(text):
    import hashlib
    return hashlib.sha256(text.encode()).hexdigest()


def open_source(path, row):
    dataset = rasterio.open(source_path(path, row))
    if dataset.driver != 'GTiff' or dataset.count != 1 or not dataset.crs:
        dataset.close()
        raise ValueError('Expected one georeferenced USGS elevation band')
    return dataset
