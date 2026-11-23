"""Verify a live relief archive against a reviewed pointer, using an injected fetcher."""
from __future__ import annotations

from collections.abc import Iterator
import gzip
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
from tempfile import SpooledTemporaryFile, TemporaryDirectory
from typing import BinaryIO, cast
import zlib

from skippercast.relief import digests, package

# Staged root and chunk objects share a one MiB limit.
_INDEX_LIMIT = 1 << 20
_CHUNK_NAME = re.compile(r'([89]|1[0-7])/(0|[1-9][0-9]{0,3})_(0|[1-9][0-9]{0,3})\.json')


def _samples(data, minzoom, maxzoom):
    root = package.decode_document(data)
    chunks = root.get('chunks')
    if root.keys() != {'chunks'} or not isinstance(chunks, dict):
        raise ValueError('invalid root inventory')
    samples = {}
    for name, sha in chunks.items():
        match = _CHUNK_NAME.fullmatch(name)
        if not match or not package.is_sha256(sha):
            raise ValueError('invalid root reference')
        z, bx, by = map(int, match.groups())
        if not minzoom <= z <= maxzoom or max(bx, by) >= 1 << (z - 6):
            raise ValueError('root reference outside zoom or tile grid')
        block = (bx, by)
        if z not in samples or block < samples[z][0]:
            samples[z] = (block, name, sha)
    return samples


def _first_tile(data, block):
    rows = json.loads(data)
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], list) or len(rows[0]) != 3:
        raise ValueError('invalid chunk sample')
    x, y, sha = rows[0]
    if (type(x) is not int or type(y) is not int or not package.is_sha256(sha)
            or (x // digests.BLOCK_SIZE, y // digests.BLOCK_SIZE) != block):
        raise ValueError('invalid tile row')
    return rows[0]


def check_archive(pointer, fetch, *, budget=20, _verify_archive_hash: bool = True) -> list[dict]:
    """Return ordered per-object checks. ``fetch(key, max_bytes=...)`` yields bytes or None.

    The pointer must already be reviewed. Fetcher exceptions propagate to the caller.
    ``_verify_archive_hash=False`` is for isolated tile tamper tests only; the
    streaming cap still applies. No tile or range requests are made.
    """
    stem = f"tiles/relief/{pointer['region']}/{pointer['sha256']}"
    archive_key = f'{stem}.pmtiles'
    digest_prefix = f"{stem}.digests/{pointer['digest_root_sha256']}/"
    root_key = f'{digest_prefix}root.json'
    rows = []

    def record(check, key, reason=''):
        rows.append({'check': check, 'key': key, 'status': 'FAIL' if reason else 'PASS', 'reason': reason})

    def read(key, limit, sha, output, *, size=None, verify=True):
        nonlocal budget
        if budget <= 0:
            return 'budget'
        budget -= 1
        body: Iterator[bytes] | None = fetch(key, max_bytes=limit)
        if body is None:
            return 'missing'
        count, digest = 0, hashlib.sha256()
        try:
            for block in body:
                count += len(block)
                if count > limit:
                    return 'oversize'
                digest.update(block)
                output.write(block)
        finally:
            close = getattr(body, 'close', None)
            if close is not None:
                close()
        if verify:
            if size is not None and count != size:
                return 'size'
            if digest.hexdigest() != sha:
                return 'sha256'
        return ''

    size = pointer['bytes']
    with TemporaryDirectory(prefix='relief-live-') as temp, SpooledTemporaryFile(max_size=_INDEX_LIMIT) as spool:
        reason = read(archive_key, size, pointer['sha256'], spool, size=size, verify=_verify_archive_hash)
        if not reason:
            try:
                digests.write_index(cast(BinaryIO, spool), Path(temp))
            except (digests.DigestError, gzip.BadGzipFile, EOFError, zlib.error):
                reason = 'invalid'
        record('archive', archive_key, reason)
        if reason:
            return rows

        root = BytesIO()
        reason = read(root_key, _INDEX_LIMIT, pointer['digest_root_sha256'], root)
        if reason:
            record('root', root_key, reason)
            return rows
        try:
            samples = _samples(root.getvalue(), pointer['minzoom'], pointer['maxzoom'])
        except ValueError:
            record('root', root_key, 'invalid')
            return rows
        record('root', root_key)

        low, high = pointer['minzoom'], pointer['maxzoom']
        support = pointer.get('native_support_by_zoom')
        empty_zooms = set()
        if isinstance(support, dict):
            for z in range(low + 1, high):
                tier = support.get(str(z))
                if (isinstance(tier, dict) and type(tier.get('tiles')) is int
                        and tier['tiles'] == 0 and tier.get('sources') == []):
                    empty_zooms.add(z)

        local_zooms = set()
        if empty_zooms:
            # The fresh local root lists every block found in the verified archive.
            local_root = package.decode_document((Path(temp) / 'root.json').read_bytes())
            local_zooms = {int(name.split('/', 1)[0]) for name in local_root['chunks']}

        for z in range(low, high + 1):
            if z in empty_zooms:
                if z in samples or z in local_zooms:
                    record('chunk', f'{digest_prefix}{z}/', 'invalid')
                # No object to fetch or report if both inventories corroborate the gap.
                continue
            if z not in samples:
                record('chunk', f'{digest_prefix}{z}/', 'missing')
                continue
            block, name, sha = samples[z]
            chunk_key = digest_prefix + name
            chunk = BytesIO()
            reason = read(chunk_key, _INDEX_LIMIT, sha, chunk)
            if reason:
                record('chunk', chunk_key, reason)
                if reason == 'budget':
                    break
                continue
            try:
                tile = _first_tile(chunk.getvalue(), block)
            except ValueError:
                record('chunk', chunk_key, 'invalid')
                continue
            record('chunk', chunk_key)

            x, y, _ = tile
            local_path = Path(temp) / name
            local_rows = json.loads(local_path.read_bytes()) if local_path.is_file() else []
            local_tile = next((row for row in local_rows if row[:2] == [x, y]), None)
            reason = 'missing' if local_tile is None else ('sha256' if local_tile != tile else '')
            record('tile', f'{archive_key}#{z}/{x}/{y}', reason)
    return rows
