// SP-17 frozen synthetic contract: malformed stored targets must never become navigable.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DatabaseSync} from 'node:sqlite';

const cases = JSON.parse(readFileSync(new URL('./fixtures/sp1708_destination_controls/cases.json', import.meta.url), 'utf8'));
globalThis.REGIONS = { 'morro-bay': JSON.parse(readFileSync(new URL('../regions/morro-bay/region.json', import.meta.url), 'utf8')) };
globalThis.DEPLOYMENT = JSON.parse(readFileSync(new URL('../deployments/production.json', import.meta.url), 'utf8'));
globalThis.SHELLS = {'/': '/index.0123456789.html', '/admin.html': '/admin.0123456789.html'};
globalThis.BUILD_ID = 'sp1708-test';
const {default: deployed} = await import('../server/index.ts');
const {safeTarget} = await import('../server/fleet/go.ts');

const ORIGIN = 'https://skippercast.com';
const ASSETS = {fetch: async request => new Response(new URL(request.url).pathname, {status: 299})};
const NOW = '2026-10-04T12:00:00Z';
function database() {
  const sql = new DatabaseSync(':memory:');
  const journal = JSON.parse(readFileSync(new URL('../drizzle/meta/_journal.json', import.meta.url), 'utf8'));
  for (const {tag} of [...journal.entries].sort((a,b) => a.idx-b.idx)) sql.exec(readFileSync(new URL(`../drizzle/${tag}.sql`, import.meta.url), 'utf8'));
  const adapter = {prepare(query) {let args=[]; const statement=sql.prepare(query); return {bind(...a){args=a;return this;}, async first(){return statement.get(...args)||null;}, async all(){return {results:statement.all(...args)};}, async run(){const r=statement.run(...args);return {meta:{changes:Number(r.changes)}};}};}};
  return {sql,adapter};
}
function seed(sql, bookingUrl) {
  sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,website,booking_url,status,profile_status,first_seen_at,last_seen_at,created_at,updated_at)
  VALUES(?,'morro-bay',?,'sp1708 example','sp1708 example','https://site.example.com/',?,'active','listed',?,?,?,?)`)
    .run(cases.vessel.id, cases.vessel.slug, bookingUrl, NOW, NOW, NOW, NOW);
}
const clicks = sql => sql.prepare('SELECT * FROM fleet_link_clicks').all();
const go = (path, env, init={}) => deployed.fetch(new Request(ORIGIN+path,init),{ASSETS,...env});
const route = `/go/${cases.vessel.slug}?t=booking&p=profile`;

test('SP1708 A1 baseline: embedded LF booking target is rejected by safeTarget and redirect route without click work', async () => {
  const bad = 'https://book.example.com/trips\n?boat=bo-control-ok';
  const direct = safeTarget(bad);
  const {sql,adapter}=database(); seed(sql,bad);
  try {
    const response=await go(route,{DB:adapter,FLEET_ENABLED:'true'});
    const observed = {safeTarget: direct?.href ?? null, status: response.status, location: response.headers.get('Location'), clicks: clicks(sql)};
    assert.deepEqual(observed, {safeTarget:null,status:404,location:null,clicks:[]});
  } finally {sql.close();}
});

test('SP1708 healthy control: clean HTTPS booking target redirects and counts as before', async () => {
  const {sql,adapter}=database(); seed(sql,cases.clean_booking_url);
  try {const response=await go(route,{DB:adapter,FLEET_ENABLED:'true'}); assert.equal(response.status,302); assert.equal(response.headers.get('Location'),'https://book.example.com/trips?boat=sp1708&utm_source=operator&utm_medium=referral&utm_campaign=fleet-morro-bay&utm_content=profile#top'); assert.equal(clicks(sql).length,1); assert.equal(Number(clicks(sql)[0].count),1);}
  finally {sql.close();}
});

test('SP1708 A2: reject embedded ASCII C0 and DEL in host, path and query; retain trim and encoded bytes', () => {
  const base = 'https://book.example.com/path?x=1';
  for (const control of ['\r','\t','\0','\x7f']) {
    assert.equal(safeTarget(`https://book${control}.example.com/path`),null,`host ${JSON.stringify(control)}`);
    assert.equal(safeTarget(`https://book.example.com/pa${control}th`),null,`path ${JSON.stringify(control)}`);
    assert.equal(safeTarget(`https://book.example.com/path?x=1${control}2`),null,`query ${JSON.stringify(control)}`);
  }
  for (const c of Array.from({length:32},(_,i)=>String.fromCharCode(i))) assert.equal(safeTarget(`https://book.example.com/a${c}b`),null,`C0 ${c.charCodeAt(0)}`);
  assert.equal(safeTarget(' https://book.example.com/path ').href,'https://book.example.com/path');
  assert.equal(safeTarget('https://book.example.com/%0A%09').href,'https://book.example.com/%0A%09');
  assert.equal(safeTarget(base).href,base);
});

test('SP1708 A3: clean URL query, fragment and existing UTM stay intact; malformed and non-HTTPS remain refused', async () => {
  const {sql,adapter}=database(); seed(sql,cases.clean_booking_url);
  try {const r=await go(route,{DB:adapter,FLEET_ENABLED:'true'}); assert.equal(r.status,302); assert.equal(r.headers.get('Location'),'https://book.example.com/trips?boat=sp1708&utm_source=operator&utm_medium=referral&utm_campaign=fleet-morro-bay&utm_content=profile#top');}
  finally {sql.close();}
  for (const value of ['http://book.example.com/','https://user:pass@book.example.com/','not a url','https://book.example.com/'+ 'x'.repeat(2050)]) assert.equal(safeTarget(value),null);
});

test('SP1708 A4: excluded vessels, invalid selectors, missing URL and HEAD preserve existing behavior', async () => {
  const {sql,adapter}=database(); seed(sql,null);
  const add = sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,website,booking_url,status,profile_status,first_seen_at,last_seen_at,created_at,updated_at)
    VALUES(?,'morro-bay',?,?,?,'https://site.example.com/','https://book.example.com/',?,?, ?,?,?,?)`);
  for (const [id,slug,status,profile] of [['hidden','sp1708-hidden','active','hidden'],['inactive','sp1708-inactive','inactive','listed'],['excluded','sp1708-excluded','excluded','listed']])
    add.run(id,slug,slug,slug,status,profile,NOW,NOW,NOW,NOW);
  try {
    for(const path of [`${route}`,`/go/sp1708-hidden?t=booking&p=profile`,`/go/sp1708-inactive?t=booking&p=profile`,`/go/sp1708-excluded?t=booking&p=profile`,`/go/not-real?t=booking&p=profile`,`/go/sp1708-example?t=bad&p=profile`]) assert.equal((await go(path,{DB:adapter,FLEET_ENABLED:'true'})).status,404);
    const head=await go('/go/sp1708-example?t=website&p=profile',{DB:adapter,FLEET_ENABLED:'true'},{method:'HEAD'});
    assert.equal(head.status,302); assert.deepEqual(clicks(sql),[]);
  } finally {sql.close();}
});
