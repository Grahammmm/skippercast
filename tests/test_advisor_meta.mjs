// Meta Graph API client (TA-S0; docs/plans/text-advisor/09-social.md § Publishing,
// "Graph API client"): appsecret_proof for a known token and secret, every call's
// versioned URL, token and proof, the retry on 5xx and rate-limit codes (and
// none on a token error), error logs with code/subcode/fbtrace_id and never the
// token, the publishing-limit parse, each helper's request shape against the
// recorded responses in fixtures/advisor/meta/, the admin health's quota line
// (cached), the owner's token script (meta-token.mjs) and the deploy wiring for
// the META_* secrets. All offline: a fake fetch answers.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync, mkdtempSync, rmSync, writeFileSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createHmac} from 'node:crypto';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const readJson = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': readJson('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = readJson('../deployments/production.json');
const meta = await import('../server/advisor/social/meta.ts');
const {metaHealth, adminHealth, META_QUOTA_KEY, META_QUOTA_TTL_MS} = await import('../server/advisor/admin/health.ts');
const script = await import('../scripts/advisor/meta-token.mjs');

const fixture = name => JSON.parse(readFileSync(new URL(`./fixtures/advisor/meta/${name}.json`, import.meta.url)));
const TOKEN = 'EAAB-PLACEHOLDER-TOKEN', SECRET = 'app-secret-PLACEHOLDER';
const PROOF = '3b522790c3cd511325101032fd91e068ea263c7b07b4adce7114eb47586f640c';
const IG = '17841400000000000', PAGE = '100000000000001';
const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const quiet = async fn => { const saved = {log: console.log, warn: console.warn, error: console.error}, lines = []; console.log = console.warn = console.error = (...a) => lines.push(a.join(' ')); try { return {value: await fn(), lines}; } finally { Object.assign(console, saved); } };
const jsonResponse = (body, status = 200) => new Response(JSON.stringify(body), {status, headers: {'content-type': 'application/json'}});

/** A fake fetch answering each call from `answers` in order (a function gets the call), recording method, URL, query/body params and headers. */
function fakeFetch(answers) {
  const calls = [];
  const fetcher = async (url, init = {}) => {
    const u = new URL(url), params = Object.fromEntries((init.method === 'POST' && typeof init.body === 'string' ? new URLSearchParams(init.body) : u.searchParams).entries());
    const call = {method: init.method ?? 'GET', url, path: u.origin + u.pathname, params, headers: {...(init.headers ?? {})}, signal: init.signal};
    calls.push(call);
    const next = answers.length > 1 ? answers.shift() : answers[0];
    if (typeof next === 'function') return next(call);
    if (next instanceof Error) throw next;
    return next instanceof Response ? next.clone() : jsonResponse(next);   // a clone: the last answer repeats
  };
  return {fetcher, calls};
}
const cfg = (fetcher, extra = {}) => ({token: TOKEN, appSecret: SECRET, fetcher, sleep: async () => {}, ...extra});

test('appsecret_proof is the hex HMAC-SHA256 of the token keyed with the app secret', async () => {
  assert.equal(await meta.appsecretProof(TOKEN, SECRET), PROOF);
  assert.equal(PROOF, createHmac('sha256', SECRET).update(TOKEN).digest('hex'), 'the known pair is HMAC(secret, token)');
  assert.notEqual(await meta.appsecretProof(TOKEN, 'another-secret'), PROOF);
});

test('every call goes to the versioned base with the token and appsecret_proof, in the query (GET) or the form body (POST), with a timeout', async () => {
  assert.match(meta.GRAPH_BASE, /^https:\/\/graph\.facebook\.com\/v\d+\.0$/);
  const {fetcher, calls} = fakeFetch([fixture('page-info'), fixture('container-created')]);
  await meta.graph(cfg(fetcher), 'GET', `/${PAGE}`, {fields: 'id'});
  await meta.graph(cfg(fetcher), 'POST', `/${IG}/media`, {image_url: 'https://skippercast.com/media/a.jpg', caption: 'x'});
  assert.equal(calls[0].path, `${meta.GRAPH_BASE}/${PAGE}`);
  assert.deepEqual(calls[0].params, {fields: 'id', access_token: TOKEN, appsecret_proof: PROOF});
  assert.equal(calls[1].method, 'POST');
  assert.equal(new URL(calls[1].url).search, '', 'a POST carries nothing in the query');
  assert.equal(calls[1].headers['content-type'], 'application/x-www-form-urlencoded');
  assert.equal(calls[1].params.access_token, TOKEN);
  assert.equal(calls[1].params.appsecret_proof, PROOF);
  for (const c of calls) assert.ok(c.signal instanceof AbortSignal, 'each call has the 20 s timeout signal');
  assert.equal(meta.TIMEOUT_MS, 20_000);
  await assert.rejects(meta.graph(cfg(fetcher), 'GET', '/x?access_token=y'), TypeError);
  await assert.rejects(meta.graph(cfg(fetcher), 'GET', 'x'), TypeError);
});

test('5xx and rate-limit codes 4, 17, 32 and 613 are retried with backoff; a token error is not', async () => {
  const waits = [];
  const sleep = async ms => { waits.push(ms); };
  // 500 then 4 then success.
  let f = fakeFetch([jsonResponse(fixture('error-server'), 500), jsonResponse(fixture('error-rate-limit-4'), 400), fixture('media-published')]);
  const {value} = await quiet(() => meta.graph(cfg(f.fetcher, {sleep}), 'POST', `/${IG}/media_publish`, {creation_id: '1'}));
  assert.deepEqual(value, fixture('media-published'));
  assert.equal(f.calls.length, 3);
  assert.deepEqual(waits, [...meta.BACKOFF_MS]);
  for (const code of [17, 32, 613]) {
    f = fakeFetch([jsonResponse({error: {code, fbtrace_id: 'T'}}, 400), {id: '9'}]);
    assert.deepEqual((await quiet(() => meta.graph(cfg(f.fetcher), 'GET', '/9'))).value, {id: '9'}, `code ${code} retried`);
  }
  // Three rate-limit answers: gives up after MAX_ATTEMPTS.
  f = fakeFetch([jsonResponse(fixture('error-rate-limit-32'), 400)]);
  const failed = await quiet(() => meta.graph(cfg(f.fetcher), 'GET', `/${PAGE}`).catch(e => e));
  assert.ok(failed.value instanceof meta.MetaError);
  assert.equal(failed.value.code, 32);
  assert.equal(f.calls.length, meta.MAX_ATTEMPTS);
  // A token error: one call.
  f = fakeFetch([jsonResponse(fixture('error-invalid-token'), 400)]);
  const bad = await quiet(() => meta.graph(cfg(f.fetcher), 'GET', `/${PAGE}`).catch(e => e));
  assert.equal(bad.value.code, 190);
  assert.equal(bad.value.subcode, 460);
  assert.equal(bad.value.retryable, false);
  assert.equal(f.calls.length, 1);
  // A network failure: retried for a GET, never for a POST (it may have been applied).
  f = fakeFetch([new TypeError('fetch failed'), {id: '1'}]);
  assert.deepEqual((await quiet(() => meta.graph(cfg(f.fetcher), 'GET', '/1'))).value, {id: '1'});
  f = fakeFetch([new TypeError('fetch failed'), {id: '1'}]);
  assert.ok((await quiet(() => meta.graph(cfg(f.fetcher), 'POST', `/${IG}/media`, {image_url: 'https://x/y.jpg'}).catch(e => e))).value instanceof meta.MetaError);
  assert.equal(f.calls.length, 1);
  // attempts: 1 (the health read) never retries.
  f = fakeFetch([jsonResponse(fixture('error-rate-limit-4'), 400), {id: '1'}]);
  await quiet(() => meta.graph(cfg(f.fetcher, {attempts: 1}), 'GET', '/1').catch(() => null));
  assert.equal(f.calls.length, 1);
});

test('error logs carry the status, code, subcode, fbtrace_id and edge, never the token, proof, URL or message', async () => {
  const f = fakeFetch([jsonResponse(fixture('error-invalid-token'), 400)]);
  const {lines} = await quiet(() => meta.graph(cfg(f.fetcher), 'POST', `/${IG}/media_publish`, {creation_id: '17890000000000101'}).catch(() => null));
  assert.equal(lines.length, 1);
  const line = JSON.parse(lines[0]);
  assert.equal(line.event, 'advisor_meta_error');
  assert.deepEqual({edge: line.edge, status: line.status, code: line.code, subcode: line.subcode, fbtrace_id: line.fbtrace_id}, {edge: 'media_publish', status: 400, code: 190, subcode: 460, fbtrace_id: 'APLACEHOLDERTRACE90'});
  const all = lines.join('\n');
  for (const secret of [TOKEN, PROOF, SECRET, 'access_token', 'graph.facebook.com', 'session is invalid']) assert.ok(!all.includes(secret), `${secret} is not logged`);
  // The error object itself holds nothing secret either.
  const e = await quiet(() => meta.graph(cfg(fakeFetch([jsonResponse(fixture('error-rate-limit-4'), 400)]).fetcher, {attempts: 1}), 'GET', '/1').catch(x => x));
  assert.ok(!JSON.stringify({...e.value, message: e.value.message}).includes(TOKEN));
  assert.equal(meta.edgeOf(`/${IG}/content_publishing_limit`), 'content_publishing_limit');
  assert.equal(meta.edgeOf(`/${IG}`), 'node');
});

test('the publishing limit parses quota_usage and config, and rejects a body without them', async () => {
  assert.deepEqual(meta.parsePublishingLimit(fixture('publishing-limit')), {quota_usage: 3, quota_total: 50, quota_duration: 86400});
  assert.deepEqual(meta.parsePublishingLimit({data: [{quota_usage: 0}]}), {quota_usage: 0, quota_total: null, quota_duration: null});
  assert.equal(meta.parsePublishingLimit({data: []}), null);
  assert.equal(meta.parsePublishingLimit(null), null);
  const f = fakeFetch([fixture('publishing-limit')]);
  assert.deepEqual(await meta.igPublishingLimit(cfg(f.fetcher), IG), {quota_usage: 3, quota_total: 50, quota_duration: 86400});
  assert.equal(f.calls[0].path, `${meta.GRAPH_BASE}/${IG}/content_publishing_limit`);
  assert.equal(f.calls[0].params.fields, 'quota_usage,config');
  await assert.rejects(meta.igPublishingLimit(cfg(fakeFetch([{data: []}]).fetcher), IG), meta.MetaError);
});

test('Instagram helpers: container shapes per kind, status, publish and permalink', async () => {
  const img = 'https://skippercast.com/media/m1.jpg', vid = 'https://skippercast.com/media/m2.mp4';
  assert.deepEqual(meta.igContainerParams({kind: 'image', image_url: img, caption: 'c', collaborators: ['a', 'b', 'c', 'd'], user_tags: [{username: 'a', x: 0.5, y: 0.5}]}),
    {image_url: img, caption: 'c', collaborators: '["a","b","c"]', user_tags: '[{"username":"a","x":0.5,"y":0.5}]'});
  assert.deepEqual(meta.igContainerParams({kind: 'reel', video_url: vid, caption: 'c', share_to_feed: true, collaborators: ['a']}),
    {media_type: 'REELS', video_url: vid, share_to_feed: true, caption: 'c', collaborators: '["a"]'});
  assert.deepEqual(meta.igContainerParams({kind: 'story', image_url: img, caption: 'dropped', collaborators: ['a'], user_tags: [{username: 'a', x: 0, y: 0}]}),
    {media_type: 'STORIES', image_url: img}, 'stories take no caption, collaborators or tags');
  assert.deepEqual(meta.igContainerParams({kind: 'carousel_item', image_url: img, caption: 'dropped'}), {is_carousel_item: true, image_url: img});
  assert.deepEqual(meta.igContainerParams({kind: 'carousel_item', video_url: vid}), {is_carousel_item: true, media_type: 'VIDEO', video_url: vid});
  assert.deepEqual(meta.igContainerParams({kind: 'carousel', children: ['1', '2'], caption: 'c'}), {media_type: 'CAROUSEL', children: '1,2', caption: 'c'});
  assert.throws(() => meta.igContainerParams({kind: 'carousel', children: ['1']}), TypeError);
  assert.throws(() => meta.igContainerParams({kind: 'image', image_url: 'http://x/y.jpg'}), TypeError);
  assert.throws(() => meta.igContainerParams({kind: 'image'}), TypeError);

  const f = fakeFetch([fixture('container-created'), fixture('container-in-progress'), fixture('container-finished'), fixture('media-published'), fixture('permalink')]);
  const c = cfg(f.fetcher);
  assert.equal(await meta.igContainer(c, IG, {kind: 'image', image_url: img, caption: 'c'}), '17890000000000101');
  assert.deepEqual(await meta.igContainerStatus(c, '17890000000000101'), {status_code: 'IN_PROGRESS', status: 'In Progress: Media is still being processed.'});
  assert.equal((await meta.igContainerStatus(c, '17890000000000101')).status_code, 'FINISHED');
  assert.equal(await meta.igPublish(c, IG, '17890000000000101'), '17890000000000202');
  assert.equal(await meta.igPermalink(c, '17890000000000202'), 'https://www.instagram.com/p/PLACEHOLDER0001/');
  assert.deepEqual(f.calls.map(x => `${x.method} ${x.path.slice(meta.GRAPH_BASE.length)}`), [
    `POST /${IG}/media`, 'GET /17890000000000101', 'GET /17890000000000101', `POST /${IG}/media_publish`, 'GET /17890000000000202']);
  assert.equal(f.calls[1].params.fields, 'status_code,status');
  assert.equal(f.calls[3].params.creation_id, '17890000000000101');
  assert.equal(f.calls[4].params.fields, 'permalink');
  await assert.rejects(meta.igPublish(c, '../me', '1'), TypeError, 'ids are checked before they reach a path');
});

test('Facebook Page helpers: photo (now and scheduled), the 3-phase Reel upload, a photo Story and the page info', async () => {
  let f = fakeFetch([fixture('page-photo'), fixture('page-photo')]);
  assert.deepEqual(await meta.fbPhoto(cfg(f.fetcher), PAGE, {url: 'https://skippercast.com/media/m1.jpg', message: 'Hello'}), {id: '100000000000301', post_id: '100000000000001_100000000000302'});
  await meta.fbPhoto(cfg(f.fetcher), PAGE, {url: 'https://skippercast.com/media/m1.jpg', message: 'Later', scheduled_publish_time: 1791200000});
  assert.equal(f.calls[0].path, `${meta.GRAPH_BASE}/${PAGE}/photos`);
  assert.deepEqual({url: f.calls[0].params.url, message: f.calls[0].params.message, published: f.calls[0].params.published}, {url: 'https://skippercast.com/media/m1.jpg', message: 'Hello', published: 'true'});
  assert.deepEqual({published: f.calls[1].params.published, at: f.calls[1].params.scheduled_publish_time}, {published: 'false', at: '1791200000'});

  f = fakeFetch([fixture('reel-start'), fixture('reel-upload'), fixture('reel-finish')]);
  assert.deepEqual(await meta.fbVideoReel(cfg(f.fetcher), PAGE, {video_url: 'https://skippercast.com/media/m2.mp4', description: 'Reel'}), {video_id: '100000000000401', post_id: '100000000000402'});
  assert.equal(f.calls[0].path, `${meta.GRAPH_BASE}/${PAGE}/video_reels`);
  assert.equal(f.calls[0].params.upload_phase, 'start');
  assert.equal(f.calls[1].path, `${meta.RUPLOAD_BASE}/100000000000401`);
  assert.deepEqual(f.calls[1].headers, {Authorization: `OAuth ${TOKEN}`, file_url: 'https://skippercast.com/media/m2.mp4'});
  assert.deepEqual({phase: f.calls[2].params.upload_phase, video: f.calls[2].params.video_id, state: f.calls[2].params.video_state, description: f.calls[2].params.description},
    {phase: 'finish', video: '100000000000401', state: 'PUBLISHED', description: 'Reel'});
  assert.equal(f.calls[2].params.appsecret_proof, PROOF);

  f = fakeFetch([fixture('page-photo'), fixture('photo-story')]);
  assert.deepEqual(await meta.fbPhotoStory(cfg(f.fetcher), PAGE, {url: 'https://skippercast.com/media/m1.jpg'}), {photo_id: '100000000000301', post_id: '100000000000501'});
  assert.equal(f.calls[0].params.published, 'false');
  assert.equal(f.calls[1].path, `${meta.GRAPH_BASE}/${PAGE}/photo_stories`);
  assert.equal(f.calls[1].params.photo_id, '100000000000301');

  f = fakeFetch([fixture('page-info')]);
  assert.deepEqual(await meta.pageInfo(cfg(f.fetcher), PAGE), {id: PAGE, name: 'SkipperCast', instagram: {id: IG, username: 'skippercast'}});
  assert.equal(f.calls[0].params.fields, 'id,name,instagram_business_account{id,username}');
});

test('metaConfigured needs the app secret, the Page token and both ids; META_IG_TOKEN is not used', () => {
  const full = {META_APP_SECRET: 's', META_PAGE_TOKEN: 't', META_IG_USER_ID: IG, META_PAGE_ID: PAGE};
  assert.equal(meta.metaConfigured(full), true);
  for (const k of Object.keys(full)) assert.equal(meta.metaConfigured({...full, [k]: ''}), false, k);
  assert.equal(meta.metaConfigured({META_IG_TOKEN: 'x', META_APP_SECRET: 's', META_IG_USER_ID: IG, META_PAGE_ID: PAGE}), false);
  assert.deepEqual(meta.metaConfig(full), {token: 't', appSecret: 's'});
});

dbTest('admin health: meta not configured makes no call; configured reads the quota once and caches it for 10 minutes; a failure shows unavailable', async () => {
  const {db} = advisorDatabase();
  const T0 = Date.parse('2026-10-04T15:00:00Z');
  const none = fakeFetch([fixture('publishing-limit')]);
  assert.deepEqual((await adminHealth({DB: db}, T0, {metaFetcher: none.fetcher})).meta, {configured: false, quota_usage: null, quota_total: null, checked_at: null, error: null});
  assert.equal(none.calls.length, 0);
  const env = {DB: db, META_APP_SECRET: SECRET, META_PAGE_TOKEN: TOKEN, META_IG_USER_ID: IG, META_PAGE_ID: PAGE};
  const f = fakeFetch([fixture('publishing-limit')]);
  const first = await metaHealth(env, T0, f.fetcher);
  assert.deepEqual(first, {configured: true, quota_usage: 3, quota_total: 50, checked_at: new Date(T0).toISOString(), error: null});
  assert.deepEqual(await metaHealth(env, T0 + META_QUOTA_TTL_MS - 1, f.fetcher), first, 'cached');
  assert.equal(f.calls.length, 1);
  assert.equal(f.calls[0].params.appsecret_proof, PROOF);
  const g = fakeFetch([jsonResponse(fixture('error-rate-limit-4'), 400)]);
  const {value: later} = await quiet(() => metaHealth(env, T0 + META_QUOTA_TTL_MS, g.fetcher));
  assert.deepEqual(later, {configured: true, quota_usage: null, quota_total: null, checked_at: new Date(T0 + META_QUOTA_TTL_MS).toISOString(), error: 'unavailable'});
  assert.equal(g.calls.length, 1, 'one try in a health read');
  const stored = JSON.parse((await db.prepare('SELECT value FROM job_state WHERE key=?').bind(META_QUOTA_KEY).first()).value);
  assert.equal(stored.error, 'unavailable');
  assert.ok(!JSON.stringify(stored).includes(TOKEN));
});

test('meta-token.mjs: the dialog URL has the scopes, the pasted address gives the code, and the run prints the Page id, token and IG id without writing a file', async () => {
  const url = new URL(script.dialogUrl('100000000000999', script.DEFAULT_REDIRECT, 'state123'));
  assert.equal(url.origin + url.pathname, `https://www.facebook.com/${meta.GRAPH_VERSION}/dialog/oauth`);
  assert.equal(url.searchParams.get('scope'), 'pages_show_list,pages_read_engagement,pages_manage_posts,pages_manage_metadata,pages_messaging,instagram_basic,instagram_content_publish,instagram_manage_comments,instagram_manage_messages,instagram_manage_insights,business_management');
  assert.equal(url.searchParams.get('response_type'), 'code');
  const code = 'AQPLACEHOLDERCODE0123456789';
  assert.equal(script.parseCode(`${script.DEFAULT_REDIRECT}?code=${code}&state=state123#_=_`, 'state123'), code);
  assert.throws(() => script.parseCode(`${script.DEFAULT_REDIRECT}?code=${code}&state=other`, 'state123'), /state/);
  assert.throws(() => script.parseCode(`${script.DEFAULT_REDIRECT}?error=access_denied&error_reason=user_denied&state=state123`, 'state123'), /not approved/);
  assert.equal(script.parseCode(code, 's'), code);
  assert.throws(() => script.parseArgs(['--secret', 'x']), /usage/);

  const igUnknownField = jsonResponse(fixture('error-unknown-field'), 400);
  const {fetcher, calls} = fakeFetch([fixture('oauth-short'), fixture('oauth-long'), fixture('me-accounts'), igUnknownField, {id: IG, username: 'skippercast'}, fixture('publishing-limit'), fixture('debug-token-never')]);
  const out = [];
  let asked = '';
  const ask = async () => { const state = new URL(out.find(l => l.includes('dialog/oauth')).trim()).searchParams.get('state'); asked = state; return `${script.DEFAULT_REDIRECT}?code=${code}&state=${state}`; };
  const env = {META_APP_ID: '100000000000999', META_APP_SECRET: SECRET};
  const {value: status} = await quiet(() => script.main([], {env, fetcher, ask, log: l => out.push(l)}));
  assert.equal(status, 0);
  assert.ok(asked);
  const text = out.join('\n');
  assert.match(text, /META_PAGE_ID +100000000000001/);
  assert.match(text, /META_PAGE_TOKEN +EAAB-PLACEHOLDER-PAGE-TOKEN/);
  assert.match(text, new RegExp(`META_IG_USER_ID +${IG}`));
  assert.match(text, /does not expire/);
  assert.match(text, /3 of 50/);
  assert.match(text, /did not return it/);
  // The exchanges: code -> short -> long (client_secret, no proof), then Graph calls with the long user token's proof, then the Page token's.
  assert.equal(calls[0].params.code, code);
  assert.equal(calls[1].params.grant_type, 'fb_exchange_token');
  assert.equal(calls[1].params.fb_exchange_token, 'EAAB-PLACEHOLDER-SHORT-USER-TOKEN');
  assert.equal(calls[2].path, `${meta.GRAPH_BASE}/me/accounts`);
  assert.equal(calls[2].params.access_token, 'EAAB-PLACEHOLDER-LONG-USER-TOKEN');
  assert.equal(calls[2].params.appsecret_proof, createHmac('sha256', SECRET).update('EAAB-PLACEHOLDER-LONG-USER-TOKEN').digest('hex'));
  assert.equal(calls[5].path, `${meta.GRAPH_BASE}/${IG}/content_publishing_limit`);
  assert.equal(calls[5].params.access_token, 'EAAB-PLACEHOLDER-PAGE-TOKEN');
  const source = readFileSync(new URL('../scripts/advisor/meta-token.mjs', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /writeFile|appendFile|createWriteStream/, 'the script never writes the secrets to disk');
  // A Creator account fails the run.
  const creator = fakeFetch([fixture('oauth-short'), fixture('oauth-long'), fixture('me-accounts'), {id: IG, username: 'skippercast', account_type: 'MEDIA_CREATOR'}, fixture('publishing-limit'), fixture('debug-token-never')]);
  const lines = [];
  const {value: bad} = await quiet(() => script.main([], {env, fetcher: creator.fetcher, ask: async () => { const s = new URL(lines.find(l => l.includes('dialog/oauth')).trim()).searchParams.get('state'); return `${script.DEFAULT_REDIRECT}?code=${code}&state=${s}`; }, log: l => lines.push(l)}));
  assert.equal(bad, 1);
  assert.match(lines.join('\n'), /not BUSINESS/);
  await assert.rejects(script.main([], {env: {}, fetcher, ask, log: () => {}}), /META_APP_ID/);
});

test('deploy wiring: the workflow passes the META_* secrets, and the deploy uploads each only when set (META_IG_TOKEN stays out)', () => {
  const NAMES = ['META_APP_ID', 'META_APP_SECRET', 'META_VERIFY_TOKEN', 'META_IG_USER_ID', 'META_PAGE_ID', 'META_PAGE_TOKEN'];
  const workflow = readFileSync(new URL('../.github/workflows/deploy-cloudflare.yml', import.meta.url), 'utf8');
  for (const n of NAMES) assert.match(workflow, new RegExp(`^ {10}${n}: \\$\\{\\{ secrets\\.${n} \\}\\}$`, 'm'), n);
  assert.doesNotMatch(workflow, /META_IG_TOKEN/);
  const sh = readFileSync(new URL('../scripts/cloudflare_deploy.sh', import.meta.url), 'utf8');
  const python = sh.slice(sh.indexOf("python3 - <<'PY' > var/cloudflare-secrets.json") + "python3 - <<'PY' > var/cloudflare-secrets.json".length, sh.indexOf('\nPY\n')).trim();
  const dir = mkdtempSync(join(tmpdir(), 'secrets-'));
  try {
    const file = join(dir, 'secrets.py');
    writeFileSync(file, python);
    const run = env => JSON.parse(spawnSync('python3', [file], {encoding: 'utf8', env: {PATH: process.env.PATH, ...env}}).stdout);
    const all = Object.fromEntries(NAMES.map(n => [n, `v-${n}`]));
    assert.deepEqual(run({...all, META_IG_TOKEN: 'unused'}), all);
    assert.deepEqual(run({META_PAGE_TOKEN: 't'}), {META_PAGE_TOKEN: 't'});
    assert.deepEqual(run({}), {});
  } finally { rmSync(dir, {recursive: true, force: true}); }
});
