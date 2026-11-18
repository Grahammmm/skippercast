// SCA-248 / F03-09: /go/<slug> applies the profile's exact-value evidence rule at redirect time.
// Contract protected: a stored website/booking URL redirects (and counts) only while a current, displayable
// fact for that field carries exactly that URL (display.ts displayableLink). Bug that makes these fail: /go/
// checking only safeTarget syntax, so a link whose supporting fact was superseded, replaced, low-confidence,
// internal-only, AIS-derived or for another field keeps forwarding and counting.
// Offline, through the Worker, against the real migrations in node:sqlite. Synthetic example.com data only.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html', '/admin.html': '/admin.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
import {withSessions} from './fixtures/test-sessions.mjs';
const {default: deployed} = await import('../server/index.ts');
const worker = withSessions(deployed);

const ORIGIN = 'https://skippercast.com';
const ASSETS = {fetch: async request => new Response(new URL(request.url).pathname, {status: 299})};
const NOW = '2026-10-04T12:00:00Z';
const SITE = 'https://site.example.com/', BOOK = 'https://book.example.com/trips?boat=one#top';

function database() {
  const sql = new DatabaseSync(':memory:'), journal = read('../drizzle/meta/_journal.json');
  for (const {tag} of [...journal.entries].sort((a, b) => a.idx - b.idx)) sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`, import.meta.url), 'utf8'));
  const adapter = {prepare(query) { let args = []; const statement = sql.prepare(query); return {bind(...a) { args = a; return this; }, async first() { return statement.get(...args) || null; }, async all() { return {results: statement.all(...args)}; }, async run() { const info = statement.run(...args); return {meta: {changes: Number(info.changes)}}; }}; }};
  return {sql, adapter};
}
let n = 0;
function vessel(sql, slug, website, booking) {
  sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,website,booking_url,status,profile_status,first_seen_at,last_seen_at,created_at,updated_at)
    VALUES(?,'morro-bay',?,?,?,?,?,'active','listed',?,?,?,?)`).run('v-' + slug, slug, slug, slug, website, booking, NOW, NOW, NOW, NOW);
}
function fact(sql, slug, field, value, {confidence = 0.9, rights = 'facts-only', method = 'page', superseded = null} = {}) {
  const id = `f-${++n}`;
  sql.prepare(`INSERT INTO fleet_vessel_facts(id,vessel_id,field,value_json,value_key,source_id,source_url,method,confidence,rights,retrieved_at,first_seen_at,last_seen_at,superseded_at)
    VALUES(?,?,?,?,?,'test','https://landing.example.com/',?,?,?,?,?,?,?)`).run(id, 'v-' + slug, field, JSON.stringify(value), id, method, confidence, rights, NOW, NOW, NOW, superseded);
}
const clicks = sql => sql.prepare('SELECT * FROM fleet_link_clicks').all().map(r => ({...r}));
const go = (path, env, init = {}) => worker.fetch(new Request(ORIGIN + path, init), {ASSETS, FLEET_ENABLED: 'true', ...env});
const sink = () => { const points = []; return {points, ANALYTICS: {writeDataPoint: p => points.push(structuredClone(p))}}; };
const fleetPoints = points => points.filter(p => p.indexes[0] === 'fleet_click');

test('valid positive control: a link with a current displayable fact for its exact value redirects with its referral tags; HEAD is not counted', async () => {
  const {sql, adapter} = database(); vessel(sql, 'good', SITE, BOOK);
  fact(sql, 'good', 'website', SITE); fact(sql, 'good', 'booking_url', BOOK);
  const {points, ANALYTICS} = sink(), env = {DB: adapter, ANALYTICS};
  try {
    const booking = await go('/go/good?t=booking&p=profile', env);
    assert.equal(booking.status, 302);
    assert.equal(booking.headers.get('Location'), 'https://book.example.com/trips?boat=one&utm_source=skippercast&utm_medium=referral&utm_campaign=fleet-morro-bay&utm_content=profile#top');
    assert.equal((await go('/go/good?t=website&p=map', env)).headers.get('Location'),
      'https://site.example.com/?utm_source=skippercast&utm_medium=referral&utm_campaign=fleet-morro-bay&utm_content=map');
    assert.equal(clicks(sql).length, 2);
    const before = JSON.stringify(clicks(sql)), pointsBefore = fleetPoints(points).length;
    assert.equal((await go('/go/good?t=booking&p=profile', env, {method: 'HEAD'})).status, 302);
    assert.equal(JSON.stringify(clicks(sql)), before, 'HEAD stays uncounted');
    assert.equal(fleetPoints(points).length, pointsBefore);
  } finally { sql.close(); }
});

test('negative controls: superseded, replaced, weak, restricted, AIS, other-field and missing evidence neither redirect nor count', async () => {
  const {sql, adapter} = database();
  const cases = {
    superseded: () => fact(sql, 'superseded', 'website', SITE, {superseded: NOW}),    // the cited failure: the supporting fact ended
    replaced: () => { fact(sql, 'replaced', 'website', SITE, {superseded: NOW}); fact(sql, 'replaced', 'website', 'https://new.example.com/'); },   // a newer value superseded this URL
    'low-confidence': () => fact(sql, 'low-confidence', 'website', SITE, {confidence: 0.4}),
    'internal-only': () => fact(sql, 'internal-only', 'website', SITE, {rights: 'internal-only'}),
    ais: () => fact(sql, 'ais', 'website', SITE, {method: 'ais'}),
    'other-field': () => fact(sql, 'other-field', 'booking_url', SITE),   // a booking fact does not back the website column
    'near-miss': () => fact(sql, 'near-miss', 'website', 'https://site.example.com'),   // not exactly the stored value
    none: () => {},
  };
  const {points, ANALYTICS} = sink(), env = {DB: adapter, ANALYTICS};
  try {
    for (const [slug, add] of Object.entries(cases)) { vessel(sql, slug, SITE, null); add(); }
    for (const slug of Object.keys(cases)) for (const method of ['GET', 'HEAD']) {
      const response = await go(`/go/${slug}?t=website&p=profile`, env, {method});
      assert.equal(response.status, 404, `${slug} ${method}`);
      assert.equal(response.headers.get('Location'), null, `${slug} ${method}`);
    }
    assert.deepEqual(clicks(sql), [], 'a refused redirect counts nothing');
    assert.deepEqual(fleetPoints(points), []);
  } finally { sql.close(); }
});

test('support is per target: a website fact does not keep the booking link alive and the support is the fleet_vessels value itself', async () => {
  const {sql, adapter} = database(); vessel(sql, 'half', SITE, BOOK);
  fact(sql, 'half', 'website', SITE);
  try {
    assert.equal((await go('/go/half?t=website', {DB: adapter})).status, 302);
    assert.equal((await go('/go/half?t=booking', {DB: adapter})).status, 404);
    // Another vessel's fact for the same URL never supports this vessel.
    vessel(sql, 'other', SITE, null); fact(sql, 'other', 'website', SITE);
    sql.prepare("UPDATE fleet_vessel_facts SET superseded_at=? WHERE vessel_id='v-half'").run(NOW);
    assert.equal((await go('/go/half?t=website', {DB: adapter})).status, 404);
    assert.equal((await go('/go/other?t=website', {DB: adapter})).status, 302);
    assert.equal(clicks(sql).length, 2, 'only the two redirected GETs counted');
  } finally { sql.close(); }
});

test('display.ts does not import go.ts (one-way import, no cycle)', () => {
  assert.doesNotMatch(readFileSync(new URL('../server/fleet/display.ts', import.meta.url), 'utf8'), /^import .*['"]\.\/go\.ts['"]/m);
});
