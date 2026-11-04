// BF-saved-spots: private saved spots with a note. No visibility column; another account gets not-found; the
// export and account deletion include them; GPX export goes through the planner's export path (name cleaning,
// protected-area screen, GPX check); no public page, feed or public code reads them.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, readdirSync, statSync} from 'node:fs';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {DatabaseSync} from 'node:sqlite';
import {withSessions} from './fixtures/test-sessions.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.BUILD_ID = 'build-test';
globalThis.SHELLS = {'/': '/index.0123456789.html', '/index.html': '/index.0123456789.html', '/landing.html': '/landing.0123456789.html', '/app.html': '/app.0123456789.html'};
const {default: deployed} = await import('../server/index.ts');
const {spotItemHTML, spotBody, exportSpots, spotVerdicts} = await import('../dist/account.js');
const {initProtectedAreas} = await import('../dist/protected-areas.js');
const {getRegion} = await import('../dist/region.js');
const {pointInGeometry} = await import('../dist/geo-screen.js');
const worker = withSessions(deployed), ORIGIN = 'https://skippercast.com';

function database() {
  const sql = new DatabaseSync(':memory:');
  for (const {tag} of [...read('../drizzle/meta/_journal.json').entries].sort((a, b) => a.idx - b.idx)) sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`, import.meta.url), 'utf8'));
  const adapter = {prepare(query) { let args = []; const statement = sql.prepare(query); return {bind(...a) { args = a; return this; }, async first() { return statement.get(...args) || null; }, async all() { return {results: statement.all(...args)}; }, async run() { const info = statement.run(...args); return {meta: {changes: Number(info.changes)}}; }}; },
    async batch(queries) { sql.exec('BEGIN'); try { const out = []; for (const q of queries) out.push(await q.run()); sql.exec('COMMIT'); return out; } catch (e) { sql.exec('ROLLBACK'); throw e; } }};
  return {sql, adapter};
}
const call = (env, path, {owner, method = 'GET', body} = {}) => {
  const headers = {'Content-Type': 'application/json', 'CF-Connecting-IP': '203.0.113.9'};
  if (owner) headers['x-test-owner'] = owner;
  if (method !== 'GET') headers.Origin = ORIGIN;
  return worker.fetch(new Request(ORIGIN + path, {method, headers, body: body === undefined ? undefined : JSON.stringify(body)}), env);
};
const post = async (env, owner, spot) => { const r = await call(env, '/api/spots', {owner, method: 'POST', body: spot}); return {status: r.status, data: await r.json()}; };
const count = (sql, owner) => sql.prepare('SELECT COUNT(*) AS n FROM saved_spots WHERE owner=?').get(owner).n;

// Protected areas: the committed ds582 polygons through the real shared screen (offline fetch), as test_closure_every_output does.
const MPAS = read('../dist/data/protected-areas.geojson');
const buchon = MPAS.features.find(f => f.properties.NAME === 'Point Buchon SMR');
const ring = buchon.geometry.type === 'Polygon' ? buchon.geometry.coordinates[0] : buchon.geometry.coordinates[0][0];
const INSIDE = {lat: ring[0][1], lon: ring[0][0]};
const OPEN = {lat: 35.0, lon: -121.6};
async function screenAt(checkedAt = new Date().toISOString()) {
  const saved = {fetch: globalThis.fetch, document: globalThis.document};
  globalThis.fetch = async () => ({ok: true, json: async () => ({...MPAS, checked_at: checkedAt})});
  globalThis.document = {getElementById: () => ({classList: {toggle() {}}, textContent: ''}), dispatchEvent() {}};
  try { return await initProtectedAreas(null, () => {}); } finally { Object.assign(globalThis, saved); }
}
const names = gpx => [...gpx.matchAll(/<wpt[^>]*><name>(.*?)<\/name>/g)].map(m => m[1]);
let serial = 0;
const saved = (name, at = OPEN, id = 'n' + ++serial) => ({id: 'id-' + id, name, lat: at.lat, lon: at.lon, note: null});

const NOTE = 'SPOTNOTE-private <b>bold</b> 🐟 & "quotes"', SPOT = {name: 'SPOTNAME-Secret Reef', lat: 35.123456789, lon: -120.987654321, note: NOTE};

test('a spot with a note is saved, read back with the 4-byte emoji intact, and shown as text', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  const made = await post(env, 'alice', SPOT);
  assert.equal(made.status, 201);
  const list = await (await call(env, '/api/spots', {owner: 'alice'})).json();
  assert.deepEqual(list.spots.map(s => [s.name, s.lat, s.lon, s.note]), [[SPOT.name, SPOT.lat, SPOT.lon, NOTE]]);
  assert.deepEqual(Object.keys(list.spots[0]).sort(), ['created_at', 'id', 'lat', 'lon', 'name', 'note', 'owner'], 'no visibility field in the row');
  assert.deepEqual((await (await call(env, '/api/spots/' + made.data.id, {owner: 'alice'})).json()).note, NOTE);
  assert.ok(!sql.prepare("PRAGMA table_info('saved_spots')").all().some(c => /visib|public|shared/i.test(c.name)), 'no visibility column');
  const html = spotItemHTML(list.spots[0], {text: 'x <i>'});
  assert.ok(!html.includes('<b>') && !html.includes('<i>') && html.includes('&lt;b&gt;bold&lt;/b&gt; 🐟 &amp;'), 'markup is escaped');
  assert.deepEqual(spotBody({name: 'N', lat: '35.5', lon: ' ', note: ''}), {name: 'N', lat: 35.5, lon: null, note: null});
  sql.close();
});

test('another account gets the not-found shape for the same id and cannot delete it; its list is empty', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  const mine = await post(env, 'alice', SPOT);
  const other = await call(env, '/api/spots/' + mine.data.id, {owner: 'bob'}), never = await call(env, '/api/spots/no-such-id', {owner: 'bob'});
  const shape = async r => { const {request_id, ...rest} = await r.json(); return [r.status, rest]; };
  assert.equal(other.status, 404);
  assert.deepEqual(await shape(other), await shape(never), 'identical to an id that never existed');
  assert.deepEqual((await (await call(env, '/api/spots', {owner: 'bob'})).json()).spots, []);
  assert.equal((await call(env, '/api/spots/' + mine.data.id, {owner: 'bob', method: 'DELETE', body: {}})).status, 404);
  assert.equal(count(sql, 'alice'), 1);
  assert.equal((await call(env, '/api/spots/' + mine.data.id, {owner: 'alice', method: 'DELETE', body: {}})).status, 200);
  assert.equal((await call(env, '/api/spots/' + mine.data.id, {owner: 'alice', method: 'DELETE', body: {}})).status, 404, 'a second delete is not found');
  sql.close();
});

test('the account export holds the spot and its note, and deleting the account removes them', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  await post(env, 'alice', SPOT); await post(env, 'bob', {...SPOT, name: 'SPOTNAME-bob', note: 'SPOTNOTE-bob'});
  const out = await (await call(env, '/api/privacy', {owner: 'alice'})).json();
  assert.deepEqual(out.saved_spots.map(s => [s.name, s.note, s.lat, s.lon]), [[SPOT.name, NOTE, SPOT.lat, SPOT.lon]]);
  assert.ok(!JSON.stringify(out).includes('SPOTNAME-bob'), "bob's spot is not in alice's export");
  assert.equal((await call(env, '/api/privacy', {owner: 'alice', method: 'DELETE', body: {}})).status, 200);
  assert.equal(count(sql, 'alice'), 0);
  assert.equal(count(sql, 'bob'), 1, "bob's spot is untouched");
  sql.close();
});

test('no spot name, note or coordinate reaches any public page or feed, and no public code reads the table', async () => {
  const {sql, adapter} = database(), original = globalThis.fetch;
  const env = {DB: adapter, FEEDS: {get: async () => null, head: async () => null, list: async () => ({objects: []})}, ASSETS: {fetch: async () => new Response('<!doctype html><title>shell</title>', {headers: {'Content-Type': 'text/html'}})}};
  await post(env, 'alice', SPOT);
  const secrets = ['SPOTNAME', 'SPOTNOTE', '35.123456789', '-120.987654321', 'saved_spots'];
  const paths = ['/', '/map', '/privacy', '/sources', '/status', '/coverage', '/api/session', '/api/daily', '/api/forecast', '/api/intelligence', '/api/habitat', '/api/health', '/feeds/daily.json', '/feeds/index.json', '/api/om/v1/forecast?latitude=35&longitude=-120'];
  globalThis.fetch = async () => { throw new Error('offline'); };
  try {
    for (const who of [undefined, 'bob']) for (const path of paths) {
      const text = await (await call(env, path, {owner: who})).text();
      for (const s of secrets) assert.ok(!text.includes(s), `${path} (${who ?? 'anonymous'}) must not contain ${s}`);
    }
    assert.equal((await call(env, '/api/spots')).status, 401, 'anonymous gets no list');
  } finally { globalThis.fetch = original; }
  const root = fileURLToPath(new URL('..', import.meta.url)), allowed = new Set(['server/routes/spots.ts', 'server/routes/account.ts', 'server/app.ts', 'db/schema.ts', 'dist/account.js']);
  const hits = [];
  const walk = dir => { for (const name of readdirSync(dir)) { const full = join(dir, name), rel = full.slice(root.length).replaceAll('\\', '/').replace(/^\//, '');
    if (name === 'node_modules' || name.startsWith('.') || rel === 'dist/client' || rel === 'dist/server') continue;
    if (statSync(full).isDirectory()) walk(full); else if (/\.(ts|tsx|js|mjs|py)$/.test(name) && /saved_spots\b|api\/spots|routes\/spots/.test(readFileSync(full, 'utf8')) && !allowed.has(rel)) hits.push(rel); } };
  for (const dir of ['server', 'web', 'dist', 'src', 'packages', 'scripts']) walk(join(root, dir));
  assert.deepEqual(hits, [], 'only the route, the export, the mount, the schema and the account view mention saved spots');
  sql.close();
});

test('bad coordinates, a missing position, an over-long name or note and a 101st spot are refused, nothing stored', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  const bad = [[{lat: 35.5}, 'coordinates_incomplete'], [{lat: 91, lon: 0}, 'coordinates_out_of_range'], [{lat: 0, lon: 180}, 'coordinates_out_of_range'], [{lat: '35', lon: '-121'}, 'coordinates_not_finite'], [{}, 'coordinates_required'], [{lat: 1, lon: 1, name: 'x'.repeat(81)}, 'name must be'], [{lat: 1, lon: 1, note: 'x'.repeat(1001)}, 'note must be'], [{lat: 1, lon: 1, name: 7}, 'name must be'], [{lat: 1, lon: 1, note: 7}, 'note must be']];
  for (const [fields, word] of bad) { const r = await post(env, 'alice', fields); assert.equal(r.status, 400, JSON.stringify(fields)); assert.match(r.data.error, new RegExp(word)); }
  assert.equal(count(sql, 'alice'), 0);
  for (let i = 0; i < 100; i++) sql.prepare('INSERT INTO saved_spots(id,owner,name,lat,lon,created_at) VALUES(?,?,?,?,?,?)').run('s' + i, 'alice', 'n' + i, 1, 1, 'x');
  const full = await post(env, 'alice', {lat: 1, lon: 1});
  assert.equal(full.status, 400); assert.match(full.data.error, /at most 100/);
  assert.equal((await post(env, 'bob', {lat: 1, lon: 1})).status, 201, 'the cap is per account');
  sql.close();
});

test('GPX export cleans empty, whitespace and forbidden-character names, keeps duplicates unique, and passes the GPX check', async () => {
  const screen = await screenAt(), region = getRegion();
  const spots = [saved(''), saved('   ', OPEN, 'b'), saved('Reef\u0001\uFFFE & <rock> 😀 ', OPEN, 'c'), saved('Dup', OPEN, 'd'), saved('dup', OPEN, 'e'), saved('\u0001\u0002', OPEN, 'f')];
  spots[2].note = 'SPOTNOTE-not-in-gpx';
  const out = await exportSpots(spots, screen, region, new Date());
  assert.equal(out.exported, 6); assert.equal(out.withheld, 0);
  assert.deepEqual(names(out.gpx), ['Waypoint', 'Waypoint (2)', 'Reef &amp; &lt;rock&gt; 😀', 'Dup', 'dup (2)', 'Waypoint (3)']);
  assert.ok(!out.gpx.includes('SPOTNOTE') && !/[\u0000-\u0008\uFFFE\uFFFF]/.test(out.gpx), 'the note never leaves in GPX and no forbidden character does');
});

test('a spot inside a protected area is shown with the verdict and refused on export; the rest still export', async () => {
  const screen = await screenAt(), region = getRegion();
  assert.ok(pointInGeometry([INSIDE.lon, INSIDE.lat], buchon.geometry), 'fixture is inside the reserve');
  const spots = [saved('Open water'), saved('Inside the reserve', INSIDE, 'in')];
  const [clear, held] = await spotVerdicts(spots, screen);
  assert.equal(clear.status, 'clear');
  assert.equal(held.status, 'excluded'); assert.match(held.text, /Point Buchon State Marine Reserve/); assert.match(held.text, /excluded as a fishing target/);
  assert.match(spotItemHTML(spots[1], held), /Point Buchon State Marine Reserve/);
  const out = await exportSpots(spots, screen, region);
  assert.deepEqual(names(out.gpx), ['Open water']); assert.equal(out.withheld, 1);
  assert.ok(!out.gpx.includes(String(INSIDE.lat)), 'the protected coordinate is not exported');
  await assert.rejects(exportSpots([spots[1]], screen, region), /inside or near a protected area/);
});

test('with no screen, a stale screen or no spots nothing is exported, and the list reads unavailable', async () => {
  const region = getRegion(), stale = await screenAt(new Date(Date.now() - 48 * 3600000).toISOString());
  for (const screen of [null, stale]) {
    await assert.rejects(exportSpots([saved('Open water')], screen, region), /unavailable or older than 36 hours/);
    assert.equal((await spotVerdicts([saved('Open water')], screen))[0].status, 'unavailable');
  }
  await assert.rejects(exportSpots([], await screenAt(), region), /no saved spots/);
});
