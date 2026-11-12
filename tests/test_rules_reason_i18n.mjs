// UXFIX-02: the rule-state reasons and labels web/regs.ts builds read in Spanish; the English text is unchanged.
import './helpers/spanish-ready.mjs';   // the Spanish table, before the Spanish renders
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';
import test, {after} from 'node:test';
import {regulationState, ruleLabel, ruleReason} from '../web/regs.ts';
import {t} from '../web/i18n.ts';
import catalogue from '../catalog/app/strings.json' with {type: 'json'};

const fixture = JSON.parse(readFileSync(new URL('./fixtures/regulations/fe61-v1.json', import.meta.url)));
const REGION = fixture.region, HOUR = 3600000, NOW = Date.parse('2026-09-21T18:00:00Z');

function data(at = NOW) {
  const d = structuredClone(fixture.regulations);
  d.reviewed_at = new Date(at - HOUR).toISOString();
  d.rules_review_status = 'reviewed';
  for (const [id, s] of Object.entries(d.sources)) {
    s.approved_content_sha256 = 'a'.repeat(64);
    d.checks[id] = {url: s.url, normalization: s.normalization, status: 'unchanged', source_status: 'ok', content_sha256: 'a'.repeat(64), data_retrieved_at: new Date(at).toISOString()};
  }
  return d;
}
const state = (d, over = {}) => regulationState(d, 'lingcod', REGION, over.now ?? NOW, over.date ?? null, over.instant ?? null);

function scenarios() {
  const changed = data(); for (const id of Object.keys(changed.checks)) changed.checks[id].status = 'changed';
  const review = data(); review.rules_review_status = 'draft';
  const geo = data(); geo.species.lingcod.windows = geo.species.lingcod.windows.map(w => ({...w, geography: {kind: 'latitude-band', south: 34.5, north: 36, source_id: geo.species.lingcod.source_ids[0], note: 'Synthetic band.'}}));
  const timed = data(); timed.species.lingcod.windows = [{start: '2026-09-21', end: '2026-12-31', start_at: '2026-09-21T20:00:00Z'}];
  return {
    sourceChanged: [state(changed), 'rules.reason.sourceChanged'],
    checkOld: [state(data(NOW - 40 * HOUR)), 'rules.reason.checkOld'],
    needsReview: [state(review), 'rules.reason.needsReview'],
    outsidePeriod: [state(data(), {date: '2031-01-01'}), 'rules.reason.outsidePeriod'],
    seasonStarts: [state(timed, {date: '2026-09-21'}), 'rules.reason.seasonStarts'],
    beforeOpening: [state(timed, {date: '2026-09-21', instant: NOW}), 'rules.reason.beforeOpening'],
    geography: [state(geo), 'rules.reason.geography'],
  };
}

test('every reason and label id has an English and a Spanish text', () => {
  const ids = Object.keys(catalogue.strings).filter(id => id.startsWith('rules.reason.') || id.startsWith('rules.label.'));
  assert.ok(ids.length >= 16, 'the ids exist');
  for (const id of ids) assert.ok(catalogue.strings[id].en && catalogue.strings[id].es, id);
});

test('each rule state reads in Spanish without its English sentence, and English is the unchanged text', () => {
  for (const [name, [s, id]] of Object.entries(scenarios())) {
    assert.equal(s.reasonId, id, name);
    const en = ruleReason(s, 'en'), es = ruleReason(s, 'es');
    assert.equal(en.text, s.reason, `${name}: English is byte-identical`);
    assert.equal(en.english, false, name);
    assert.notEqual(es.text, s.reason, `${name}: Spanish differs`);
    assert.equal(es.english, false, `${name}: app wording is not marked English`);
    assert.ok(!es.text.includes(s.reason.slice(0, 30)), `${name}: no English sentence in Spanish`);
  }
});

test('the English sentences are the ones the card showed before', () => {
  const s = scenarios();
  assert.equal(s.sourceChanged[0].reason, 'An official source changed after review. The saved limits below may have changed; check CDFW.');
  assert.equal(s.checkOld[0].reason, 'The daily source check is incomplete or over 36 hours old. Check CDFW; saved rules are shown below.');
  assert.match(ruleReason(s.checkOld[0], 'es').text, /36 horas/);
  assert.equal(s.needsReview[0].reason, 'Saved regulatory content needs review. Consult the official rules before fishing.');
  assert.equal(s.outsidePeriod[0].reason, 'This date is outside the reviewed rule period. Current-year rules need review.');
  assert.match(s.seasonStarts[0].reason, /^Season starts Sep 21, 2026, 1:00 PM PT\. The opening date is not an all-day opening\.$/);
  assert.match(s.beforeOpening[0].reason, /^Before the legal opening time\. Season starts /);
  assert.equal(s.geography[0].reason, 'This season applies only within a geographic area. Synthetic band.');
  assert.equal(ruleReason(s.geography[0], 'es').note, 'Synthetic band.'); assert.doesNotMatch(ruleReason(s.geography[0], 'es').text, /Synthetic/);
});

test('labels read in Spanish; the English label is unchanged; unknown never reads as open', () => {
  const s = scenarios();
  assert.equal(s.geography[0].label, 'Choose fishing location');
  assert.equal(ruleLabel(s.geography[0], 'en'), 'Choose fishing location');
  assert.equal(ruleLabel(s.geography[0], 'es'), 'Elige el lugar de pesca');
  assert.equal(ruleLabel(s.sourceChanged[0], 'en'), 'Check rules');
  assert.equal(ruleLabel(s.sourceChanged[0], 'es'), 'Revisa las reglas oficiales');
  assert.equal(t('preset.halibut', 'es'), 'Lenguado');
  assert.equal(t('preset.halibut', 'en'), 'Halibut');
});

test('registry wording with no catalogue sentence is still marked English on a Spanish page', () => {
  const d = data(); d.species.lingcod.windows = d.species.lingcod.windows.map(w => ({...w, restriction: 'Registry restriction text.'}));
  const s = state(d);
  assert.equal(s.reasonId, undefined);
  assert.deepEqual(ruleReason(s, 'es'), {text: 'Registry restriction text.', english: true});
  assert.deepEqual(ruleReason(s, 'en'), {text: 'Registry restriction text.', english: false});
});

test('a geography note stays separate English data: the Spanish sentence has no note, the note is its own lang="en" span', () => {
  const [s] = scenarios().geography;
  assert.deepEqual(ruleReason(s, 'es'), {text: 'Esta temporada solo rige dentro de un área geográfica.', english: false, note: 'Synthetic band.'});
  assert.deepEqual(ruleReason(s, 'en'), {text: 'This season applies only within a geographic area. Synthetic band.', english: false});
});

// The rendered markup: the Spanish page's rules cards (PlanRules in the planner, TargetRules in the plan view).
const ROOT = new URL('..', import.meta.url).pathname, dir = await mkdtemp(join(tmpdir(), 'rules-reason-')), out = join(dir, 'ui.mjs');
await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
    export {PlanRules} from './web/app/PlanRules.tsx';
    export {TargetRules} from './web/app/PlanView.tsx';
    export {regionInfo} from './web/app/region-info.ts';
    export {regsData} from './web/regs.ts';
    export {language} from './web/i18n.ts';
    export * as state from './web/state.ts';
    export {render} from 'preact-render-to-string'; export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins});
const m = await import(pathToFileURL(out).href);
after(async () => { m.regsData.value = null; m.regionInfo.value = null; m.language.value = 'en'; await rm(dir, {recursive: true, force: true}); });
const NOTE = '<span lang="en">Synthetic band.</span>';
function setup(loaded, lang) {
  m.state.configureStore({v2: true, storage: null});
  m.state.syncFromURL('https://s.test/map?region=morro-bay&profile=boat&view=plan&target=lingcod');
  m.regionInfo.value = {id: 'morro-bay', name: 'Morro Bay', timezone: 'America/Los_Angeles', center: [35, -121], rules: REGION};
  m.regsData.value = loaded ? {region: 'morro-bay', data: loaded} : null;
  m.language.value = lang;
}
const target = () => m.render(m.h(m.TargetRules, {now: new Date(NOW)}));
const planner = () => m.render(m.h(m.PlanRules, {date: '2026-09-21', species: 'lingcod', region: {id: 'morro-bay', timezone: 'America/Los_Angeles'}, now: NOW}));

test('Spanish TargetRules: the status label, reason and verified/freshness lines are Spanish, an unknown state never reads "Check rules"', () => {
  const [geo] = scenarios().geography;
  assert.equal(geo.status, 'unknown');
  const d = data(); d.species.lingcod.windows = d.species.lingcod.windows.map(w => ({...w, geography: {kind: 'latitude-band', south: 34.5, north: 36, source_id: d.species.lingcod.source_ids[0], note: 'Synthetic band.'}}));
  for (const loaded of [d, null, {...data(), rules_review_status: 'pending'}]) {
    setup(loaded, 'es');
    const es = target();
    assert.match(es, /data-status="unknown">Revisa las reglas</, 'the badge is the Spanish label');
    assert.doesNotMatch(es, /Check rules|Choose fishing location|Verified|Checked/, 'no English label or status line');
    assert.doesNotMatch(es, /\(en inglés\)/, 'the plan view adds no marker');
    setup(loaded, 'en');
    assert.match(target(), />Check rules</, 'English is unchanged');
  }
  setup(d, 'es');
  assert.match(target(), new RegExp(`área geográfica\\. ${NOTE}</p>`), 'the English note is its own lang="en" span');
  setup(d, 'en');
  assert.match(target(), /geographic area\. Synthetic band\.<\/p>/);
  assert.doesNotMatch(target(), /lang="en"/);
});

test('Spanish PlanRules: the geography note is a separate lang="en" span marked (en inglés); English has no marking', () => {
  const d = data(); d.species.lingcod.windows = d.species.lingcod.windows.map(w => ({...w, geography: {kind: 'latitude-band', south: 34.5, north: 36, source_id: d.species.lingcod.source_ids[0], note: 'Synthetic band.'}}));
  setup(d, 'es');
  const es = planner();
  assert.match(es, new RegExp(`Esta temporada solo rige dentro de un área geográfica\\. ${NOTE} \\(en inglés\\)`));
  assert.doesNotMatch(es, /Synthetic band\.(?!<\/span>)/, 'the note never appears outside its span');
  setup(d, 'en');
  const en = planner();
  assert.match(en, /geographic area\. Synthetic band\./); assert.doesNotMatch(en, /lang="en"|en inglés/);
});
