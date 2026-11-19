#!/usr/bin/env node
// SC-PERF-REEFDIET-1 parity and load check on a real export: the brief's ranking from the slim file against the same ranking from the full export.
// Three runs per input, which must give the identical result:
//   old   full export, verdicts and fingerprint removed: the run-time outline check (what the brief did before SC-PERF-PROTCHECK-1)
//   full  full export with the publish-time verdicts (main today)
//   slim  loadReefTripBrief: the slim file, no outlines
// Build the input directory with scripts/reef_slim_build.py. Usage: node scripts/reef_slim_parity.mjs <dir> [loads]
// Exit 0 only when the rankings match and every reef has the same eligibility in both paths. Region morro-bay, boundaries dist/data/protected-areas.geojson.
import {readFileSync} from 'node:fs';
import {initProtectedAreas} from '../dist/protected-areas.js';
import {loadReefTrip, loadReefTripBrief} from '../dist/reef-trip-data.js';
import {ranking} from '../web/ranking.ts';
import {placeRefused} from '../dist/geo-screen.js';

const [dir, loads = '3'] = process.argv.slice(2);
const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url), 'utf8'));
const manifest = JSON.parse(readFileSync(`${dir}/manifest.json`, 'utf8'));
const files = {[manifest.export_file]: readFileSync(`${dir}/${manifest.export_file}`), ...(manifest.slim_file ? {[manifest.slim_file]: readFileSync(`${dir}/${manifest.slim_file}`)} : {})};
const mpas = read('../dist/data/protected-areas.geojson');
globalThis.document = {getElementById: () => ({classList: {toggle() {}}, textContent: ''}), dispatchEvent() {}, createElement: () => ({classList: {toggle() {}}})};
const real = globalThis.fetch;
globalThis.fetch = async () => ({ok: true, json: async () => ({...mpas, checked_at: new Date().toISOString()})});
const screen = await initProtectedAreas(null, () => {});
const served = [];
const fetchImpl = async url => {
  const name = String(url).split('/').at(-1);
  served.push(name);
  return String(url).includes('manifest-') ? new Response(JSON.stringify(manifest)) : new Response(files[name]);
};
const now = Date.parse(manifest.built_at) + 3600000, opts = {fetchImpl, now};
const timed = async f => { const t = performance.now(); const r = await f(); return [r, Math.round(performance.now() - t)]; };

const loadTimes = {full: [], slim: []};
let full, slim;
for (let i = 0; i < +loads; i++) {
  [full] = await timed(async () => { const r = await loadReefTrip('morro-bay', opts); loadTimes.full.push(0); return r; });
}
loadTimes.full = []; loadTimes.slim = [];
for (let i = 0; i < +loads; i++) {
  let [r, ms] = await timed(() => loadReefTrip('morro-bay', opts)); full = r; loadTimes.full.push(ms);
  [r, ms] = await timed(() => loadReefTripBrief('morro-bay', opts)); slim = r; loadTimes.slim.push(ms);
}
if (!slim.slim) throw Error('the brief did not get the slim file (served: ' + served.join(', ') + ')');
const strip = l => { const {protected_fingerprint, ...rest} = l; return {...rest, targets: l.targets.map(({protected_place, ...t}) => t)}; };
const old = strip(full);
const DATA = {region: {...read('../dist/regions/morro-bay/region.json'), id: 'morro-bay'}, atlas: read('../dist/data/atlas.json'), survey: null, geology: null};
const cases = [];
for (const coast of ['lingcod', 'rockfish-reef', 'all']) for (const profile of ['boat', 'kayak', 'spear']) for (const reachNm of [null, 8]) cases.push({coast, profile, reachNm});
const run = (loaded, c) => ranking({region: 'morro-bay', profile: c.profile, target: c.coast, coast: c.coast, data: DATA, screen: {status: 'ready', note: '', source: 't', boundaries: [], until: Infinity},
  terrain: {state: 'idle'}, now: Date.now(), reachNm: c.reachNm, place: () => ({state: 'water'}), publication: {state: 'ready', region: 'morro-bay', loaded},
  plannerScreen: {state: 'loaded', region: 'morro-bay', screen}, top: 50});
let bad = 0, picks = 0;
const rankTimes = {old: [], full: [], slim: []};
for (const c of cases) {
  const out = {};
  for (const [name, loaded] of [['old', old], ['full', full], ['slim', slim]]) { const [r, ms] = await timed(() => run(loaded, c)); out[name] = JSON.stringify(r); rankTimes[name].push(ms); }
  picks += JSON.parse(out.slim).picks?.length ?? 0;
  const same = out.old === out.full && out.full === out.slim;
  if (!same) { bad++; console.log('DIFFERENT', JSON.stringify(c), 'old==full', out.old === out.full, 'full==slim', out.full === out.slim); }
}
const sum = a => a.reduce((x, y) => x + y, 0);
// Every reef, not only the ones a ranking picks: use full geometry and the actual slim verdict, joined one-to-one by target ID.
function indexTargets(targets, label) {
  const byId = new Map();
  for (const t of targets) {
    if (typeof t.id !== 'string' || !t.id.trim()) throw Error(`Missing target ID in ${label} export`);
    if (byId.has(t.id)) throw Error(`Duplicate ${label} target ID: ${t.id}`);
    byId.set(t.id, t);
  }
  return byId;
}
const fullById = indexTargets(full.targets, 'full'), slimById = indexTargets(slim.targets, 'slim');
for (const id of slimById.keys()) {
  if (!fullById.has(id)) throw Error(`Unexpected slim target ID: ${id}`);
}
let mismatch = 0, refusedOld = 0;
const areaOf = new Map(full.areas.map(a => [a.id, a.geometry]));
for (const [id, t] of fullById) {
  if (!slimById.has(id)) throw Error(`Missing slim target ID: ${id}`);
  const verdict = slimById.get(id).protected_place;
  const allowedOld = screen.pointAllowed(t) && t.area_ids.every(id => screen.geometryAllowed(areaOf.get(id)));
  const allowedSlim = !placeRefused(verdict);
  if (!allowedOld) refusedOld++;
  if (allowedOld !== allowedSlim) { mismatch++; console.log('ELIGIBILITY DIFFERS', id, 'old allows', allowedOld, 'verdict', JSON.stringify(verdict)); }
}
console.log(`every reef: ${full.targets.length} checked, ${refusedOld} refused by the run-time outline check, eligibility mismatches ${mismatch}`);
bad += mismatch;
console.log(`cases ${cases.length}, picks compared ${picks}, reefs ${full.targets.length}, differences ${bad}`);
console.log(`fingerprint load==screen: ${slim.protected_fingerprint === screen.fingerprint()}  (${slim.protected_fingerprint})`);
console.log(`bytes on the wire: full ${manifest.export_bytes}, slim ${manifest.slim_bytes}`);
console.log(`load ms (fetch from memory + hash + gunzip + parse + build), per run: full ${loadTimes.full.join(',')}  slim ${loadTimes.slim.join(',')}`);
console.log(`ranking() total ms over ${cases.length} cases: old ${sum(rankTimes.old)}, full+verdicts ${sum(rankTimes.full)}, slim ${sum(rankTimes.slim)}`);
process.exit(bad ? 1 : 0);
