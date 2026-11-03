// RF1240-17: the request-id middleware adds `request_id` to every 4xx/5xx JSON
// error body whatever the Content-Type spelling (parameters, letter case), and
// leaves every other response untouched.
import test from 'node:test';
import assert from 'node:assert/strict';
import {Hono} from 'hono';
import {requestId} from '../server/middleware/request-id.ts';

const ERROR = JSON.stringify({error: 'x'});
const ROUTES = {
  '/charset': [400, 'application/json; charset=utf-8', ERROR],
  '/upper': [400, 'Application/JSON', ERROR],
  '/spaced': [422, 'application/json ; charset=UTF-8', ERROR],
  '/exact': [404, 'application/json', ERROR],
  '/jsonx': [400, 'application/jsonx', ERROR],
  '/problem': [400, 'application/problem+json', ERROR],
  '/text': [400, 'text/plain', ERROR],
  '/ok': [200, 'application/json; charset=utf-8', ERROR],
  '/array': [500, 'application/json; charset=utf-8', JSON.stringify([{error: 'x'}])],
  '/kept': [400, 'Application/Json; charset=utf-8', JSON.stringify({error: 'x', request_id: 'theirs123'})],
  '/no-error': [400, 'application/json; charset=utf-8', JSON.stringify({message: 'x'})],
  '/broken': [400, 'application/json; charset=utf-8', '{"error": '],
};
const app = new Hono();
app.use('*', requestId);
for (const [path, [status, type, body]] of Object.entries(ROUTES)) {
  app.get(path, () => new Response(body, {status, headers: {'Content-Type': type}}));
}
const get = (path, headers = {}) => app.request(path, {headers});

async function added(path) {
  const response = await get(path);
  const [status, type] = ROUTES[path];
  const id = response.headers.get('X-Request-Id');
  assert.equal(response.status, status);
  assert.equal(response.headers.get('Content-Type'), type, 'original Content-Type text kept');
  assert.deepEqual(await response.json(), {error: 'x', request_id: id});
  assert.match(id, /^[\w-]{8,64}$/);
}

async function untouched(path) {
  const response = await get(path);
  const [status, type, body] = ROUTES[path];
  assert.equal(response.status, status);
  assert.equal(response.headers.get('Content-Type'), type);
  assert.match(response.headers.get('X-Request-Id'), /^[\w-]{8,64}$/);
  assert.equal(await response.text(), body);
}

test('a JSON error with a charset gets request_id equal to X-Request-Id', () => added('/charset'));
test('other letter case and spaces before the parameters still count as JSON', async () => {
  await added('/upper');
  await added('/spaced');
});
test('exact application/json keeps getting request_id', () => added('/exact'));
test('a media type that only resembles JSON is untouched', async () => {
  for (const path of ['/jsonx', '/problem', '/text']) await untouched(path);
});
test('success, array, already-tagged and error-less JSON bodies are untouched', async () => {
  for (const path of ['/ok', '/array', '/kept', '/no-error']) await untouched(path);
});
test('a body that is not valid JSON under a JSON type is returned as is with the header', () => untouched('/broken'));
test('a valid incoming X-Request-Id is the body id; an invalid one is replaced', async () => {
  const kept = await get('/charset', {'X-Request-Id': 'abcd1234'});
  assert.equal(kept.headers.get('X-Request-Id'), 'abcd1234');
  assert.deepEqual(await kept.json(), {error: 'x', request_id: 'abcd1234'});
  const replaced = await get('/upper', {'X-Request-Id': 'bad id'});
  const id = replaced.headers.get('X-Request-Id');
  assert.notEqual(id, 'bad id');
  assert.match(id, /^[\w-]{8,64}$/);
  assert.deepEqual(await replaced.json(), {error: 'x', request_id: id});
});
