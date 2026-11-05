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

function database(beforeRun) {
  const sql = new DatabaseSync(':memory:');
  for (const {tag} of [...read('../drizzle/meta/_journal.json').entries].sort((a, b) => a.idx - b.idx)) sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`, import.meta.url), 'utf8'));
  const adapter = {prepare(query) { let args = []; const statement = sql.prepare(query); return {bind(...a) { args = a; return this; }, async first() { if (beforeRun) await beforeRun(query, args); return statement.get(...args) || null; }, async all() { return {results: statement.all(...args)}; }, async run() { if (beforeRun) await beforeRun(query, args); const info = statement.run(...args); return {meta: {changes: Number(info.changes)}}; }}; },
    async batch(queries) { sql.exec('BEGIN'); try { const out = []; for (const q of queries) out.push(await q.run()); sql.exec('COMMIT'); return out; } catch (e) { sql.exec('ROLLBACK'); throw e; } }};
  return {sql, adapter};
}
const call = (env, path, {owner, method = 'GET', body, raw, origin = true} = {}) => {
  const headers = {'Content-Type': 'application/json', 'CF-Connecting-IP': '203.0.113.9'};
  if (owner) headers['x-test-owner'] = owner;
  if (method !== 'GET' && origin) headers.Origin = ORIGIN;
  return worker.fetch(new Request(ORIGIN + path, {method, headers, body: raw !== undefined ? raw : body === undefined ? undefined : JSON.stringify(body)}), env);
};
const post = async (env, owner, spot) => { const r = await call(env, '/api/spots', {owner, method: 'POST', body: spot}); return {status: r.status, data: await r.json()}; };
const seed = (sql, owner, n, tag = owner) => { for (let i = 0; i < n; i++) sql.prepare('INSERT INTO saved_spots(id,owner,name,lat,lon,created_at) VALUES(?,?,?,?,?,?)').run(`${tag}-${i}`, owner, 'n' + i, 1, 1, 'x'); };
const isSpotInsert = query => /^\s*INSERT\s+INTO\s+saved_spots/i.test(query);
// Test-only write barrier: the first `parties` saved-spot INSERT statements wait here, whatever their VALUES/SELECT form, then run together.
function barrier(parties) {
  let arrived = 0, release; const opened = new Promise(r => { release = r; });
  const timer = setTimeout(release, 2000);
  return {release, hook: async query => { if (!isSpotInsert(query) || arrived >= parties) return; if (++arrived >= parties) release(); await opened; }, arrived: () => arrived, done: () => clearTimeout(timer)};
}
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
  assert.deepEqual(spotBody({name: 'N', lat: '35.5', lon: '-121', note: ''}), {name: 'N', lat: 35.5, lon: -121, note: null});
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
  const root = fileURLToPath(new URL('..', import.meta.url)), allowed = new Set(['server/routes/spots.ts', 'server/routes/account.ts', 'server/app.ts', 'db/schema.ts', 'dist/account.js', 'web/planner.ts', 'web/saved-spots.ts', 'web/map/saved-spots.ts']);
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

test('a spot 30 m outside a boundary is inside the planning margin: read as such and left out of the export', async () => {
  const screen = await screenAt(), region = getRegion(), v = ring[0], mLon = 1 / (111320 * Math.cos(v[1] * Math.PI / 180));
  const out30 = [1, -1].map(k => ({lat: v[1], lon: v[0] + k * 30 * mLon})).find(p => !pointInGeometry([p.lon, p.lat], buchon.geometry) && !pointInGeometry([v[0] + Math.sign(p.lon - v[0]) * mLon, v[1]], buchon.geometry));
  assert.ok(out30, 'fixture: a point just outside the reserve');
  const near = saved('Near the line', out30), [verdict] = await spotVerdicts([near], screen);
  assert.equal(verdict.status, 'excluded'); assert.match(verdict.text, /within 70 m/);
  await assert.rejects(exportSpots([near], screen, region), /inside or near a protected area/);
  assert.deepEqual(names((await exportSpots([near, saved('Open water')], screen, region)).gpx), ['Open water']);
});

// SC0022-04: the screen only speaks for the envelope its boundary file was fetched for (Morro Bay's mpa.bounds).
const TEXT = 'Protected areas not checked for this spot: outside coverage or check unavailable; not exported.';
const REFUSAL = /unavailable or older than 36 hours, or a saved spot is outside coverage\. Nothing was exported\./;
const FAR = {lat: 40.0, lon: -124.0};
const E = getRegion().mpa.bounds, EDGE = {lat: 35.4, lon: E[0] + 30 / (111412.84 * Math.cos(35.4 * Math.PI / 180))};
async function refreshed(screen, answer) {
  const was = {fetch: globalThis.fetch, document: globalThis.document};
  globalThis.fetch = answer; globalThis.document = {getElementById: () => ({classList: {toggle() {}}, textContent: ''}), dispatchEvent() {}};
  try { await screen.refresh(); } finally { Object.assign(globalThis, was); }
}

test('saved_spot_outside_current_screen_is_not_checked', async () => {
  assert.deepEqual(E, [-121.9, 34.95, -120.55, 35.85], 'the envelope this test reasons about');
  const screen = await screenAt(), region = getRegion(), far = saved('Far away', FAR, 'far'), open = saved('Open water');
  assert.equal(screen.ready(), true, 'a fresh screen');
  // A spot far outside the envelope is neither clear nor accused: the reading is the exact not-checked line, without a boundary.
  const [verdict] = await spotVerdicts([far], screen);
  assert.deepEqual(verdict, {status: 'unavailable', text: TEXT});
  const html = spotItemHTML(far, verdict);
  assert.ok(html.includes(`<p class="account-hint">${TEXT}</p>`), html);
  assert.doesNotMatch(html, /excluded|Inside|within 70 m|Point Buchon/);
  // The spot inside the envelope keeps its reading, byte for byte.
  assert.deepEqual((await spotVerdicts([open], screen))[0], {status: 'clear', text: ''});
  assert.equal(spotItemHTML(open, {status: 'clear', text: ''}).includes('account-hint'), false, 'no clear badge or text');
  // The 70 m search halo inside the envelope's edge is not checked either.
  assert.equal((await spotVerdicts([saved('Edge', EDGE, 'edge')], screen))[0].text, TEXT);
  // One outside spot refuses the whole export, alone or in a mixed list, and nothing is handed over.
  for (const list of [[far], [open, far], [far, open], [open, far, saved('Inside the reserve', INSIDE, 'in')], [open, saved('Edge', EDGE, 'edge2')]]) {
    let out = null;
    await assert.rejects((async () => { out = await exportSpots(list, screen, region); })(), REFUSAL);
    assert.equal(out, null, 'no GPX bytes are returned');
  }
  assert.equal((await exportSpots([open], screen, region)).exported, 1, 'the in-envelope list still exports');
  // Repeat after a live refresh, a daily-feed refresh and a failed refresh: coverage never changes, a stale screen stays unchecked.
  const live = async () => ({ok: true, json: async () => ({...MPAS, checked_at: new Date().toISOString()})});
  await refreshed(screen, live);
  assert.equal(screen.ready(), true);
  assert.equal((await spotVerdicts([far], screen))[0].text, TEXT); await assert.rejects(exportSpots([open, far], screen, region), REFUSAL);
  const daily = async url => String(url).includes('/api/daily') || String(url).includes('latest.json')
    ? {ok: true, json: async () => ({schema_version: 1, region_id: 'morro-bay', part: 'mpa-boundaries', generated_at: new Date().toISOString(), catch_probability: null, bite_score: null,
        sources: {'mpa-boundaries': {status: 'ok', data_retrieved_at: new Date().toISOString(), data: {geojson: MPAS}}}})}
    : {ok: false, status: 503, json: async () => ({})};
  const viaDaily = await screenAt(new Date(Date.now() - 48 * 3600000).toISOString());
  await refreshed(viaDaily, daily);
  assert.equal(viaDaily.ready(), true, 'the daily feed renewed the check');
  assert.equal((await spotVerdicts([far], viaDaily))[0].text, TEXT); await assert.rejects(exportSpots([open, far], viaDaily, region), REFUSAL);
  const stale = await screenAt(new Date(Date.now() - 48 * 3600000).toISOString());
  await refreshed(stale, async () => ({ok: false, status: 503, json: async () => ({})}));
  assert.equal(stale.ready(), false);
  for (const spot of [far, open]) assert.equal((await spotVerdicts([spot], stale))[0].text, TEXT, 'a stale screen reads every spot as not checked');
  await assert.rejects(exportSpots([open], stale, region), REFUSAL);
});

test('a far-away spot stays stored and readable by its owner, and its list reading is not checked', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  const made = await post(env, 'alice', {name: 'FARSPOT', ...FAR});
  assert.equal(made.status, 201, 'the server keeps its storage scope: a spot elsewhere is saved');
  const {spots} = await (await call(env, '/api/spots', {owner: 'alice'})).json();
  assert.deepEqual(spots.map(s => [s.name, s.lat, s.lon]), [['FARSPOT', FAR.lat, FAR.lon]]);
  const screen = await screenAt(), [verdict] = await spotVerdicts(spots, screen);
  assert.equal(verdict.text, TEXT); assert.ok(spotItemHTML(spots[0], verdict).includes(TEXT));
  await assert.rejects(exportSpots(spots, screen, getRegion()), REFUSAL);
  sql.close();
});

// RF1020-1: the cap is admitted and written by one statement, so competing saves cannot pass a stale count.
const FULL_MESSAGE = 'you can keep at most 100 saved spots; remove one first';
const owned = (sql, owner) => sql.prepare('SELECT id,name,note FROM saved_spots WHERE owner=? AND id NOT LIKE ?').all(owner, owner + '-%');
async function race(env, gate, jobs) {
  try { return await Promise.all(jobs); } finally { gate.release(); gate.done(); }
}

test('saved_spots_two_saves_compete_for_last_slot', {timeout: 15000}, async () => {
  const gate = barrier(2), {sql, adapter} = database(gate.hook), env = {DB: adapter};
  try {
    seed(sql, 'alice', 99);
    const results = await race(env, gate, [post(env, 'alice', {name: 'first', lat: 1, lon: 1}), post(env, 'alice', {name: 'second', lat: 2, lon: 2})]);
    assert.equal(gate.arrived(), 2, 'both saves reached their write together');
    assert.deepEqual(results.map(r => r.status).sort(), [201, 400]);
    const [won] = results.filter(r => r.status === 201), [lost] = results.filter(r => r.status === 400);
    assert.equal(lost.data.error, FULL_MESSAGE);
    assert.deepEqual(Object.keys(lost.data).filter(k => k !== 'request_id'), ['error'], 'no saved-row payload on a refusal');
    assert.equal(count(sql, 'alice'), 100);
    assert.equal((await (await call(env, '/api/spots', {owner: 'alice'})).json()).spots.length, 100);
    const added = owned(sql, 'alice');
    assert.equal(added.length, 1);
    assert.equal(added[0].id, won.data.id); assert.equal(added[0].name, won.data.name);
    assert.equal(sql.prepare("SELECT COUNT(*) AS n FROM saved_spots WHERE owner='alice' AND name LIKE 'n%'").get().n, 99, "the owner's existing spots are unchanged");
  } finally { gate.done(); sql.close(); }
});

test('saved_spots_two_slots_accept_both', {timeout: 15000}, async () => {
  const gate = barrier(2), {sql, adapter} = database(gate.hook), env = {DB: adapter};
  try {
    seed(sql, 'alice', 98);
    const results = await race(env, gate, [post(env, 'alice', {name: 'first', lat: 1, lon: 1}), post(env, 'alice', {name: 'second', lat: 2, lon: 2})]);
    assert.deepEqual(results.map(r => r.status), [201, 201]);
    assert.equal(count(sql, 'alice'), 100);
    assert.deepEqual(owned(sql, 'alice').map(r => r.id).sort(), results.map(r => r.data.id).sort());
  } finally { gate.done(); sql.close(); }
});

test('saved_spots_cap_is_owner_scoped_during_competing_saves', {timeout: 15000}, async () => {
  const gate = barrier(3), {sql, adapter} = database(gate.hook), env = {DB: adapter};
  try {
    seed(sql, 'alice', 100); seed(sql, 'bob', 50); seed(sql, 'carol', 103);
    const [a, b, c] = await race(env, gate, [post(env, 'alice', {lat: 1, lon: 1}), post(env, 'bob', {lat: 1, lon: 1}), post(env, 'carol', {lat: 1, lon: 1})]);
    assert.equal(a.status, 400); assert.equal(a.data.error, FULL_MESSAGE);
    assert.equal(b.status, 201);
    assert.equal(c.status, 400, 'an owner already above the cap is refused too'); assert.equal(c.data.error, FULL_MESSAGE);
    assert.deepEqual([count(sql, 'alice'), count(sql, 'bob'), count(sql, 'carol')], [100, 51, 103], 'nothing was added to the full owners and nothing was deleted');
    assert.equal((await call(env, '/api/spots', {method: 'POST', body: {lat: 1, lon: 1}})).status, 401, 'anonymous save stays refused');
  } finally { gate.done(); sql.close(); }
});

test('saved_spots_delete_releases_one_slot', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  try {
    seed(sql, 'alice', 100);
    const refused = await post(env, 'alice', {lat: 1, lon: 1});
    assert.equal(refused.status, 400); assert.equal(refused.data.error, FULL_MESSAGE);
    assert.equal((await call(env, '/api/spots/alice-0', {owner: 'bob', method: 'DELETE', body: {}})).status, 404);
    assert.equal((await post(env, 'alice', {lat: 1, lon: 1})).status, 400, "another owner's delete attempt frees nothing");
    assert.equal((await call(env, '/api/spots/alice-0', {owner: 'alice', method: 'DELETE', body: {}})).status, 200);
    assert.equal((await post(env, 'alice', {lat: 1, lon: 1})).status, 201);
    assert.equal((await post(env, 'alice', {lat: 1, lon: 1})).status, 400);
    assert.equal(count(sql, 'alice'), 100);
  } finally { sql.close(); }
});

test('saved_spots_validation_and_storage_failure_are_not_success', async () => {
  const writes = []; let failWrite = false;
  const {sql, adapter} = database(async query => { if (isSpotInsert(query)) { writes.push(query); if (failWrite) throw new Error('D1 down'); } }), env = {DB: adapter};
  const quiet = console.error; console.error = () => {};
  try {
    for (const fields of [{lat: 35.5}, {lat: 1, lon: 1, name: 'x'.repeat(81)}, {lat: 1, lon: 1, note: 7}]) assert.equal((await post(env, 'alice', fields)).status, 400);
    assert.equal(writes.length, 0, 'malformed input is refused before any write');
    seed(sql, 'alice', 100);
    const full = await post(env, 'alice', {lat: 1, lon: 1});
    assert.equal(full.status, 400); assert.equal(full.data.error, FULL_MESSAGE);
    assert.equal(writes.length, 1); assert.ok(!('id' in full.data) && !('created_at' in full.data), 'a zero-change write returns no saved row');
    sql.prepare("DELETE FROM saved_spots WHERE id='alice-0'").run(); failWrite = true;
    const down = await post(env, 'alice', {lat: 1, lon: 1});
    assert.equal(down.status, 503); assert.doesNotMatch(down.data.error, /at most 100/);
    assert.equal(count(sql, 'alice'), 99, 'a storage failure stores nothing and is not reported as success');
  } finally { console.error = quiet; sql.close(); }
});

// SC1137-08: PATCH /api/spots/:id changes a saved spot's name and/or private note, nothing else.
const patch = async (env, owner, id, fields, extra = {}) => { const r = await call(env, '/api/spots/' + id, {owner, method: 'PATCH', body: fields, ...extra}); return {status: r.status, data: await r.json()}; };
const row = (sql, id) => sql.prepare('SELECT * FROM saved_spots WHERE id=?').get(id);
const envelope = ({status, data: {request_id, ...rest}}) => [status, rest];
const POSITION_WORDS = ['lat cannot be changed; save a new spot for a different position', 'lon cannot be changed; save a new spot for a different position'];

test('spot_patch_rename_retains_identity_position_and_note', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  try {
    const first = await post(env, 'alice', SPOT);
    await post(env, 'alice', {name: 'second', lat: 2, lon: 2});
    const before = {...row(sql, first.data.id)}, order = (await (await call(env, '/api/spots', {owner: 'alice'})).json()).spots.map(s => s.id);
    const renamed = await patch(env, 'alice', first.data.id, {name: 'Fixed Reef'});
    assert.equal(renamed.status, 200);
    assert.deepEqual(renamed.data, {...before, name: 'Fixed Reef'}, 'the stored row comes back, only the name changed');
    assert.deepEqual({...row(sql, first.data.id)}, renamed.data);
    assert.equal((await (await call(env, '/api/spots/' + first.data.id, {owner: 'alice'})).json()).name, 'Fixed Reef');
    assert.deepEqual((await (await call(env, '/api/spots', {owner: 'alice'})).json()).spots.map(s => s.id), order, 'list order unchanged');
    const both = await patch(env, 'alice', first.data.id, {name: 'Again', note: 'new note'});
    assert.deepEqual(both.data, {...before, name: 'Again', note: 'new note'});
    for (const blank of [null, '']) {
      const r = await patch(env, 'alice', first.data.id, {name: blank});
      assert.equal(r.status, 200); assert.equal(r.data.name, '', 'a blank name is stored as POST stores it'); assert.equal(r.data.note, 'new note');
    }
    const exported = await (await call(env, '/api/privacy', {owner: 'alice'})).json(), other = (await call(env, '/api/spots', {owner: 'alice'}).then(r => r.json())).spots.find(s => s.id !== first.data.id);
    assert.deepEqual(exported.saved_spots.find(s => s.id === first.data.id), {...before, name: '', note: 'new note'}, 'the owner export carries the edited row');
    assert.deepEqual([other.name, other.note, other.lat, other.lon], ['second', null, 2, 2], 'the other spot is untouched');
  } finally { sql.close(); }
});

test('spot_patch_note_set_clear_and_unicode_limits', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  try {
    const made = await post(env, 'alice', {name: 'keep', lat: 3, lon: 4, note: 'old'}), id = made.data.id;
    assert.deepEqual(await patch(env, 'alice', id, {note: 'private'}).then(r => [r.status, r.data.name, r.data.note]), [200, 'keep', 'private'], 'a note-only edit leaves the name');
    for (const clear of [null, '', '   \n\t ']) {
      await patch(env, 'alice', id, {note: 'something'});
      const r = await patch(env, 'alice', id, {note: clear});
      assert.deepEqual([r.status, r.data.note, row(sql, id).note, r.data.name], [200, null, null, 'keep'], JSON.stringify(clear));
    }
    assert.equal((await patch(env, 'alice', id, {note: '  padded  '})).data.note, '  padded  ', 'a nonblank note is not trimmed');
    const fish = n => '🐟'.repeat(n);
    assert.equal((await patch(env, 'alice', id, {note: fish(1000)})).status, 200, '1000 code points');
    const longNote = await patch(env, 'alice', id, {note: fish(1001)});
    assert.equal(longNote.status, 400); assert.match(longNote.data.error, /note must be text of at most 1000/);
    assert.equal(row(sql, id).note, fish(1000), 'a refused note changes nothing');
    assert.equal((await patch(env, 'alice', id, {name: fish(40)})).status, 200, '40 surrogate pairs are 80 UTF-16 units');
    assert.equal((await patch(env, 'alice', id, {name: 'x'.repeat(80)})).status, 200);
    for (const name of [fish(41), 'x'.repeat(81)]) { const r = await patch(env, 'alice', id, {name}); assert.equal(r.status, 400); assert.match(r.data.error, /name must be text of at most 80/); }
    assert.equal(row(sql, id).name, 'x'.repeat(80));
    // A bad value in one field refuses the whole request: the other field is not applied either.
    const mixed = await patch(env, 'alice', id, {name: 'changed', note: 7});
    assert.equal(mixed.status, 400); assert.match(mixed.data.error, /note must be/);
    assert.equal(row(sql, id).name, 'x'.repeat(80));
    for (const fields of [{name: 7}, {name: ['a']}, {note: {a: 1}}, {note: false}]) { assert.equal((await patch(env, 'alice', id, fields)).status, 400, JSON.stringify(fields)); }
    assert.deepEqual([row(sql, id).name, row(sql, id).note, row(sql, id).lat, row(sql, id).lon], ['x'.repeat(80), fish(1000), 3, 4]);
  } finally { sql.close(); }
});

test('spot_patch_position_and_unknown_keys_refused', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  try {
    const made = await post(env, 'alice', {name: 'stay', lat: 35.5, lon: -121.2, note: 'n'}), id = made.data.id, before = {...row(sql, id)};
    const refused = [[{lat: 36}, POSITION_WORDS[0]], [{lon: -120}, POSITION_WORDS[1]], [{lat: 36, lon: -120}, POSITION_WORDS[0]], [{lon: -120, lat: 36, name: 'moved'}, POSITION_WORDS[0]],
      [{lat: null}, POSITION_WORDS[0]], [{lon: null}, POSITION_WORDS[1]], [{lat: 35.5}, POSITION_WORDS[0]], [{lat: 35.5, lon: -121.2, name: 'same spot'}, POSITION_WORDS[0]]];
    for (const [fields, message] of refused) { const r = await patch(env, 'alice', id, fields); assert.equal(r.status, 400, JSON.stringify(fields)); assert.equal(r.data.error, message, JSON.stringify(fields)); }
    for (const fields of [{latitude: 36}, {longitude: 1}, {owner: 'bob'}, {id: 'other'}, {created_at: 'x'}, {visibility: 'public'}, {name: 'renamed', extra: 1}, {name: 'renamed', note: 'x', owner: 'alice'}]) {
      const r = await patch(env, 'alice', id, fields); assert.equal(r.status, 400, JSON.stringify(fields)); assert.equal(r.data.error, 'only name and note can be changed');
    }
    assert.deepEqual({...row(sql, id)}, before, 'no refused request changed anything');
    assert.equal(count(sql, 'alice'), 1);
  } finally { sql.close(); }
});

test('spot_patch_unknown_and_foreign_indistinguishable', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  try {
    const mine = await post(env, 'alice', SPOT), before = {...row(sql, mine.data.id)};
    for (const fields of [{name: 'taken'}, {lat: 1}, {unknown: 1}, {}, {note: 'x'.repeat(2000)}]) {
      const foreign = await patch(env, 'bob', mine.data.id, fields), missing = await patch(env, 'bob', 'no-such-id', fields);
      assert.equal(foreign.status, 404, JSON.stringify(fields));
      assert.deepEqual(envelope(foreign), envelope(missing), 'identical to an id that never existed');
      assert.equal(foreign.data.error, 'Not found');
    }
    for (const raw of ['{"name":', '[]', 'null', '']) {
      const foreign = await call(env, '/api/spots/' + mine.data.id, {owner: 'bob', method: 'PATCH', raw}), missing = await call(env, '/api/spots/no-such-id', {owner: 'bob', method: 'PATCH', raw});
      assert.deepEqual([foreign.status, (await foreign.json()).error], [404, 'Not found']); assert.equal(missing.status, 404, 'a malformed body is no ownership oracle');
    }
    assert.deepEqual({...row(sql, mine.data.id)}, before, "the other owner's row is untouched");
    // Signed out and a missing Origin never reach the row.
    const out = await call(env, '/api/spots/' + mine.data.id, {method: 'PATCH', body: {name: 'x'}});
    assert.equal(out.status, 401);
    const noOrigin = await call(env, '/api/spots/' + mine.data.id, {owner: 'alice', method: 'PATCH', body: {name: 'x'}, origin: false});
    assert.equal(noOrigin.status, 400); assert.match((await noOrigin.json()).error, /origin rejected/);
    assert.deepEqual({...row(sql, mine.data.id)}, before);
    assert.equal((await patch(env, 'alice', mine.data.id, {name: 'mine'})).status, 200, 'the owner can still edit');
  } finally { sql.close(); }
});

test('spot_patch_bad_json_and_empty_object', async () => {
  const writes = []; const {sql, adapter} = database(async query => { if (/^\s*UPDATE\s+saved_spots/i.test(query)) writes.push(query); }), env = {DB: adapter};
  try {
    const made = await post(env, 'alice', SPOT), id = made.data.id, before = {...row(sql, id)};
    const send = async raw => { const r = await call(env, '/api/spots/' + id, {owner: 'alice', method: 'PATCH', raw}); return {status: r.status, error: (await r.json()).error}; };
    for (const [raw, message] of [['{"name":', 'invalid JSON body'], ['[]', 'invalid JSON body'], ['[{"name":"x"}]', 'invalid JSON body'], ['null', 'invalid JSON body'], ['"name"', 'invalid JSON body'], ['7', 'invalid JSON body'], ['', 'invalid JSON body'],
      [JSON.stringify({note: 'x'.repeat(9000)}), 'body too large'], ['{}', 'send name and/or note']]) {
      assert.deepEqual(await send(raw), {status: 400, error: message}, String(raw).slice(0, 30));
    }
    assert.equal(writes.length, 0, 'no update statement ran for any of them');
    assert.deepEqual({...row(sql, id)}, before);
  } finally { sql.close(); }
});

test('spot_patch_at_cap_and_interleaved_updates', {timeout: 15000}, async () => {
  const updates = query => /^\s*UPDATE\s+saved_spots/i.test(query);
  const quiet = console.error; console.error = () => {};
  try {
    // A metadata edit adds nothing, so it works at the cap and above it; the POST cap is untouched.
    const full = database(), fullEnv = {DB: full.adapter};
    seed(full.sql, 'alice', 100); seed(full.sql, 'carol', 103);
    assert.equal((await patch(fullEnv, 'alice', 'alice-3', {name: 'renamed', note: 'kept'})).status, 200);
    assert.equal((await patch(fullEnv, 'carol', 'carol-0', {note: 'legacy'})).status, 200);
    assert.deepEqual([count(full.sql, 'alice'), count(full.sql, 'carol')], [100, 103]);
    assert.equal((await post(fullEnv, 'alice', {lat: 1, lon: 1})).data.error, FULL_MESSAGE, 'a full account still cannot save another');
    full.sql.close();
    // Two edits in flight together, each to its own column, both land.
    let arrived = 0, release; const opened = new Promise(r => { release = r; }), timer = setTimeout(release, 2000);
    const both = database(async query => { if (!updates(query) || arrived >= 2) return; if (++arrived >= 2) release(); await opened; }), env = {DB: both.adapter};
    try {
      const id = (await post(env, 'alice', {name: 'orig', lat: 5, lon: 6, note: 'orig note'})).data.id;
      const results = await Promise.all([patch(env, 'alice', id, {name: 'new name'}), patch(env, 'alice', id, {note: 'new note'})]);
      assert.equal(arrived, 2, 'both edits reached their write together');
      assert.deepEqual(results.map(r => r.status), [200, 200]);
      assert.deepEqual([row(both.sql, id).name, row(both.sql, id).note], ['new name', 'new note']);
    } finally { clearTimeout(timer); release(); both.sql.close(); }
    // A delete that lands between the ownership check and the write answers not-found and brings nothing back.
    let deleted = null;
    const raced = database(async query => { if (updates(query) && deleted) { deleted.sql.prepare("DELETE FROM saved_spots WHERE id='gone'").run(); deleted = null; } }), racedEnv = {DB: raced.adapter};
    seed(raced.sql, 'alice', 1, 'gone'); raced.sql.prepare("UPDATE saved_spots SET id='gone' WHERE id='gone-0'").run(); deleted = raced;
    const lost = await patch(racedEnv, 'alice', 'gone', {name: 'late'});
    assert.deepEqual(envelope(lost), [404, {error: 'Not found'}]); assert.equal(row(raced.sql, 'gone'), undefined, 'the deleted spot is not recreated');
    raced.sql.close();
    // A storage failure is not success and changes nothing.
    let fail = false; const broken = database(async query => { if (fail && updates(query)) throw new Error('D1 down'); }), brokenEnv = {DB: broken.adapter};
    const kept = (await post(brokenEnv, 'alice', {name: 'kept', lat: 1, lon: 1})).data.id; fail = true;
    const down = await patch(brokenEnv, 'alice', kept, {name: 'lost'});
    assert.equal(down.status, 503); assert.ok(!('name' in down.data));
    assert.equal(row(broken.sql, kept).name, 'kept'); broken.sql.close();
  } finally { console.error = quiet; }
});
