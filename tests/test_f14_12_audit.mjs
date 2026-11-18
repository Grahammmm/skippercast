import assert from 'node:assert/strict';
import test from 'node:test';
import {degraded, watchDegraded} from '../web/degraded.ts';

const yesterday = Date.parse('2026-11-17T23:59:30Z');
const today = Date.parse('2026-11-18T00:00:30Z');
const oldSaved = '2026-11-15T12:00:00.000Z';
const feed = '/feeds/conditions/example.json';
const marked = since => new Response('{}', {headers: {
  'X-SC-Degraded': 'cost-ceiling', ...(since ? {'X-SC-Last-Known-At': since} : {}),
}});
const liveHeaders = ms => ({Date: new Date(ms).toUTCString(), 'X-Feed-Source': 'r2', 'X-SC-Cache': 'miss'});

// Node's constructed Responses have no URL/type. Supply the browser metadata
// alongside the Worker headers without using a real transport or looking at the body.
function reply(path, headers, status = 200, type = 'basic') {
  const response = new Response('{}', {headers, status});
  return Object.defineProperties(response, {type: {value: type}, url: {value: `https://example.test${path}`}});
}

test('a marked day survives unverified responses but a later live refresh retires only its notice', async t => {
  t.mock.timers.enable({apis: ['Date'], now: yesterday});
  // Drive the production wrapper: unchanged main sticks at yesterday's since
  // even after the refresh, while clearing just because midnight passed fails the controls.
  let response;
  const read = watchDegraded(async () => response);
  const send = async (value, path = feed) => {
    response = value;
    assert.equal(await read(path), value, 'fetch returns the original response');
  };
  const saved = marked(oldSaved);
  await send(saved);
  await send(reply(feed, liveHeaders(yesterday)));
  assert.deepEqual(degraded.peek(), {since: oldSaved}, 'not even a same-day live read clears the mark');

  let finishYesterday;
  const pending = watchDegraded(() => new Promise(resolve => { finishYesterday = resolve; }))(feed);
  t.mock.timers.setTime(today);
  for (const [reason, value, path] of [
    ['unrelated asset', reply('/data/example.json', liveHeaders(today)), '/data/example.json'],
    ['yesterday’s live HTTP response', reply(feed, liveHeaders(yesterday))],
    ['undated response', reply(feed, {'X-Feed-Source': 'r2'})],
    ['edge cache hit', reply(feed, {...liveHeaders(today), 'X-SC-Cache': 'hit'})],
    ['HTTP cache replay', reply(feed, {...liveHeaders(today), Age: '15'})],
    ['offline copy', reply(feed, {...liveHeaders(today), 'X-SC-Offline': oldSaved})],
    ['last-known copy', reply(feed, {...liveHeaders(today), 'X-SC-Last-Known-At': oldSaved})],
    ['free tile fallback', reply('/feeds/tiles/example.pmtiles', {...liveHeaders(today), 'X-Feed-Source': 'assets'}), '/feeds/tiles/example.pmtiles'],
    ['failed feed', reply(feed, liveHeaders(today), 503)],
    ['non-local response', reply(feed, liveHeaders(today), 200, 'cors')],
  ]) {
    await send(value, path);
    assert.deepEqual(degraded.peek(), {since: oldSaved}, `${reason} cannot clear the notice`);
  }

  const live = reply(feed, liveHeaders(today));
  await send(live);
  assert.equal(degraded.peek(), null, 'a verified later-day live read clears the notice');
  assert.equal(saved.headers.get('X-SC-Degraded'), 'cost-ceiling');
  assert.equal(saved.headers.get('X-SC-Last-Known-At'), oldSaved);
  assert.equal(await saved.text(), '{}');
  finishYesterday(marked(oldSaved));
  await pending;
  assert.equal(degraded.peek(), null, 'a prior-day request finishing late cannot restore the notice');

  // The current day can still hit its own ceiling, even if the saved copy
  // it serves is from before midnight. That copy's time is not its budget day.
  await send(marked(oldSaved));
  await send(live);
  assert.deepEqual(degraded.peek(), {since: oldSaved});

  const tomorrow = today + 86_400_000;
  t.mock.timers.setTime(tomorrow);
  await send(marked());
  assert.deepEqual(degraded.peek(), {since: null}, 'a new day’s undated fallback does not inherit an old copy time');
  const path = '/api/daily?part=brief';
  await send(reply(path, {Date: new Date(tomorrow).toUTCString(), 'X-SC-Cache': 'miss'}), path);
  assert.deepEqual(degraded.peek(), {since: null}, 'a current day mark still wins over an API miss');
  const later = tomorrow + 86_400_000;
  t.mock.timers.setTime(later);
  await send(reply(path, {Date: new Date(later).toUTCString(), 'X-SC-Cache': 'miss'}), path);
  assert.equal(degraded.peek(), null, 'an uncached regional API refresh also proves recovery');
});
