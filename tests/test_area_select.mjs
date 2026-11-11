// SC1722-15: the Area picker draws only when there is something to choose.
// With no ?area= it renders nothing (no select whose only option is "Whole region"); with ?area=x it keeps
// both options, and choosing Whole region clears ?area= through the real store. Synthetic state, no network.
import assert from 'node:assert/strict';
import test from 'node:test';
import util from 'node:util';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const ORIGIN = 'https://s.test/map';
const NOW = new Date('2026-10-05T20:00:00Z');
const none = {getItem: () => null, setItem() {}};

let shell;
async function load() {
  if (shell) return shell;
  const out = join(await mkdtemp(join(tmpdir(), 'area-select-')), 'area.mjs');
  await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
    export {AreaSelect, CommandBar} from './web/app/CommandBar.tsx';
    export {Mobile} from './web/app/Mobile.tsx';
    export {language, setLanguage} from './web/i18n.ts';
    export * as state from './web/state.ts';
    export {render} from 'preact-render-to-string';
    export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins});
  shell = await import(pathToFileURL(out).href);
  return shell;
}

/** Run with a fake address bar and history that count writes, in the given language; always restored. */
async function withAddress(lang, link, run) {
  const m = await load();
  const saved = {location: globalThis.location, history: globalThis.history};
  const writes = {push: 0, replace: 0, reload: 0};
  globalThis.location = {href: link, origin: 'https://s.test', assign() { writes.reload += 1; }, replace() { writes.reload += 1; }};
  globalThis.history = {state: null,
    pushState(_s, _t, url) { writes.push += 1; globalThis.location.href = url; },
    replaceState(_s, _t, url) { writes.replace += 1; globalThis.location.href = url; }};
  m.setLanguage(lang, {storage: none, doc: null});
  m.state.syncFromURL(link);
  try { return await run(m, writes); } finally {
    m.setLanguage('en', {storage: none, doc: null});
    m.state.syncFromURL(`${ORIGIN}?region=morro-bay`);
    for (const key of ['location', 'history']) if (saved[key] === undefined) delete globalThis[key]; else globalThis[key] = saved[key];
  }
}
const options = html => [...html.matchAll(/<option([^>]*)>([^<]*)<\/option>/g)].map(x => [x[1].trim(), x[2]]);
/** The native change handler of the rendered select, the one the browser calls. */
const changeHandler = (m) => {
  const label = m.AreaSelect();
  const select = label.props.children[1];
  assert.equal(select.type, 'select');
  return select.props.onChange;
};
const choose = (handler, value) => handler({currentTarget: {value}});

test('area_absent_and_empty: no ?area= (or an empty one) draws no Area label, select or empty slot, in English and Spanish', async () => {
  for (const lang of ['en', 'es']) {
    for (const link of [`${ORIGIN}?region=morro-bay`, `${ORIGIN}?region=morro-bay&area=`]) {
      await withAddress(lang, link, m => {
        assert.equal(m.AreaSelect(), null, `${lang} ${link}: the component returns nothing`);
        assert.equal(m.render(m.h(m.AreaSelect, {})), '', `${lang} ${link}: nothing is rendered`);
        for (const C of [m.CommandBar, m.Mobile]) {
          const html = m.render(m.h(C, {now: NOW}));
          assert.doesNotMatch(html, /<option value>(?:Whole region|Toda la región)<\/option>/, `${lang} ${C.name}: no Whole region option`);
          assert.doesNotMatch(html, /<label>(?:Area|Área)</, `${lang} ${C.name}: no Area label`);
          const [group, port] = lang === 'es' ? ['Área y puerto', 'Elegir puerto'] : ['Area and port', 'Choose port'];
          assert.ok(html.includes(`role="group" aria-label="${group}"><button aria-label="${port}"`), `${lang} ${C.name}: the Area and port group stays and its first item is the port control`);
          assert.ok(html.includes(lang === 'es' ? 'aria-label="Compartir esta vista"' : 'aria-label="Share this view"'), `${lang} ${C.name}: the share control stays`);
        }
      });
    }
  }
});

test('area_link_has_two_options: ?area=estero gives Whole region and the selected area, in English and Spanish', async () => {
  for (const [lang, whole, label] of [['en', 'Whole region', 'Area'], ['es', 'Toda la región', 'Área']]) {
    await withAddress(lang, `${ORIGIN}?region=morro-bay&area=estero`, m => {
      const html = m.render(m.h(m.AreaSelect, {}));
      assert.ok(html.startsWith(`<label>${label}<select>`), html);
      assert.ok(util.isDeepStrictEqual(options(html), [['value', whole], ['selected value="estero"', 'Estero']]), `${lang}: ${html}`);
      for (const C of [m.CommandBar, m.Mobile]) assert.ok(m.render(m.h(C, {now: NOW})).includes(html), `${lang} ${C.name} draws the same picker`);
    });
  }
  // An unlinked or odd area keeps both options, shown as written and escaped.
  await withAddress('en', `${ORIGIN}?region=morro-bay&area=${encodeURIComponent('x"><b>y')}`, m => {
    const html = m.render(m.h(m.AreaSelect, {}));
    assert.equal(options(html).length, 2, html);
    assert.doesNotMatch(html, /<b>/, 'the area name is escaped');
  });
});

test('whole_region_clears_real_address: choosing Whole region replaces the address without ?area= and the picker goes', async () => {
  await withAddress('en', `${ORIGIN}?region=morro-bay&target=halibut&day=2026-10-06&area=estero#brief`, (m, writes) => {
    const handler = changeHandler(m);
    choose(handler, '');
    assert.ok(util.isDeepStrictEqual({...writes}, {push: 0, replace: 1, reload: 0}), `one replace, no push or reload: ${JSON.stringify(writes)}`);
    const url = new URL(globalThis.location.href);
    assert.equal(url.searchParams.get('area'), null, 'area is out of the address');
    assert.ok(util.isDeepStrictEqual([url.searchParams.get('region'), url.searchParams.get('target'), url.searchParams.get('day'), url.hash], ['morro-bay', 'halibut', '2026-10-06', '#brief']), 'unrelated state survives');
    assert.equal(m.state.area.value, null, 'the signal follows');
    assert.equal(m.render(m.h(m.AreaSelect, {})), '', 'the picker is gone');
  });
});

test('area_navigation_and_language_roundtrip: following the address and the language changes only what is drawn', async () => {
  await withAddress('en', `${ORIGIN}?region=morro-bay`, m => {
    assert.equal(m.render(m.h(m.AreaSelect, {})), '');
    m.state.syncFromURL(`${ORIGIN}?region=morro-bay&area=estero`);
    const en = m.render(m.h(m.AreaSelect, {}));
    assert.match(en, /<label>Area<select>/);
    m.setLanguage('es', {storage: none, doc: null});
    const es = m.render(m.h(m.AreaSelect, {}));
    assert.match(es, /<label>Área<select>/);
    assert.ok(util.isDeepStrictEqual(options(es).map(o => o[0]), options(en).map(o => o[0])), 'value and selected stay put');
    assert.equal(m.state.area.value, 'estero');
    m.setLanguage('en', {storage: none, doc: null});
    assert.equal(m.render(m.h(m.AreaSelect, {})), en, 'back to English draws the same picker');
    m.state.syncFromURL(`${ORIGIN}?region=morro-bay`);
    assert.equal(m.render(m.h(m.AreaSelect, {})), '', 'the link without area removes it again');
  });
  // The legacy focus alias reads into the same area signal, so it keeps the two options.
  await withAddress('en', `${ORIGIN}?region=morro-bay&focus=estero`, m => {
    assert.equal(options(m.render(m.h(m.AreaSelect, {}))).length, 2);
  });
});
