#!/usr/bin/env node
// PERF-BASELINE-1: tile-size budget view of a PMTiles archive (header, metadata, and per-zoom tile byte statistics).
// Reads only the header and directories (a few range requests), never the tiles.
// Usage: node reports/perf/pmtiles_sizes.mjs <url or local path> [...]
import {readFileSync, openSync, readSync, fstatSync} from 'node:fs';
import {PMTiles, FetchSource} from 'pmtiles';

class FileSource {
  constructor(path) { this.path = path; this.fd = openSync(path, 'r'); }
  getKey() { return this.path; }
  async getBytes(offset, length) { const b = Buffer.alloc(length); const n = readSync(this.fd, b, 0, length, offset); return {data: b.buffer.slice(b.byteOffset, b.byteOffset + n)}; }
}
const zxy = (id) => { // tile id -> z (Hilbert order per zoom: zoom z starts at (4^z - 1) / 3)
  let z = 0, acc = 0; while (acc + 4 ** z <= id) { acc += 4 ** z; z++; } return z; };
const out = {};
for (const src of process.argv.slice(2)) {
  const p = new PMTiles(/^https?:/.test(src) ? new FetchSource(src) : new FileSource(src));
  const h = await p.getHeader();
  let meta = {}; try { meta = await p.getMetadata(); } catch {}
  const per = {};
  const walk = async (offset, length) => {
    const dir = await p.cache.getDirectory(p.source, offset, length, h);
    for (const e of dir) {
      if (e.runLength === 0) { await walk(h.leafDirectoryOffset + e.offset, e.length); continue; }
      const z = zxy(e.tileId); const s = per[z] ||= {tiles: 0, bytes: 0, max: 0, sizes: []};
      s.tiles += e.runLength; s.bytes += e.length * e.runLength; s.max = Math.max(s.max, e.length); s.sizes.push(e.length);
    }
  };
  await walk(h.rootDirectoryOffset, h.rootDirectoryLength);
  const zooms = {};
  for (const [z, s] of Object.entries(per)) { s.sizes.sort((a, b) => a - b); zooms[z] = {tiles: s.tiles, totalBytes: s.bytes, medianBytes: s.sizes[s.sizes.length >> 1], p95Bytes: s.sizes[Math.floor(s.sizes.length * 0.95)], maxBytes: s.max, over500KB: s.sizes.filter(x => x > 500e3).length}; }
  out[src] = {tileType: h.tileType, tileCompression: h.tileCompression, internalCompression: h.internalCompression, minZoom: h.minZoom, maxZoom: h.maxZoom, clustered: h.clustered,
    vectorLayers: (meta.vector_layers || []).map(l => `${l.id} z${l.minzoom}-${l.maxzoom}`), zooms};
}
console.log(JSON.stringify(out, null, 1));
