// RF2040-4: a text/html range with a repeated q weight cannot override an exclusion into the branded 404.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {withSessions} from './fixtures/test-sessions.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
const PAGE = readFileSync(new URL('../web/404.html', import.meta.url), 'utf8');
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/landing.html': '/landing.0123456789.html', '/app.html': '/app.0123456789.html', '/sources.html': '/sources.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
globalThis.NOT_FOUND_HTML = PAGE;
const {default: deployed} = await import('../server/index.ts');
const {acceptsHtml} = await import('../server/routes/assets.ts');
const worker = withSessions(deployed);

const ASSETS = {fetch: async () => new Response('asset-404-body', {status: 404, headers: {'X-Sentinel': 'asset'}})};
const get = accept => worker.fetch(new Request('https://skippercast.com/nope', {headers: {Accept: accept}}), {ASSETS});

test('html_accept_duplicate_q_cannot_override_zero', async () => {
  assert.equal(acceptsHtml('text/html;q=0;q=1'), false);
  const response = await get('text/html;q=0;q=1');
  assert.equal(response.status, 404);
  assert.equal(response.headers.get('X-Sentinel'), 'asset');
  assert.equal(await response.text(), 'asset-404-body');
});

test('html_accept_duplicate_q_boundary', () => {
  for (const accept of ['text/html;q=0.5;q=0.9', 'text/html;q=1;q=1', 'text/html;q=0.2;Q=0.8', 'text/html; q = 0.2 ; q = 0.8', 'text/html;q=1;q=0.5;q=0.2', 'text/html;q=x;q=1, text/html', 'text/html;q=0;q=1, text/html;q=1']) {
    assert.equal(acceptsHtml(accept), false, accept);
  }
});

test('html_accept_single_weight_control', async () => {
  for (const accept of ['text/html', 'text/html;q=1', 'text/html;q=0.001', 'text/html;level=1;q=0.8']) assert.equal(acceptsHtml(accept), true, accept);
  for (const accept of ['text/html;q=0', '*/*', 'text/*']) assert.equal(acceptsHtml(accept), false, accept);
  const response = await get('text/html;q=0.8');
  assert.equal(response.status, 404);
  assert.equal(response.headers.get('Cache-Control'), 'no-store');
  assert.equal(response.headers.get('Vary'), 'Accept');
  assert.ok((await response.text()) === PAGE, 'authored page');
});

test('html_accept_range_state_is_local', () => {
  assert.equal(acceptsHtml('text/html;q=0.5, text/html;q=0.9'), true);
  assert.equal(acceptsHtml('text/html;q=0.5, text/html;q=0'), false);
  assert.equal(acceptsHtml('text/html;q=0, text/html;q=0.9'), false);
});
