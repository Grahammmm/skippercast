"""Content-addressed original-file cache; local imports are verified, never trusted."""
import hashlib
from pathlib import Path
import re
from urllib.parse import urlsplit

from skippercast import http
from skippercast.platform.contracts import atomic_json
from .io import sha256
from .rights import CSUMB_ARCHIVES, POINT_LOBOS_ARCHIVE

GENERAL_PREFIXES = ('https://cmgds.marine.usgs.gov/', 'https://pubs.usgs.gov/',
            'https://data.ngdc.noaa.gov/platforms/ocean/nos/coast/',
            'https://data.ngdc.noaa.gov/platforms/ocean/ships/harold_heath/',
            'https://data.ngdc.noaa.gov/platforms/ocean/ships/ventresca/')
PREFIXES = GENERAL_PREFIXES + (POINT_LOBOS_ARCHIVE,)
HOSTS = tuple(urlsplit(prefix).hostname for prefix in PREFIXES)


def fetch_source(row, cache, *, fetch=False, local=None, max_bytes=2_000_000_000, session=None):
    url, expected = row['url'], row['sha256']
    if not (url.startswith(GENERAL_PREFIXES) or url == POINT_LOBOS_ARCHIVE) or any(
            s in url.lower() for s in ('bluetopo', '/modeling/')):
        raise ValueError('Unreviewed original-source URL')
    if not re.fullmatch(r'[a-f0-9]{64}|unknown', expected):
        raise ValueError('Invalid source checksum')
    extension = Path(urlsplit(url).path).suffix.lower()
    if urlsplit(url).path.lower().endswith('.tar.gz'):
        extension = '.tar.gz'
    if extension not in {'.zip', '.bag', '.tif', '.tiff'} and not (
            row.get('format') == 'arcgrid' and (
                extension == '.tgz' and url.startswith('https://pubs.usgs.gov/') or
                extension == '.tar.gz' and (url.startswith(CSUMB_ARCHIVES)
                                           or url == POINT_LOBOS_ARCHIVE))):
        raise ValueError('Unsupported source container')
    cache = Path(cache)
    destination = cache / expected / ('source' + extension)
    if expected != 'unknown' and destination.exists():
        if sha256(destination) != expected:
            raise ValueError('Cached original checksum mismatch')
        if row['bytes'] != 'unknown' and destination.stat().st_size != row['bytes']:
            raise ValueError('Cached original byte count mismatch')
        return destination, False
    if local is None and not fetch:
        raise FileNotFoundError('Original source missing; use --fetch or --local')
    cache.mkdir(parents=True, exist_ok=True)
    temporary = cache / (hashlib.sha256(url.encode()).hexdigest() + '.part')
    try:
        if local is not None:
            digest, size = hashlib.sha256(), 0
            with Path(local).open('rb') as stream, temporary.open('wb') as output:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError('Original source exceeds byte limit')
                    digest.update(chunk)
                    output.write(chunk)
            actual = digest.hexdigest()
        else:
            with temporary.open('wb') as output:
                try:
                    receipt = (session or http.default_session()).download(
                        url, output, timeout=60, max_bytes=max_bytes,
                        allowed_hosts=HOSTS, allowed_prefixes=PREFIXES).receipt
                except http.BodyTooLarge as error:
                    raise ValueError('Original source exceeds byte limit') from error
                except http.DisallowedHost as error:
                    raise ValueError('Original source redirected outside reviewed publishers') from error
            actual, size = receipt.sha256, receipt.bytes
        if size == 0:
            raise ValueError('Original source is empty')
        if expected != 'unknown' and actual != expected:
            raise ValueError('Original source checksum mismatch')
        if row['bytes'] != 'unknown' and row['bytes'] != size:
            raise ValueError('Original source byte count mismatch')
        destination = cache / actual / ('source' + extension)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary.replace(destination)
        atomic_json(destination.parent / 'source.json', {'url': url, 'sha256': actual, 'bytes': size})
        return destination, local is None
    finally:
        temporary.unlink(missing_ok=True)


def restore_private(s3, bucket, destination, expected, *, max_bytes=2_000_000_000):
    """Optional private R2 restore; credentials/client are supplied by the job."""
    if not re.fullmatch(r'[a-f0-9]{64}', expected):
        raise ValueError('Invalid private cache checksum')
    destination = Path(destination)
    key = f'seafloor-cache/{expected}/{destination.name}'
    temporary = destination.with_suffix(destination.suffix + '.part')
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        with s3.get_object(Bucket=bucket, Key=key)['Body'] as stream, temporary.open('wb') as output:
            size = 0
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError('Private source exceeds byte limit')
                output.write(chunk)
        if sha256(temporary) != expected:
            raise ValueError('Private source cache checksum mismatch')
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def upload_private(s3, bucket, source):
    source = Path(source)
    digest = sha256(source)
    with source.open('rb') as stream:
        s3.put_object(Bucket=bucket, Key=f'seafloor-cache/{digest}/{source.name}', Body=stream,
                      CacheControl='private, no-store', ContentType='application/octet-stream')
