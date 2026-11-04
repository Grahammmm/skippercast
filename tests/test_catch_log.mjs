// BF-catch-log: the private effort log. A blank is a first-class outcome; coordinates stay private;
// the log is in the account export and gone on deletion; it appears in no feed or public page.
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
const {recordReads, resetMeter} = await import('../server/cost-ceiling.ts');
const {logItemHTML, logBody} = await import('../dist/account.js');
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
  const root = fileURLToPath(new URL('..', import.meta.url)), allowed = new Set(['server/routes/catch-log.ts', 'server/routes/account.ts', 'server/app.ts', 'db/schema.ts', 'dist/account.js']);
  const hits = [];
  const walk = dir => { for (const name of readdirSync(dir)) { const full = join(dir, name), rel = full.slice(root.length).replaceAll('\\', '/').replace(/^\//, '');
    if (name === 'node_modules' || name.startsWith('.') || rel === 'dist/client' || rel === 'dist/server') continue;
    if (statSync(full).isDirectory()) walk(full); else if (/\.(ts|tsx|js|mjs|py)$/.test(name) && /catch_log\b|api\/catch-log|routes\/catch-log/.test(readFileSync(full, 'utf8')) && !allowed.has(rel)) hits.push(rel); } };
  for (const dir of ['server', 'web', 'dist', 'src', 'packages', 'scripts']) walk(join(root, dir));
  assert.deepEqual(hits, [], 'only the log route, the export, the app mount, the schema and the account view mention the log');
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
