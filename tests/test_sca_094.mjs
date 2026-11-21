import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {mkdirSync, mkdtempSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {test} from 'node:test';
import {captureSessions} from '../research/scripts/measure_session_cost.mjs';

const SITE = 'https://capture.invalid';
const MATCH = '1111111111', OTHER = '2222222222';
const REVISION = '1'.repeat(40), CHANGED_REVISION = '2'.repeat(40);
const bundle = build => `/assets/app.${build}.js`;
const health = (build = MATCH, revision = REVISION) => ({service: 'SkipperCast', build, revision});
const shell = build => `<html><head>${build ? `<meta name="skippercast-build" content="${build}">` : ''}</head></html>`;

function reference(t, withIdentity = true) {
  const dir = mkdtempSync(join(tmpdir(), 'sca094-'));
  t.after(() => rmSync(dir, {recursive: true, force: true}));
  mkdirSync(join(dir, 'assets'));
  writeFileSync(join(dir, bundle(MATCH)), '// synthetic asset');
  if (withIdentity) writeFileSync(join(dir, 'precache.json'), JSON.stringify({schema_version: 1, build: MATCH}));
  return dir;
}

// Feed the browser-response boundary without a browser binary, listeners on
// sockets, or outbound requests. All navigations and health probes are inert.
function replay({probe = () => health(), document = () => MATCH, asset = MATCH, failClick = false} = {}) {
  let probes = 0, navigations = 0;
  const browser = {
    async newContext() {
      const context = new EventEmitter();
      const respond = (url, {type = 'fetch', status = 200, bytes = 10, body = '', sw = false} = {}) => {
        context.emit('response', {
          fromServiceWorker: () => sw, url: () => url, status: () => status, text: async () => body,
          request: () => ({resourceType: () => type, sizes: async () => {
            if (bytes === null) throw new Error('size unavailable');
            return {responseBodySize: bytes};
          }}),
        });
      };
      context.request = {async get(url, options) {
        assert.equal(url, SITE + '/api/health');
        assert.equal(options.maxRedirects, 0);
        const data = probe(++probes);
        return {ok: () => true, json: async () => data, dispose: async () => {}};
      }};
      context.newPage = async () => ({
        async goto(url) {
          assert.equal(new URL(url).origin, SITE);
          const build = document(++navigations);
          respond(url, {type: 'document', body: shell(build)});
          respond(SITE + bundle(asset) + '?probe=private-query-marker', {bytes: 31});
          respond(SITE + '/api/daily?region=private-query-marker', {bytes: 9});
          respond(SITE + '/api/daily?region=another-private-marker', {bytes: null});
          respond(SITE + '/api/daily', {status: 503, bytes: 5});
          respond(SITE + '/api/private-path-marker', {bytes: 4});
          respond('https://third-party-marker.invalid/private-path-marker?probe=private-query-marker', {bytes: 7});
          respond(SITE + '/api/daily', {sw: true});
        },
        getByRole: () => ({first: () => ({click: async () => {
          if (failClick) throw new Error('navigation-private-marker');
        }})}),
        locator: () => ({first: () => ({boundingBox: async () => null})}),
        mouse: {move: async () => {}, down: async () => {}, up: async () => {}, wheel: async () => {}},
        waitForLoadState: async () => {}, waitForTimeout: async () => {}, addInitScript: async () => {},
      });
      context.close = async () => {};
      return context;
    },
  };
  return {browser, observations: () => ({probes, navigations})};
}

const group = (kind, route, status, count, bytes, missing_bytes = 0) => ({kind, route, status, count, bytes, missing_bytes});

test('matching builds preserve attribution and fold responses into private route/status aggregates', async t => {
  const {browser, observations} = replay();
  const receipt = await captureSessions(browser, SITE, reference(t));
  assert.deepEqual(observations(), {probes: 6, navigations: 6});
  assert.equal(receipt.reference_build, MATCH);
  assert.equal(receipt.eligible_for_cost_estimates, true);
  assert.equal(receipt.attribution, 'matched');
  assert.deepEqual(receipt.issues, []);
  const rows = receipt.sessions['first-run'];
  assert.deepEqual(rows.sort((a, b) => a.route.localeCompare(b.route) || a.status - b.status), [
    group('worker', '/', 200, 1, 10), group('worker', '/api', 200, 1, 4),
    group('worker', '/api/daily', 200, 2, 9, 1), group('worker', '/api/daily', 503, 1, 5),
    group('asset', '/assets', 200, 1, 31), group('third-party', 'external', 200, 1, 7),
  ]);
  assert.doesNotMatch(JSON.stringify(receipt), /marker|capture\.invalid|app\.1111111111|\?|\/api\/health/);
});

for (const [name, options, issue, withIdentity] of [
  ['missing reference ID', {}, 'reference-build-missing', false],
  ['missing observed ID', {probe: () => ({service: 'SkipperCast'})}, 'health-build-missing'],
  ['different build with an equivalent fingerprinted bundle', {probe: () => health(OTHER), document: () => OTHER, asset: OTHER}, 'health-build-mismatch'],
  ['deployment changes after a session starts', {probe: n => health(n === 4 ? OTHER : MATCH)}, 'health-build-mismatch'],
  ['revision changes without a client rebuild', {probe: n => health(MATCH, n > 3 ? CHANGED_REVISION : REVISION)}, 'deployment-revision-changed'],
  ['transient build seen on an actual document between matching health probes', {document: n => n === 4 ? OTHER : MATCH}, 'document-build-mismatch'],
  ['missing document stamp even with matching health', {document: n => n === 4 ? null : MATCH}, 'document-build-missing'],
  ['foreign fingerprinted asset even with matching health and documents', {asset: OTHER}, 'foreign-fingerprinted-asset'],
  ['browser journey fails after responses have been observed', {failClick: true}, 'session-incomplete'],
]) {
  test(`${name} disqualifies the entire capture`, async t => {
    const {browser} = replay(options);
    const receipt = await captureSessions(browser, SITE, reference(t, withIdentity));
    assert.equal(receipt.attribution, 'unclassified');
    assert.equal(receipt.eligible_for_cost_estimates, false);
    assert.ok(receipt.issues.includes(issue));
    assert.doesNotMatch(JSON.stringify(receipt), /private-marker/);
    for (const rows of Object.values(receipt.sessions)) {
      assert.deepEqual(new Set(rows.map(row => row.kind)), new Set(['unclassified', 'third-party']));
    }
    assert.deepEqual(receipt.sessions['first-run'].find(row => row.route === '/assets'),
      group('unclassified', '/assets', 200, 1, 31));
  });
}
