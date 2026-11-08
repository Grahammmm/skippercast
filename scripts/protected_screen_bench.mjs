#!/usr/bin/env node
// SC-PERF-PROTCHECK-1: main-thread time the brief's reef list costs (web/ranking.ts `ranking`: bestSpots over the loaded publication, then each pick's
// protected-area verdict), through the real loadReefTrip and the real protected-area screen, for one real export. Run it on an export built before
// this change and on one built after it to see the difference. Region morro-bay (the default region), boundaries dist/data/protected-areas.geojson.
// Usage: node scripts/protected_screen_bench.mjs <manifest.json> <habitat-export.geojson.gz> [runs]
import {readFileSync} from 'node:fs';
import {initProtectedAreas} from '../dist/protected-areas.js';
import {loadReefTrip} from '../dist/reef-trip-data.js';
import {ranking} from '../web/ranking.ts';

const [manifestPath, exportPath, runs = '3'] = process.argv.slice(2);
const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url), 'utf8'));
const manifest = JSON.parse(readFileSync(manifestPath, 'utf8')), bytes = readFileSync(exportPath);
const mpas = read('../dist/data/protected-areas.geojson');
globalThis.fetch = async () => ({ok: true, json: async () => ({...mpas, checked_at: new Date().toISOString()})});
globalThis.document = {getElementById: () => ({classList: {toggle() {}}, textContent: ''}), dispatchEvent() {}, createElement: () => ({classList: {toggle() {}}})};
const screen = await initProtectedAreas(null, () => {});
const fetchImpl = async url => String(url).includes('manifest-') ? new Response(JSON.stringify(manifest)) : new Response(bytes);
let t = performance.now();
const loaded = await loadReefTrip('morro-bay', {fetchImpl, now: Date.parse(manifest.built_at) + 3600000});
const loadMs = performance.now() - t;
const DATA = {region: {...read('../dist/regions/morro-bay/region.json'), id: 'morro-bay'}, atlas: read('../dist/data/atlas.json'), survey: null, geology: null};
const times = [];
for (let i = 0; i < +runs; i++) {
  t = performance.now();
  const r = ranking({region: 'morro-bay', profile: 'boat', target: 'lingcod', coast: 'lingcod', data: DATA, screen: {status: 'ready', note: '', source: 't', boundaries: [], until: Infinity},
    terrain: {state: 'idle'}, now: Date.now(), place: () => ({state: 'water'}), publication: {state: 'ready', region: 'morro-bay', loaded},
    plannerScreen: {state: 'loaded', region: 'morro-bay', screen}});
  times.push(Math.round(performance.now() - t));
  if (!i) console.log('picks', r.picks.length, r.picks.map(p => `${p.id.slice(0, 8)}:${p.screen.name}@${p.screen.distanceM}`).join(' '));
}
console.log(`export ${loaded.protected_fingerprint ? 'WITH' : 'without'} publish-time verdicts; reefs ${loaded.targets.length}; loadReefTrip ${Math.round(loadMs)} ms; ranking(): ${times.join(', ')} ms`);
