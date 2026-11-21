#!/usr/bin/env node
// SC-PERF-PROTCHECK-1 parity oracle: the verdict the browser's own code gives each reef of a habitat export, and the fingerprint
// of the boundary data its screen holds. It runs the real dist/protected-areas.js `initProtectedAreas` and dist/geo-screen.js
// `screenPlace`, called exactly as web/ranking.ts calls them for a picked reef (outline + reference point).
// Used by protected_screen_parity.py. Stdin binds the region, clock and exact boundary bytes.
// Args: <habitat-export.geojson[.gz]> <out.json> [--limit N] [--offset N]
import {createHash} from 'node:crypto';
import {readFileSync, writeFileSync} from 'node:fs';
import {gunzipSync} from 'node:zlib';
import {setRegion} from '../dist/region.js';
import {screenPlace} from '../dist/geo-screen.js';

const args = process.argv.slice(2), opt = (name, dflt) => { const i = args.indexOf('--' + name); return i < 0 ? dflt : args[i + 1]; };
const [path, out] = args;
const raw = readFileSync(path), exp = JSON.parse((path.endsWith('.gz') ? gunzipSync(raw) : raw).toString('utf8'));
const packet = readFileSync(0);
const {region, now, assets} = JSON.parse(packet);
if (!Number.isSafeInteger(now)) throw Error('oracle requires a pinned test clock');
Date.now = () => now;
globalThis.fetch = () => { throw Error('oracle cannot fetch external inputs'); };
globalThis.document = {getElementById: () => ({classList: {toggle() {}}, textContent: ''}), dispatchEvent() {}, createElement: () => ({classList: {toggle() {}}})};
setRegion(region);
// The browser module binds its query envelope at import time.
const {initProtectedAreas} = await import('../dist/protected-areas.js');
const screen = await initProtectedAreas(null, () => {}, async url => {
  if (!Object.hasOwn(assets, url)) throw Error('oracle requested an unpinned boundary');
  return JSON.parse(Buffer.from(assets[url], 'base64'));
});
if (!screen.ready()) throw Error('oracle screen is not current');
const offset = +opt('offset', 0), limit = +opt('limit', Infinity);
const t0 = performance.now(), verdicts = {};
for (const f of exp.features.slice(offset, offset + limit)) {
  const w = f.properties.waypoint;
  verdicts[f.properties.id] = screenPlace(screen, {latitude: w.latitude, longitude: w.longitude, geometries: [f.geometry]});
}
const inputSha256 = createHash('sha256').update(packet).digest('hex');
writeFileSync(out, JSON.stringify({fingerprint: screen.fingerprint(), verdicts, inputSha256, ms: Math.round(performance.now() - t0)}));
console.log(`oracle: ${Object.keys(verdicts).length} reefs in ${Math.round(performance.now() - t0)} ms`);
