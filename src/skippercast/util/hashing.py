"""Content hashes for receipts and publication manifests."""
import hashlib
from pathlib import Path

CHUNK = 1024 * 1024


def sha256_file(path):
    """Lower-case hex SHA-256 of a file's bytes, read in 1 MiB chunks."""
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b''):
            digest.update(chunk)
    return digest.hexdigest()
