// BF-catch-log: the private effort log. A blank is a first-class outcome; coordinates stay private;
// the log is in the account export and gone on deletion; it appears in no feed or public page.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, readdirSync, statSync} from 'node:fs';
import {join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {DatabaseSync} from 'node:sqlite';
import util from 'node:util';
import {withSessions} from './fixtures/test-sessions.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.BUILD_ID = 'build-test';
globalThis.SHELLS = {'/': '/index.0123456789.html', '/index.html': '/index.0123456789.html', '/landing.html': '/landing.0123456789.html', '/app.html': '/app.0123456789.html'};
const {default: deployed} = await import('../server/index.ts');
const {recordReads, resetMeter} = await import('../server/cost-ceiling.ts');
const {logItemHTML, logBody, logTripLabel, logTripOptionsHTML} = await import('../dist/account.js');
const worker = withSessions(deployed), ORIGIN = 'https://skippercast.com';

function database(wrap = a => a) {
  const sql = new DatabaseSync(':memory:');
  for (const {tag} of [...read('../drizzle/meta/_journal.json').entries].sort((a, b) => a.idx - b.idx)) sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`, import.meta.url), 'utf8'));
  const adapter = {prepare(query) { let args = []; const statement = sql.prepare(query); return {bind(...a) { args = a; return this; }, async first() { return statement.get(...args) || null; }, async all() { return {results: statement.all(...args)}; }, async run() { const info = statement.run(...args); return {meta: {changes: Number(info.changes)}}; }}; },
    async batch(queries) { sql.exec('BEGIN'); try { const out = []; for (const q of queries) out.push(await q.run()); sql.exec('COMMIT'); return out; } catch (e) { sql.exec('ROLLBACK'); throw e; } }};
  return {sql, adapter: wrap(adapter)};
}
const call = (env, path, {owner, method = 'GET', body, raw} = {}) => {
  const headers = {'Content-Type': 'application/json', 'CF-Connecting-IP': '203.0.113.9'};
  if (owner) headers['x-test-owner'] = owner;
  if (method !== 'GET') headers.Origin = ORIGIN;
  return worker.fetch(new Request(ORIGIN + path, {method, headers, body: raw ?? (body === undefined ? undefined : JSON.stringify(body))}), env);
};
const FISH = {started_at: '2026-11-01T14:00:00Z', ended_at: '2026-11-01T19:30:00Z', outcome: 'fish', count: 3, method: 'drift', species: 'lingcod', lat: 35.123456789, lon: -120.987654321, note: 'LOGNOTE-private-fish'};
const BLANK = {started_at: '2026-11-02T14:00:00Z', outcome: 'blank', method: 'troll', species: 'salmon', lat: 35.5, lon: -121.25, note: 'LOGNOTE-private-blank'};
const post = async (env, owner, entry) => { const r = await call(env, '/api/catch-log', {owner, method: 'POST', body: entry}); return {status: r.status, data: await r.json()}; };
const logCount = (sql, owner) => sql.prepare('SELECT COUNT(*) AS n FROM catch_log WHERE owner=?').get(owner).n;

test('a fish row and a blank row are written for one account and read back, with a blank kept as a blank at zero count', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  const fish = await post(env, 'alice', FISH), blank = await post(env, 'alice', BLANK);
  assert.deepEqual([fish.status, blank.status], [201, 201]);
  const list = await (await call(env, '/api/catch-log', {owner: 'alice'})).json();
  assert.deepEqual(list.entries.map(e => e.id), [blank.data.id, fish.data.id], 'newest first');
  const b = await (await call(env, '/api/catch-log/' + blank.data.id, {owner: 'alice'})).json();
  assert.deepEqual([b.outcome, b.count, b.species, b.lat, b.lon], ['blank', 0, 'salmon', 35.5, -121.25]);
  const f = await (await call(env, '/api/catch-log/' + fish.data.id, {owner: 'alice'})).json();
  assert.deepEqual([f.outcome, f.count, f.lat, f.lon, f.ended_at], ['fish', 3, 35.123456789, -120.987654321, '2026-11-01T19:30:00.000Z'], 'coordinates stored as entered');
  assert.deepEqual({...sql.prepare("SELECT outcome,count FROM catch_log WHERE id=?").get(blank.data.id)}, {outcome: 'blank', count: 0}, 'stored, not dropped as empty');
  assert.equal((await post(env, 'alice', {started_at: BLANK.started_at, outcome: 'blank', count: 0})).status, 201, 'a blank with an explicit zero and no coordinates');
  assert.equal(sql.prepare('SELECT lat,lon FROM catch_log WHERE count=0 AND lat IS NULL').all().length, 1, 'coordinates are optional');
  sql.close();
});

test('another account gets the not-found shape for the same ids, and cannot delete or attach to them', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  const mine = await post(env, 'alice', FISH);
  const other = await call(env, '/api/catch-log/' + mine.data.id, {owner: 'bob'}), never = await call(env, '/api/catch-log/no-such-id', {owner: 'bob'});
  assert.equal(other.status, 404);
  const shape = async r => { const {request_id, ...rest} = await r.json(); return [r.status, rest]; };
  assert.deepEqual(await shape(other), await shape(never), 'identical to an id that never existed');
  assert.deepEqual((await (await call(env, '/api/catch-log', {owner: 'bob'})).json()).entries, []);
  assert.equal((await call(env, '/api/catch-log/' + mine.data.id, {owner: 'bob', method: 'DELETE', body: {}})).status, 404);
  assert.equal(logCount(sql, 'alice'), 1, 'bob could not delete it');
  sql.prepare("INSERT INTO trips(id,owner,region,point,species,date,start_hour,end_hour,wind_limit,gust_limit,sea_limit,created_at) VALUES('trip-a','alice','morro-bay','north','reef','2026-11-05',7,13,8,12,3,'x')").run();
  assert.equal((await post(env, 'bob', {...FISH, trip_id: 'trip-a'})).status, 404, "bob cannot log against alice's trip");
  assert.equal((await post(env, 'alice', {...FISH, trip_id: 'trip-a'})).status, 201);
  assert.equal(logCount(sql, 'bob'), 0);
  assert.equal((await call(env, '/api/catch-log/' + mine.data.id, {owner: 'alice', method: 'DELETE', body: {}})).status, 200);
  assert.equal((await call(env, '/api/catch-log/' + mine.data.id, {owner: 'alice', method: 'DELETE', body: {}})).status, 404, 'a second delete is not found');
  sql.close();
});

test('the account export holds both rows with their coordinates, and deleting the account removes them', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  await post(env, 'alice', FISH); await post(env, 'alice', BLANK); await post(env, 'bob', {...BLANK, note: 'LOGNOTE-bob'});
  const out = await (await call(env, '/api/privacy', {owner: 'alice'})).json();
  assert.deepEqual(out.catch_log.map(e => [e.outcome, e.count, e.lat, e.lon]), [['fish', 3, 35.123456789, -120.987654321], ['blank', 0, 35.5, -121.25]]);
  assert.ok(!JSON.stringify(out).includes('LOGNOTE-bob'), "bob's row is not in alice's export");
  assert.equal((await call(env, '/api/privacy', {owner: 'alice', method: 'DELETE', body: {}})).status, 200);
  assert.equal(logCount(sql, 'alice'), 0);
  assert.equal(logCount(sql, 'bob'), 1, "bob's log is untouched");
  sql.close();
});

// The exact files that may mention the private log: the route, the export, the app mount, the schema, the account sheet,
// the private trip cleanup (delete route, retention prune), and (SC0022-07) the two signed-in
// readers of the past-trip recap. Never a directory or a pattern.
const PRIVATE_READERS = new Set(['server/routes/catch-log.ts', 'server/routes/account.ts', 'server/app.ts', 'db/schema.ts', 'dist/account.js', 'server/routes/trips.ts', 'server/trips.ts', 'web/alerts.ts', 'web/app/TripAlerts.tsx']);
const isUnapprovedReader = (rel, text) => /\.(ts|tsx|js|mjs|py)$/.test(rel) && /catch_log\b|api\/catch-log|routes\/catch-log/.test(text) && !PRIVATE_READERS.has(rel);

test('private_log_reader_allowlist_stays_exact', () => {
  assert.deepEqual([...PRIVATE_READERS].filter(p => p.startsWith('web/')).sort(), ['web/alerts.ts', 'web/app/TripAlerts.tsx']);
  const mention = '// GET /api/catch-log';
  for (const rel of PRIVATE_READERS) assert.equal(isUnapprovedReader(rel, mention), false, rel);
  // Anywhere else, including beside an approved reader, the same text is rejected.
  for (const rel of ['web/app/Brief.tsx', 'web/app/TripAlerts2.tsx', 'web/alerts.js', 'web/public-feed.ts', 'dist/feed.js', 'server/routes/feeds.ts', 'scripts/export.py', 'web/app/TripAlerts.tsx.bak.ts'])
    assert.equal(isUnapprovedReader(rel, mention), true, rel);
  assert.equal(isUnapprovedReader('web/public-feed.ts', 'SELECT * FROM catch_log'), true);
  assert.equal(isUnapprovedReader('web/public-feed.ts', 'no mention of the log'), false);
  assert.equal(isUnapprovedReader('web/notes.md', mention), false, 'non-code files are not scanned');
});

test('no log field reaches any feed or public page, and no public code reads the log table', async () => {
  const {sql, adapter} = database(), original = globalThis.fetch;
  const env = {DB: adapter, FEEDS: {get: async () => null, head: async () => null, list: async () => ({objects: []})}, ASSETS: {fetch: async () => new Response('<!doctype html><title>shell</title>', {headers: {'Content-Type': 'text/html'}})}};
  await post(env, 'alice', FISH); await post(env, 'alice', BLANK);
  const secrets = ['LOGNOTE-private', 'lingcod', '35.123456789', '-120.987654321', '35.5', '-121.25', 'catch_log'];
  const paths = ['/', '/map', '/privacy', '/sources', '/status', '/coverage', '/api/session', '/api/daily', '/api/forecast', '/api/intelligence', '/api/habitat', '/api/health', '/feeds/daily.json', '/feeds/index.json', '/api/om/v1/forecast?latitude=35&longitude=-120'];
  globalThis.fetch = async () => { throw new Error('offline'); };
  try {
    for (const who of [undefined, 'bob']) for (const path of paths) {
      const text = await (await call(env, path, {owner: who})).text();
      for (const s of secrets) assert.ok(!text.includes(s), `${path} (${who ?? 'anonymous'}) must not contain ${s}`);
    }
  } finally { globalThis.fetch = original; }
  const root = fileURLToPath(new URL('..', import.meta.url));
  const hits = [];
  const walk = dir => { for (const name of readdirSync(dir)) { const full = join(dir, name), rel = full.slice(root.length).replaceAll('\\', '/').replace(/^\//, '');
    if (name === 'node_modules' || name.startsWith('.') || rel === 'dist/client' || rel === 'dist/server') continue;
    if (statSync(full).isDirectory()) walk(full); else if (isUnapprovedReader(rel, readFileSync(full, 'utf8'))) hits.push(rel); } };
  for (const dir of ['server', 'web', 'dist', 'src', 'packages', 'scripts']) walk(join(root, dir));
  assert.deepEqual(hits, [], 'only the log route, the export, the app mount, the schema, the account view, the private trip cleanup and the two signed-in readers mention the log');
  sql.close();
});

test('coordinates at a pole, at the antimeridian, half given or not finite are refused by name, and nothing is stored', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  const base = {started_at: BLANK.started_at, outcome: 'blank'};
  const named = [[{lat: 35.5}, 'coordinates_incomplete'], [{lon: -121}, 'coordinates_incomplete'], [{lat: 90, lon: 0}, 'coordinates_out_of_range'], [{lat: -90, lon: 0}, 'coordinates_out_of_range'],
    [{lat: 0, lon: 180}, 'coordinates_out_of_range'], [{lat: 0, lon: -180}, 'coordinates_out_of_range'], [{lat: 95, lon: 10}, 'coordinates_out_of_range'], [{lat: '35.5', lon: '-121'}, 'coordinates_not_finite'], [{lat: true, lon: 1}, 'coordinates_not_finite']];
  for (const [coords, name] of named) {
    const r = await post(env, 'alice', {...base, ...coords});
    assert.equal(r.status, 400, JSON.stringify(coords)); assert.match(r.data.error, new RegExp('^' + name), JSON.stringify(coords));
  }
  for (const raw of ['{"started_at":"2026-11-02T14:00:00Z","outcome":"blank","lat":1e999,"lon":1}', '{"started_at":"2026-11-02T14:00:00Z","outcome":"blank","lat":1,"lon":-1e999}']) {
    const r = await call(env, '/api/catch-log', {owner: 'alice', method: 'POST', raw});
    assert.equal(r.status, 400); assert.match((await r.json()).error, /^coordinates_not_finite/);
  }
  assert.equal((await post(env, 'alice', {...base, lat: 89.9999, lon: 179.9999})).status, 201, 'just inside the limits is accepted');
  for (const bad of [{outcome: 'caught'}, {outcome: 'blank', count: 2}, {outcome: 'unknown', count: 1}, {outcome: 'fish'}, {outcome: 'fish', count: 0}, {outcome: 'fish', count: 1.5}, {outcome: 'fish', count: -1},
    {outcome: 'blank', started_at: undefined}, {outcome: 'blank', started_at: 'yesterday'}, {outcome: 'blank', ended_at: '2026-11-01T00:00:00Z'}, {outcome: 'blank', note: 'x'.repeat(1001)}])
    assert.equal((await post(env, 'alice', {...base, ...bad})).status, 400, JSON.stringify(bad));
  assert.equal(logCount(sql, 'alice'), 1, 'only the one valid entry was kept');
  sql.close();
});

test('a note with markup and a 4-byte emoji round-trips as text and is rendered escaped', async () => {
  const {sql, adapter} = database(), env = {DB: adapter}, note = '<img src=x onerror=alert(1)> & "quote" 🎣 𝒳';
  const made = await post(env, 'alice', {...BLANK, note});
  assert.equal((await (await call(env, '/api/catch-log/' + made.data.id, {owner: 'alice'})).json()).note, note);
  assert.equal(sql.prepare('SELECT note FROM catch_log').get().note, note);
  const html = logItemHTML({...made.data, note, species: '<b>x</b>'});
  assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt;') && html.includes('🎣 𝒳') && html.includes('&lt;b&gt;x&lt;/b&gt;'), html);
  assert.ok(!/<img|<b>/.test(html), 'no stored markup is live');
  assert.match(logItemHTML({id: 'a"b', outcome: 'blank', started_at: BLANK.started_at, count: 0}), /data-remove-log="a&quot;b"/);
  assert.deepEqual([logBody({outcome: 'blank', count: '7', lat: '', lon: ''}).count, logBody({outcome: 'blank', lat: '', lon: ''}).lat], [undefined, null], 'a blank sends no count and no position');
  assert.equal(logBody({outcome: 'fish', count: '4', lat: '35.5', lon: '-121'}).count, 4);
  sql.close();
});

test('an unauthenticated write is refused before any D1 call', async () => {
  const calls = [], {sql, adapter} = database(a => ({...a, prepare(q) { calls.push(q); return a.prepare(q); }, batch: a.batch}));
  const env = {DB: adapter};
  for (const [method, path] of [['POST', '/api/catch-log'], ['DELETE', '/api/catch-log/x'], ['GET', '/api/catch-log']]) {
    const r = await call(env, path, {method, body: method === 'GET' ? undefined : BLANK});
    assert.equal(r.status, 401, method);
  }
  assert.deepEqual(calls, [], 'no statement was prepared');
  assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM catch_log').get().n, 0);
  sql.close();
});

test('under the cost-ceiling degraded state a write succeeds and is stored; a failing database says unavailable and stores nothing', async () => {
  const {sql, adapter} = database(), env = {DB: adapter, FEEDS: {get: async () => null, head: async () => null}, COST_CEILING_R2_READS_PER_DAY: '1'};
  resetMeter(); recordReads(5);
  try {
    const r = await call(env, '/api/catch-log', {owner: 'alice', method: 'POST', body: BLANK});
    assert.equal(r.headers.get('X-SC-Degraded'), 'cost-ceiling', 'the worker is degraded');
    assert.equal(r.status, 201, 'the write succeeds; it is never silently dropped');
    assert.equal(logCount(sql, 'alice'), 1);
  } finally { resetMeter(); }
  const down = database(a => ({...a, prepare(q) { if (/INSERT INTO catch_log/.test(q)) throw new Error('D1 unavailable'); return a.prepare(q); }}));
  const failed = await call({DB: down.adapter}, '/api/catch-log', {owner: 'alice', method: 'POST', body: BLANK});
  assert.equal(failed.status, 503, 'unavailable, not a success');
  assert.equal(logCount(down.sql, 'alice'), 0);
  sql.close(); down.sql.close();
});

// The real /my-data page script, run against the worker with a stub DOM: `owner` plays the session cookie.
async function runMyData({hash = '', owner, env}) {
  const els = new Map(), fetched = [], saved = {};
  const el = id => els.get(id) || els.set(id, {id, textContent: '', hidden: false, disabled: false, className: '', handlers: {}, addEventListener(t, f) { this.handlers[t] = f; }}).get(id);
  const saveGlobals = ['document', 'location', 'fetch'].map(k => [k, globalThis[k]]);
  Object.assign(globalThis, {location: {hash}, document: {getElementById: el, body: {append() {}}, createElement: () => ({click() { saved.name = this.download; }, remove() {}})},
    fetch: async (path, init = {}) => { fetched.push([path, init]); const headers = {...(init.headers || {})}; if (owner && init.credentials === 'same-origin') headers['x-test-owner'] = owner; return worker.fetch(new Request(ORIGIN + path, {method: init.method || 'GET', headers: {'CF-Connecting-IP': '203.0.113.9', ...headers}}), env); }});
  const realCreate = URL.createObjectURL; URL.createObjectURL = blob => { saved.blob = blob; return 'blob:x'; };
  try { await import('../dist/advisor/my-data.js?run=' + Math.random()); if (!el('data-download').hidden && el('data-download').handlers.click) await el('data-download').handlers.click(); }
  finally { URL.createObjectURL = realCreate; for (const [k, v] of saveGlobals) { if (v === undefined) delete globalThis[k]; else globalThis[k] = v; } }
  return {button: el('data-download'), status: el('data-status'), fetched, saved, body: saved.blob ? JSON.parse(await saved.blob.text()) : null};
}

test('the /my-data page downloads the signed-in account export with fish and blank rows and coordinates, and never mixes it with the Advisor token', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  await post(env, 'alice', FISH); await post(env, 'alice', BLANK); await post(env, 'bob', {...BLANK, note: 'LOGNOTE-bob'});
  const page = await runMyData({owner: 'alice', env});
  assert.equal(page.button.hidden, false);
  assert.deepEqual(page.fetched.map(([p]) => p), ['/api/session', '/api/privacy'], 'no Advisor export is called');
  assert.ok(page.fetched.every(([, i]) => i.credentials === 'same-origin' && !(i.headers && i.headers['X-Export-Token'])));
  assert.deepEqual(page.body.catch_log.map(e => [e.outcome, e.count, e.lat, e.lon]), [['fish', 3, 35.123456789, -120.987654321], ['blank', 0, 35.5, -121.25]]);
  assert.ok(!JSON.stringify(page.body).includes('LOGNOTE-bob'));
  assert.equal(page.saved.name, 'skippercast-data.json');
  const out = await runMyData({owner: undefined, env});
  assert.deepEqual([out.button.hidden, out.body, out.fetched.map(([p]) => p)], [true, null, ['/api/session']], 'signed out: nothing to download, no export call');
  assert.ok(out.status.textContent.length > 3 && !out.status.hidden);
  const tok = await runMyData({hash: '#abc-DEF_1', owner: 'alice', env});
  assert.deepEqual(tok.fetched.map(([p, i]) => [p, i.credentials, i.headers['X-Export-Token']]), [['/api/advisor/export', 'omit', 'abc-DEF_1']], 'a token page calls only the Advisor export, without the session');
  assert.equal(tok.body, null);
  sql.close();
});

// SC0237-05: a trip that goes (delete route or 90-day retention) must not leave a dangling catch-log link.
const {prune} = await import('../server/trips.ts');
const TRIP = 'INSERT INTO trips(id,owner,region,point,species,date,start_hour,end_hour,wind_limit,gust_limit,sea_limit,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)';
const addTrip = (sql, id, owner, date, created = '2026-11-01T00:00:00.000Z') => sql.prepare(TRIP).run(id, owner, 'morro-bay', 'north', 'reef', date, 7, 13, 8, 12, 3, created);
const addEvent = (sql, id, trip, owner, created = '2026-11-01T00:00:00.000Z') => { sql.prepare('INSERT INTO alert_events(id,trip_id,owner,kind,message,created_at) VALUES(?,?,?,?,?,?)').run(id, trip, owner, 'change', 'm', created); sql.prepare('INSERT INTO delivery_receipts(id,event_id,subscription_id,status,attempt_at) VALUES(?,?,?,?,?)').run('r-' + id, id, 's', 'accepted', created); };
const addSentinel = (sql, id, owner, trip) => sql.prepare('INSERT INTO catch_log(id,owner,trip_id,started_at,outcome,count,lat,lon,note,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)').run(id, owner, trip, '2026-11-03T14:00:00.000Z', 'blank', 0, 35.5, -121.25, 'LOGNOTE-sentinel', '2026-11-03T15:00:00.000Z');
const rows = sql => sql.prepare('SELECT * FROM catch_log ORDER BY id').all().map(r => ({...r}));
const links = sql => Object.fromEntries(sql.prepare('SELECT id,trip_id FROM catch_log ORDER BY id').all().map(r => [r.id, r.trip_id]));
const ids = (sql, table) => sql.prepare(`SELECT id FROM ${table} ORDER BY id`).all().map(r => r.id);
const exportRows = async (env, owner) => (await (await call(env, '/api/privacy', {owner})).json()).catch_log;
const listRows = async (env, owner) => (await (await call(env, '/api/catch-log', {owner})).json()).entries;
// An adapter whose batch fails on the trip deletion, after every earlier statement (the link update included) has run.
const failingTripDelete = a => ({...a, prepare(q) { const s = a.prepare(q); const w = {bind(...x) { s.bind(...x); return w; }, first: () => s.first(), all: () => s.all(), run() { if (/^DELETE FROM trips/.test(q)) throw new Error('late failure'); return s.run(); }}; return w; }, batch: a.batch});
const delTrip = (env, owner, id) => call(env, '/api/trips', {owner, method: 'DELETE', body: {id}});

test('delete_trip_detaches_only_owners_matching_entries', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  addTrip(sql, 'trip-a', 'alice', '2026-11-05'); addTrip(sql, 'trip-b', 'alice', '2026-11-06'); addTrip(sql, 'trip-bob', 'bob', '2026-11-05');
  const fish = await post(env, 'alice', {...FISH, trip_id: 'trip-a'}), blank = await post(env, 'alice', {...BLANK, trip_id: 'trip-a'});
  const other = await post(env, 'alice', {...FISH, trip_id: 'trip-b'}), loose = await post(env, 'alice', BLANK);
  assert.deepEqual([fish.status, blank.status, other.status, loose.status], [201, 201, 201, 201]);
  addSentinel(sql, 'bob-sentinel', 'bob', 'trip-a');
  addEvent(sql, 'ev-a', 'trip-a', 'alice');
  const before = rows(sql);
  const r = await delTrip(env, 'alice', 'trip-a');
  assert.deepEqual([r.status, await r.json()], [200, {deleted: true}]);
  assert.deepEqual(ids(sql, 'trips'), ['trip-b', 'trip-bob'], 'only the deleted trip went');
  assert.deepEqual([ids(sql, 'alert_events'), ids(sql, 'delivery_receipts')], [[], []], 'events and receipts still go');
  const expected = before.map(x => x.id === fish.data.id || x.id === blank.data.id ? {...x, trip_id: null} : x);
  assert.ok(util.isDeepStrictEqual(rows(sql), expected), 'only the two matching rows lost trip_id; every other field and row is the same');
  assert.equal(links(sql)['bob-sentinel'], 'trip-a', "another owner's row is untouched");
  assert.equal(links(sql)[other.data.id], 'trip-b'); assert.equal(links(sql)[loose.data.id], null);
  for (const entries of [await listRows(env, 'alice'), await exportRows(env, 'alice')]) {
    assert.equal(entries.length, 4, 'every entry is kept');
    assert.deepEqual(entries.map(e => [e.id, e.trip_id ?? null]).sort(), [[fish.data.id, null], [blank.data.id, null], [other.data.id, 'trip-b'], [loose.data.id, null]].sort());
    assert.ok(entries.some(e => e.note === 'LOGNOTE-private-fish' && e.lat === 35.123456789), 'private fields kept');
  }
  const again = await delTrip(env, 'alice', 'trip-a');
  assert.deepEqual([again.status, await again.json()], [200, {deleted: true}], 'a repeat delete keeps the success shape');
  assert.ok(util.isDeepStrictEqual(rows(sql), expected), 'and changes nothing further');
  sql.close();
});

test('delete_foreign_missing_invalid_trip_never_detaches_others', async () => {
  const calls = [], {sql, adapter} = database(a => ({...a, prepare(q) { calls.push(q); return a.prepare(q); }, batch: a.batch})), env = {DB: adapter};
  addTrip(sql, 'trip-a', 'alice', '2026-11-05');
  await post(env, 'alice', {...FISH, trip_id: 'trip-a'});
  const before = rows(sql);
  assert.deepEqual([(await delTrip(env, 'bob', 'trip-a')).status, (await delTrip(env, 'bob', 'no-such-trip')).status], [200, 200], 'a foreign or missing id keeps the existing no-op success');
  assert.ok(util.isDeepStrictEqual(rows(sql), before), "bob cannot detach alice's entry");
  assert.deepEqual(ids(sql, 'trips'), ['trip-a'], "alice's trip survives");
  for (const body of [{}, {id: ''}, {id: 'x'.repeat(65)}, {id: 7}, {id: null}, {id: ['trip-a']}]) assert.equal((await call(env, '/api/trips', {owner: 'alice', method: 'DELETE', body})).status, 400, JSON.stringify(body));
  assert.ok(util.isDeepStrictEqual(rows(sql), before), 'invalid ids detach nothing');
  calls.length = 0;
  assert.equal((await call(env, '/api/trips', {method: 'DELETE', body: {id: 'trip-a'}})).status, 401, 'signed out is refused');
  assert.deepEqual(calls, [], 'before any statement is prepared');
  assert.ok(util.isDeepStrictEqual(rows(sql), before));
  sql.close();
});

test('prune_detaches_only_expired_same_owner_trips', async () => {
  const {sql, adapter} = database(), env = {DB: adapter}, now = Date.parse('2026-11-04T12:00:00Z');
  // cutoff is 2026-08-06T12:00Z; the trip date comparison is strict on the UTC date 2026-08-06.
  addTrip(sql, 'before', 'alice', '2026-08-05'); addTrip(sql, 'exact', 'alice', '2026-08-06'); addTrip(sql, 'after', 'alice', '2026-08-07');
  addTrip(sql, 'old-created-current', 'alice', '2026-11-20', '2026-01-01T00:00:00.000Z');
  addTrip(sql, 'fresh-created-expired', 'alice', '2026-07-01', '2026-11-04T00:00:00.000Z');
  addTrip(sql, 'bob-expired', 'bob', '2026-07-01');
  const made = {};
  for (const t of ['before', 'exact', 'after', 'old-created-current', 'fresh-created-expired']) made[t] = (await post(env, 'alice', {...BLANK, trip_id: t})).data.id;
  made.none = (await post(env, 'alice', BLANK)).data.id;
  made.bobOwn = (await post(env, 'bob', {...FISH, trip_id: 'bob-expired'})).data.id;
  addSentinel(sql, 'bob-sentinel', 'bob', 'before'); addSentinel(sql, 'alice-sentinel', 'alice', 'bob-expired');
  addEvent(sql, 'ev-before', 'before', 'alice', '2026-07-01T00:00:00.000Z');
  const before = rows(sql);
  await prune(env, now);
  assert.deepEqual(ids(sql, 'trips'), ['after', 'exact', 'old-created-current'], 'trip retention is unchanged');
  const detached = new Set([made.before, made['fresh-created-expired'], made.bobOwn]);
  assert.ok(util.isDeepStrictEqual(rows(sql), before.map(x => detached.has(x.id) ? {...x, trip_id: null} : x)), 'only strictly expired same-owner links cleared; no other field or row changed');
  assert.deepEqual([links(sql)[made.exact], links(sql)[made.after], links(sql)[made['old-created-current']], links(sql)[made.none]], ['exact', 'after', 'old-created-current', null]);
  assert.equal(links(sql)['bob-sentinel'], 'before', "another owner's mismatched reference is left alone");
  assert.equal(links(sql)['alice-sentinel'], 'bob-expired');
  assert.equal(logCount(sql, 'alice'), 7); assert.equal(logCount(sql, 'bob'), 2);
  for (const owner of ['alice', 'bob']) for (const entries of [await listRows(env, owner), await exportRows(env, owner)]) {
    assert.ok(entries.length > 0);
    for (const e of entries) assert.equal(e.trip_id ?? null, links(sql)[e.id], 'list and export agree with the table');
  }
  const settled = rows(sql);
  await prune(env, now);
  assert.ok(util.isDeepStrictEqual(rows(sql), settled), 'a second prune changes nothing');
  sql.close();
});

test('cleanup_batch_failure_rolls_back_links_and_deletes', async () => {
  const {sql, adapter} = database(failingTripDelete), env = {DB: adapter}, now = Date.parse('2026-11-04T12:00:00Z');
  addTrip(sql, 'trip-a', 'alice', '2026-11-05'); addTrip(sql, 'old', 'alice', '2026-07-01');
  const live = await post(env, 'alice', {...FISH, trip_id: 'trip-a'}), old = await post(env, 'alice', {...BLANK, trip_id: 'old'});
  addEvent(sql, 'ev-a', 'trip-a', 'alice'); addEvent(sql, 'ev-old', 'old', 'alice', '2026-07-01T00:00:00.000Z');
  const before = rows(sql), state = () => [ids(sql, 'trips'), ids(sql, 'alert_events'), ids(sql, 'delivery_receipts')];
  const start = state();
  const r = await delTrip(env, 'alice', 'trip-a');
  assert.ok(r.status >= 500, 'an error status, never success: ' + r.status);
  assert.ok(util.isDeepStrictEqual(rows(sql), before), 'the link update rolled back with the failed delete');
  assert.deepEqual(state(), start, 'trip, event and receipt all survive together');
  assert.equal(links(sql)[live.data.id], 'trip-a');
  await assert.rejects(prune(env, now), /late failure/);
  assert.ok(util.isDeepStrictEqual(rows(sql), before), 'the prune link update rolled back too');
  assert.deepEqual(state(), start);
  assert.equal(links(sql)[old.data.id], 'old');
  sql.close();
});

test('private_cleanup_does_not_publish_catch_data', async () => {
  // The allowlist test above admits exactly the two private cleanup modules; each holds one catch_log statement, the detachment.
  for (const p of ['server/routes/trips.ts', 'server/trips.ts']) {
    const text = readFileSync(new URL('../' + p, import.meta.url), 'utf8');
    assert.equal((text.match(/catch_log/g) || []).length, p === 'server/trips.ts' ? 3 : 1, p);
    assert.ok(/UPDATE catch_log SET trip_id=NULL WHERE/.test(text), p);
  }
  const {sql, adapter} = database(), original = globalThis.fetch, env = {DB: adapter, FEEDS: {get: async () => null, head: async () => null, list: async () => ({objects: []})}, ASSETS: {fetch: async () => new Response('<!doctype html><title>shell</title>', {headers: {'Content-Type': 'text/html'}})}};
  addTrip(sql, 'trip-a', 'alice', '2026-11-05');
  await post(env, 'alice', {...FISH, trip_id: 'trip-a'});
  await delTrip(env, 'alice', 'trip-a'); await prune(env, Date.parse('2026-11-04T12:00:00Z'));
  globalThis.fetch = async () => { throw new Error('offline'); };
  try {
    for (const path of ['/', '/map', '/privacy', '/api/daily', '/feeds/daily.json', '/api/session']) {
      const text = await (await call(env, path)).text();
      for (const s of ['LOGNOTE-private', 'lingcod', '35.123456789', '-120.987654321', 'catch_log']) assert.ok(!text.includes(s), `${path} must not contain ${s}`);
    }
  } finally { globalThis.fetch = original; }
  sql.close();
});

// SC0022-06: an entry can name one of the person's saved trips (optional trip_id, checked by the route as the caller's own).
const TRIP_ROW = (id, date, point = 'north', region = 'morro-bay') => ({id, region, point, date});
const ACTIVE_REGION = {id: 'morro-bay', forecast_points: [{id: 'north', name: 'Point Estero'}, {id: 'south', name: 'Cayucos'}]};

test('log_body_trip_is_optional_and_exact', () => {
  for (const none of [undefined, null, '']) assert.ok(!('trip_id' in logBody({outcome: 'blank', trip_id: none})), `trip_id ${JSON.stringify(none)} is omitted`);
  assert.ok(!('trip_id' in logBody({outcome: 'blank'})), 'no field at all is omitted');
  for (const outcome of ['fish', 'blank', 'unknown']) assert.equal(logBody({outcome, count: '2', trip_id: 'trip-A b/1'}).trip_id, 'trip-A b/1', `${outcome}: the chosen id survives unchanged`);
  assert.equal(logBody({outcome: 'blank', trip_id: ' padded '}).trip_id, ' padded ', 'an id is never trimmed or repaired');
  const blank = logBody({outcome: 'blank', count: '7', lat: '', lon: '', trip_id: 't1'}), fish = logBody({outcome: 'fish', count: '4', lat: '35.5', lon: '-121', trip_id: 't1'});
  assert.deepEqual([blank.count, blank.lat, blank.lon, fish.count, fish.lat, fish.lon], [undefined, null, null, 4, 35.5, -121], 'count and position rules are unchanged');
});

test('log_trip_options_are_own_saved_rows_and_escape_markup', () => {
  const was = process.env.TZ; process.env.TZ = 'America/Los_Angeles';
  try {
    assert.equal(logTripLabel(TRIP_ROW('a', '2026-11-05'), ACTIVE_REGION), '2026-11-05 · Point Estero', 'the stored date as written, never shifted to the evening before');
    assert.equal(logTripLabel(TRIP_ROW('a', '2026-01-01', 'gone'), ACTIVE_REGION), '2026-01-01 · morro-bay / gone', 'unknown point of the active region');
    assert.equal(logTripLabel(TRIP_ROW('a', '2026-01-01', 'north', 'central'), ACTIVE_REGION), '2026-01-01 · central / north', "another region's point id is not renamed from this region");
    assert.equal(logTripLabel(TRIP_ROW('a', '2026-01-01'), null), '2026-01-01 · morro-bay / north', 'no region metadata falls back to the raw names');
    const trips = [TRIP_ROW('past', '2025-06-30'), TRIP_ROW('same-1', '2026-11-05', 'south'), TRIP_ROW('same-2', '2026-11-05', 'south'), TRIP_ROW('future', '2027-03-01')];
    const html = logTripOptionsHTML(trips, ACTIVE_REGION);
    assert.deepEqual([...html.matchAll(/value="([^"]*)"/g)].map(m => m[1]), ['past', 'same-1', 'same-2', 'future'], 'all rows, API order, duplicate dates stay distinct ids');
    assert.ok(html.includes('2025-06-30 · Point Estero') && html.includes('2027-03-01 · Point Estero') && html.includes('2026-11-05 · Cayucos'), html);
    const nasty = logTripOptionsHTML([{id: '"><script>x</script>', region: 'morro-bay', point: '<b>p</b>', date: '<i>d</i>'}], ACTIVE_REGION);
    assert.ok(!/<script|<b>|<i>/.test(nasty) && nasty.includes('&lt;i&gt;d&lt;/i&gt; · morro-bay / &lt;b&gt;p&lt;/b&gt;') && nasty.includes('value="&quot;&gt;&lt;script&gt;'), nasty);
    assert.equal(logTripOptionsHTML([], ACTIVE_REGION), '', 'no trips: nothing after the form\'s own No trip');
    assert.equal(logTripOptionsHTML(undefined, ACTIVE_REGION), '');
  } finally { if (was === undefined) delete process.env.TZ; else process.env.TZ = was; }
});

test('log_item_trip_date_requires_exact_saved_id', () => {
  const entry = {id: 'e1', outcome: 'blank', started_at: BLANK.started_at, count: 0, note: '<b>n</b>'}, trips = [TRIP_ROW('t1', '2026-11-05'), TRIP_ROW('t2', '2026-12-25')];
  assert.ok(logItemHTML({...entry, trip_id: 't1'}, trips).includes('Trip: 2026-11-05'), 'the matched trip date is shown');
  assert.ok(logItemHTML({...entry, trip_id: 't1'}, trips).includes('Blank: no fish'), "the entry's own started date and outcome stay");
  for (const [label, row, list] of [['null', {...entry, trip_id: null}, trips], ['orphan', {...entry, trip_id: 'deleted'}, trips], ['near-miss', {...entry, trip_id: 'T1'}, trips], ['no trips read', {...entry, trip_id: 't1'}, []], ['bad list', {...entry, trip_id: 't1'}, null]]) {
    const html = logItemHTML(row, list);
    assert.ok(!html.includes('Trip:') && html.includes('data-remove-log="e1"'), `${label}: no date, entry and Remove stay`);
  }
  const legacy = logItemHTML({...entry, trip_id: 't1'});
  assert.ok(!legacy.includes('Trip:') && legacy.includes('&lt;b&gt;n&lt;/b&gt;') && !legacy.includes('<b>'), 'one argument still works, note still escaped');
  assert.ok(logItemHTML({...entry, trip_id: 'x'}, [{id: 'x', date: '<u>9</u>'}]).includes('Trip: &lt;u&gt;9&lt;/u&gt;'), 'the added date is escaped');
});

test('deleted_trip_is_refused_without_new_log', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  const trip = (id, owner) => sql.prepare("INSERT INTO trips(id,owner,region,point,species,date,start_hour,end_hour,wind_limit,gust_limit,sea_limit,created_at) VALUES(?,?,'morro-bay','north','reef','2026-11-05',7,13,8,12,3,'x')").run(id, owner);
  trip('mine', 'alice'); trip('theirs', 'bob');
  assert.equal((await post(env, 'alice', {...BLANK, trip_id: 'mine'})).status, 201, 'own trip accepted');
  assert.equal(sql.prepare('SELECT trip_id FROM catch_log WHERE owner=?').get('alice').trip_id, 'mine');
  assert.equal((await post(env, 'alice', BLANK)).status, 201, 'no trip behaves as before');
  sql.prepare('DELETE FROM trips WHERE id=?').run('mine');
  const before = logCount(sql, 'alice'), stale = await post(env, 'alice', {...BLANK, trip_id: 'mine'});
  assert.deepEqual([stale.status, stale.data.error], [404, 'Not found'], 'the route\'s own message');
  assert.equal(logCount(sql, 'alice'), before, 'nothing was written');
  const foreign = await post(env, 'alice', {...BLANK, trip_id: 'theirs'});
  assert.deepEqual([foreign.status, foreign.data.error], [404, 'Not found'], 'another account\'s trip answers the same');
  assert.equal(logCount(sql, 'alice'), before);
  sql.close();
});

// RF0920-1: the written calendar day must exist and the written hour must be 00-23; nothing is rolled into another day.
const TIME_ERROR = name => `${name} must be an ISO date and time with a zone`;
// Runs `fn` with the network blocked and the database closed even when an assertion fails.
async function withLog(fn, wrap) {
  const {sql, adapter} = database(wrap), original = globalThis.fetch;
  globalThis.fetch = async () => { throw new Error('offline'); };
  try { await fn(sql, {DB: adapter}); } finally { globalThis.fetch = original; sql.close(); }
}
// The write route allows 30 calls a minute per account, so each refusal in a long matrix is sent as its own account.
let refusals = 0;
const totalRows = sql => sql.prepare('SELECT COUNT(*) AS n FROM catch_log').get().n;
const refuseField = async (env, field, value) => {
  const entry = field === 'started_at' ? {...BLANK, started_at: value} : {...BLANK, ended_at: value};
  const r = await post(env, 'refused-' + refusals++, entry);
  assert.deepEqual([r.status, r.data.error], [400, TIME_ERROR(field)], `${field} ${value}`);
};

test('catch_log_refuses_impossible_written_dates', async () => withLog(async (sql, env) => {
  const impossible = ['2026-02-29', '2026-02-30', '2026-04-31', '2100-02-29', '2026-06-31', '2026-11-31', '2026-01-32', '2026-00-10', '2026-13-01', '2026-01-00'];
  for (const day of impossible) for (const zone of ['Z', '+05:00', '-07:00']) for (const field of ['started_at', 'ended_at']) await refuseField(env, field, `${day}T14:00:00${zone}`);
  assert.equal(totalRows(sql), 0, 'no row saved');
}));

test('catch_log_refuses_normalized_midnight', async () => withLog(async (sql, env) => {
  for (const t of ['24:00', '24:00:00', '24:00:00.0', '24:00:00.000', '24:00:00.00']) for (const zone of ['Z', '+02:00', '-08:00']) for (const field of ['started_at', 'ended_at']) await refuseField(env, field, `2026-11-01T${t}${zone}`);
  assert.equal(totalRows(sql), 0, 'no row saved');
  for (const t of ['23:59', '23:59:59', '00:00', '00:00:00.000']) assert.equal((await post(env, 'alice', {...BLANK, started_at: `2026-11-01T${t}Z`})).status, 201, t);
  assert.equal(logCount(sql, 'alice'), 4, 'the valid hours are stored');
}));

test('catch_log_preserves_real_zoned_calendar_times', async () => withLog(async (sql, env) => {
  const cases = [['2028-02-29T12:00:00Z', '2028-02-29T12:00:00.000Z'], ['2000-02-29T00:00:00Z', '2000-02-29T00:00:00.000Z'], ['2026-02-28T23:59:59Z', '2026-02-28T23:59:59.000Z'],
    ['0096-02-29T12:00:00Z', '0096-02-29T12:00:00.000Z'], ['2026-12-31T23:59:59-08:00', '2027-01-01T07:59:59.000Z'], ['2026-01-01T00:00:00+05:30', '2025-12-31T18:30:00.000Z'],
    ['2026-03-01T00:00:00+05:30', '2026-02-28T18:30:00.000Z'], ['2026-02-28T22:00:00-05:00', '2026-03-01T03:00:00.000Z'], ['2026-11-01T14:00Z', '2026-11-01T14:00:00.000Z'],
    ['2026-11-01T14:00:00.1Z', '2026-11-01T14:00:00.100Z'], ['2026-11-01T14:00:00.12Z', '2026-11-01T14:00:00.120Z'], ['2026-11-01T14:00:00.123Z', '2026-11-01T14:00:00.123Z'], ['2026-04-30T09:00:00+00:00', '2026-04-30T09:00:00.000Z']];
  for (const [input, stored] of cases) {
    const r = await post(env, 'alice', {...BLANK, started_at: input, ended_at: '2100-01-01T00:00:00Z'});
    assert.equal(r.status, 201, input);
    assert.equal(r.data.started_at, stored, input);
    assert.equal(sql.prepare('SELECT started_at FROM catch_log WHERE id=?').get(r.data.id).started_at, stored, `${input} stored`);
  }
  const end = await post(env, 'alice', {...BLANK, started_at: '2026-02-27T00:00:00Z', ended_at: '2028-02-29T23:00:00-01:00'});
  assert.deepEqual([end.status, end.data.ended_at], [201, '2028-03-01T00:00:00.000Z'], 'an end time converts the same way');
}));

test('catch_log_invalid_time_has_no_write_or_trip_lookup', async () => {
  const calls = [];
  await withLog(async (sql, env) => {
    addTrip(sql, 'trip-a', 'alice', '2026-11-05');
    for (const bad of [{started_at: '2026-02-30T14:00:00Z'}, {started_at: '2026-11-01T24:00:00Z'}, {ended_at: '2026-04-31T14:00:00-07:00'}, {ended_at: '2026-11-02T24:00:00Z'}]) {
      calls.length = 0;
      const r = await post(env, 'alice', {...FISH, trip_id: 'trip-a', ...bad});
      assert.equal(r.status, 400, JSON.stringify(bad));
      assert.equal(r.data.error, TIME_ERROR(Object.keys(bad)[0]), 'an invalid optional end is refused, not discarded');
      assert.deepEqual(calls.filter(q => /FROM trips|INTO catch_log/.test(q)), [], 'no trip lookup and no log insert after validation fails');
      assert.equal(logCount(sql, 'alice'), 0);
    }
    calls.length = 0;
    assert.equal((await post(env, 'alice', {...FISH, trip_id: 'trip-a'})).status, 201, 'a valid request in the same fixture stores once');
    assert.equal(logCount(sql, 'alice'), 1);
    assert.ok(calls.some(q => /FROM trips/.test(q)) && calls.some(q => /INSERT INTO catch_log/.test(q)));
    const anon = await call(env, '/api/catch-log', {method: 'POST', body: {...FISH, started_at: '2026-02-30T14:00:00Z'}});
    assert.equal(anon.status, 401, 'anonymous stays 401');
  }, a => ({...a, prepare(q) { calls.push(q); return a.prepare(q); }, batch: a.batch}));
});

test('catch_log_orders_valid_instants_after_offset_conversion', async () => withLog(async (sql, env) => {
  const same = await post(env, 'alice', {...BLANK, started_at: '2026-11-01T14:00:00Z', ended_at: '2026-11-01T07:00:00-07:00'});
  assert.deepEqual([same.status, same.data.started_at, same.data.ended_at], [201, '2026-11-01T14:00:00.000Z', '2026-11-01T14:00:00.000Z'], 'equal instants in different offsets are accepted');
  const reversed = await post(env, 'alice', {...BLANK, started_at: '2026-11-01T14:00:00Z', ended_at: '2026-11-01T06:59:00-07:00'});
  assert.deepEqual([reversed.status, reversed.data.error], [400, 'ended_at is before started_at'], 'a real reversed interval keeps its own message');
  for (const absent of [{}, {ended_at: null}]) assert.equal((await post(env, 'alice', {...BLANK, ...absent})).status, 201, 'optional end absent or null');
  for (const absent of [{started_at: undefined}, {started_at: null}]) {
    const r = await post(env, 'alice', {...BLANK, ...absent});
    assert.deepEqual([r.status, r.data.error], [400, 'started_at is required']);
  }
  assert.equal(logCount(sql, 'alice'), 3, 'only the accepted entries were stored');
}));
