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
const {logItemHTML, logBody, logTripLabel, logTripOptionsHTML, readLogPage} = await import('../dist/account.js');
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
  for (const [method, path] of [['POST', '/api/catch-log'], ['PATCH', '/api/catch-log/x'], ['DELETE', '/api/catch-log/x'], ['GET', '/api/catch-log']]) {
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

// SC0922-03: every stored entry stays reachable by its owner, a page at a time.
const HAS_MORE = 'X-SC-Catch-Log-Has-More', NEXT = 'X-SC-Catch-Log-Next-Cursor', PAGE = 200;
const cursorOf = (started_at, id) => Buffer.from(JSON.stringify([1, started_at, id])).toString('base64url');
const stamp = i => new Date(Date.UTC(2026, 0, 1) + i * 60000).toISOString();
/** Insert rows straight into the table: `rows` are [id, owner, started_at]; POST is rate-limited and is not what is under test. */
function seed(sql, rows) {
  const insert = sql.prepare("INSERT INTO catch_log(id,owner,started_at,outcome,count,note,created_at) VALUES(?,?,?,'blank',0,?,'x')");
  sql.exec('BEGIN'); for (const [id, owner, at] of rows) insert.run(id, owner, at, 'NOTE-' + owner); sql.exec('COMMIT');
}
/** Walk the pages with the headers' own cursors; returns every page as {ids, more, next}. */
async function walk(env, owner) {
  const pages = []; let cursor = null;
  for (let guard = 0; guard < 20; guard++) {
    const r = await call(env, '/api/catch-log' + (cursor ? '?cursor=' + encodeURIComponent(cursor) : ''), {owner});
    assert.equal(r.status, 200);
    const data = await r.json();
    assert.deepEqual(Object.keys(data), ['entries'], 'the body shape never changes');
    pages.push({ids: data.entries.map(e => e.id), more: r.headers.get(HAS_MORE), next: r.headers.get(NEXT), owners: new Set(data.entries.map(e => e.owner))});
    cursor = r.headers.get(NEXT); if (!cursor) return pages;
  }
  throw new Error('pages never ended');
}

test('all_rows_reachable_0_200_201_450', async () => {
  for (const [total, sizes] of [[0, [0]], [200, [200]], [201, [200, 1]], [450, [200, 200, 50]]]) {
    const {sql, adapter} = database(), env = {DB: adapter};
    // Alice's rows are numbered newest = highest; bob's rows are interleaved with the same timestamps and sort among hers.
    const mine = Array.from({length: total}, (_, i) => [`a${String(i).padStart(4, '0')}`, 'alice', stamp(i)]);
    seed(sql, [...mine, ...mine.map(([id, , at]) => ['b' + id, 'bob', at]), ['bob-newest', 'bob', stamp(9999)]]);
    const pages = await walk(env, 'alice');
    assert.deepEqual(pages.map(p => p.ids.length), sizes, `page sizes for ${total}`);
    assert.deepEqual(pages.map(p => p.more), sizes.map((_, i) => String(i < sizes.length - 1)), 'has-more says false only on the last page');
    assert.deepEqual(pages.map(p => p.next !== null), sizes.map((_, i) => i < sizes.length - 1), 'a next cursor only while more exist');
    const all = pages.flatMap(p => p.ids);
    assert.deepEqual(all, [...mine].sort((a, b) => (a[2] < b[2] ? 1 : a[2] > b[2] ? -1 : a[0] < b[0] ? -1 : 1)).map(r => r[0]), 'every id once, in the route order');
    assert.equal(new Set(all).size, total);
    assert.ok(pages.every(p => [...p.owners].every(o => o === 'alice')), "another owner's rows never appear");
    // No cursor: exactly today's first page.
    const first = await call(env, '/api/catch-log', {owner: 'alice'});
    assert.deepEqual((await first.json()).entries.map(e => e.id), pages[0].ids);
    assert.equal(first.headers.get('Cache-Control'), 'no-store');
    assert.equal(first.headers.get('X-Content-Type-Options'), 'nosniff');
    sql.close();
  }
  assert.equal(PAGE, 200);
});

test('same_timestamp_uses_ascending_id_and_deleted_anchor', async () => {
  const {sql, adapter} = database(), env = {DB: adapter}, at = '2026-06-01T10:00:00.000Z';
  seed(sql, Array.from({length: 450}, (_, i) => [`t${String(449 - i).padStart(3, '0')}`, 'alice', at]));   // inserted in reverse id order
  const ids = Array.from({length: 450}, (_, i) => `t${String(i).padStart(3, '0')}`);
  const one = await call(env, '/api/catch-log', {owner: 'alice'}), first = (await one.json()).entries.map(e => e.id);
  assert.deepEqual(first, ids.slice(0, 200), 'ties break by ascending id');
  assert.equal(one.headers.get(NEXT), cursorOf(at, 't199'), 'the cursor names the last returned row, never the lookahead');
  // The anchor row is deleted, a row dated later and a row dated earlier are added, between the two requests.
  assert.equal((await call(env, '/api/catch-log/t199', {owner: 'alice', method: 'DELETE', body: {}})).status, 200);
  seed(sql, [['newer', 'alice', '2026-06-02T00:00:00.000Z'], ['older', 'alice', '2026-05-01T00:00:00.000Z']]);
  const two = await call(env, '/api/catch-log?cursor=' + one.headers.get(NEXT), {owner: 'alice'}), second = (await two.json()).entries.map(e => e.id);
  assert.deepEqual(second.slice(0, 200), ids.slice(200, 400), 'no skip or repeat across the deleted anchor');
  assert.ok(!second.includes('newer'), 'a newer row appears on a first-page refresh, not on an older page');
  assert.equal(two.headers.get(HAS_MORE), 'true');
  const third = await call(env, '/api/catch-log?cursor=' + two.headers.get(NEXT), {owner: 'alice'});
  assert.deepEqual((await third.json()).entries.map(e => e.id), [...ids.slice(400), 'older'], 'a row dated earlier than the cursor is reached');
  assert.equal(third.headers.get(HAS_MORE), 'false');
  assert.equal(third.headers.get(NEXT), null);
  sql.close();
});

test('invalid_cursor_400_before_query', async () => {
  const listed = [], {sql, adapter} = database(a => ({...a, prepare(q) { if (/catch_log/.test(q)) listed.push(q); return a.prepare(q); }, batch: a.batch})), env = {DB: adapter};
  const b64 = v => Buffer.from(typeof v === 'string' ? v : JSON.stringify(v)).toString('base64url');
  const good = b64([1, '2026-06-01T10:00:00.000Z', 'row-1']);
  const cases = {
    empty: '?cursor=', duplicate: `?cursor=${good}&cursor=${good}`, oversize: '?cursor=' + 'A'.repeat(513), padded: '?cursor=' + good + '=',
    alphabet: '?cursor=' + good + '!', plus: '?cursor=ab%2Bcd%2Fef',
    truncated: '?cursor=' + good.slice(0, 7), notUtf8: '?cursor=' + Buffer.from([0xff, 0xfe, 0x5b]).toString('base64url'), notJson: '?cursor=' + b64('not json'),
    object: '?cursor=' + b64({a: 1}), tooShort: '?cursor=' + b64([1, '2026-06-01T10:00:00.000Z']), tooLong: '?cursor=' + b64([1, '2026-06-01T10:00:00.000Z', 'x', 'y']),
    version: '?cursor=' + b64([2, '2026-06-01T10:00:00.000Z', 'row-1']), versionText: '?cursor=' + b64(['1', '2026-06-01T10:00:00.000Z', 'row-1']),
    numberTime: '?cursor=' + b64([1, 5, 'row-1']), numberId: '?cursor=' + b64([1, '2026-06-01T10:00:00.000Z', 7]),
    notADate: '?cursor=' + b64([1, '2026-13-45T10:00:00.000Z', 'row-1']), noMillis: '?cursor=' + b64([1, '2026-06-01T10:00:00Z', 'row-1']),
    zoned: '?cursor=' + b64([1, '2026-06-01T10:00:00.000+00:00', 'row-1']), emptyId: '?cursor=' + b64([1, '2026-06-01T10:00:00.000Z', '']),
    longId: '?cursor=' + b64([1, '2026-06-01T10:00:00.000Z', 'x'.repeat(65)]), controlId: '?cursor=' + b64([1, '2026-06-01T10:00:00.000Z', 'a\nb']),
  };
  const bodies = new Set();
  for (const [name, query] of Object.entries(cases)) {
    const r = await call(env, '/api/catch-log' + query, {owner: 'alice'}), text = await r.text();
    assert.equal(r.status, 400, name);
    const {request_id, ...rest} = JSON.parse(text); bodies.add(JSON.stringify(rest));
    assert.equal(r.headers.get(HAS_MORE), null, name);
    const token = query.slice('?cursor='.length);
    if (token.length > 8) assert.ok(!text.includes(token) && !text.includes('row-1'), `${name}: the answer never echoes the cursor`);
  }
  assert.deepEqual([...bodies], ['{"error":"invalid catch-log cursor"}'], 'one stable error for every refusal');
  assert.deepEqual(listed.filter(q => /SELECT \* FROM catch_log/.test(q)), [], 'refused before the list query is prepared');
  assert.equal((await call(env, '/api/catch-log?cursor=' + good, {owner: 'alice'})).status, 200, 'a well-formed cursor is accepted');
  sql.close();
});

test('cursor_is_not_an_owner_capability', async () => {
  const calls = [], {sql, adapter} = database(a => ({...a, prepare(q) { calls.push(q); return a.prepare(q); }, batch: a.batch})), env = {DB: adapter};
  seed(sql, [...Array.from({length: 5}, (_, i) => [`a${i}`, 'alice', stamp(10 + i)]), ...Array.from({length: 5}, (_, i) => [`b${i}`, 'bob', stamp(10 + i)])]);
  const alices = cursorOf(stamp(12), 'a2'), anyBobs = cursorOf(stamp(12), 'b2');
  for (const cursor of [alices, cursorOf(stamp(12), 'bob-only-anchor'), cursorOf(stamp(12), 'b2')]) {
    const r = await call(env, '/api/catch-log?cursor=' + cursor, {owner: 'bob'});
    assert.equal(r.status, 200);
    assert.ok((await r.json()).entries.every(e => e.owner === 'bob'), "bob never sees alice's rows through a cursor");
  }
  const forAlice = (await (await call(env, '/api/catch-log?cursor=' + anyBobs, {owner: 'alice'})).json()).entries;
  assert.deepEqual(forAlice.map(e => e.id), ['a1', 'a0'], "bob's anchor only positions alice's own list");
  const nobody = await call(env, '/api/catch-log?cursor=' + alices, {owner: 'carol'});
  assert.deepEqual([nobody.status, (await nobody.json()).entries, nobody.headers.get(HAS_MORE)], [200, [], 'false']);
  assert.equal((await call(env, '/api/catch-log/a1', {owner: 'bob'})).status, 404, 'a foreign id stays not found');
  assert.equal((await call(env, '/api/catch-log/a1', {owner: 'bob', method: 'DELETE', body: {}})).status, 404);
  assert.equal(logCount(sql, 'alice'), 5);
  calls.length = 0;
  const out = await call(env, '/api/catch-log?cursor=' + alices);
  assert.equal(out.status, 401, 'signed out, with a cursor');
  assert.deepEqual(calls, [], 'refused before any D1 call');
  sql.close();
});

test('an_older_entry_is_deleted_like_any_other_and_pages_adjust', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  seed(sql, Array.from({length: 201}, (_, i) => [`e${String(i).padStart(3, '0')}`, 'alice', stamp(1000 - i)]));
  const first = await call(env, '/api/catch-log', {owner: 'alice'}); await first.json();
  const older = await (await call(env, '/api/catch-log?cursor=' + first.headers.get(NEXT), {owner: 'alice'})).json();
  assert.deepEqual(older.entries.map(e => e.id), ['e200']);
  assert.equal((await call(env, '/api/catch-log/e200', {owner: 'alice', method: 'DELETE', body: {}})).status, 200);
  const after = await call(env, '/api/catch-log?cursor=' + first.headers.get(NEXT), {owner: 'alice'});
  assert.deepEqual([after.status, (await after.json()).entries, after.headers.get(HAS_MORE)], [200, [], 'false'], 'the old cursor still works with its rows gone');
  sql.close();
});

test('read_log_page_reads_headers_and_refuses_incomplete_answers', async () => {
  const original = globalThis.fetch, urls = [];
  const answer = (body, headers) => async url => { urls.push(String(url)); return new Response(JSON.stringify(body), {status: 200, headers: {'Content-Type': 'application/json', ...headers}}); };
  try {
    globalThis.fetch = answer({entries: [{id: 'a'}]}, {[HAS_MORE]: 'true', [NEXT]: 'tok/+='});
    assert.deepEqual(await readLogPage(), {entries: [{id: 'a'}], nextCursor: 'tok/+=', hasMore: true});
    assert.deepEqual(await readLogPage('tok/+='), {entries: [{id: 'a'}], nextCursor: 'tok/+=', hasMore: true});
    assert.deepEqual(urls, ['/api/catch-log', '/api/catch-log?cursor=tok%2F%2B%3D'], 'the cursor is only a query value');
    globalThis.fetch = answer({entries: []}, {[HAS_MORE]: 'false'});
    assert.deepEqual(await readLogPage(), {entries: [], nextCursor: null, hasMore: false});
    for (const [name, body, headers] of [['no headers', {entries: []}, {}], ['more without a cursor', {entries: []}, {[HAS_MORE]: 'true'}], ['cursor without more', {entries: []}, {[HAS_MORE]: 'false', [NEXT]: 'x'}],
      ['odd flag', {entries: []}, {[HAS_MORE]: 'yes'}], ['entries not a list', {entries: {}}, {[HAS_MORE]: 'false'}], ['no entries', {}, {[HAS_MORE]: 'false'}]]) {
      globalThis.fetch = answer(body, headers);
      await assert.rejects(readLogPage(), /incomplete/, name);
    }
    globalThis.fetch = async () => new Response(JSON.stringify({error: 'Not found'}), {status: 404});
    await assert.rejects(readLogPage(), e => e.status === 404, 'a refused read keeps its status');
  } finally { globalThis.fetch = original; }
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

// SC1137-10: PATCH /api/catch-log/:id merges the named fields, validates the whole entry, and stays owner-only.
const patch = async (env, owner, id, bodyOrRaw, extra = {}) => {
  const r = await call(env, '/api/catch-log/' + id, typeof bodyOrRaw === 'string' ? {owner, method: 'PATCH', raw: bodyOrRaw, ...extra} : {owner, method: 'PATCH', body: bodyOrRaw, ...extra});
  return {status: r.status, data: await r.json()};
};
const rowOf = (sql, id) => ({...sql.prepare('SELECT * FROM catch_log WHERE id=?').get(id)});

test('patch_each_mutable_field_preserves_identity', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  addTrip(sql, 'trip-a', 'alice', '2026-11-05'); addTrip(sql, 'trip-b', 'alice', '2026-11-05');
  const made = (await post(env, 'alice', {...FISH, trip_id: 'trip-a'})).data, before = rowOf(sql, made.id);
  const changes = [{trip_id: 'trip-b'}, {ended_at: '2026-11-02T01:00:00Z'}, {started_at: '2026-11-01T15:00:00-08:00'}, {method: 'troll'}, {species: 'halibut'}, {count: 7}, {lat: 36.5, lon: -122.25}, {note: '  keep my spaces 🎣 '}, {outcome: 'blank', count: 0}];
  for (const change of changes) {
    const r = await patch(env, 'alice', made.id, change), now = rowOf(sql, made.id);
    assert.equal(r.status, 200, JSON.stringify(change));
    assert.deepEqual(r.data, now, 'the response is the stored row');
    for (const k of ['id', 'owner', 'created_at']) assert.equal(now[k], before[k], k);
    const expected = {...before, ...change}; for (const k of ['started_at', 'ended_at']) if (change[k]) expected[k] = new Date(change[k]).toISOString();
    for (const k of Object.keys(change)) assert.equal(now[k], expected[k], `${k} after ${JSON.stringify(change)}`);
    Object.assign(before, now);
    assert.deepEqual(await (await call(env, '/api/catch-log/' + made.id, {owner: 'alice'})).json(), now, 'GET id agrees');
  }
  assert.equal(before.note, '  keep my spaces 🎣 ', 'nonblank text keeps its original bytes');
  const same = await patch(env, 'alice', made.id, {});
  assert.deepEqual([same.status, same.data], [200, rowOf(sql, made.id)], 'an empty object is a validated no-op');
  const together = await patch(env, 'alice', made.id, {trip_id: 'trip-a', started_at: '2026-11-03T10:00:00Z', ended_at: '2026-11-03T12:00:00Z', method: 'jig', species: 'rockfish', outcome: 'fish', count: 2, lat: 35.1, lon: -120.9, note: 'all at once'});
  assert.equal(together.status, 200);
  assert.deepEqual((await (await call(env, '/api/privacy', {owner: 'alice'})).json()).catch_log, [rowOf(sql, made.id)], 'the export reads the updated row');
  assert.equal(logCount(sql, 'alice'), 1, 'no replacement row');
  sql.close();
});

test('patch_fish_blank_unknown_count_transitions', async () => {
  const {sql, adapter} = database(), env = {DB: adapter}, made = (await post(env, 'alice', FISH)).data;
  const refused = async change => { const was = rowOf(sql, made.id), r = await patch(env, 'alice', made.id, change); assert.equal(r.status, 400, JSON.stringify(change)); assert.deepEqual(rowOf(sql, made.id), was, 'refusal changes nothing'); };
  await refused({outcome: 'blank'});   // count 3 is never silently repaired
  await refused({outcome: 'unknown'});
  await refused({count: 0}); await refused({count: null});   // a fish keeps a count of at least 1
  for (const count of [1.5, -1, 10000, '4', true]) await refused({count});
  assert.equal((await patch(env, 'alice', made.id, {count: 9999})).status, 200);
  for (const step of [{outcome: 'blank', count: 0}, {outcome: 'unknown', count: null}, {outcome: 'blank'}]) {
    const r = await patch(env, 'alice', made.id, step); assert.equal(r.status, 200, JSON.stringify(step));
    assert.deepEqual([r.data.outcome, r.data.count], [step.outcome, 0]);
  }
  await refused({count: 2}); await refused({outcome: 'fish'}); await refused({outcome: 'fish', count: 0}); await refused({outcome: 'caught'}); await refused({outcome: null});
  const back = await patch(env, 'alice', made.id, {outcome: 'fish', count: 1});
  assert.deepEqual([back.status, back.data.outcome, back.data.count], [200, 'fish', 1]);
  sql.close();
});

test('patch_clear_optional_fields_and_position_pair', async () => {
  const {sql, adapter} = database(), env = {DB: adapter}, made = (await post(env, 'alice', FISH)).data;
  addTrip(sql, 'trip-a', 'alice', '2026-11-05');
  assert.equal((await patch(env, 'alice', made.id, {trip_id: 'trip-a'})).status, 200);
  const cleared = await patch(env, 'alice', made.id, {method: null, species: '   ', note: '', trip_id: null, ended_at: null});
  assert.deepEqual([cleared.status, cleared.data.method, cleared.data.species, cleared.data.note, cleared.data.trip_id, cleared.data.ended_at], [200, null, null, null, null, null]);
  assert.equal(cleared.data.lat, FISH.lat, 'untouched position kept at full precision');
  assert.equal((await patch(env, 'alice', made.id, {ended_at: ''})).status, 400, 'an empty end time is not a clear');
  assert.equal((await patch(env, 'alice', made.id, {started_at: null})).status, 400, 'started_at cannot be cleared');
  const limits = await patch(env, 'alice', made.id, {method: 'm'.repeat(40), species: 's'.repeat(60), note: '🎣'.repeat(1000)});
  assert.equal(limits.status, 200, 'limits are in code points');
  const before = rowOf(sql, made.id);
  for (const change of [{method: 'm'.repeat(41)}, {species: 's'.repeat(61)}, {note: '🎣'.repeat(1001)}, {method: 5}, {trip_id: 't'.repeat(65)}]) assert.equal((await patch(env, 'alice', made.id, change)).status, 400, JSON.stringify(change).slice(0, 40));
  for (const change of [{lat: 40}, {lon: -100}, {lat: 40, lon: null}, {lat: null, lon: -100}, {lat: 90, lon: 0}, {lat: 0, lon: -180}, {lat: '1', lon: 2}, {lat: null}]) {
    const r = await patch(env, 'alice', made.id, change); assert.equal(r.status, 400, JSON.stringify(change));
    assert.match(r.data.error, /^coordinates_/);
  }
  const raw = await call(env, '/api/catch-log/' + made.id, {owner: 'alice', method: 'PATCH', raw: '{"lat":1e999,"lon":1}'});
  assert.equal(raw.status, 400);
  assert.deepEqual(rowOf(sql, made.id), before, 'every refusal left the row byte-identical');
  const pair = await patch(env, 'alice', made.id, {lat: 89.9999, lon: 179.9999});
  assert.deepEqual([pair.status, pair.data.lat, pair.data.lon], [200, 89.9999, 179.9999]);
  const none = await patch(env, 'alice', made.id, {lat: null, lon: null});
  assert.deepEqual([none.status, none.data.lat, none.data.lon], [200, null, null]);
  sql.close();
});

test('patch_revalidates_full_time_and_trip', async () => {
  const {sql, adapter} = database(), env = {DB: adapter}, made = (await post(env, 'alice', FISH)).data;   // 14:00Z to 19:30Z
  addTrip(sql, 'trip-a', 'alice', '2026-11-05'); addTrip(sql, 'trip-bob', 'bob', '2026-11-05');
  const was = rowOf(sql, made.id);
  for (const change of [{started_at: '2026-11-01T19:30:01Z'}, {ended_at: '2026-11-01T13:59:59Z'}, {started_at: '2026-02-30T10:00:00Z'}, {started_at: '2026-11-01T24:00:00Z'}, {ended_at: '2026-11-01T25:00:00Z'}, {started_at: '2026-11-01 14:00'}, {started_at: '2026-11-01T14:00:00'}, {started_at: 5}])
    assert.equal((await patch(env, 'alice', made.id, change)).status, 400, JSON.stringify(change));
  assert.deepEqual(rowOf(sql, made.id), was);
  assert.equal((await patch(env, 'alice', made.id, {ended_at: '2026-11-01T14:00:00Z'})).status, 200, 'equal endpoints pass');
  const moved = await patch(env, 'alice', made.id, {started_at: '2026-11-01T06:00:00-08:00', ended_at: '2026-11-01T07:00:00-08:00'});
  assert.deepEqual([moved.status, moved.data.started_at, moved.data.ended_at], [200, '2026-11-01T14:00:00.000Z', '2026-11-01T15:00:00.000Z'], 'offsets normalize to UTC');
  const before = rowOf(sql, made.id);
  for (const trip_id of ['trip-bob', 'no-such-trip']) {
    const r = await patch(env, 'alice', made.id, {trip_id, count: 9, note: 'would be partial'});
    assert.equal(r.status, 404, trip_id);
    assert.deepEqual(rowOf(sql, made.id), before, 'no partial write');
  }
  const own = await patch(env, 'alice', made.id, {trip_id: 'trip-a'});
  assert.deepEqual([own.status, own.data.trip_id], [200, 'trip-a']);
  const detached = await patch(env, 'alice', made.id, {trip_id: null});
  assert.deepEqual([detached.status, detached.data.trip_id], [200, null]);
  sql.close();
});

test('patch_foreign_missing_and_immutable_keys', async () => {
  const {sql, adapter} = database(), env = {DB: adapter}, mine = (await post(env, 'alice', FISH)).data, bobs = (await post(env, 'bob', BLANK)).data;
  const strip = async r => { const {request_id, ...rest} = r.data; return [r.status, rest]; };
  const was = [rowOf(sql, mine.id), rowOf(sql, bobs.id)];
  const foreign = await patch(env, 'bob', mine.id, {count: 9}), never = await patch(env, 'bob', 'no-such-id', {count: 9});
  assert.equal(foreign.status, 404);
  assert.deepEqual(await strip(foreign), await strip(never), 'identical to an id that never existed');
  for (const raw of ['{not json', '[]', 'null', '"x"', '']) assert.deepEqual(await strip(await patch(env, 'bob', mine.id, raw)), await strip(never), `malformed ${raw} is still 404 on a foreign id`);
  assert.deepEqual([rowOf(sql, mine.id), rowOf(sql, bobs.id)], was, "another owner's row never changes");
  for (const change of [{id: 'x'}, {owner: 'bob'}, {created_at: '2020-01-01T00:00:00.000Z'}, {colour: 'red'}, {count: 4, owner: 'alice'}, JSON.parse('{"__proto__":{"count":4}}')]) {
    const r = await patch(env, 'alice', mine.id, change); assert.equal(r.status, 400, JSON.stringify(change));
  }
  assert.deepEqual(rowOf(sql, mine.id), was[0], 'refused keys changed nothing');
  sql.close();
});

test('patch_body_auth_storage_and_private_readers', async () => {
  const {sql, adapter} = database(), env = {DB: adapter}, made = (await post(env, 'alice', FISH)).data, was = rowOf(sql, made.id);
  for (const raw of ['{bad', '', '[]', 'null', '7', '"s"', '{"note":' + JSON.stringify('x'.repeat(9000)) + '}']) {
    const r = await patch(env, 'alice', made.id, raw); assert.equal(r.status, 400, raw.slice(0, 20));
  }
  assert.equal((await patch(env, 'alice', made.id, {count: 5})).status, 200);
  const headers = {'Content-Type': 'application/json', 'x-test-owner': 'alice', Origin: 'https://evil.example', 'CF-Connecting-IP': '203.0.113.9'};
  const bad = await worker.fetch(new Request(ORIGIN + '/api/catch-log/' + made.id, {method: 'PATCH', headers, body: JSON.stringify({count: 6})}), env);
  assert.equal(bad.status, 400, 'a foreign Origin is refused');
  assert.equal(rowOf(sql, made.id).count, 5);
  Object.assign(was, {count: 5});
  const calls = [], quiet = database(a => ({...a, prepare(q) { calls.push(q); return a.prepare(q); }, batch: a.batch}));
  assert.equal((await call({DB: quiet.adapter}, '/api/catch-log/x', {method: 'PATCH', body: {count: 1}})).status, 401);
  assert.deepEqual(calls, [], 'signed-out: no statement was prepared');
  quiet.sql.close();
  const degradedEnv = {DB: adapter, FEEDS: {get: async () => null, head: async () => null}, COST_CEILING_R2_READS_PER_DAY: '1'};
  resetMeter(); recordReads(5);
  try { const r = await patch(degradedEnv, 'alice', made.id, {count: 8}); assert.equal(r.status, 200, 'a degraded write succeeds'); assert.equal(rowOf(sql, made.id).count, 8); } finally { resetMeter(); }
  const down = database(a => ({...a, prepare(q) { if (/UPDATE catch_log/.test(q)) throw new Error('D1 unavailable'); return a.prepare(q); }}));
  const dm = (await post({DB: down.adapter}, 'alice', FISH)).data, dwas = rowOf(down.sql, dm.id);
  assert.equal((await patch({DB: down.adapter}, 'alice', dm.id, {count: 9})).status, 503, 'unavailable, not success');
  assert.deepEqual(rowOf(down.sql, dm.id), dwas);
  down.sql.close();
  assert.equal((await call(env, '/api/catch-log/' + made.id, {owner: 'alice', method: 'DELETE', body: {}})).status, 200);
  assert.equal((await patch(env, 'alice', made.id, {count: 1})).status, 404, 'a deleted entry is not recreated');
  assert.equal(logCount(sql, 'alice'), 0);
  sql.close();
});

test('patch_reorders_without_changing_cursor_contract', async () => {
  const {sql, adapter} = database(), env = {DB: adapter}, ins = sql.prepare("INSERT INTO catch_log(id,owner,started_at,outcome,count,created_at) VALUES(?,?,?,'blank',0,'x')");
  for (let i = 0; i < 201; i++) ins.run('a' + String(i).padStart(3, '0'), 'alice', new Date(Date.UTC(2026, 0, 1, 0, i)).toISOString());
  ins.run('b000', 'bob', '2026-02-01T00:00:00.000Z');
  const first = await call(env, '/api/catch-log', {owner: 'alice'}), page = await first.json(), cursor = first.headers.get('X-SC-Catch-Log-Next-Cursor');
  assert.deepEqual([page.entries.length, first.headers.get('X-SC-Catch-Log-Has-More'), page.entries[0].id, page.entries[199].id], [200, 'true', 'a200', 'a001']);
  assert.ok(cursor);
  assert.equal((await patch(env, 'alice', 'a000', {started_at: '2026-06-01T00:00:00Z'})).status, 200);
  const fresh = await call(env, '/api/catch-log', {owner: 'alice'}), top = await fresh.json();
  assert.deepEqual([top.entries[0].id, top.entries.length, fresh.headers.get('X-SC-Catch-Log-Has-More')], ['a000', 200, 'true'], 'a fresh read sees the new order and the same header shape');
  const old = await call(env, '/api/catch-log?cursor=' + encodeURIComponent(cursor), {owner: 'alice'});
  assert.equal(old.status, 200, 'an issued cursor still decodes');
  assert.deepEqual((await old.json()).entries.map(e => e.id), [], 'the moved row is not repeated after the old position');
  const theirs = await call(env, '/api/catch-log?cursor=' + encodeURIComponent(cursor), {owner: 'bob'});
  assert.deepEqual((await theirs.json()).entries.map(e => e.id), [], "alice's cursor stays owner-bound: bob's own rows sort before it and none of alice's appear");
  sql.close();
});

// RF1540-2: a PATCH that read an older row is refused with 409 instead of restoring omitted fields over a saved correction.
// The hook returns the outer request's real SELECT result only after a nested real request has committed its own change.
async function stalePatch(seed, nested, outer, {owner = 'alice', afterSnapshot} = {}) {
  let armed = null;
  const {sql, adapter} = database(a => ({...a, prepare(q) {
    const s = a.prepare(q);
    if (!armed || !/^SELECT \* FROM catch_log WHERE id=\? AND owner=\?$/.test(q)) return s;
    const w = {bind(...x) { s.bind(...x); return w; }, async first() { const snap = await s.first(), run = armed; armed = null; await run(); return snap; }};
    return w;
  }, batch: a.batch})), env = {DB: adapter}, made = (await post(env, 'alice', seed)).data;
  let inner;
  armed = async () => { inner = nested ? await patch(env, 'alice', made.id, nested) : await call(env, '/api/catch-log/' + made.id, {owner: 'alice', method: 'DELETE', body: {}}).then(async r => ({status: r.status, data: await r.json()})); };
  const out = await patch(env, owner, made.id, outer);
  return {sql, env, made, inner, out};
}
const CONFLICT = {error: 'This entry changed while you were editing it. Reload it and try again.'};

test('stale_patch_conflicts_and_keeps_the_saved_correction', async () => {
  for (const outer of [{note: 'new note'}, {}]) {
    const {sql, env, made, inner, out} = await stalePatch(FISH, {count: 4}, outer);
    assert.equal(inner.status, 200); assert.equal(inner.data.count, 4);
    assert.deepEqual([out.status, out.data.error], [409, CONFLICT.error], JSON.stringify(outer));
    assert.deepEqual([rowOf(sql, made.id).count, rowOf(sql, made.id).note], [4, FISH.note], 'winner and original note stay');
    assert.deepEqual(await (await call(env, '/api/catch-log/' + made.id, {owner: 'alice'})).json(), rowOf(sql, made.id), 'GET agrees');
    assert.equal((await (await call(env, '/api/privacy', {owner: 'alice'})).json()).catch_log[0].count, 4, 'export agrees');
    assert.equal((await patch(env, 'alice', made.id, outer)).status, 200, 'a fresh edit after rereading works');
    sql.close();
  }
});

test('stale_patch_cannot_combine_into_an_invalid_entry', async () => {
  const a = await stalePatch({...FISH, count: 1}, {outcome: 'blank', count: 0}, {count: 9999});
  assert.equal(a.out.status, 409);
  assert.deepEqual([rowOf(a.sql, a.made.id).outcome, rowOf(a.sql, a.made.id).count], ['blank', 0]);
  a.sql.close();
  const b = await stalePatch(FISH, {started_at: '2026-11-01T14:00:00Z', ended_at: '2026-11-01T15:00:00Z'}, {ended_at: '2026-11-01T18:00:00Z'});
  assert.equal(b.out.status, 409);
  assert.equal(rowOf(b.sql, b.made.id).ended_at, '2026-11-01T15:00:00.000Z');
  b.sql.close();
});

test('stale_patch_compares_null_fields_and_unchanged_rows_still_succeed', async () => {
  const minimal = {started_at: '2026-11-01T14:00:00Z', outcome: 'unknown'};
  const ok = await stalePatch(minimal, {note: 'noted'}, {}); // nested succeeded, so the outer snapshot is stale
  assert.equal(ok.out.status, 409); ok.sql.close();
  const nul = await stalePatch(minimal, {species: 'lingcod'}, {method: 'drift'});
  assert.equal(nul.out.status, 409); assert.equal(rowOf(nul.sql, nul.made.id).method, null); nul.sql.close();
  const { sql, adapter } = database(), env = {DB: adapter}, made = (await post(env, 'alice', minimal)).data;
  assert.equal((await patch(env, 'alice', made.id, {method: 'drift'})).status, 200, 'null optional fields compare equal');
  assert.equal((await patch(env, 'alice', made.id, {})).status, 200, 'unchanged {} is a 200 no-op');
  sql.close();
});

test('stale_patch_after_delete_or_for_another_owner_is_404_and_leaks_nothing', async () => {
  const gone = await stalePatch(FISH, null, {note: 'x'});
  assert.deepEqual([gone.inner.status, gone.out.status, gone.out.data.error], [200, 404, 'Not found']);
  assert.equal(totalRows(gone.sql), 0, 'not recreated'); gone.sql.close();
  const {sql, adapter} = database(), env = {DB: adapter}, made = (await post(env, 'alice', FISH)).data;
  for (const id of [made.id, 'nope']) { const r = await patch(env, 'bob', id, {note: 'x'}); assert.deepEqual([r.status, r.data.error], [404, 'Not found']); }
  assert.equal(rowOf(sql, made.id).note, FISH.note);
  const conflict = await stalePatch(FISH, {count: 5}, {note: 'SECRET-submitted'});
  assert.ok(!JSON.stringify(conflict.out.data).includes('SECRET') && !JSON.stringify(conflict.out.data).includes('LOGNOTE'), 'no row or submitted data in 409');
  sql.close(); conflict.sql.close();
});

// SC1137-11: the account panel's edit form. logEditBody sends every mutable field so a cleared box really clears.
const {logEditBody, localInputValue, sortLogEntries, createCopy} = await import('../dist/account.js');
const FORM = {started: '', ended: '', outcome: 'fish', count: '3', species: 'lingcod', method: 'drift', trip: 'trip-a', lat: '35.5', lon: '-120.5', note: 'n'};
const STORED = {started_at: '2026-11-01T14:00:00.123Z', ended_at: '2026-11-01T19:30:00.000Z', lat: 35.123456789, lon: -120.987654321};

test('edit_body_sends_every_field_and_an_untouched_box_keeps_the_stored_value', () => {
  const original = {...STORED, startedShown: 'S', endedShown: 'E', latShown: '35.123456789', lonShown: '-120.987654321'};
  const same = logEditBody({...FORM, started: 'S', ended: 'E', lat: '35.123456789', lon: '-120.987654321'}, original);
  assert.equal(same.started_at, STORED.started_at, 'an untouched start is the stored instant, milliseconds and all');
  assert.equal(same.ended_at, STORED.ended_at); assert.equal(same.lat, STORED.lat); assert.equal(same.lon, STORED.lon);
  assert.deepEqual(Object.keys(same).sort(), ['count', 'ended_at', 'lat', 'lon', 'method', 'note', 'outcome', 'species', 'started_at', 'trip_id']);
  const cleared = logEditBody({started: 'S', ended: '', outcome: 'blank', count: '3', species: '', method: ' ', trip: '', lat: '', lon: '', note: ''}, original);
  assert.deepEqual({...cleared, method: null}, {started_at: STORED.started_at, ended_at: null, outcome: 'blank', count: 0, species: null, method: null, trip_id: null, lat: null, lon: null, note: null});
  assert.equal(cleared.method, ' ', 'text is sent as typed; the server turns blank text into null');
  const changed = logEditBody({...FORM, started: '2026-11-02T08:15', ended: ''}, original);
  assert.equal(changed.started_at, new Date('2026-11-02T08:15').toISOString());
  assert.equal(changed.lat, 35.5);
  assert.equal(logEditBody({...FORM, started: 'S', outcome: 'fish', count: ''}, original).count, null, 'fish with no count is left for the server to refuse');
  assert.equal(logEditBody({...FORM, started: 'S', lat: '0', lon: '0'}, {...original, lat: 0, lon: 0, latShown: '0', lonShown: '0'}).lat, 0, 'a zero coordinate is a position');
  const half = logEditBody({...FORM, started: 'S', lat: '', lon: '-120.5'}, original);
  assert.ok(half.lat === null && half.lon === -120.5, 'a half-entered pair reaches the server as it is');
});

test('edit_body_local_time_refusals_use_the_catalogue', () => {
  const es = createCopy({lang: 'es', strings: {'account.log.invalidTime': 'ES-INVALID'}});
  for (const f of [{...FORM, started: ''}, {...FORM, started: 'not a time'}, {...FORM, started: '2026-11-02T08:15', ended: 'nope'}]) {
    assert.throws(() => logEditBody(f, {}), error => error.local === true && error.message === 'Enter a valid start and optional end time.');
    assert.throws(() => logEditBody(f, {}, es), error => error.message === 'ES-INVALID');
  }
  assert.throws(() => logBody({started: '2026-11-02T08:15', ended: 'nope', outcome: 'blank'}), error => error.local === true);
  assert.equal(logBody({started: '2026-11-02T08:15', ended: '2026-11-02T09:15', outcome: 'blank'}).ended_at, new Date('2026-11-02T09:15').toISOString());
  assert.ok(!('ended_at' in logBody({started: '2026-11-02T08:15', ended: '', outcome: 'blank'})), 'create still omits an empty end');
});

test('edit_input_value_keeps_the_local_calendar_and_subsecond_precision', () => {
  const d = new Date(2026, 10, 1, 9, 5, 7, 45);
  assert.equal(localInputValue(d.toISOString()), '2026-11-01T09:05:07.045');
  assert.equal(new Date(localInputValue(d.toISOString())).getTime(), d.getTime(), 'the control value names the same instant');
  assert.equal(localInputValue(new Date(2026, 10, 1, 9, 5, 0, 0).toISOString()), '2026-11-01T09:05:00');
  assert.equal(localInputValue(null), ''); assert.equal(localInputValue('nonsense'), '');
});

test('edit_list_offers_edit_and_sorts_loaded_rows_newest_first_then_id', () => {
  assert.match(logItemHTML({id: 'a"b', outcome: 'blank', started_at: BLANK.started_at, count: 0}), /data-edit-log="a&quot;b">Edit<\/button>/);
  assert.match(logItemHTML({id: 'x', outcome: 'blank', started_at: BLANK.started_at, count: 0}, [], 'dd', {lang: 'es', strings: {'account.log.edit': 'Editar'}}), />Editar<\/button>/);
  const rows = [{id: 'b', started_at: '2026-01-01T00:00:00.000Z'}, {id: 'c', started_at: '2026-03-01T00:00:00.000Z'}, {id: 'a', started_at: '2026-01-01T00:00:00.000Z'}];
  assert.deepEqual(sortLogEntries(rows).map(r => r.id), ['c', 'a', 'b']);
});

test('edit_body_round_trips_through_the_route_and_a_no_op_changes_nothing', async () => {
  const {sql, adapter} = database(), env = {DB: adapter};
  addTrip(sql, 'trip-a', 'alice', '2026-11-05');
  const made = (await post(env, 'alice', {...FISH, trip_id: 'trip-a', started_at: '2026-11-01T14:00:00.123Z'})).data, before = rowOf(sql, made.id);
  const original = {...made, startedShown: 'S', endedShown: 'E', latShown: String(made.lat), lonShown: String(made.lon)};
  const none = await patch(env, 'alice', made.id, logEditBody({started: 'S', ended: 'E', outcome: made.outcome, count: String(made.count), species: made.species, method: made.method, trip: made.trip_id, lat: String(made.lat), lon: String(made.lon), note: made.note}, original));
  assert.equal(none.status, 200); assert.ok(util.isDeepStrictEqual(rowOf(sql, made.id), before), 'an untouched form leaves the stored row exactly as it was');
  const clear = await patch(env, 'alice', made.id, logEditBody({started: 'S', ended: '', outcome: 'blank', count: '', species: '', method: '', trip: '', lat: '', lon: '', note: ''}, original));
  assert.equal(clear.status, 200);
  const after = rowOf(sql, made.id);
  assert.ok(after.ended_at === null && after.trip_id === null && after.lat === null && after.lon === null && after.note === null && after.count === 0 && after.outcome === 'blank', 'every cleared box is cleared');
  const half = await patch(env, 'alice', made.id, logEditBody({started: 'S', ended: '', outcome: 'blank', count: '', species: '', method: '', trip: '', lat: '', lon: '-120.5', note: ''}, original));
  assert.equal(half.status, 400); assert.match(half.data.error, /^coordinates_incomplete/);
  sql.close();
});
