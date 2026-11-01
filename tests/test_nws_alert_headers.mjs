// SC1537-01: the Worker's api.weather.gov alerts read identifies SkipperCast
// (NWS requires a User-Agent) and asks for GeoJSON; every other feed read is unchanged.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';
import {readFeed, NWS_HEADERS, RAW} from '../server/feeds.ts';
const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
const {checkTrips} = await import('../server/index.ts');
const UA = 'SkipperCast-worker (+https://skippercast.com)';
const ALERTS = 'https://api.weather.gov/alerts/active?zone=PZZ670';

async function withFetch(stub, run) {
  const original = globalThis.fetch, calls = [];
  globalThis.fetch = async (url, init) => { calls.push({url: String(url), init}); return stub(String(url), init); };
  try { return await run(calls); } finally { globalThis.fetch = original; }
}
const sentUA = init => init?.headers?.['User-Agent'];

test('an api.weather.gov read sends exactly the NWS User-Agent and Accept headers', async () => {
  assert.ok(Object.isFrozen(NWS_HEADERS));
  await withFetch(() => Response.json({features: [{properties: {event: 'Small Craft Advisory'}}]}), async calls => {
    const value = await readFeed(ALERTS);
    assert.equal(value.features[0].properties.event, 'Small Craft Advisory');
    assert.equal(calls.length, 1);
    const {init} = calls[0];
    assert.deepEqual(Object.keys(init).sort(), ['headers', 'redirect', 'signal']);
    assert.deepEqual({...init.headers}, {'User-Agent': UA, Accept: 'application/geo+json'});
    assert.equal(init.redirect, 'manual');
    assert.ok(init.signal instanceof AbortSignal);
  });
});

test('a GitHub raw feed read keeps the old init shape with no headers key', async () => {
  await withFetch(() => Response.json({ok: true}), async calls => {
    assert.deepEqual(await readFeed(RAW + 'data/regions/morro-bay/latest.json'), {ok: true});
    assert.deepEqual(Object.keys(calls[0].init).sort(), ['redirect', 'signal']);
    assert.equal(calls[0].init.redirect, 'manual');
  });
});

test('look-alike hosts and non-https NWS URLs get no NWS headers', async () => {
  const urls = ['https://api.weather.gov.example.com/alerts/active?zone=PZZ670', 'https://xapi.weather.gov/alerts/active?zone=PZZ670',
    'https://weather.gov/alerts/active?zone=PZZ670', 'http://api.weather.gov/alerts/active?zone=PZZ670',
    'https://example.com/?u=https://api.weather.gov/alerts'];
  await withFetch(() => Response.json({features: []}), async calls => {
    for (const url of urls) await readFeed(url);
    assert.equal(calls.length, urls.length);
    for (const {url, init} of calls) assert.equal(Object.hasOwn(init, 'headers'), false, url);
  });
});

test('an NWS 503 still throws and the log line names the host only, never the headers', async () => {
  const original = console.error, logged = [];
  console.error = (...args) => logged.push(args);
  try {
    await withFetch(() => new Response('busy', {status: 503}), async calls => {
      await assert.rejects(readFeed(ALERTS), /feed HTTP 503/);
      assert.equal(sentUA(calls[0].init), UA);
    });
  } finally { console.error = original; }
  assert.equal(logged.length, 1);
  const [message, detail] = logged[0];
  assert.equal(message, 'Regional feed unavailable');
  assert.deepEqual(Object.keys(detail).sort(), ['host', 'reason', 'stage']);
  assert.equal(detail.host, 'api.weather.gov');
  const text = JSON.stringify(logged);
  for (const leak of ['User-Agent', 'SkipperCast-worker', 'geo+json']) assert.equal(text.includes(leak), false, leak);
});

function database() {
  const sql = new DatabaseSync(':memory:'), journal = read('../drizzle/meta/_journal.json');
  for (const {tag} of [...journal.entries].sort((a, b) => a.idx - b.idx)) sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`, import.meta.url), 'utf8'));
  const adapter = {prepare(query) { let args = []; const statement = sql.prepare(query); return {bind(...a) { args = a; return this; }, async first() { return statement.get(...args) || null; },
    async all() { return {results: statement.all(...args)}; }, async run() { const info = statement.run(...args); return {meta: {changes: Number(info.changes)}}; }}; },
  async batch(queries) { sql.exec('BEGIN'); try { const result = []; for (const q of queries) result.push(await q.run()); sql.exec('COMMIT'); return result; } catch (e) { sql.exec('ROLLBACK'); throw e; } }};
  const date = new Intl.DateTimeFormat('en-CA', {timeZone: 'America/Los_Angeles'}).format(new Date(Date.now() + 2 * 86400000));
  sql.prepare('INSERT INTO trips(id,owner,region,point,species,date,start_hour,end_hour,wind_limit,gust_limit,sea_limit,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)')
    .run('trip-1', 'alice', 'morro-bay', 'north', 'reef', date, 7, 13, 8, 12, 3, new Date().toISOString());
  return {sql, adapter};
}
// NWS refuses requests without the identifying User-Agent. The intelligence feed is the minimum that
// reaches the advisory check (region and forecast points); the daily feed is down.
const REGION = globalThis.REGIONS['morro-bay'];
const INTEL = {region_id: REGION.id, forecast: {requested_points: REGION.forecast_points.map(p => [p.id, p.latitude, p.longitude])}};
async function tripIssues(nws) {
  const {sql, adapter} = database();
  try {
    return await withFetch((url, init) => new URL(url).hostname === 'api.weather.gov' ? nws(url, init)
      : url === REGION.intelligence_feed ? Response.json(INTEL) : Response.json({}, {status: 503}), async calls => {
      const result = await checkTrips({DB: adapter});
      assert.equal(result.changes, 1);
      const nwsCalls = calls.filter(c => new URL(c.url).hostname === 'api.weather.gov');
      assert.ok(nwsCalls.length >= 1 && nwsCalls.every(c => sentUA(c.init) === UA), 'every NWS read carries the User-Agent');
      return JSON.parse(sql.prepare('SELECT last_assessment FROM trips').get().last_assessment).issues;
    });
  } finally { sql.close(); }
}

test('with the User-Agent the trip check reads NWS advisories; a 403 regardless still fails closed', async () => {
  const requireUA = (url, init) => sentUA(init) === UA ? Response.json({features: []}) : new Response('{"title":"Forbidden"}', {status: 403});
  const issues = await tripIssues(requireUA);
  assert.equal(issues.includes('Marine advisories unavailable'), false, issues.join('; '));
  const refused = await tripIssues(() => new Response('{"title":"Forbidden"}', {status: 403}));
  assert.ok(refused.includes('Marine advisories unavailable'), 'an NWS refusal still marks advisories unavailable');
});
