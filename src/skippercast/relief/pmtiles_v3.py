"""Streaming PMTiles v3 writer for relief PNG tiles."""

import gzip
import hashlib
import json
from collections.abc import Iterable
from pathlib import Path
import struct
import tempfile

_HEADER_SIZE = 127
_ROOT_LIMIT = 16384 - _HEADER_SIZE
_START_LEAF_ENTRIES = 4096

Tile = tuple[int, int, int]  # z, x, y
_Entry = tuple[int, int, int, int]  # tile id, section-relative offset, length, run length


def _tile_id(z: int, x: int, y: int) -> int:
    """Cumulative Hilbert position (PMTiles v3 §4.1)."""
    if not 0 <= z <= 26 or not (0 <= x < 1 << z and 0 <= y < 1 << z):
        raise ValueError(f'invalid PMTiles coordinate: {(z, x, y)}')
    tid = ((1 << (2 * z)) - 1) // 3
    step = (1 << z) // 2
    while step:
        rx, ry = bool(x & step), bool(y & step)
        tid += step * step * ((3 * rx) ^ ry)
        if not ry:
            if rx:
                x, y = step - 1 - x, step - 1 - y
            x, y = y, x
        step //= 2
    return tid


def _varint(out: bytearray, value: int) -> None:
    while value >= 128:
        out.append((value & 127) | 128)
        value >>= 7
    out.append(value)


def _directory(entries: list[_Entry]) -> bytes:
    out = bytearray()
    _varint(out, len(entries))
    last = 0
    for tid, _, _, _ in entries:
        _varint(out, tid - last)
        last = tid
    for _, _, _, run in entries:
        _varint(out, run)
    for _, _, length, _ in entries:
        _varint(out, length)
    end = -1
    for _, offset, length, _ in entries:
        _varint(out, 0 if offset == end else offset + 1)
        end = offset + length
    return gzip.compress(out, mtime=0)


def _directories(entries: list[_Entry]) -> tuple[bytes, bytearray]:
    root = _directory(entries)
    if len(root) <= _ROOT_LIMIT:
        return root, bytearray()

    # Use one level of leaves. Increase the chunk size if the pointers alone
    # do not fit in the reader's first 16 KiB fetch.
    chunk_size = _START_LEAF_ENTRIES
    while True:
        pointers, leaves = [], bytearray()
        for start in range(0, len(entries), chunk_size):
            leaf = _directory(entries[start:start + chunk_size])
            pointers.append((entries[start][0], len(leaves), len(leaf), 0))
            leaves.extend(leaf)
        root = _directory(pointers)
        if len(root) <= _ROOT_LIMIT:
            return root, leaves
        chunk_size *= 2


def write_pmtiles(
    path: str | Path,
    tiles: Iterable[tuple[Tile, bytes]],
    *,
    metadata: dict,
    bounds: tuple[float, float, float, float],
    minzoom: int,
    maxzoom: int,
    center: tuple[int, float, float],
) -> Path:
    """Write legacy-compatible relief PNG PMTiles, atomically replacing `path`.

    Consume ((z, x, y), png_bytes) pairs from a single-pass iterable, or pass
    `tiles.items()` for an existing mapping. Input can be in any order, but
    coordinates must be unique. Only the tile index and directories grow in
    memory; temporary disk usage can reach input plus output size. Distinct
    contents are stored in order of first Hilbert occurrence.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    records = []
    with tempfile.TemporaryFile(dir=path.parent) as spool:
        for zxy, data in tiles:
            if not data:
                raise ValueError(f'empty tile payload at {zxy}')
            records.append((_tile_id(*zxy), spool.tell(), len(data), hashlib.sha256(data).digest()))
            spool.write(data)
        records.sort()

        entries, contents = [], {}
        size, previous = 0, -1
        for tid, source, length, digest in records:
            if tid == previous:
                raise ValueError(f'duplicate tile id: {tid}')
            previous = tid
            if digest not in contents:
                contents[digest] = (size, source)
                size += length
            offset, _ = contents[digest]
            if entries and entries[-1][0] + entries[-1][3] == tid and entries[-1][1] == offset:
                entries[-1] = (*entries[-1][:3], entries[-1][3] + 1)
            else:
                entries.append((tid, offset, length, 1))

        root, leaves = _directories(entries)
        meta = gzip.compress(json.dumps(metadata, sort_keys=True, separators=(',', ':')).encode(), mtime=0)
        meta_offset = _HEADER_SIZE + len(root)
        leaf_offset = meta_offset + len(meta)
        data_offset = leaf_offset + len(leaves)
        header = (
            b'PMTiles\x03'
            + struct.pack('<11Q', _HEADER_SIZE, len(root), meta_offset, len(meta),
                          leaf_offset if leaves else data_offset + size, len(leaves),  # legacy no-leaf offset
                          data_offset, size, len(records), len(entries), len(contents))
            + bytes([1, 2, 1, 2, minzoom, maxzoom])  # clustered, gzip internals, uncompressed PNG payloads
            + struct.pack('<4iB2i', *(round(v * 1e7) for v in bounds), center[0],
                          round(center[1] * 1e7), round(center[2] * 1e7))
        )
        part = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, suffix='.part', delete=False) as output:
                part = Path(output.name)
                output.write(header)
                output.write(root)
                output.write(meta)
                output.write(leaves)
                # Read each distinct blob once, in first-occurrence order.
                for _, source, length, digest in records:
                    if source == contents[digest][1]:
                        spool.seek(source)
                        output.write(spool.read(length))
            part.replace(path)
        finally:
            if part is not None:
                part.unlink(missing_ok=True)
    return path
