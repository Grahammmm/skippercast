// Offline wire-format test against the same PMTiles package the app imports.
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';
import { PMTiles, tileIdToZxy, zxyToTileId } from 'pmtiles';

const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const src = fileURLToPath(new URL('../src/', import.meta.url));
const headerSize = 127;

function directory(entries, compress) {
  const bytes = [];
  function varint(n) {
    while (n >= 128) {
      bytes.push((n % 128) | 128);
      n = Math.floor(n / 128);
    }
    bytes.push(n);
  }
  varint(entries.length);
  entries.forEach(([id], i) => varint(id - (i ? entries[i - 1][0] : 0)));
  entries.forEach(([, run]) => varint(run));
  entries.forEach(([, , length]) => varint(length));
  entries.forEach(([, , , offset], i) => {
    const previous = entries[i - 1];
    varint(previous && offset === previous[3] + previous[2] ? 0 : offset + 1);
  });
  return compress(Buffer.from(bytes));
}

function fixture(gzip, changed = false) {
  const compress = bytes => gzip ? gzipSync(bytes, { level: 0 }) : Buffer.from(bytes);
  const a = zxyToTileId(8, 3, 5);
  const b = zxyToTileId(8, 70, 80);
  const c = zxyToTileId(17, 20003, 50001);
  const shared = compress('same payload for two consecutive IDs');
  const single = compress(changed ? 'leaf payload b' : 'leaf payload a');
  const deep = compress('z17 leaf payload');
  // Includes a root run, two leaf directories, a noncontiguous reused payload,
  // implicit contiguous offsets, and a z17 ID larger than 32 bits.
  const leaf1 = directory([[b, 1, single.length, shared.length], [b + 2, 1, shared.length, 0]], compress);
  const leaf2 = directory([[c, 1, deep.length, shared.length + single.length]], compress);
  const root = directory([
    [a, 2, shared.length, 0], [b, 0, leaf1.length, 0], [c, 0, leaf2.length, leaf1.length],
  ], compress);
  const metadata = compress('{}');
  const metaOffset = headerSize + root.length;
  const leafOffset = metaOffset + metadata.length;
  const tileOffset = leafOffset + leaf1.length + leaf2.length;
  const header = Buffer.alloc(headerSize);
  header.write('PMTiles');
  header[7] = 3;
  const values = [headerSize, root.length, metaOffset, metadata.length,
    leafOffset, leaf1.length + leaf2.length, tileOffset, shared.length + single.length + deep.length, 5, 4, 3];
  values.forEach((n, i) => header.writeBigUInt64LE(BigInt(n), 8 + i * 8));
  header.set([1, gzip ? 2 : 1, gzip ? 2 : 0, 0, 8, 17], 96);
  return {
    bytes: Buffer.concat([header, root, metadata, leaf1, leaf2, shared, single, deep]),
    coords: [a, a + 1, b, b + 2, c].map(tileIdToZxy),
    missing: tileIdToZxy(b + 1),
    changedTile: tileIdToZxy(b).join('/'),
  };
}

async function crossCheck(archive, index) {
  const { bytes, coords, missing } = archive;
  const reader = new PMTiles({
    getKey: () => 'fixture.pmtiles',
    async getBytes(offset, length) {
      const part = bytes.subarray(offset, offset + length);
      return { data: Uint8Array.from(part).buffer };
    },
  });
  const root = JSON.parse(readFileSync(join(index, 'root.json')));
  const indexed = new Map();
  for (const [name, expected] of Object.entries(root.chunks)) {
    const chunk = readFileSync(join(index, name));
    assert.equal(sha(chunk), expected, name);
    const z = Number(name.split('/')[0]);
    for (const [x, y, digest] of JSON.parse(chunk)) {
      assert.equal(name, `${z}/${Math.floor(x / 64)}_${Math.floor(y / 64)}.json`);
      const key = `${z}/${x}/${y}`;
      assert.ok(!indexed.has(key), `duplicate ${key}`);
      indexed.set(key, digest);
    }
  }
  assert.deepEqual([...indexed.keys()].sort(), coords.map(xyz => xyz.join('/')).sort());
  for (const xyz of coords) {
    const tile = await reader.getZxy(...xyz);
    assert.ok(tile, xyz.join('/'));
    assert.equal(indexed.get(xyz.join('/')), sha(Buffer.from(tile.data)), xyz.join('/'));
  }
  assert.equal(await reader.getZxy(...missing), undefined);
  return indexed;
}

for (const gzip of [false, true]) {
  test(`Python index matches pmtiles getZxy for every tile (${gzip ? 'gzip' : 'raw'})`, async () => {
    const dir = mkdtempSync(join(tmpdir(), 'relief-digests-'));
    try {
      const driver = join(dir, 'index_fixture.py');
      writeFileSync(driver, [
        'import sys',
        'from pathlib import Path',
        'sys.path.insert(0, sys.argv[1])',
        'from skippercast.relief.digests import write_index',
        'with Path(sys.argv[2]).open("rb") as archive:',
        '    write_index(archive, Path(sys.argv[3]))',
        '',
      ].join('\n'));
      const build = (name, archive) => {
        const path = join(dir, `${name}.pmtiles`);
        const index = join(dir, name);
        writeFileSync(path, archive.bytes);
        mkdirSync(index);
        const result = spawnSync('python3', [driver, src, path, index], { encoding: 'utf8' });
        assert.equal(result.status, 0, result.error?.message ?? result.stderr);
        return index;
      };
      const original = fixture(gzip);
      const a = build('original', original);
      const first = await crossCheck(original, a);
      const b = build('repeat', original);
      const rootHash = path => sha(readFileSync(join(path, 'root.json')));
      assert.equal(rootHash(a), rootHash(b));
      assert.deepEqual(await crossCheck(original, b), first);

      const changed = fixture(gzip, true);
      assert.equal(changed.bytes.length, original.bytes.length);
      assert.deepEqual(changed.bytes.subarray(0, headerSize), original.bytes.subarray(0, headerSize));
      const changedIndex = build('changed', changed);
      const after = await crossCheck(changed, changedIndex);
      assert.notEqual(rootHash(a), rootHash(changedIndex));
      assert.deepEqual([...first.keys()].filter(tile => first.get(tile) !== after.get(tile)), [changed.changedTile]);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
}
