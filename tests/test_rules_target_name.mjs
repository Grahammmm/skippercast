import assert from 'node:assert/strict';
import test from 'node:test';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';

const {outputFiles: [bundle]} = await build({
  stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
    export {LeadRules} from './web/brief/Brief.tsx';
    export {RulesLine} from './web/app/RulesCard.tsx';
    export {PlanRules} from './web/app/PlanRules.tsx';
    export {regionInfo} from './web/app/region-info.ts';
    export {markData} from './web/map/marks.ts';
    export {region, species, profile} from './web/state.ts';
    export {regsData} from './web/regs.ts';
    export {language} from './web/i18n.ts';
    export {targetsFor} from './web/species.ts';
    export {shellTargetText} from './web/app/CommandBar.tsx';
    export {rulesTargetName} from './web/rules-target-name.ts';
    export {h} from 'preact'; export {render} from 'preact-render-to-string';`},
  bundle: true, format: 'esm', platform: 'node', write: false, jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins,
});
const m = await import(`data:text/javascript;base64,${Buffer.from(bundle.contents).toString('base64')}`);
const cases = [['spear', 'cabezon-shallow-reef', 'Cabezon'], ['shore', 'surfperch', 'Barred surfperch']];
const languages = ['en', 'es'];

test('C1: full name precedence and all fallback paths', () => {
  const inputs = [
    ['reef', 'A member profile', 'Lingcod & rockfish'],
    ['surfperch', 'Published name / alias', 'Published name / alias'],
    ['cabezon', undefined, 'Cabezon'], // legacy id resolves to the picker entry
    ['surfperch', null, 'Barred surfperch'],
    ['surfperch', '', 'Barred surfperch'],
    ['dungeness-crab', undefined, 'Dungeness Crab'],
  ];
  for (const lang of languages) {
    assert.deepEqual(inputs.map(([id, name]) => m.rulesTargetName(id, name, lang)), inputs.map(row => row[2]), lang);
  }
});

test('C2: the Spanish picker and rules share the same untranslated name', () => {
  for (const [mode, id, label] of cases) {
    const option = m.targetsFor(mode, null, {}, id, {plansLoaded: false}).find(t => t.id === id);
    assert.deepEqual(languages.map(lang => m.shellTargetText(option, lang)), [label, label], id);
    assert.deepEqual(languages.map(lang => m.rulesTargetName(id, null, lang)), [label, label], id);
  }
});

test('C3: extraction preserves picker output, including plan override and title-cased rows', () => {
  const plans = {'cabezon-shallow-reef': {name: 'Published Cabezon plan'}, 'test-reef-fish': {methods: ['dive']}};
  assert.deepEqual(m.targetsFor('spear', null, plans, 'shared-link-target'), [
    {id: 'shared-link-target', label: 'Shared Link Target', group: 'link', state: 'unresearched'},
    {id: 'cabezon-shallow-reef', label: 'Published Cabezon plan', group: 'plan', state: 'plan'},
    {id: 'test-reef-fish', label: 'Test Reef Fish', group: 'plan', state: 'plan'},
  ]);
  assert.deepEqual(m.targetsFor('shore', null, {}), [
    {id: 'surfperch', label: 'Barred surfperch', group: 'profile', state: 'unresearched'},
    {id: 'halibut', label: 'California halibut', group: 'profile', state: 'unresearched'},
  ]);
});

const rules = {id: 'fixture-coast', timezone: 'America/Los_Angeles'};
const date = '2026-10-13', now = new Date('2026-10-12T18:00:00Z');
const area = 'https://wildlife.ca.gov/Fishing/Ocean/Regulations/Fishing-Map/Central';
const cdfw = 'https://wildlife.ca.gov/Fishing/Ocean';
const entry = name => ({name, bag: '', size: '', season: '', windows: [], details: [], source_ids: ['area']});
const render = (lang, mode, target, profiles = {}) => {
  m.language.value = lang;
  m.region.value = rules.id;
  m.profile.value = mode;
  m.species.value = target;
  m.regionInfo.value = {...rules, rules};
  m.markData.value = {region: rules};
  // An actual registry for the region, but no matching record unless the test supplies one.
  m.regsData.value = {region: rules.id, data: {schema_version: 1, valid_from: '2026-01-01', valid_through: '2026-12-31',
    reviewed_at: now.toISOString(), rules_review_status: 'draft', common_notes: [], sources: {area: {url: area}}, checks: {}, species: profiles}};
  return [m.render(m.h(m.LeadRules, {date, now})), m.render(m.h(m.RulesLine, {mark: {id: 'spot:fixture'}})),
    m.render(m.h(m.PlanRules, {date, now: +now, species: target, region: rules}))];
};
const aria = html => [...html.matchAll(/aria-label="([^"]*)"/g)].map(m => m[1]);
const hrefs = html => [...html.matchAll(/href="([^"]*)"/g)].map(m => m[1]);
const headings = html => [...html.matchAll(/<strong>([^<]*)<\/strong>/g)].map(m => m[1]);
const leadText = html => /<span [^>]*>([^<]*)<\/span> ([^<]*?\.) /.exec(html)?.slice(1).join(' ');
const words = {
  en: {lead: name => `Check rules ${name} tomorrow.`, glance: name => `Rules at a glance: ${name}`,
    link: (name, label = 'Official CDFW rules') => `${label} for ${name} (official page, opens in a new tab)`,
    plan: "Rules on the plan's date", official: 'Official rules', area: name => `Area regulations page, not specific to ${name}.`},
  es: {lead: name => `Revisa las reglas ${name} mañana.`, glance: name => `Reglas de un vistazo: ${name}`,
    link: (name, label = 'Reglas oficiales de CDFW') => `${label} para ${name} (página oficial, se abre en una pestaña nueva)`,
    plan: 'Reglas para la fecha del plan', official: 'Reglas oficiales', area: name => `Página de reglas del área, no específica de ${name}.`},
};

test('C4: all three surfaces retain their official destinations and unknown status', () => {
  for (const lang of languages) {
    const html = render(lang, 'spear', 'cabezon-shallow-reef');
    assert.deepEqual(html.map(hrefs), [[cdfw], [cdfw], [cdfw]], lang);
    assert.deepEqual(html.map(s => [...s.matchAll(/data-status="([^"]*)"/g)].map(m => m[1])),
      [['unknown', 'unknown'], ['unknown'], ['unknown', 'unknown']], lang);
  }
});

for (const lang of languages) {
  const copy = words[lang];
  for (const [mode, target, label] of cases) {
    test(`C5: ${lang} ${mode} uses the full picker name in all three rendered surfaces`, () => {
      const [lead, card, plan] = render(lang, mode, target);
      const link = copy.link(label);
      assert.deepEqual({lead: [leadText(lead), aria(lead)], card: aria(card), plan: [headings(plan), aria(plan)]}, {
        lead: [copy.lead(label), [link]], card: [copy.glance(label), link], plan: [[label], [copy.plan, link]],
      });
    });
  }

  test(`C5: ${lang} retains the registry wording, including the rules card's area note`, () => {
    const name = 'Reviewed surfperch name';
    const [lead, card, plan] = render(lang, 'shore', 'surfperch', {surfperch: entry(name)});
    const link = copy.link(name, copy.official);
    assert.deepEqual([leadText(lead), aria(lead)], [copy.lead(name), [link]]);
    assert.deepEqual([aria(card), /<p class="app-mark-regs-note">([^<]*)<\/p>/.exec(card)?.[1]], [
      [copy.glance(name), link], copy.area(name),
    ]);
    assert.deepEqual([headings(plan), aria(plan)], [[name], [copy.plan, link]]);
  });

  test(`C5: ${lang} keeps combined reef wording in the brief and card but two species links in the planner`, () => {
    const [lead, card] = render(lang, 'boat', 'reef', {lingcod: entry('Member profile')});
    const name = 'Lingcod &amp; rockfish'; // Preact HTML serialization of the literal ampersand.
    assert.deepEqual([leadText(lead), aria(lead), aria(card)], [copy.lead(name), [copy.link(name)], [copy.glance(name), copy.link(name)]]);
    const [, , plan] = render(lang, 'boat', 'reef');
    assert.deepEqual([headings(plan), aria(plan), hrefs(plan)], [
      ['Lingcod, Reef rockfish'], [copy.plan, copy.link('Lingcod'), copy.link('Reef rockfish')], [cdfw, cdfw],
    ]);
  });
}
