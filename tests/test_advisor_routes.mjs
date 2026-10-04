// The Text Advisor's mount and hard switch (server/routes/advisor.ts, server/advisor/gate.ts):
// one app instance, two envs. Off, every reserved advisor path is a JSON 404 and never
// falls through to the static site; on, /api/advisor/health answers without secrets.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {default: worker} = await import('../server/index.ts');
const {SECURITY_HEADERS} = await import('../server/security-headers.ts');

// Static assets answer 299 with the path, so a fall-through to the site is visible.
const ASSETS = {fetch: async request => new Response(new URL(request.url).pathname, {status: 299})};
const ORIGIN = 'https://skippercast.com';
const get = (path, env) => worker.fetch(new Request(ORIGIN + path), {ASSETS, ...env});
const OFF = {}, ON = {TEXT_ADVISOR_ENABLED: 'true'};
const RESERVED = ['/api/advisor/health', '/api/advisor/inbound/bluebubbles/x', '/ports/morro-bay', '/ports/x', '/species/lingcod',
  '/boats/some-boat', '/media/abc.jpg', '/u/token', '/contact.vcf', '/text', '/qr/text.svg',
  // Hono's "/x/*" also matches "/x"; no site page lives at these bare paths.
  '/api/advisor', '/ports', '/species', '/boats', '/media', '/u', '/qr'];

test('with the flag off every reserved advisor path is a JSON 404, never the static site', async () => {
  for (const env of [OFF, {TEXT_ADVISOR_ENABLED: 'false'}, {TEXT_ADVISOR_ENABLED: 'yes'}]) {
    for (const path of RESERVED) {
      const response = await get(path, env);
      assert.equal(response.status, 404, `${path} with ${JSON.stringify(env)}`);
      assert.equal((await response.json()).error, 'Not found', path);
      for (const [name, value] of Object.entries(SECURITY_HEADERS)) assert.equal(response.headers.get(name), value, `${path}: ${name}`);
    }
  }
});

test('the same app answers /api/advisor/health once the flag is on, with no secret and no number', async () => {
  assert.equal((await get('/api/advisor/health', OFF)).status, 404);
  const env = {...ON, ADVISOR_NUMBER: '+18055550123', ADVISOR_WEBHOOK_TOKEN: 'secret-token', ANTHROPIC_API_KEY: 'sk-secret', ADVISOR_CHANNEL: 'twilio', ADVISOR_VISION_PROVIDERS: 'claude'};
  const response = await get('/api/advisor/health', env);
  assert.equal(response.status, 200);
  assert.equal(response.headers.get('Cache-Control'), 'no-store');
  const text = await response.text();
  assert.deepEqual(JSON.parse(text), {enabled: true, channel: 'twilio', providers: ['claude'], relay: null}, 'no D1: relay unknown');
  for (const leak of ['8055550123', 'secret-token', 'sk-secret']) assert.ok(!text.includes(leak), leak);
  assert.deepEqual(await (await get('/api/advisor/health', ON)).json(), {enabled: true, channel: 'bluebubbles', providers: ['hermes', 'claude'], relay: null});
  // And off again on the next request: the switch is read per request, not at module load.
  assert.equal((await get('/api/advisor/health', OFF)).status, 404);
});

test('advisor prefixes are exact: neighbouring site paths still reach the static site, flag on or off', async () => {
  for (const env of [OFF, ON]) {
    for (const path of ['/', '/species.js', '/species-research.html', '/portsx', '/textx', '/text/', '/contact.vcfx', '/qrx', '/index.html']) {
      const response = await get(path, env);
      assert.equal(response.status, 299, `${path} with ${JSON.stringify(env)}`);
    }
  }
});

test('an unrouted advisor path with the flag on is not served by the site', async () => {
  // Later tasks add these routes; until then /api/advisor/* falls to the /api/ 404 handling and pages to the site.
  assert.notEqual((await get('/api/advisor/nope', ON)).status, 299);
});
