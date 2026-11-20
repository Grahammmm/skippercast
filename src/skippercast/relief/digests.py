"""Index the tile bytes returned by the app's PMTiles 4.5 reader (E2E-PIPELINE §4).

Run before package. Include both the archive producer and `digests` in package's
upstreams and the digest receipt's output paths in the public layer inventory.

Index format: root.json is {"chunks": {"<z>/<block_x>_<block_y>.json": "<sha256>"}}.
Paths are relative to the root. Each chunk is a sorted array of [x, y, sha256]
rows for the tiles present in that 64×64 block. Hashes are lowercase hex.
"""
from __future__ import annotations

from collections import defaultdict
import gzip
import hashlib
import os
from pathlib import Path
import struct
from typing import BinaryIO, Iterator

from skippercast.relief import package, receipts

HEADER_SIZE = 127
ROOT_READ_SIZE = 16384
MAX_READER_ZOOM = 26
MAX_RELIEF_ZOOM = 17
BLOCK_SIZE = 64
INDEX_TARGET = Path(package.DIGEST_ROOT).parent.as_posix()


class DigestError(ValueError):
    """The archive cannot be indexed by the same rules as the app's reader."""


def _tile_id_start(z: int) -> int:
    return ((1 << (2 * z)) - 1) // 3


def _zxy(tile_id: int) -> tuple[int, int, int]:
    # Tile IDs concatenate the Hilbert curves for every zoom, starting at z0.
    z = ((3 * tile_id + 1).bit_length() - 1) // 2
    d = tile_id - _tile_id_start(z)
    x = y = 0
    s = 1
    while s < 1 << z:
        rx = (d >> 1) & 1
        ry = (d ^ rx) & 1
        if not ry:
            if rx:
                x, y = s - 1 - x, s - 1 - y
            x, y = y, x
        x += s * rx
        y += s * ry
        d >>= 2
        s <<= 1
    return z, x, y


def _varints(data: bytes) -> Iterator[int]:
    value = shift = 0
    for byte in data:
        value |= (byte & 127) << shift
        if byte < 128:
            if value >= 1 << 53:  # pmtiles 4.5 represents IDs and offsets as JS numbers
                raise DigestError('PMTiles directory varint exceeds the safe integer range')
            yield value
            value = shift = 0
        else:
            shift += 7
            if shift >= 56:
                raise DigestError('PMTiles directory varint is too long')
    if shift:
        raise DigestError('truncated PMTiles directory varint')


def _entries(data: bytes) -> Iterator[tuple[int, int, int, int]]:
    # v3 stores columns: tile ID deltas, run lengths, byte lengths, and offsets.
    values = _varints(data)
    count = next(values, 0)
    if not 0 < count <= (len(data) - 1) // 4:
        raise DigestError('empty or truncated PMTiles directory')
    columns = [[next(values, None) for _ in range(count)] for _ in range(4)]
    if None in columns[-1] or next(values, None) is not None:
        raise DigestError('invalid PMTiles directory columns')
    tile_id = end = 0
    for i, (delta, run, length, offset_code) in enumerate(zip(*columns)):
        if (i and delta == 0) or length == 0 or (not i and offset_code == 0):
            raise DigestError('invalid PMTiles directory entry')
        tile_id += delta
        offset = offset_code - 1 if offset_code else end
        end = offset + length
        yield tile_id, run, offset, length


def _decompress(data: bytes, compression: int) -> bytes:
    if compression == 2:
        return gzip.decompress(data)
    # The app's default reader treats both Unknown and None as passthrough.
    return data


class _Archive:
    def __init__(self, stream: BinaryIO):
        self.stream = stream
        self.size = stream.seek(0, os.SEEK_END)
        header = self.read(0, HEADER_SIZE)
        if header[:8] != b'PMTiles\x03':
            raise DigestError('expected a PMTiles v3 archive')
        root, root_len, _, _, leaves, leaves_len, tiles, tiles_len, addressed = struct.unpack_from('<9Q', header, 8)
        if root < HEADER_SIZE or root + root_len > ROOT_READ_SIZE:
            raise DigestError('PMTiles root directory is outside the app reader’s initial 16 KiB range')
        self.root = (root, root_len)
        self.leaves = (leaves, leaves_len)
        self.tiles = (tiles, tiles_len)
        for start, length in (self.root, self.leaves, self.tiles):
            if length and (start < HEADER_SIZE or start + length > self.size):
                raise DigestError('PMTiles section is outside the archive')
        self.directory_compression, self.tile_compression = header[97:99]
        if any(c not in (0, 1, 2) for c in (self.directory_compression, self.tile_compression)):
            raise DigestError('compression not supported by the app’s default PMTiles reader')
        self.min_zoom, self.max_zoom = header[100:102]
        if not self.min_zoom <= self.max_zoom <= MAX_READER_ZOOM:
            raise DigestError('invalid PMTiles zoom range')
        self.addressed = addressed

    def read(self, offset: int, length: int) -> bytes:
        if offset < 0 or length > self.size - offset:
            raise DigestError('PMTiles byte range is outside the archive')
        self.stream.seek(offset)
        data = self.stream.read(length)
        if len(data) != length:
            raise DigestError('truncated PMTiles byte range')
        return data

    def ranges(self, offset: int, length: int, low: int, high: int, depth: int = 0):
        """Yield (id, run, absolute offset, length) in TileID order."""
        data = _decompress(self.read(offset, length), self.directory_compression)
        entries = list(_entries(data))
        for i, (tile_id, run, relative, size) in enumerate(entries):
            limit = entries[i + 1][0] if i + 1 < len(entries) else high
            if not low <= tile_id < limit <= high or tile_id + run > limit:
                raise DigestError('overlapping PMTiles entries or entry outside its tile ID range')
            start, section_length = self.tiles if run else self.leaves
            if relative + size > section_length:
                raise DigestError('PMTiles entry extends past its data section')
            if run:
                yield tile_id, run, start + relative, size
            elif depth < 3:  # the app allows the root plus at most three leaf lookups
                yield from self.ranges(start + relative, size, tile_id, limit, depth + 1)
            else:
                raise DigestError('maximum PMTiles directory depth exceeded')


def write_index(stream: BinaryIO, output: Path) -> dict[str, int]:
    """Write a relief digest index into a fresh staging directory; no network I/O."""
    archive = _Archive(stream)
    if archive.max_zoom > MAX_RELIEF_ZOOM:
        raise DigestError('relief indexes may not include zooms above z17')
    chunks = defaultdict(list)
    count = 0
    for first_id, run, offset, length in archive.ranges(
            *archive.root, _tile_id_start(archive.min_zoom), _tile_id_start(archive.max_zoom + 1)):
        digest = receipts.sha256_bytes(_decompress(archive.read(offset, length), archive.tile_compression))
        for tile_id in range(first_id, first_id + run):
            z, x, y = _zxy(tile_id)
            chunks[f'{z}/{x // BLOCK_SIZE}_{y // BLOCK_SIZE}.json'].append([x, y, digest])
        count += run
    # Zero in a PMTiles count field means the count was not recorded.
    if not count or (archive.addressed and count != archive.addressed):
        raise DigestError('PMTiles addressed tile count does not match its directories')
    root = {}
    for name, rows in sorted(chunks.items()):
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        data = receipts.canonical(sorted(rows))
        path.write_bytes(data)
        root[name] = receipts.sha256_bytes(data)
    (output / 'root.json').write_bytes(receipts.canonical({'chunks': root}))
    return {'tiles': count, 'chunks': len(root)}


def main(argv=None) -> int:
    parser = package.stage_parser('digests')
    parser.description = 'Hash each public relief tile as returned by the app’s PMTiles reader.'
    parser.add_argument('--upstream', default='tiles:public', help='archive producer stage[:scope] (default: tiles:public)')
    args = parser.parse_args(argv)
    try:
        region = package.stage_region(args.out, args.region, INDEX_TARGET)
        ref = receipts.Ref.parse(args.upstream)
        if ref.scope not in (None, 'public') or ref.stage in {'digests', 'package', 'qa', 'envelope', 'publish'}:
            raise DigestError('digests requires a public archive producer')
        # Check every existing ancestor before the receipt runner can mkdir/rename.
        if any((region.dir / subdir).is_symlink() for subdir in ('layers', package.LAYERS)):
            raise DigestError('symlink in relief layer directory')
        code = receipts.stage_digest([('digests.py', Path(__file__)), ('package.py', Path(package.__file__))])
    except (OSError, ValueError) as exc:
        parser.error(str(exc))

    producer = {}
    archive = region.dir / package.ARCHIVE

    def plan(upstream):
        producer.update((row['path'], row) for row in upstream[ref.key]['outputs'])
        return receipts.Plan([receipts.Input(archive, 'relief_archive')])

    def build(out_dir):
        expected = producer.get(package.ARCHIVE)
        if not expected:
            raise DigestError('the current upstream receipt does not own relief.pmtiles')
        archive_path = package.artifact_path(region.dir, package.ARCHIVE)
        pending = receipts.read_receipt(region.receipt_path('digests'))
        if pending is None or pending['inputs'][0]['sha256'] != expected['sha256']:
            raise DigestError('archive input and upstream receipt disagree')
        with archive_path.open('rb') as stream:
            stat = os.fstat(stream.fileno())
            metrics = write_index(stream, out_dir)
            stream.seek(0)
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            current = archive_path.stat()
            identity = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
            if (digest != expected['sha256'] or stat.st_size != expected['bytes']
                    or any(getattr(stat, field) != getattr(current, field) for field in identity)):
                raise DigestError('archive changed while its tiles were indexed')
        return metrics

    result = receipts.run_stage(receipts.StageRun(region, 'digests', build, code,
                                upstream=[ref], plan=plan, target=INDEX_TARGET))
    print(result.line())
    return result.exit_code
