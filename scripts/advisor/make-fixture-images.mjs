#!/usr/bin/env node
// Synthetic test images for the Text Advisor vision fixtures
// (docs/plans/text-advisor/07-vision.md § Claude provider, TA-V1): a drawn
// count board, a fish silhouette, a blank frame and a stick figure on a deck.
// No real customer photo ever enters the repository; these let the vision
// pipeline (and TA-V2's Hermes conformance script) run end to end offline.
//
// Each image is written as inline SVG and rasterised here by a small renderer
// for the subset the drawings use (rect, circle, ellipse, line, polygon and
// text in a built-in 5x7 bitmap font; solid fills and strokes, no
// anti-aliasing), then encoded as an 8-bit RGB PNG by a PNG writer in this
// file (zlib from node:zlib for the deflate stream). Output stays under 50 KB
// and 256 px per side.
//
//   node scripts/advisor/make-fixture-images.mjs            write tests/fixtures/advisor/vision/images/*.png
//   node scripts/advisor/make-fixture-images.mjs --check    exit 1 if a committed PNG differs from a fresh render
//
// The PNGs are binary files, so their SHA-256 is pinned in
// scripts/web-vendor-sha256.json (scripts/check_repository.py); the script
// updates those entries when it writes.
import {deflateSync, crc32} from 'node:zlib';
import {createHash} from 'node:crypto';
import {mkdirSync, readFileSync, writeFileSync, existsSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

const ROOT = fileURLToPath(new URL('../../', import.meta.url));
export const OUT_DIR = 'tests/fixtures/advisor/vision/images';
const MANIFEST = 'scripts/web-vendor-sha256.json';
export const MAX_BYTES = 50 * 1024, MAX_SIDE = 256;

// ---- The drawings ------------------------------------------------------------------

export const IMAGES = {
  'count-board.png': `<svg xmlns="http://www.w3.org/2000/svg" width="256" height="192">
  <rect x="0" y="0" width="256" height="192" fill="#8a6a44"/>
  <rect x="8" y="8" width="240" height="176" fill="#23402f"/>
  <text x="18" y="18" font-size="14" fill="#f2f2e8">RITA G  10/03</text>
  <line x1="18" y1="38" x2="238" y2="38" stroke="#f2f2e8" stroke-width="2"/>
  <text x="18" y="48" font-size="14" fill="#f2f2e8">ANGLERS 22</text>
  <text x="18" y="72" font-size="14" fill="#f2f2e8">VERMILION 45</text>
  <text x="18" y="96" font-size="14" fill="#f2f2e8">LINGCOD 12 (2)</text>
  <text x="18" y="120" font-size="14" fill="#f2f2e8">COPPER 8</text>
  <text x="18" y="144" font-size="14" fill="#f2f2e8">CABEZON 3</text>
  <rect x="200" y="160" width="36" height="10" fill="#dddddd"/>
</svg>`,
  'fish.png': `<svg xmlns="http://www.w3.org/2000/svg" width="256" height="160">
  <rect x="0" y="0" width="256" height="160" fill="#cfe3ee"/>
  <polygon points="190,80 246,44 236,80 246,116" fill="#b8402e"/>
  <ellipse cx="118" cy="80" rx="82" ry="34" fill="#c8462f"/>
  <polygon points="80,50 100,24 150,26 170,52" fill="#a8382a"/>
  <polygon points="120,110 140,134 160,110" fill="#a8382a"/>
  <circle cx="62" cy="72" r="7" fill="#f4d23a"/>
  <circle cx="62" cy="72" r="3" fill="#111111"/>
  <line x1="40" y1="88" x2="60" y2="92" stroke="#5a1a12" stroke-width="2"/>
</svg>`,
  'blank.png': `<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128">
  <rect x="0" y="0" width="128" height="128" fill="#9a9a9a"/>
</svg>`,
  'deck-person.png': `<svg xmlns="http://www.w3.org/2000/svg" width="256" height="192">
  <rect x="0" y="0" width="256" height="96" fill="#a9cbe6"/>
  <rect x="0" y="96" width="256" height="40" fill="#2f5f86"/>
  <polygon points="0,136 256,136 256,192 0,192" fill="#d9d2c0"/>
  <line x1="0" y1="136" x2="256" y2="136" stroke="#6b5b45" stroke-width="3"/>
  <circle cx="110" cy="70" r="12" fill="#e8b48f"/>
  <line x1="110" y1="82" x2="110" y2="130" stroke="#1d2a3a" stroke-width="5"/>
  <line x1="110" y1="96" x2="138" y2="88" stroke="#1d2a3a" stroke-width="4"/>
  <line x1="110" y1="96" x2="86" y2="110" stroke="#1d2a3a" stroke-width="4"/>
  <line x1="110" y1="130" x2="96" y2="166" stroke="#1d2a3a" stroke-width="5"/>
  <line x1="110" y1="130" x2="124" y2="166" stroke="#1d2a3a" stroke-width="5"/>
  <line x1="136" y1="90" x2="210" y2="30" stroke="#333333" stroke-width="2"/>
  <line x1="210" y1="30" x2="220" y2="120" stroke="#eeeeee" stroke-width="1"/>
</svg>`,
};

// ---- A 5x7 bitmap font (rows top to bottom, 5 bits, high bit on the left) ---------

const FONT = {
  A: '0e11111f111111', B: '1e11111e11111e', C: '0e11101010110e', D: '1e11111111111e', E: '1f10101e10101f', F: '1f10101e101010',
  G: '0e11101711110f', H: '1111111f111111', I: '0e04040404040e', J: '0702020202120c', K: '11121418141211', L: '1010101010101f',
  M: '111b1515111111', N: '11111915131111', O: '0e11111111110e', P: '1e11111e101010', Q: '0e11111115120d', R: '1e11111e141211',
  S: '0f10100e01011e', T: '1f040404040404', U: '1111111111110e', V: '11111111110a04', W: '1111111515150a', X: '11110a040a1111',
  Y: '1111110a040404', Z: '1f01020408101f',
  0: '0e11131519110e', 1: '040c040404040e', 2: '0e11010204081f', 3: '1f02040201110e', 4: '02060a121f0202', 5: '1f101e0101110e',
  6: '0608101e11110e', 7: '1f010204080808', 8: '0e11110e11110e', 9: '0e11110f01020c',
  '/': '01010204081010', ':': '000c0c000c0c00', '-': '0000001f000000', '(': '02040808080402', ')': '08040202020408', ' ': '00000000000000',
};

// ---- SVG subset parser and rasteriser ----------------------------------------------

const attrs = s => Object.fromEntries([...s.matchAll(/([\w-]+)="([^"]*)"/g)].map(m => [m[1], m[2]]));
const rgb = hex => { const m = /^#([0-9a-f]{6})$/i.exec(hex || ''); if (!m) throw Error(`colour ${hex}`); const n = parseInt(m[1], 16); return [n >> 16, (n >> 8) & 255, n & 255]; };
const num = (a, k, d = 0) => a[k] === undefined ? d : Number(a[k]);

export function rasterise(svg) {
  const root = attrs(/<svg\b([^>]*)>/.exec(svg)[1]);
  const width = num(root, 'width'), height = num(root, 'height');
  if (!(width > 0 && height > 0 && width <= MAX_SIDE && height <= MAX_SIDE)) throw Error(`bad size ${width}x${height}`);
  const px = new Uint8Array(width * height * 3).fill(255);
  const set = (x, y, c) => { if (x < 0 || y < 0 || x >= width || y >= height) return; const i = (y * width + x) * 3; px[i] = c[0]; px[i + 1] = c[1]; px[i + 2] = c[2]; };
  const fill = (test, c, box = [0, 0, width, height]) => {
    for (let y = Math.max(0, Math.floor(box[1])); y < Math.min(height, Math.ceil(box[3])); y++)
      for (let x = Math.max(0, Math.floor(box[0])); x < Math.min(width, Math.ceil(box[2])); x++) if (test(x + 0.5, y + 0.5)) set(x, y, c);
  };
  const segment = (x1, y1, x2, y2, w, c) => {
    const dx = x2 - x1, dy = y2 - y1, len2 = dx * dx + dy * dy || 1, r = w / 2;
    fill((x, y) => { const t = Math.max(0, Math.min(1, ((x - x1) * dx + (y - y1) * dy) / len2)); const ex = x1 + t * dx - x, ey = y1 + t * dy - y; return ex * ex + ey * ey <= r * r; }, c,
      [Math.min(x1, x2) - r, Math.min(y1, y2) - r, Math.max(x1, x2) + r, Math.max(y1, y2) + r]);
  };
  for (const m of svg.matchAll(/<(rect|circle|ellipse|line|polygon|text)\b([^>]*?)\/?>(?:([^<]*)<\/text>)?/g)) {
    const [, tag, raw, content] = m, a = attrs(raw);
    if (tag === 'rect') { const x = num(a, 'x'), y = num(a, 'y'); fill(() => true, rgb(a.fill), [x, y, x + num(a, 'width'), y + num(a, 'height')]); }
    else if (tag === 'circle' || tag === 'ellipse') {
      const cx = num(a, 'cx'), cy = num(a, 'cy'), rx = tag === 'circle' ? num(a, 'r') : num(a, 'rx'), ry = tag === 'circle' ? num(a, 'r') : num(a, 'ry');
      fill((x, y) => ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1, rgb(a.fill), [cx - rx, cy - ry, cx + rx, cy + ry]);
    } else if (tag === 'line') segment(num(a, 'x1'), num(a, 'y1'), num(a, 'x2'), num(a, 'y2'), num(a, 'stroke-width', 1), rgb(a.stroke));
    else if (tag === 'polygon') {
      const p = a.points.trim().split(/[\s,]+/).map(Number), xs = p.filter((_, i) => i % 2 === 0), ys = p.filter((_, i) => i % 2 === 1);
      fill((x, y) => { let inside = false; for (let i = 0, j = xs.length - 1; i < xs.length; j = i++) if ((ys[i] > y) !== (ys[j] > y) && x < (xs[j] - xs[i]) * (y - ys[i]) / (ys[j] - ys[i]) + xs[i]) inside = !inside; return inside; },
        rgb(a.fill), [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]);
    } else if (tag === 'text') {
      // y is the top of the glyph cell (not an SVG baseline): this renderer's one liberty with the format.
      const scale = Math.max(1, Math.round(num(a, 'font-size', 7) / 7)), c = rgb(a.fill);
      let x = num(a, 'x'); const y = num(a, 'y');
      for (const ch of content.toUpperCase()) {
        const glyph = FONT[ch]; if (!glyph) throw Error(`no glyph for ${JSON.stringify(ch)}`);
        for (let row = 0; row < 7; row++) {
          const bits = parseInt(glyph.slice(row * 2, row * 2 + 2), 16);
          for (let col = 0; col < 5; col++) if (bits & (16 >> col)) for (let sy = 0; sy < scale; sy++) for (let sx = 0; sx < scale; sx++) set(x + col * scale + sx, y + row * scale + sy, c);
        }
        x += 6 * scale;
      }
    }
  }
  return {width, height, px};
}

// ---- PNG writer (8-bit RGB, filter 0 on every row) ---------------------------------

function chunk(type, data) {
  const out = Buffer.alloc(12 + data.length), name = Buffer.from(type, 'latin1');
  out.writeUInt32BE(data.length, 0); name.copy(out, 4); Buffer.from(data).copy(out, 8);
  out.writeUInt32BE(crc32(Buffer.concat([name, Buffer.from(data)])) >>> 0, 8 + data.length);
  return out;
}
export function encodePng({width, height, px}) {
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0); ihdr.writeUInt32BE(height, 4); ihdr[8] = 8; ihdr[9] = 2; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
  const raw = Buffer.alloc((width * 3 + 1) * height);
  for (let y = 0; y < height; y++) { raw[y * (width * 3 + 1)] = 0; Buffer.from(px.buffer, y * width * 3, width * 3).copy(raw, y * (width * 3 + 1) + 1); }
  return Buffer.concat([Buffer.from('\x89PNG\r\n\x1a\n', 'latin1'), chunk('IHDR', ihdr), chunk('IDAT', deflateSync(raw, {level: 9})), chunk('IEND', Buffer.alloc(0))]);
}

export function render(name) { return encodePng(rasterise(IMAGES[name])); }

// ---- CLI ----------------------------------------------------------------------------

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const check = process.argv.includes('--check');
  mkdirSync(ROOT + OUT_DIR, {recursive: true});
  const manifest = JSON.parse(readFileSync(ROOT + MANIFEST, 'utf8'));
  let failed = 0;
  for (const name of Object.keys(IMAGES)) {
    const png = render(name), path = `${OUT_DIR}/${name}`;
    if (png.length > MAX_BYTES) throw Error(`${name} is ${png.length} bytes (limit ${MAX_BYTES})`);
    if (check) {
      const same = existsSync(ROOT + path) && Buffer.compare(readFileSync(ROOT + path), png) === 0;
      if (!same) { failed++; console.error(`${path} differs from a fresh render`); }
      continue;
    }
    writeFileSync(ROOT + path, png);
    manifest[path] = createHash('sha256').update(png).digest('hex');
    console.log(`${path} ${png.length} bytes`);
  }
  if (!check) writeFileSync(ROOT + MANIFEST, JSON.stringify(Object.fromEntries(Object.entries(manifest).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)), null, 2) + '\n');
  process.exit(failed ? 1 : 0);
}
