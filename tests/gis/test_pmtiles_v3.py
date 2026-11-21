"""Relief PNG archive contracts. Run the large JS readback after pnpm install:

    .venv/bin/python -m tests.gis.test_pmtiles_v3 ../pmtiles-proof

The GIS CI job does not install the web dependencies; its tests below use a
small independent directory decoder instead. The optional command uses the
app's locked reader and measures writer RSS before starting Node.
"""

import gzip
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import TypedDict

import pytest

from skippercast.relief.pmtiles_v3 import write_pmtiles
from tests._support import ROOT


class _Options(TypedDict):
    metadata: dict[str, str]
    bounds: tuple[int, int, int, int]
    minzoom: int
    maxzoom: int
    center: tuple[int, float, float]


_OPTIONS: _Options = {
    'metadata': {'name': 'synthetic relief', 'format': 'png'},
    'bounds': (-122, 35, -121, 36),
    'minzoom': 9,
    'maxzoom': 9,
    'center': (9, -121.5, 35.5),
}
_COUNT = 50_000


def _payload(index: int, small: bool) -> bytes:
    # Index 1 shares the first Hilbert tile's payload (a run); the later
    # multiples of 1000 also reuse it, including across leaf boundaries.
    key = 0 if index == 1 or index % 1000 == 0 else index
    raw = hashlib.shake_256(struct.pack('<I', key)).digest(4096 if not small else 127)
    length = 1 + int.from_bytes(raw[:2], 'little') % len(raw)
    return raw[:length]


def _tiles(count: int, *, small: bool = False):
    for index in reversed(range(count)):
        yield (9, index // 256, index % 256), _payload(index, small)


@pytest.mark.parametrize('count', [2, 7145])
def test_root_only_archive_matches_legacy(tmp_path, count):
    # Reordering payloads, changing gzip settings or changing a legacy header
    # field would break exact-byte compatibility with the current writer.
    from scripts.build_bathy_tiles import write_pmtiles as legacy_writer

    old = legacy_writer(tmp_path / 'old.pmtiles', dict(_tiles(count, small=True)), **_OPTIONS)
    new = write_pmtiles(tmp_path / 'new.pmtiles', _tiles(count, small=True), **_OPTIONS)
    assert new.read_bytes() == old.read_bytes()


def test_leaf_offsets_runs_and_payload_order(tmp_path):
    # Independent decoder catches absolute/relative offset mixups, missing
    # runs/shared payloads and storing payloads in input (not Hilbert) order.
    from scripts.build_bathy_tiles import tile_id  # independently retained legacy Hilbert implementation
    from tests.gis.test_build_bathy_tiles import varints

    count = 12000
    path = write_pmtiles(tmp_path / 'leaf.pmtiles', _tiles(count), **_OPTIONS)
    with path.open('rb') as archive:
        def read_at(offset, length):
            archive.seek(offset)
            return archive.read(length)

        def directory(offset, length):
            raw = gzip.decompress(read_at(offset, length))
            (n,), pos = varints(raw, 0, 1)
            deltas, pos = varints(raw, pos, n)
            runs, pos = varints(raw, pos, n)
            lengths, pos = varints(raw, pos, n)
            offsets, pos = varints(raw, pos, n)
            assert pos == len(raw)
            tid = end = 0
            for delta, run, size, start in zip(deltas, runs, lengths, offsets, strict=True):
                tid += delta
                start = start - 1 if start else end
                end = start + size
                yield tid, run, size, start

        header = archive.read(127)
        root, root_size, _, _, leaf, leaf_size, data, data_size, addressed, entries, contents = \
            struct.unpack_from('<11Q', header, 8)
        assert root + root_size <= 16384 and leaf_size > 0 and leaf + leaf_size == data
        assert header[96:100] == bytes([1, 2, 1, 2])
        assert (addressed, entries, contents) == (count, count - 1, count - 12)
        expected = sorted((tile_id(9, i // 256, i % 256), i) for i in range(count))
        actual = []
        end = 0
        seen = set()
        next_leaf = 0
        for first, run, length, offset in directory(root, root_size):
            assert run == 0 and offset == next_leaf
            next_leaf += length
            start = len(actual)
            for tid, run, length, offset in directory(leaf + offset, length):
                assert run > 0
                if offset not in seen:
                    assert offset == end
                    end += length
                    seen.add(offset)
                actual.extend((tid + i, offset, length) for i in range(run))
            assert actual[start][0] == first
        assert next_leaf == leaf_size and end == data_size and len(seen) == contents
        for (tid, index), (actual_tid, offset, length) in zip(expected, actual, strict=True):
            assert tid == actual_tid
            assert read_at(data + offset, length) == _payload(index, small=False)


def test_interrupted_input_does_not_replace_existing_archive(tmp_path):
    # A streaming producer can fail after output has started; preserve the old file.
    path = tmp_path / 'existing.pmtiles'
    path.write_bytes(b'previous archive')

    def broken_tiles():
        yield (9, 0, 0), b'one tile'
        raise RuntimeError('render failed')

    with pytest.raises(RuntimeError, match='render failed'):
        write_pmtiles(path, broken_tiles(), **_OPTIONS)
    assert path.read_bytes() == b'previous archive'
    assert list(tmp_path.iterdir()) == [path]


_JS_READBACK = r"""
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {open} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {join} from 'node:path';

const [repo, path, countArg] = process.argv.slice(2);
const require = createRequire(join(repo, 'package.json'));
const {PMTiles} = require('pmtiles');
const {version} = require(join(repo, 'node_modules/pmtiles/package.json'));
assert.match(version, /^4\.5\./);
const count = Number(countArg);
const file = await open(path, 'r');
try {
  const archive = new PMTiles({
    getKey: () => path,
    getBytes: async (offset, length) => {
      const data = new ArrayBuffer(length);
      const {bytesRead} = await file.read(new Uint8Array(data), 0, length, offset);
      assert.equal(bytesRead, length, `short archive read at ${offset}`);
      return {data};
    },
  });
  const h = await archive.getHeader();
  assert.equal(h.numAddressedTiles, count);
  assert.ok(h.rootDirectoryOffset + h.rootDirectoryLength <= 16384);
  assert.ok(h.leafDirectoryLength > 0);
  assert.equal(h.clustered, true);
  assert.equal(h.tileType, 2);
  assert.deepEqual([h.minZoom, h.maxZoom, h.minLon, h.minLat, h.maxLon, h.maxLat],
    [9, 9, -122, 35, -121, 36]);
  assert.deepEqual(await archive.getMetadata(), {name: 'synthetic relief', format: 'png'});
  const key = Buffer.alloc(4);
  for (let i = 0; i < count; i++) {
    key.writeUInt32LE(i === 1 || i % 1000 === 0 ? 0 : i);
    const raw = createHash('shake256', {outputLength: 4096}).update(key).digest();
    const expected = raw.subarray(0, 1 + raw.readUInt16LE() % raw.length);
    const tile = await archive.getZxy(9, Math.floor(i / 256), i % 256);
    assert.ok(tile && Buffer.from(tile.data).equals(expected), `incorrect tile at index ${i}`);
  }
  assert.equal(await archive.getZxy(9, Math.floor(count / 256), count % 256), undefined);
  console.log(`pmtiles ${version}: ${count} exact tile payloads + missing tile PASS; ${h.leafDirectoryLength} leaf bytes`);
} finally {
  await file.close();
}
"""


def _js_acceptance(scratch: Path) -> None:
    import resource  # Linux ru_maxrss, KiB

    scratch.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=scratch) as directory:
        path = Path(directory)
        archive = write_pmtiles(path / 'tiles.pmtiles', _tiles(_COUNT), **_OPTIONS)
        print(json.dumps({'tiles': _COUNT, 'archive_bytes': archive.stat().st_size,
                          'writer_peak_rss_kib': resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}), flush=True)
        reader = path / 'readback.mjs'
        reader.write_text(_JS_READBACK, encoding='utf-8')
        subprocess.run(['node', str(reader), str(ROOT), str(archive), str(_COUNT)], check=True)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('usage: python -m tests.gis.test_pmtiles_v3 SCRATCH_DIR')
    _js_acceptance(Path(sys.argv[1]))
