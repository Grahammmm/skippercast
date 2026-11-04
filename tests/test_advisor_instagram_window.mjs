// RF1230-16: Instagram replies respect Meta's reply windows when the stored time
// is unreadable or in the future. withinWindow is true only for a readable time at
// most CLOCK_SKEW_MS ahead and at most the window ago; the DM send and the private
// comment reply refuse anything else as 'outside-window' without calling Meta.
// Offline: real migrations in node:sqlite and an injected Graph fetcher.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {createInstagram, commentChannel, withinWindow, CLOCK_SKEW_MS, DM_WINDOW_MS, PRIVATE_REPLY_WINDOW_MS} = await import('../server/advisor/channels/instagram.ts');
const {findOrCreateContact} = await import('../server/advisor/contacts.ts');

const dbTest = (name, fn) => test(name, {skip: sqliteUnavailable || false}, fn);
const fixture = name => read(`./fixtures/advisor/meta/${name}.json`);
const jsonResponse = body => new Response(JSON.stringify(body), {status: 200, headers: {'content-type': 'application/json'}});
const iso = ms => new Date(ms).toISOString();
const T0 = Date.parse('2026-10-04T18:00:00Z');
const MIN = 60000, HOUR = 3600000, DAY = 86400000;
const IG = '17841400000000000', SID = '5550000000000001';
const META = {META_APP_SECRET: 'app-secret-PLACEHOLDER', META_PAGE_TOKEN: 'EAAB-PLACEHOLDER-TOKEN', META_IG_USER_ID: IG, META_PAGE_ID: '100000000000001', META_VERIFY_TOKEN: 'verify-token-PLACEHOLDER'};
const ON = {TEXT_ADVISOR_ENABLED: 'true', ADVISOR_INBOX_ENABLED: 'true', ...META};

/** A recorded Graph API: every request is kept; messages and comment replies answer from the fixtures. */
function graphFake() {
  const calls = [];
  const fetcher = async (url, init = {}) => {
    const path = new URL(url).pathname.replace(/^\/v\d+\.0/, '');
    calls.push({method: init.method ?? 'GET', path});
    if (path === `/${IG}/messages`) return jsonResponse(fixture('message-sent'));
    if (path.endsWith('/replies')) return jsonResponse(fixture('comment-reply'));
    return new Response('{}', {status: 400});
  };
  return {fetcher, calls};
}

/** A fresh database with one Instagram contact and, unless `at` is undefined, one inbound DM stored at `at`. */
async function dmEnv(at) {
  const {sql, db} = advisorDatabase();
  const contact = await findOrCreateContact(db, null, {igSid: SID}, new Date(T0 - 30 * DAY));
  if (at !== undefined) sql.prepare(`INSERT INTO advisor_messages(id,contact_id,direction,channel,provider_id,body,status,created_at) VALUES('in1',?,'in','instagram_dm','mid-1','hi','done',?)`).run(contact.id, at);
  return {...ON, DB: db};
}
async function sendDm(at) {
  const env = await dmEnv(at), graph = graphFake();
  const result = await createInstagram({fetcher: graph.fetcher, now: () => T0}).send({id: 'o1', to: SID, text: 'hello'}, env);
  return {result, calls: graph.calls};
}
const OUTSIDE = {providerId: null, status: 'failed', error: 'outside-window'};

test('withinWindow: a readable age from 0 to the window is inside; past it, unreadable, missing or more than 5 min ahead is outside', () => {
  const W = DM_WINDOW_MS;
  assert.equal(CLOCK_SKEW_MS, 5 * MIN);
  assert.equal(withinWindow(iso(T0), T0, W), true, 'age 0');
  assert.equal(withinWindow(iso(T0 - W), T0, W), true, 'exactly the window is inside');
  assert.equal(withinWindow(iso(T0 - W - 1), T0, W), false, 'one ms past the window');
  for (const at of ['not a time', '', null, undefined]) assert.equal(withinWindow(at, T0, W), false, `unreadable: ${JSON.stringify(at)}`);
  assert.equal(withinWindow(iso(T0 + 4 * MIN), T0, W), true, '4 min ahead is clock skew');
  assert.equal(withinWindow(iso(T0 + CLOCK_SKEW_MS), T0, W), true, 'exactly the skew tolerance');
  assert.equal(withinWindow(iso(T0 + 6 * MIN), T0, W), false, '6 min ahead');
  assert.equal(withinWindow(iso(T0 + DAY), T0, W), false, 'a day ahead');
  assert.equal(withinWindow(iso(T0 - 6 * DAY), T0, PRIVATE_REPLY_WINDOW_MS), true, 'the window length is the argument');
});

dbTest('DM send: 1 h ago is sent; 25 h ago, no inbound DM, an unreadable or a future time is outside-window with no request to Meta', async () => {
  const ok = await sendDm(iso(T0 - HOUR));
  assert.equal(ok.result.status, 'sent');
  assert.equal(ok.calls.length, 1);
  for (const [name, at] of [['25 h ago', iso(T0 - 25 * HOUR)], ['no inbound DM', undefined], ['unreadable', 'not a time'], ['a day in the future', iso(T0 + DAY)], ['6 min in the future', iso(T0 + 6 * MIN)]]) {
    const {result, calls} = await sendDm(at);
    assert.deepEqual(result, OUTSIDE, name);
    assert.equal(calls.length, 0, `${name}: no request`);
  }
  const skew = await sendDm(iso(T0 + 4 * MIN));
  assert.equal(skew.result.status, 'sent', '4 min ahead is within the clock skew');
});

dbTest('private comment reply: 2 days is sent, 8 days or unreadable is outside-window with no request; one reply per comment still holds', async () => {
  const env = {...ON, DB: advisorDatabase().db};
  const reply = (receivedAt, graph) => commentChannel(env, {providerId: '18000000000000001', receivedAt}, 'private', {fetcher: graph.fetcher, now: () => T0});
  const okGraph = graphFake(), ok = reply(iso(T0 - 2 * DAY), okGraph);
  assert.equal((await ok.send({id: 'o1', to: '', text: 'Here is the answer'})).status, 'sent');
  assert.equal(okGraph.calls.length, 1);
  assert.deepEqual(await ok.send({id: 'o2', to: '', text: 'again'}), {providerId: null, status: 'failed', error: 'one-reply'});
  assert.equal(okGraph.calls.length, 1, 'no second reply');
  for (const [name, at] of [['8 days ago', iso(T0 - 8 * DAY)], ['unreadable', 'x'], ['empty', ''], ['a day in the future', iso(T0 + DAY)]]) {
    const graph = graphFake(), channel = reply(at, graph);
    assert.deepEqual(await channel.send({id: 'o1', to: '', text: 'late'}), OUTSIDE, name);
    assert.deepEqual(await channel.send({id: 'o2', to: '', text: 'again'}), {providerId: null, status: 'failed', error: 'one-reply'}, `${name}: still one reply`);
    assert.equal(graph.calls.length, 0, `${name}: no request`);
  }
});

dbTest('public comment reply has no window: an unreadable receivedAt is still sent', async () => {
  const env = {...ON, DB: advisorDatabase().db}, graph = graphFake();
  const channel = commentChannel(env, {providerId: '18000000000000001', receivedAt: 'x'}, 'public', {fetcher: graph.fetcher, now: () => T0});
  assert.equal((await channel.send({id: 'o1', to: '', text: 'Lingcod are open.'})).status, 'sent');
  assert.equal(graph.calls.length, 1);
  assert.ok(graph.calls[0].path.endsWith('/replies'));
});
