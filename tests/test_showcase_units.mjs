// scripts/showcase_skippercast.mjs: the offline current packet derives its knot factor from web/units.ts (RF2235-7)
// yet emits the exact bytes the gallery always had. Only context.route is faked; no browser, server or network.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join, resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import setup from '../scripts/showcase_skippercast.mjs';

const HERE = resolve(fileURLToPath(import.meta.url), '../..');
const SOURCE = readFileSync(join(HERE, 'scripts/showcase_skippercast.mjs'), 'utf8');
const HOUR = 3_600_000, THREE = 3 * HOUR;
const LEGACY_KT_PER_MS = 1.943844492; // independent oracle: never derived from web/units.ts

async function register(now) {
  const routes = [];
  const context = {route: async (match, handler) => { routes.push({match, handler}); }, on() { throw new Error('no listener expected'); }};
  await setup(context, {root: mkdtempSync(join(tmpdir(), 'showcase-units-')), now: new Date(now), here: HERE});
  return routes;
}

async function oceanResponse(now) {
  const routes = await register(now);
  const ocean = routes.filter(r => r.match === '**/api/coast/ocean');
  assert.equal(ocean.length, 1);
  let body;
  await ocean[0].handler({fulfill: async options => { body = options.json; }});
  return body;
}

function expectedPacket(now) {
  const iso = ms => new Date(ms).toISOString(), first = Math.floor(now / THREE) * THREE - THREE, cells = [];
  for (let j = 0; j < 9; j++) for (let i = 0; i < 17; i++) {
    const lon = +(-121.24 + i * 0.04).toFixed(6), lat = +(35.16 + j * 0.04).toFixed(6), uMs = 0.15 + i * 0.03, vMs = 0.12 - j * 0.02;
    cells.push({lat, lon, uMs, vMs, speedKnots: Math.hypot(uMs, vMs) * LEGACY_KT_PER_MS, towardDeg: (Math.atan2(uMs, vMs) * 180 / Math.PI + 360) % 360});
  }
  const wcofs = {id: 'wcofs', kind: 'forecast', label: 'NOAA WCOFS surface forecast', url: 'https://example.test/wcofs', fetchedAt: iso(now - 600_000),
    issuedAt: iso(now - THREE), sampleAt: null, nativeResolutionKm: 4, sampleStride: 1, horizontalDatum: 'NAD83', surfaceOnly: true,
    attribution: 'NOAA', license: 'public-domain-us-gov', limitations: 'Surface only.', frames: [0, 1, 2, 3].map(k => ({validAt: iso(first + k * THREE), cells}))};
  return {schemaVersion: 1, countyId: 'slo', generatedAt: iso(now - 300_000), currents: [wcofs], cloud: null, sources: []};
}

test('showcase_factor_is_derived_not_independent', () => {
  assert.match(SOURCE, /import\s*\{\s*KT_PER_MS\s*\}\s*from\s*'\.\.\/web\/units\.ts'/);
  assert.match(SOURCE, /Number\(KT_PER_MS\.toFixed\(9\)\)/);
  assert.ok(!SOURCE.includes('1.943844492'), 'no standalone knot-factor literal');
});

const BASE = Date.parse('2026-06-15T19:00:00Z');
for (const [name, now] of [['fixed clock', BASE], ['just before a 3 h boundary', Math.ceil(BASE / THREE) * THREE - 1],
  ['exactly at a 3 h boundary', Math.ceil(BASE / THREE) * THREE]]) {
  test(`showcase_ocean_json_is_legacy_identical (${name})`, async () => {
    const actual = JSON.stringify(await oceanResponse(now)), expected = JSON.stringify(expectedPacket(now));
    assert.ok(actual === expected, `ocean packet bytes differ at ${new Date(now).toISOString()}`);
  });
}

test('showcase_frame_boundary_is_unchanged', async () => {
  const before = Math.ceil(BASE / THREE) * THREE - 1, at = before + 1;
  const a = await oceanResponse(before), b = await oceanResponse(at);
  assert.equal(Date.parse(b.currents[0].frames[0].validAt) - Date.parse(a.currents[0].frames[0].validAt), THREE);
});

test('showcase_setup_stays_browser_free_and_offline', async () => {
  const routes = await register(BASE);
  assert.equal(routes.length, 13);
  const idx = pred => routes.findIndex(pred);
  const generic = idx(r => r.match instanceof RegExp && r.match.source.includes('api'));
  assert.ok(generic >= 0 && generic < idx(r => r.match === '**/api/coast/ocean'), 'generic offline route precedes the ocean route');
  let reply;
  await routes[generic].handler({fulfill: async options => { reply = options; }});
  assert.equal(reply.status, 503);
});
