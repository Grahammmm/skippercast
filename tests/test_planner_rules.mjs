// SC2037-11: the planner states each target species' rules on the plan's date (web/app/PlanRules.tsx), from the frozen FE-61
// registry (tests/fixtures/regulations/fe61-v1.json) with synthetic source checks and a frozen clock. Offline.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import test, {after} from 'node:test';
import {build} from 'esbuild';
import {rendererPlugin} from './helpers/esbuild-url.mjs';

const realFetch = globalThis.fetch;
globalThis.fetch = async () => { throw new Error('no network in this test'); };
const hookStub = {name: 'hook-stub', setup: b => {
  b.onResolve({filter: /^preact\/hooks$/}, a => a.importer.endsWith('web/app/PlanRules.tsx') ? {path: 'hooks', namespace: 'hook-stub'} : null);
  b.onLoad({filter: /.*/, namespace: 'hook-stub'}, () => ({contents: 'export const useEffect = () => {};', loader: 'js'}));
}};
const dir = await mkdtemp(join(tmpdir(), 'planner-rules-')), out = join(dir, 'ui.mjs');
await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
    export {PlanRules, planRuleLine, ruleSpecies, CHECK_RULES, NOT_LEGAL_ADVICE} from './web/app/PlanRules.tsx';
    export {regsData} from './web/regs.ts';
    export {render} from 'preact-render-to-string'; export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: [rendererPlugin, hookStub]});
const m = await import(pathToFileURL(out).href);
after(async () => { globalThis.fetch = realFetch; m.regsData.value = null; await rm(dir, {recursive: true, force: true}); });

const fixture = JSON.parse(readFileSync(new URL('./fixtures/regulations/fe61-v1.json', import.meta.url)));
const MORRO = fixture.region, HOUR = 3600000;
const NOW = Date.parse('2026-10-12T18:00:00Z');
function data(at = NOW) {
  const d = structuredClone(fixture.regulations);
  d.reviewed_at = new Date(at - HOUR).toISOString();
  d.rules_review_status = 'reviewed';
  for (const [id, source] of Object.entries(d.sources)) {
    source.approved_content_sha256 = 'a'.repeat(64);
    d.checks[id] = {url: source.url, normalization: source.normalization, status: 'unchanged', source_status: 'ok', content_sha256: 'a'.repeat(64), data_retrieved_at: new Date(at).toISOString()};
  }
  return d;
}
const html = (d, species, date = '2026-10-14', loaded = d) => {
  m.regsData.value = loaded ? {region: 'morro-bay', data: loaded} : null;
  return m.render(m.h(m.PlanRules, {date, species, region: {id: 'morro-bay', timezone: 'America/Los_Angeles'}, now: NOW}));
};
const text = s => s.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');

test('an open species reads open with its limits, verified date, freshness and the one official link', () => {
  const t = text(html(data(), 'lingcod')), line = m.planRuleLine(data(), 'lingcod', '2026-10-14', MORRO, NOW);
  assert.equal(line.kind, 'open');
  assert.match(t, /Open/); assert.match(t, /2 per person daily/); assert.match(t, /Verified Oct 12/); assert.match(t, /Checked today/);
  assert.doesNotMatch(t, new RegExp(m.CHECK_RULES));
  assert.equal((html(data(), 'lingcod').match(/<a /g) ?? []).length, 1);
  assert.match(html(data(), 'lingcod'), /href="https:\/\/[^"]+"/);
  assert.match(t, new RegExp(m.NOT_LEGAL_ADVICE));
});

test('a closed date says closed plainly, never open', () => {
  const d = data(); d.species.lingcod.windows = [{start: '2026-04-01', end: '2026-10-31'}];
  const out = html(d, 'lingcod', '2026-11-10'), t = text(out), line = m.planRuleLine(d, 'lingcod', '2026-11-10', MORRO, NOW);
  assert.equal(line.kind, 'closed');
  assert.match(t, /Closed on 2026-11-10/);
  assert.doesNotMatch(t, /\bOpen\b/);
  assert.doesNotMatch(out, /Check the official rules/);
});

test('a depth or area limit reads as that, not open', () => {
  const d = data();
  d.species.lingcod.windows = d.species.lingcod.windows.map(w => ({...w, geography: {kind: 'latitude-band', south: 34.5, north: 36, source_id: d.species.lingcod.source_ids[0], note: 'Synthetic band.'}}));
  const out = html(d, 'lingcod'), t = text(out), line = m.planRuleLine(d, 'lingcod', '2026-10-14', MORRO, NOW);
  assert.equal(line.kind, 'check');
  assert.match(t, /applies only within a geographic area/); assert.match(t, /Check the official rules before this trip/);
  assert.doesNotMatch(t, /Verified/); assert.doesNotMatch(out, /data-status="open"/);
});

test('stale, overdue and not-reviewed rules read check the official rules, never open', () => {
  const stale = data(NOW - 50 * HOUR), overdue = data(NOW - 30 * HOUR), unreviewed = data(); unreviewed.rules_review_status = 'draft';
  const outside = data();
  for (const [d, date, label] of [[stale, '2026-10-14', 'stale'], [overdue, '2026-10-14', 'overdue'], [unreviewed, '2026-10-14', 'not reviewed'], [outside, '2027-03-01', 'outside the reviewed period']]) {
    const out = html(d, 'lingcod', date), t = text(out);
    assert.equal(m.planRuleLine(d, 'lingcod', date, MORRO, NOW).kind, 'check', label);
    assert.match(t, /Check the official rules before this trip/, label);
    assert.doesNotMatch(out, /data-status="open"/, label);
    assert.doesNotMatch(t, /Verified/, label);
    assert.match(out, /href="https:\/\//, label);
  }
});

test('no rules loaded reads check the official rules with the official link and no open badge', () => {
  const out = html(null, 'lingcod', '2026-10-14', null), t = text(out);
  assert.match(t, /Check the official rules before this trip/); assert.doesNotMatch(out, />Open</);
  assert.doesNotMatch(out, /data-status="open"/); assert.match(out, /href="https:\/\//);
  m.regsData.value = {region: 'other-region', data: data()};
  assert.match(text(m.render(m.h(m.PlanRules, {date: '2026-10-14', species: 'lingcod', region: {id: 'morro-bay'}, now: NOW}))), /Check the official rules/);
});

test('reef gives a line each for lingcod and rockfish; no date gives nothing', () => {
  assert.deepEqual(m.ruleSpecies('reef'), ['lingcod', 'rockfish']);
  assert.deepEqual(m.ruleSpecies('lingcod'), ['lingcod']);
  const out = html(data(), 'reef');
  assert.equal((out.match(/class="plan-rule"/g) ?? []).length, 2);
  assert.match(text(out), /Lingcod/); assert.match(text(out), /Rockfish/);
  assert.equal(html(data(), 'reef', ''), '');
});

test('the rules block is not part of the plan, the GPX or the saved trip', () => {
  for (const f of ['../web/planner.ts', '../dist/trip-export.js', '../web/trip.ts']) {
    const src = readFileSync(new URL(f, import.meta.url), 'utf8');
    assert.doesNotMatch(src, /PlanRules|planRuleLine|regulationState/, f);
  }
});
