// MYB-3: a target the picker labels "search plan only" (web/species.ts TargetState 'plan') shows that
// search plan in the brief's "Where to look" in place of the empty list; every other case keeps the
// empty text from web/ranking.ts. planFor (web/search-plan.ts) is imported by type stripping; the view
// is bundled with esbuild and rendered to a string, as tests/test_ranking.mjs does.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {planFor, noPlanText} from '../web/search-plan.ts';

const ROOT = new URL('..', import.meta.url).pathname;
const EMPTY = 'No surveyed reef marks within 300 ft for this target.';
const NONE = {source: null, label: '', basis: '', picks: [], empty: EMPTY};
// Invented plans: a region with no coastal terrain or atlas marks, so nothing ranks places and a plan is "search plan only".
const plan = (name, extra = {}) => ({name, kind: 'pelagic', numeric_bite_model: false, search_for: `${name}: search for bait.`, habitat: 'Temperature edges.',
  timing: 'Seasonal.', required_to_confirm: ['Legal access', 'Conditions'], tactics_basis: `${name} basis line.`, ...extra});
const PLANS_A = {chinook: plan('Chinook salmon'), modelled: plan('Modelled fish', {numeric_bite_model: true})};
const PLANS_B = {chinook: plan('Other region salmon', {habitat: 'Region B habitat only.', caution: 'Region B caution.'})};

let view;
async function loadView() {
  if (view) return view;
  const out = join(await mkdtemp(join(tmpdir(), 'search-plan-')), 'view.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {WhereToLook} from './web/brief/WhereToLook.tsx';
      export {regionPlans} from './web/species.ts';
      export {regionInfo} from './web/app/region-info.ts';
      export {region, species, profile} from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: [{name: 'renderers', setup: b => b.onResolve({filter: /^\.\/(?:terrain|maplibre)\.js$/}, args => ({path: args.path, external: true}))}],
  });
  view = await import(pathToFileURL(out).href);
  return view;
}
/** Render "Where to look" for `target` in `id` with `plans` loaded for `plansRegion` and the given ranking. */
async function where({id = 'test-bay', target = 'chinook', plans = PLANS_A, plansRegion = id, ranking = NONE, name = 'Test Bay'} = {}) {
  const m = await loadView();
  m.profile.value = 'boat';
  m.region.value = id;
  m.species.value = target;
  m.regionInfo.value = name ? {id, name, center: [35, -121], timezone: 'America/Los_Angeles'} : null;
  m.regionPlans.value = plans ? {region: plansRegion, plans, reviewedAt: null} : null;
  return m.render(m.h(m.WhereToLook, {ranking}));
}
const count = (html, re) => (html.match(re) ?? []).length;

test('a plan-only target with a plan shows the plan block, every item, and no empty list', async () => {
  const html = await where();
  assert.match(html, /<div data-plan="chinook"><h3 class="ui-eyebrow">Search plan<\/h3><ul class="app-picks">/);
  assert.doesNotMatch(html, /app-empty/);
  const expected = planFor('chinook', {region: 'test-bay', plans: PLANS_A});
  assert.equal(expected.items.length, 5, 'search_for, habitat, timing and two confirm lines');
  assert.equal(count(html, /<li data-field="/g), expected.items.length);
  for (const field of ['search_for', 'habitat', 'timing']) assert.equal(count(html, new RegExp(`data-field="${field}"`, 'g')), 1, field);
  assert.equal(count(html, /data-field="required_to_confirm"/g), 2);
  assert.match(html, /What to search for: Chinook salmon: search for bait\./);
  assert.match(html, /<p data-field="tactics_basis">Chinook salmon basis line\.<\/p>/);
});

test('a plan-only target without a plan to show keeps the empty text and adds one sentence', async () => {
  const html = await where({target: 'modelled'});
  assert.match(html, /<p class="app-empty">No surveyed reef marks within 300 ft for this target\. No search plan for this species in Test Bay yet\.<\/p>/);
  assert.doesNotMatch(html, /data-plan=/);
  assert.equal(noPlanText(null), 'No search plan for this species in this region yet.');
  assert.match(await where({target: 'modelled', name: null}), /No search plan for this species in this region yet\.<\/p>/, 'never another region\'s name');
});

test('a reef target, with picks or without, renders as before', async () => {
  const reef = {reef: {name: 'Lingcod & rockfish', kind: 'reef', numeric_bite_model: false, search_for: 'Rock relief.'}};
  // morro-bay has coastal terrain, so its reef plan is ranked: the empty list stays exactly the ranking's text.
  const empty = await where({id: 'morro-bay', target: 'reef', plans: reef, name: 'Morro Bay'});
  assert.match(empty, /<p class="app-empty">No surveyed reef marks within 300 ft for this target\.<\/p>/);
  assert.doesNotMatch(empty, /data-plan=|Search plan|No search plan/);
  const picks = [{id: 'm-a', kind: 'habitat', name: 'Reef habitat', distance: '4.0 nm', depth: '~40–80 ft', fit: 'Fits 3 of 3', reason: 'Terrain score 80/100.', nm: 4, screen: {inside: false, name: null, distanceM: null, screened: true}}];
  for (const target of ['reef', 'chinook']) {
    const html = await where({id: target === 'reef' ? 'morro-bay' : 'test-bay', target, plans: target === 'reef' ? reef : PLANS_A, ranking: {...NONE, source: 'terrain', label: 'Terrain', picks}});
    assert.match(html, /<ol class="app-picks"><li data-mark="m-a">/, target);
    assert.doesNotMatch(html, /app-empty|data-plan=|Search plan/, target);
  }
  // A target the region has not researched keeps the empty text with nothing added.
  const unresearched = await where({target: 'yellowtail'});
  assert.match(unresearched, /<p class="app-empty">No surveyed reef marks within 300 ft for this target\.<\/p>/);
});

test('plan text with markup renders as text', async () => {
  const html = await where({plans: {chinook: plan('<b>Chinook</b>', {habitat: '<script>alert(1)</script>', tactics_basis: '<img src=x onerror=alert(1)>'})}});
  assert.doesNotMatch(html, /<script>|<img|<b>/);
  assert.match(html, /Habitat: &lt;script>alert\(1\)&lt;\/script>/);
  assert.match(html, /&lt;img src=x onerror=alert\(1\)>/);
});

test('the block follows the active region\'s plans, never another region\'s', async () => {
  const b = await where({id: 'other-bay', plans: PLANS_B, name: 'Other Bay'});
  assert.match(b, /Region B habitat only\./);
  assert.doesNotMatch(b, /Temperature edges\./);
  // Plans loaded for one region while another is active: no plan shows, the old empty text does.
  const stale = await where({id: 'other-bay', plans: PLANS_A, plansRegion: 'test-bay', name: 'Other Bay'});
  assert.match(stale, /<p class="app-empty">No surveyed reef marks within 300 ft for this target\.<\/p>/);
  assert.doesNotMatch(stale, /data-plan=|Temperature edges/);
  assert.equal(planFor('chinook', {region: 'test-bay', plans: PLANS_A}, 'other-bay'), null);
  assert.equal(planFor('chinook', {region: 'other-bay', plans: PLANS_B}, 'other-bay').items.find(i => i.field === 'habitat').text, 'Region B habitat only.');
});

test('planFor with no plans loaded returns null and the view shows the old empty state', async () => {
  assert.equal(planFor('chinook', null), null);
  assert.equal(planFor('chinook', undefined), null);
  assert.equal(planFor(null, {region: 'test-bay', plans: PLANS_A}), null);
  assert.equal(planFor('__proto__', {region: 'test-bay', plans: PLANS_A}), null);
  assert.equal(planFor('modelled', {region: 'test-bay', plans: PLANS_A}), null, 'a plan with a numeric model is never shown');
  const html = await where({plans: null});
  assert.match(html, /<p class="app-empty">No surveyed reef marks within 300 ft for this target\.<\/p>/);
  assert.doesNotMatch(html, /data-plan=|No search plan/);
});

test('a real region file: every non-reef plan yields its fields as items', async () => {
  const json = JSON.parse(await readFile(join(ROOT, 'dist/regions/morro-bay/search-plans.json'), 'utf8'));
  const loaded = {region: json.region_id, plans: json.profiles};
  const ids = Object.keys(json.profiles).filter(id => json.profiles[id].kind !== 'reef' && json.profiles[id].numeric_bite_model === false);
  assert.ok(ids.length > 0);
  for (const id of ids) {
    const p = json.profiles[id], got = planFor(id, loaded);
    const fields = ['life_stage', 'search_for', 'habitat', 'presentation', 'method', 'timing', 'condition_response', 'caution'].filter(f => typeof p[f] === 'string' && p[f].trim());
    assert.equal(got.items.length, fields.length + (p.required_to_confirm ?? []).length, id);
    assert.equal(got.name, p.name, id);
  }
});

// SC2207-01: a plan's reviewed {title, url} source links reach the brief's search-plan block, safe ones only.
const SAFE = [{title: 'Official page', url: 'https://example.test/path?q=1#part'}, {title: '<img src=x onerror=alert(1)> & source', url: 'https://example.test/two'}];
const UNSAFE = [{title: 'Plain http', url: 'http://example.test/x'}, {title: 'Script', url: 'javascript:alert(1)'}, {title: 'Creds', url: 'https://user:pass@example.test/c'},
  {title: 'Old shape', href: 'https://example.test/old'}, {title: ' ', url: 'https://example.test/blank'}, null, 'x'];
const anchors = html => [...html.matchAll(/<a href="([^"]*)"[^>]*>/g)].map(x => x[1]);

test('committed source URLs reach the plan the brief reads', async () => {
  const json = JSON.parse(await readFile(join(ROOT, 'dist/regions/morro-bay/search-plans.json'), 'utf8'));
  const loaded = {region: json.region_id, plans: json.profiles};
  let checked = 0;
  for (const [id, p] of Object.entries(json.profiles)) {
    if (p.numeric_bite_model !== false) continue;
    assert.ok(p.source_links.length > 0, id);
    assert.deepEqual(planFor(id, loaded).links, p.source_links.map(({title, url}) => ({title, href: url})), id);
    checked++;
  }
  assert.ok(checked > 0);
});

test('brief renders the same safe sources without changing plan items', async () => {
  const base = plan('Chinook salmon'), withLinks = plan('Chinook salmon', {source_links: [UNSAFE[0], SAFE[0], ...UNSAFE.slice(1), SAFE[1]]});
  const html = await where({plans: {chinook: withLinks}}), before = await where({plans: {chinook: base}});
  assert.deepEqual(planFor('chinook', {region: 'test-bay', plans: {chinook: withLinks}}).items, planFor('chinook', {region: 'test-bay', plans: {chinook: base}}).items);
  assert.deepEqual(anchors(html), SAFE.map(l => l.url));
  assert.match(html, /<ul aria-label="Search plan sources"><li><a href="https:\/\/example\.test\/path\?q=1#part" target="_blank" rel="noopener" aria-label="Official page \(opens in a new tab\)">Official page<\/a><\/li>/);
  assert.doesNotMatch(html, /<img|http:\/\/example|javascript:|user:pass|Old shape/);
  assert.match(html, /&lt;img src=x onerror=alert\(1\)(?:&gt;|>) &amp; source<\/a>/);
  assert.equal(count(html, /<li data-field="/g), count(before, /<li data-field="/g));
  assert.ok(html.indexOf('data-field="tactics_basis"') < html.indexOf('Search plan sources'), 'sources follow the basis');
});

test('unused source links preserve brief HTML and isolation', async () => {
  const baseline = await where();
  for (const source_links of [undefined, [], UNSAFE, 'https://example.test/s', null, {url: 'https://example.test/s'}]) {
    const html = await where({plans: {chinook: plan('Chinook salmon', {source_links})}});
    assert.equal(html, baseline);
    assert.doesNotMatch(html, /Search plan sources|<a /);
  }
  // Ranked picks and the reef empty path never show sources, even when the plan has them.
  const reef = {reef: {name: 'Lingcod & rockfish', kind: 'reef', numeric_bite_model: false, search_for: 'Rock relief.', source_links: SAFE}};
  assert.doesNotMatch(await where({id: 'morro-bay', target: 'reef', plans: reef, name: 'Morro Bay'}), /Search plan sources|example\.test/);
  const picks = [{id: 'm-a', kind: 'habitat', name: 'Reef habitat', distance: '4.0 nm', depth: '~40–80 ft', fit: 'Fits 3 of 3', reason: 'Terrain score 80/100.', nm: 4, screen: {inside: false, name: null, distanceM: null, screened: true}}];
  assert.doesNotMatch(await where({plans: {chinook: plan('Chinook salmon', {source_links: SAFE})}, ranking: {...NONE, source: 'terrain', label: 'Terrain', picks}}), /Search plan sources|example\.test/);
  // Another region's sources never leak; a numeric model never exposes them.
  const other = await where({id: 'other-bay', plans: {chinook: plan('Chinook salmon', {source_links: [{title: 'Region A only', url: 'https://example.test/a'}]})}, plansRegion: 'test-bay', name: 'Other Bay'});
  assert.doesNotMatch(other, /Region A only|example\.test\/a/);
  for (const numeric_bite_model of [true, undefined, 'false']) {
    const html = await where({target: 'modelled', plans: {modelled: plan('Modelled fish', {numeric_bite_model, source_links: SAFE})}});
    assert.doesNotMatch(html, /Search plan sources|example\.test/);
  }
  assert.equal(planFor('modelled', {region: 'test-bay', plans: PLANS_A}), null);
});
