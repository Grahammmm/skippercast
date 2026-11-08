#!/usr/bin/env node
// SC-PERF-PROTCHECK-1 parity oracle: the verdict the browser's own code gives each reef of a habitat export, and the fingerprint
// of the boundary data its screen holds. It runs the real dist/protected-areas.js `initProtectedAreas` and dist/geo-screen.js
// `screenPlace`, called exactly as web/ranking.ts calls them for a picked reef (outline + reference point).
// Usage: node scripts/protected_screen_oracle.mjs <habitat-export.geojson[.gz]> <out.json> [--limit N] [--offset N] [--boundaries file]
// Writes {fingerprint, verdicts: {id: verdict}, ms}. Region: morro-bay (the default region). Used by scripts/protected_screen_parity.py.
import {readFileSync, writeFileSync} from 'node:fs';
import {gunzipSync} from 'node:zlib';
import {initProtectedAreas} from '../dist/protected-areas.js';
import {screenPlace} from '../dist/geo-screen.js';

const args = process.argv.slice(2), opt = (name, dflt) => { const i = args.indexOf('--' + name); return i < 0 ? dflt : args[i + 1]; };
const [path, out] = args;
const raw = readFileSync(path), exp = JSON.parse((path.endsWith('.gz') ? gunzipSync(raw) : raw).toString('utf8'));
const mpas = JSON.parse(readFileSync(opt('boundaries', new URL('../dist/data/protected-areas.geojson', import.meta.url))));
globalThis.fetch = async () => ({ok: true, json: async () => ({...mpas, checked_at: new Date().toISOString()})});
globalThis.document = {getElementById: () => ({classList: {toggle() {}}, textContent: ''}), dispatchEvent() {}, createElement: () => ({classList: {toggle() {}}})};
const screen = await initProtectedAreas(null, () => {});
if (!screen.ready()) throw Error('oracle screen is not current');
const offset = +opt('offset', 0), limit = +opt('limit', Infinity);
const t0 = performance.now(), verdicts = {};
for (const f of exp.features.slice(offset, offset + limit)) {
  const w = f.properties.waypoint;
  verdicts[f.properties.id] = screenPlace(screen, {latitude: w.latitude, longitude: w.longitude, geometries: [f.geometry]});
}
writeFileSync(out, JSON.stringify({fingerprint: screen.fingerprint(), verdicts, ms: Math.round(performance.now() - t0)}));
console.log(`oracle: ${Object.keys(verdicts).length} reefs in ${Math.round(performance.now() - t0)} ms`);
