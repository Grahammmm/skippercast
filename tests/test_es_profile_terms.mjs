// SC1722-13 (UX audit S4-16, S4-17): in Spanish the Shore profile no longer shares "Costa" with the Coast view,
// and the target field's hint is short enough for its 128 px field. Synthetic state only; nothing here touches the network.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const catalog = JSON.parse(readFileSync(new URL('../catalog/app/strings.json', import.meta.url), 'utf8')).strings;
const glossary = readFileSync(new URL('../docs/i18n-glossary.md', import.meta.url), 'utf8');
const none = {getItem: () => null, setItem() {}};

test('shore_term_inventory: every catalogue entry whose English is exactly Shore is Orilla, and Coast stays Costa', () => {
  const shore = Object.entries(catalog).filter(([, v]) => v.en === 'Shore').map(([id]) => id).sort();
  assert.deepEqual(shore, ['limits.from.shore', 'where.profile.shore'], 'a new Shore label must be reviewed here');
  for (const id of shore) assert.equal(catalog[id].es, 'Orilla', id);
  assert.equal(catalog['shell.view.coast'].en, 'Coast');
  assert.equal(catalog['shell.view.coast'].es, 'Costa');
  const labels = Object.entries(catalog).filter(([, v]) => v.es === 'Costa').map(([id]) => id);
  assert.deepEqual(labels, ['shell.view.coast'], 'only the Coast view is named Costa');
  for (const id of shore) assert.ok(glossary.includes(`\`${id}\``), `${id} is in docs/i18n-glossary.md`);
  assert.ok(glossary.includes('`Orilla`') && glossary.includes('`shell.view.coast`'));
});

test('short_hint: the Spanish target hint is Busca especie; English is unchanged', () => {
  assert.equal(catalog['command.findTarget'].es, 'Busca especie');
  assert.ok(catalog['command.findTarget'].es.length <= 'Busca una espec'.length, 'short enough for the field, which cut the old text at 15 characters');
  assert.equal(catalog['command.findTarget'].en, 'Find a target');
  assert.equal(catalog['where.profile.shore'].en, 'Shore');
  assert.equal(catalog['limits.from.shore'].en, 'Shore');
  assert.equal(catalog['shell.view.coast'].en, 'Coast');
});

test('es_distinct_actions: the rendered profile switch and view navigation never give two different controls one name', async () => {
  const out = join(await mkdtemp(join(tmpdir(), 'es-profile-')), 'shell.mjs');
  await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
    export {ViewNav} from './web/app/Masthead.tsx';
    export {CommandBar, ProfileSwitch} from './web/app/CommandBar.tsx';
    export {language, setLanguage} from './web/i18n.ts';
    export * as state from './web/state.ts';
    export {render} from 'preact-render-to-string';
    export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins});
  const m = await import(pathToFileURL(out).href);
  const was = globalThis.location;
  globalThis.location = {href: 'https://s.test/map?region=morro-bay', origin: 'https://s.test'};
  m.state.syncFromURL('https://s.test/map?region=morro-bay');
  try {
    m.setLanguage('es', {storage: none, doc: null});
    const profiles = [...m.render(m.h(m.ProfileSwitch, {})).matchAll(/data-profile="(\w+)"|<button[^>]*>(?:<svg.*?<\/svg>)?([^<]+)<\/button>/g)].map(x => x[2]).filter(Boolean);
    const views = [...m.render(m.h(m.ViewNav, {})).matchAll(/data-view="(\w+)"[^>]*>(?:<svg.*?<\/svg>)?([^<]+)<\/a>|<a [^>]*>([^<]+)<\/a>/g)].map(x => x[2] ?? x[3]).filter(Boolean);
    assert.ok(profiles.includes('Orilla') && !profiles.includes('Costa'), `profiles: ${profiles}`);
    assert.ok(views.includes('Costa') && !views.includes('Orilla'), `views: ${views}`);
    const names = [...profiles, ...views];
    assert.equal(names.filter(n => n === 'Costa').length, 1, `exactly one control is named Costa: ${names}`);
    const cmd = m.render(m.h(m.CommandBar, {now: new Date('2026-10-05T20:00:00Z')}));
    assert.ok(cmd.includes('aria-label="Busca especie" placeholder="Busca especie"'), 'target field name and placeholder');
    m.setLanguage('en', {storage: none, doc: null});
    const en = m.render(m.h(m.CommandBar, {now: new Date('2026-10-05T20:00:00Z')}));
    assert.ok(en.includes('aria-label="Find a target" placeholder="Find a target"'), 'English is unchanged');
    assert.match(m.render(m.h(m.ProfileSwitch, {})), />Shore</);
  } finally {
    m.setLanguage('en', {storage: none, doc: null});
    if (was === undefined) delete globalThis.location; else globalThis.location = was;
  }
});
