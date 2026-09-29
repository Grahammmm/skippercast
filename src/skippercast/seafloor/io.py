"""Pinned small-asset cache, extracted from the existing NOAA audit downloader.

Original-survey raster caching and normalization arrive in M2.
"""
from urllib.parse import urlsplit

from .. import http
from ..util.hashing import sha256_file as sha256  # noqa: F401  (re-exported to seafloor modules)

NOAA_PREFIX = 'https://noaa-ocs-nationalbathymetry-pds.s3.amazonaws.com/'


def verified_file(url, expected, destination, fetch, *, max_bytes=128 * 1024 * 1024,
                  allowed_prefix=NOAA_PREFIX, session=None):
    if not destination.exists():
        if not fetch:
            raise FileNotFoundError(destination)
        if not url.startswith(allowed_prefix):
            raise ValueError('Unexpected source host or path')
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + '.part')
        try:
            with temporary.open('wb') as output:
                try:
                    (session or http.default_session()).download(
                        url, output, timeout=60, max_bytes=max_bytes,
                        allowed_hosts=[urlsplit(allowed_prefix).hostname], allowed_prefixes=(allowed_prefix,))
                except http.BodyTooLarge as error:
                    raise ValueError('Source exceeds byte limit') from error
                except http.DisallowedHost as error:
                    raise ValueError('Unexpected source redirect') from error
            if sha256(temporary).lower() != expected.lower():
                raise ValueError('SHA-256 mismatch for downloaded asset')
            temporary.replace(destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    actual = sha256(destination)
    if actual.lower() != expected.lower():
        raise ValueError(f'SHA-256 mismatch for {destination.name}')
    return actual
