// Charter fleet /go/<slug> redirect and click counts (CF-34; docs/plans/charter-fleet/design.md
// § 12, § 17; threat model § 10.1). Offline, through the Worker, against the real migrations
// in node:sqlite. Synthetic vessels and example.com/example.org URLs only.
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
const {withUtm, safeTarget} = await import('../server/fleet/go.ts');
const worker = withSessions(deployed);

const ORIGIN = 'https://skippercast.com';
const ASSETS = {fetch: async request => new Response(new URL(request.url).pathname, {status: 299})};
const ON = {FLEET_ENABLED: 'true'};
const NOW = '2026-10-04T12:00:00Z';

function database() {
  const sql = new DatabaseSync(':memory:'), journal = read('../drizzle/meta/_journal.json');
  for (const {tag} of [...journal.entries].sort((a, b) => a.idx - b.idx)) sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`, import.meta.url), 'utf8'));
  const adapter = {prepare(query) { let args = []; const statement = sql.prepare(query); return {bind(...a) { args = a; return this; }, async first() { return statement.get(...args) || null; }, async all() { return {results: statement.all(...args)}; }, async run() { const info = statement.run(...args); return {meta: {changes: Number(info.changes)}}; }}; },
    async batch(queries) { sql.exec('BEGIN'); try { const out = []; for (const q of queries) out.push(await q.run()); sql.exec('COMMIT'); return out; } catch (e) { sql.exec('ROLLBACK'); throw e; } }};
  return {sql, adapter};
}

const VESSELS = [
  // id, slug, website, booking_url, status, profile_status
  ['v-sea-example', 'sea-example', 'https://sea-example.example.com/', 'https://book.example.com/trips?boat=sea-example&utm_source=operator#top', 'active', 'listed'],
  ['v-tide-runner', 'tide-runner', 'https://tide-runner.example.org/about', null, 'active', 'listed'],
  ['v-hidden', 'hidden-boat', 'https://hidden.example.com/', 'https://hidden.example.com/book', 'active', 'hidden'],
  ['v-inactive', 'inactive-boat', 'https://inactive.example.com/', 'https://inactive.example.com/book', 'inactive', 'listed'],
  ['v-excluded', 'excluded-boat', 'https://excluded.example.com/', 'https://excluded.example.com/book', 'excluded', 'listed'],
  ['v-http', 'plain-http', 'http://plain.example.com/', 'javascript:alert(1)', 'active', 'listed'],
  ['v-creds', 'with-creds', 'https://user:pass@creds.example.com/', 'ftp://creds.example.com/book', 'active', 'listed'],
];
function seed(sql) {
  const insert = sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,website,booking_url,status,profile_status,first_seen_at,last_seen_at,created_at,updated_at)
    VALUES(?,'morro-bay',?,?,?,?,?,?,?,?,?,?,?)`);
  for (const [id, slug, website, booking, status, profile] of VESSELS) insert.run(id, slug, slug.replace(/-/g, ' '), slug, website, booking, status, profile, NOW, NOW, NOW, NOW);
}
const clicks = sql => sql.prepare('SELECT * FROM fleet_link_clicks ORDER BY vessel_id, target, placement').all().map(r => ({...r}));
const go = (path, env, init = {}) => worker.fetch(new Request(ORIGIN + path, init), {ASSETS, ...env});
function sink() { const points = []; return {points, ANALYTICS: {writeDataPoint: p => points.push(structuredClone(p))}}; }
const fleetPoints = points => points.filter(p => p.indexes[0] === 'fleet_click');

test('withUtm appends the four tags, keeps existing parameters, existing utm_* and the fragment; safeTarget takes plain https only', () => {
  assert.equal(withUtm(new URL('https://a.example.com/x'), 'morro-bay', 'profile'),
    'https://a.example.com/x?utm_source=skippercast&utm_medium=referral&utm_campaign=fleet-morro-bay&utm_content=profile');
  assert.equal(withUtm(new URL('https://a.example.com/x?b=1&c=two%20words&utm_source=op#frag'), 'morro-bay', 'map'),
    'https://a.example.com/x?b=1&c=two%20words&utm_source=op&utm_medium=referral&utm_campaign=fleet-morro-bay&utm_content=map#frag');
  for (const bad of ['http://a.example.com/', 'javascript:alert(1)', 'ftp://a.example.com/', 'https://u:p@a.example.com/', '//a.example.com/', '/relative', '', null, 7, 'https://a.example.com/' + 'x'.repeat(2100)])
    assert.equal(safeTarget(bad), null, String(bad).slice(0, 40));
  assert.equal(safeTarget(' https://a.example.com/b ').href, 'https://a.example.com/b');
});

test('with FLEET_ENABLED off /go/ answers 404 and counts nothing', async () => {
  const {sql, adapter} = database(); seed(sql);
  const {points, ANALYTICS} = sink();
  try {
    for (const env of [{DB: adapter, ANALYTICS}, {DB: adapter, ANALYTICS, FLEET_ENABLED: 'false'}, {DB: adapter, ANALYTICS, FLEET_ENABLED: 'yes', FLEET_MAP_ENABLED: 'true'}]) {
      const response = await go('/go/sea-example?t=booking&p=profile', env);
      assert.equal(response.status, 404);
      assert.equal(response.headers.get('Location'), null);
    }
    assert.deepEqual(clicks(sql), []);
    assert.deepEqual(fleetPoints(points), []);
  } finally { sql.close(); }
});

test('a listed active vessel redirects 302 to its stored https URL with UTM tags, no-store, and counts the click per day', async () => {
  const {sql, adapter} = database(); seed(sql);
  const {points, ANALYTICS} = sink(), env = {DB: adapter, ANALYTICS, ...ON};
  try {
    const booking = await go('/go/sea-example?t=booking&p=profile', env);
    assert.equal(booking.status, 302);
    assert.equal(booking.headers.get('Cache-Control'), 'no-store');
    assert.equal(booking.headers.get('X-Robots-Tag'), 'noindex');
    assert.equal(booking.headers.get('Location'),
      'https://book.example.com/trips?boat=sea-example&utm_source=operator&utm_medium=referral&utm_campaign=fleet-morro-bay&utm_content=profile#top');
    assert.equal((await go('/go/sea-example?t=booking&p=profile', env)).status, 302);
    const website = await go('/go/tide-runner?t=website&p=directory', env);
    assert.equal(website.headers.get('Location'),
      'https://tide-runner.example.org/about?utm_source=skippercast&utm_medium=referral&utm_campaign=fleet-morro-bay&utm_content=directory');
    // An unknown or missing placement is counted as "other" and tagged so.
    assert.match((await go('/go/tide-runner?t=website&p=newsletter', env)).headers.get('Location'), /utm_content=other$/);
    assert.match((await go('/go/tide-runner?t=website', env)).headers.get('Location'), /utm_content=other$/);
    const day = new Date().toISOString().slice(0, 10);   // the UTC day of the click
    assert.deepEqual(clicks(sql), [
      {vessel_id: 'v-sea-example', target: 'booking', placement: 'profile', day, count: 2},
      {vessel_id: 'v-tide-runner', target: 'website', placement: 'directory', day, count: 1},
      {vessel_id: 'v-tide-runner', target: 'website', placement: 'other', day, count: 2},
    ]);
    const fleet = fleetPoints(points);
    assert.equal(fleet.length, 5);
    assert.deepEqual(fleet[0], {indexes: ['fleet_click'], blobs: ['fleet_click', 'sea-example', 'booking', 'profile'], doubles: [1]});
    // Without the binding the redirect and the D1 count still work.
    assert.equal((await go('/go/sea-example?t=website&p=map', {DB: adapter, ...ON})).status, 302);
    // HEAD (link checkers) gets the redirect but is not counted.
    const before = JSON.stringify(clicks(sql));
    assert.equal((await go('/go/sea-example?t=booking&p=profile', {DB: adapter, ...ON}, {method: 'HEAD'})).status, 302);
    assert.equal(JSON.stringify(clicks(sql)), before);
  } finally { sql.close(); }
});

test('acceptance 1: a ?url=, ?next= or any request-supplied target is ignored', async () => {
  const {sql, adapter} = database(); seed(sql);
  const env = {DB: adapter, ...ON};
  try {
    for (const query of ['url=https://evil.example.net/', 'next=https://evil.example.net/', 'redirect=//evil.example.net', 'target=https://evil.example.net/', 'u=evil.example.net'])
      for (const t of ['booking', 'website']) {
        const response = await go(`/go/sea-example?t=${t}&p=profile&${query}`, env, {headers: {Referer: 'https://evil.example.net/', Host: 'evil.example.net', 'X-Forwarded-Host': 'evil.example.net'}});
        assert.equal(response.status, 302, query);
        const location = new URL(response.headers.get('Location'));
        assert.equal(location.host, t === 'booking' ? 'book.example.com' : 'sea-example.example.com', query);
        assert.ok(!response.headers.get('Location').includes('evil'), query);
      }
    // A URL in place of the slug or the target never redirects.
    for (const path of ['/go/https%3A%2F%2Fevil.example.net?t=booking', '/go/sea-example?t=https://evil.example.net/', '/go/evil.example.net?t=booking'])
      assert.equal((await go(path, env)).status, 404, path);
  } finally { sql.close(); }
});

test('acceptance 2: non-https stored URLs 404; so do unknown, hidden, inactive and excluded vessels, a missing URL and a bad t', async () => {
  const {sql, adapter} = database(); seed(sql);
  const {points, ANALYTICS} = sink(), env = {DB: adapter, ANALYTICS, ...ON};
  try {
    const refused = ['/go/plain-http?t=website', '/go/plain-http?t=booking', '/go/with-creds?t=website', '/go/with-creds?t=booking',
      '/go/hidden-boat?t=booking', '/go/inactive-boat?t=booking', '/go/excluded-boat?t=website', '/go/no-such-boat?t=booking',
      '/go/tide-runner?t=booking', '/go/sea-example', '/go/sea-example?t=phone', '/go/sea-example?t=BOOKING', '/go/Sea-Example?t=booking', '/go/-bad?t=booking'];
    for (const path of refused) {
      const response = await go(path, env);
      assert.equal(response.status, 404, path);
      assert.equal(response.headers.get('Location'), null, path);
      assert.equal(response.headers.get('Cache-Control'), 'no-store', path);
    }
    assert.deepEqual(clicks(sql), [], 'a refused redirect counts nothing');
    assert.deepEqual(fleetPoints(points), []);
    assert.equal((await go('/go/sea-example?t=booking', ON)).status, 503, 'no storage');
  } finally { sql.close(); }
});

test('acceptance 4: no IP, user agent or referrer is stored in D1 or Analytics Engine', async () => {
  const {sql, adapter} = database(); seed(sql);
  const {points, ANALYTICS} = sink(), env = {DB: adapter, ANALYTICS, ...ON};
  const visitor = {'cf-connecting-ip': '203.0.113.77', 'User-Agent': 'TestAgent/9.9 (visitor-marker)', Referer: 'https://referrer-marker.example.net/page', Cookie: 'sc_marker=cookie-marker'};
  try {
    assert.equal((await go('/go/sea-example?t=booking&p=map', env, {headers: visitor})).status, 302);
    assert.deepEqual(Object.keys(clicks(sql)[0]).sort(), ['count', 'day', 'placement', 'target', 'vessel_id']);
    const stored = JSON.stringify(sql.prepare("SELECT name FROM sqlite_master WHERE type='table'").all().flatMap(({name}) => sql.prepare(`SELECT * FROM "${name}"`).all()));
    const written = JSON.stringify(points);
    for (const marker of ['203.0.113.77', 'visitor-marker', 'TestAgent', 'referrer-marker', 'cookie-marker'])
      for (const [where, text] of [['D1', stored], ['Analytics Engine', written]]) assert.ok(!text.includes(marker), `${marker} in ${where}`);
    assert.deepEqual(fleetPoints(points)[0].blobs, ['fleet_click', 'sea-example', 'booking', 'map']);
  } finally { sql.close(); }
});

test('/go/ is limited per IP by PUBLIC_LIMITER (fleet-go:<ip>), after the flag gate', async () => {
  const {sql, adapter} = database(); seed(sql);
  const keys = [], limiter = {limit: async ({key}) => { keys.push(key); return {success: false}; }};
  try {
    const limited = await go('/go/sea-example?t=booking', {DB: adapter, PUBLIC_LIMITER: limiter, ...ON}, {headers: {'cf-connecting-ip': '198.51.100.9'}});
    assert.equal(limited.status, 429);
    assert.ok(limited.headers.get('Retry-After'));
    assert.deepEqual(keys, ['fleet-go:198.51.100.9']);
    assert.deepEqual(clicks(sql), []);
    assert.equal((await go('/go/sea-example?t=booking', {DB: adapter, PUBLIC_LIMITER: limiter})).status, 404, 'off: 404 before the limiter');
    assert.equal(keys.length, 1);
    const open = {limit: async () => ({success: true})};
    assert.equal((await go('/go/sea-example?t=booking', {DB: adapter, PUBLIC_LIMITER: open, ...ON})).status, 302);
  } finally { sql.close(); }
});

test('GET /api/admin/fleet/clicks: admins only, FLEET_ENABLED only; counts by vessel, target and placement as raw redirects', async () => {
  const {sql, adapter} = database(); seed(sql);
  sql.prepare("INSERT INTO users(id,created_at,role) VALUES('admin-1',?,'admin')").run(NOW);
  const today = new Date().toISOString().slice(0, 10), ago = n => new Date(Date.now() - n * 86_400_000).toISOString().slice(0, 10);
  const add = sql.prepare('INSERT INTO fleet_link_clicks(vessel_id,target,placement,day,count) VALUES(?,?,?,?,?)');
  add.run('v-sea-example', 'booking', 'profile', today, 5);
  add.run('v-sea-example', 'website', 'map', ago(3), 2);
  add.run('v-tide-runner', 'website', 'directory', ago(10), 4);
  add.run('v-tide-runner', 'website', 'other', ago(40), 9);
  const as = (path, env, owner = 'admin-1') => worker.fetch(new Request(ORIGIN + path, {headers: {'x-test-owner': owner}}), {ASSETS, DB: adapter, ...env});
  try {
    assert.equal((await as('/api/admin/fleet/clicks', {})).status, 404, 'fleet off');
    assert.equal((await as('/api/admin/fleet/clicks', {TEXT_ADVISOR_ENABLED: 'true'})).status, 404, 'the advisor flag does not open fleet routes');
    assert.equal((await as('/api/admin/fleet/clicks', ON, 'someone')).status, 404, 'non-admin');
    assert.equal((await worker.fetch(new Request(ORIGIN + '/api/admin/fleet/clicks'), {ASSETS, DB: adapter, ...ON})).status, 401, 'anonymous');
    assert.equal((await as('/api/admin/fleet/clicks?days=5', ON)).status, 400);
    assert.equal((await as('/api/admin/fleet/clicks?region=../x', ON)).status, 400);

    const week = await as('/api/admin/fleet/clicks?days=7', ON);
    assert.equal(week.status, 200);
    assert.equal(week.headers.get('Cache-Control'), 'no-store');
    const report = await week.json();
    assert.equal(report.unit, 'redirects');
    assert.equal(report.until, today);
    assert.equal(report.since, ago(6));
    assert.deepEqual(report.totals, {booking: 5, website: 2, total: 7, placements: {profile: 5, directory: 0, map: 2, other: 0}});
    assert.deepEqual(report.vessels, [{vessel_id: 'v-sea-example', slug: 'sea-example', name: 'sea example', region: 'morro-bay',
      booking: 5, website: 2, total: 7, placements: {profile: 5, directory: 0, map: 2, other: 0}}]);
    assert.deepEqual(report.daily, [{day: ago(3), count: 2}, {day: today, count: 5}]);

    const month = await (await as('/api/admin/fleet/clicks', ON)).json();
    assert.equal(month.days, 30);
    assert.deepEqual(month.vessels.map(v => [v.slug, v.total]), [['sea-example', 7], ['tide-runner', 4]]);
    assert.equal((await (await as('/api/admin/fleet/clicks?days=90', ON)).json()).totals.total, 20);
    assert.equal((await (await as('/api/admin/fleet/clicks?days=90&region=elsewhere', ON)).json()).totals.total, 0);
  } finally { sql.close(); }
});
