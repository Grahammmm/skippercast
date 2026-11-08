#!/usr/bin/env node
// PERF-BASELINE-1: how much smaller would the raster seafloor tiles be as WebP? Re-encodes a sample of the archive's
// PNG tiles with Chromium's own WebP encoder (OffscreenCanvas.convertToBlob) at two qualities, plus lossless-ish 1.0.
// Usage: node reports/perf/webp_trial.mjs <archive.pmtiles> <zoom> [count]
import {openSync, readSync} from 'node:fs';
import {PMTiles, tileIdToZxy} from 'pmtiles';
import {chromium} from '@playwright/test';
const [path, zoom, count = '40'] = process.argv.slice(2);
class FileSource { constructor(p) { this.p = p; this.fd = openSync(p, 'r'); } getKey() { return this.p; }
  async getBytes(o, l) { const b = Buffer.alloc(l); const n = readSync(this.fd, b, 0, l, o); return {data: b.buffer.slice(b.byteOffset, b.byteOffset + n)}; } }
const p = new PMTiles(new FileSource(path));
const h = await p.getHeader();
const ids = [];
const walk = async (off, len) => { for (const e of await p.cache.getDirectory(p.source, off, len, h)) { if (e.runLength === 0) await walk(h.leafDirectoryOffset + e.offset, e.length); else ids.push(e.tileId); } };
await walk(h.rootDirectoryOffset, h.rootDirectoryLength);
const at = ids.map(tileIdToZxy).filter(([z]) => z === +zoom);
const step = Math.max(1, Math.floor(at.length / +count));
const tiles = [];
for (let i = 0; i < at.length && tiles.length < +count; i += step) { const [z, x, y] = at[i]; const t = await p.getZxy(z, x, y); if (t) tiles.push(Buffer.from(t.data).toString('base64')); }
const EXE = process.env.PW_CHROMIUM || `${process.env.HOME}/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome`;
const browser = await chromium.launch({executablePath: EXE});
const page = await browser.newPage();
const result = await page.evaluate(async (list) => {
  const out = {tiles: list.length, png: 0, webp80: 0, webp90: 0, webp100: 0};
  for (const b64 of list) {
    const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0)); out.png += bytes.length;
    const bmp = await createImageBitmap(new Blob([bytes], {type: 'image/png'}));
    const c = new OffscreenCanvas(bmp.width, bmp.height); c.getContext('2d').drawImage(bmp, 0, 0);
    for (const [k, q] of [['webp80', 0.8], ['webp90', 0.9], ['webp100', 1]]) out[k] += (await c.convertToBlob({type: 'image/webp', quality: q})).size;
  }
  return out;
}, tiles);
console.log(JSON.stringify({archive: path, zoom: +zoom, tilesAtZoom: at.length, ...result, ratio80: +(result.webp80 / result.png).toFixed(3), ratio90: +(result.webp90 / result.png).toFixed(3), ratio100: +(result.webp100 / result.png).toFixed(3)}));
await browser.close();
