// The launch preflight (scripts/advisor/preflight.mjs; 11 § Launch checklist):
// offline against a fake deployment. Every checklist item reports PASS, FAIL or
// MANUAL; GET requests only, with the session cookie only on /api/admin/*; the
// rules judge; the argument parser; the cookie never in the output.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync, mkdirSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {parseArgs, runPreflight, formatResults, judgeRules, PILOT_SPECIES, RUNBOOKS, COOKIE} from '../scripts/advisor/preflight.mjs';

const BASE = 'https://example.test', SESSION = 'a'.repeat(43), NOW = Date.parse('2026-10-20T16:00:00Z');
const fresh = '2026-10-10T00:00:00.000Z';
const rule = (species_key, extra = {}) => ({species_key, status: 'active', due: false, reviewed_at: fresh, source_url: 'https://wildlife.ca.gov/x', ...extra});

/** A checkout with the runbooks and a threat model, so the local checks have files to find. */
function checkout({runbooks = RUNBOOKS, threat = '## Text Advisor\n'} = {}) {
  const root = mkdtempSync(join(tmpdir(), 'preflight-'));
  mkdirSync(join(root, 'docs/operations/runbooks'), {recursive: true}); mkdirSync(join(root, 'docs/legal'), {recursive: true});
  for (const name of runbooks) writeFileSync(join(root, `docs/operations/runbooks/${name}.md`), '# x\n');
  writeFileSync(join(root, 'docs/legal/threat-model.md'), threat);
  return root;
}

/** A fake deployment: routes -> [status, body, headers]; records each request. */
function deployment(overrides = {}) {
  const adminHealth = {replies_enabled: true, relay: {state: 'up', failures: 0, checked_at: '2026-10-20T15:45:00Z', last_ok_at: '2026-10-20T15:45:00Z'},
    queue: {stale_queued: 0, oldest_queued_at: null, held_outbound: 0, failed_today: 0}, vision: [{name: 'claude', down_until: null}],
    caps: {day: '2026-10-20', llm: {used: 3, limit: 2000}, vision: {used: 1, limit: 400}}, media_jobs: {pending: 0}, reviews: {open: 1},
    meta: {configured: true, quota_usage: 1, quota_total: 50, checked_at: '2026-10-20T15:50:00Z', error: null}, inbox: {enabled: false, public_replies: false, webhook_ready: true}};
  const routes = {
    '/api/health': [200, {service: 'SkipperCast', build: 'b123'}],
    '/api/advisor/health': [200, {enabled: true, channel: 'bluebubbles', providers: ['claude'], relay: {state: 'up', checked_at: '2026-10-20T15:45:00Z'}}],
    '/api/admin/health': [200, adminHealth],
    [`/api/admin/rules?jurisdiction=california-central`]: [200, {rules: PILOT_SPECIES.map(k => rule(k))}],
    '/api/admin/boats': [200, {boats: ['one', 'two', 'three'].map(slug => ({slug, status: 'verified', consent: 'given'})).concat([{slug: 'four', status: 'pending', consent: 'not given'}])}],
    '/boats/one': [200, '<html>'], '/boats/two': [200, '<html>'], '/boats/three': [200, '<html>'],
    '/contact.vcf': [200, 'BEGIN:VCARD'],
    '/text': [302, '', {location: 'sms:+15555550100?&body=hi'}],
    '/privacy.html': [200, '<h2 id="text-advisor">Text Advisor</h2><p><strong>Automatic deletion.</strong></p>'],
    ...overrides,
  };
  const requests = [];
  const fetcher = async (url, init) => {
    const path = url.slice(BASE.length);
    requests.push({path, method: init?.method ?? 'GET', cookie: init?.headers?.Cookie ?? null});
    const [status, body, headers = {}] = routes[path] ?? [404, {error: 'not found'}];
    return new Response(typeof body === 'string' ? body : JSON.stringify(body), {status, headers});
  };
  return {fetcher, requests, routes};
}
const statusOf = (results, id, title) => results.find(r => r.id === id && (!title || r.title.includes(title)))?.status;

test('parseArgs: base origin, stage, --local; http only for localhost', () => {
  assert.deepEqual(parseArgs([]), {base: 'https://skippercast.com', stage: 'live', local: false, help: false});
  assert.deepEqual(parseArgs(['--base', 'https://skippercast.workers.dev/x', '--stage', 'dark', '--local']), {base: 'https://skippercast.workers.dev', stage: 'dark', local: true, help: false});
  assert.equal(parseArgs(['--base', 'http://localhost:8787']).base, 'http://localhost:8787');
  assert.throws(() => parseArgs(['--base', 'http://skippercast.com']), /https/);
  assert.throws(() => parseArgs(['--stage', 'soon']), /dark or live/);
  assert.throws(() => parseArgs(['--send']), /unknown option/);
});

test('a ready deployment: every automatic item passes, the rest are manual; GET only, the cookie only on /api/admin/*', async () => {
  const d = deployment(), root = checkout();
  const results = await runPreflight({base: BASE, cookie: SESSION, fetcher: d.fetcher, root, now: NOW, local: true, runGolden: () => ({status: 0, stdout: '# pass 10\n# fail 0\n'})});
  const failed = results.filter(r => r.status === 'fail');
  assert.deepEqual(failed, []);
  assert.ok(results.filter(r => r.status === 'pass').length >= 18);
  for (const id of ['1', '3', '4', '6', '7', '8', '10', '12', '13', '15', '17', '18']) assert.ok(results.some(r => r.id === id && r.status === 'manual'), `item ${id} has a manual part`);
  for (const r of results) assert.match(r.id, /^\d{1,2}$/);
  assert.ok(d.requests.every(r => r.method === 'GET'));
  for (const r of d.requests) assert.equal(r.cookie !== null, r.path.startsWith('/api/admin/'), r.path);
  assert.equal(d.requests.find(r => r.cookie)?.cookie, `${COOKIE}=${SESSION}`);
  const text = formatResults(results);
  assert.ok(!text.includes(SESSION), 'the cookie is never printed');
  assert.match(text, /\d+ pass, 0 fail, \d+ manual/);
});

test('what fails: advisor off, no session, replies off on live, stale rules, too few skippers, pending media, no quota, missing runbook and threat model', async () => {
  const off = deployment({'/api/advisor/health': [404, 'Not found']});
  const noSession = await runPreflight({base: BASE, fetcher: off.fetcher, root: checkout(), now: NOW});
  assert.equal(statusOf(noSession, '2'), 'fail');
  assert.match(noSession.find(r => r.id === '10' && r.status === 'fail').detail, /no session/);
  assert.ok(!off.requests.some(r => r.path.startsWith('/api/admin/')), 'no admin call without a session');

  const health = structuredClone(deployment().routes['/api/admin/health'][1]);
  Object.assign(health, {replies_enabled: false, media_jobs: {pending: 2}, meta: {configured: true, quota_usage: null, quota_total: null, checked_at: null, error: 'unavailable'},
    caps: {day: 'x', llm: {used: 0, limit: 5000}, vision: {used: 0, limit: 400}}, queue: {stale_queued: 1, held_outbound: 0, failed_today: 0}});
  const bad = deployment({
    '/api/admin/health': [200, health],
    '/api/admin/rules?jurisdiction=california-central': [200, {rules: [rule('rockfish', {status: 'review'}), ...PILOT_SPECIES.slice(1, -1).map(k => rule(k))]}],
    '/api/admin/boats': [200, {boats: [{slug: 'one', status: 'verified', consent: 'given'}, {slug: 'gone', status: 'verified', consent: 'given'}]}],
    '/privacy.html': [200, '<h2 id="text-advisor">Text Advisor</h2>'],
  });
  const results = await runPreflight({base: BASE, cookie: SESSION, fetcher: bad.fetcher, root: checkout({runbooks: RUNBOOKS.slice(0, -1), threat: '# Threat model\n'}), now: NOW});
  assert.equal(statusOf(results, '5', 'Replies'), 'fail');
  assert.equal(statusOf(results, '5', 'Queue'), 'fail');
  const rules = results.find(r => r.id === '6' && r.status === 'fail');
  assert.match(rules.detail, /rockfish: 1 of 1 not active/); assert.match(rules.detail, /canary: no row/);
  assert.equal(statusOf(results, '8', 'Global caps'), 'fail');
  assert.match(results.find(r => r.id === '11').detail, /2 verified; pages failing: gone 404/);
  assert.equal(statusOf(results, '12', 'quota'), 'fail');
  assert.equal(statusOf(results, '13', 'Media job'), 'fail');
  assert.match(results.find(r => r.id === '14').detail, /missing: advisor-queue-stuck/);
  assert.equal(statusOf(results, '15', 'retention'), 'fail');
  assert.equal(statusOf(results, '16'), 'fail');

  // The dark stage: replies off is what it should be.
  const dark = await runPreflight({base: BASE, cookie: SESSION, stage: 'dark', fetcher: bad.fetcher, root: checkout(), now: NOW});
  assert.equal(statusOf(dark, '5', 'Replies'), 'pass');
});

test('judgeRules: every pilot species needs an active, fresh, sourced row; retired rows are ignored', () => {
  assert.deepEqual(judgeRules(PILOT_SPECIES.map(k => rule(k)), NOW), []);
  const problems = judgeRules([rule('rockfish', {reviewed_at: '2026-08-01T00:00:00Z'}), rule('lingcod', {due: true}), rule('cabezon', {source_url: 'http://x'}),
    rule('halibut', {status: 'retired'})], NOW, ['rockfish', 'lingcod', 'cabezon', 'halibut']);
  assert.deepEqual(problems.map(p => p.split(':')[0]), ['rockfish', 'lingcod', 'cabezon', 'halibut']);
  assert.match(problems[3], /no row/);
});
