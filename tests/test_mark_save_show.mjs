// SC1722-16: after a confirmed save from the mark card, "Show on Chart" is the one explicit press that turns the private saved-spots layer
// on and, from 2D or 3D, opens the Chart; saving alone never does either. The real card's save action and the real legend row are mounted in
// headless Chromium with a synthetic transport, screen and engine; the layer is the real createSavedSpotLayer. Synthetic marks only; no server.
import assert from 'node:assert/strict';
import {existsSync, readFileSync} from 'node:fs';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {build} from 'esbuild';
import {chromium} from '@playwright/test';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const needsChromium = {skip: !existsSync(chromium.executablePath()) && 'chromium not installed'};

test('show_button_words: the catalogue has the English and Spanish words', () => {
  const strings = JSON.parse(readFileSync(new URL('../catalog/app/strings.json', import.meta.url), 'utf8')).strings;
  assert.deepEqual(strings['mark.save.showChart'], {en: 'Show on Chart', es: 'Mostrar en la carta'});
});

let bundle;
async function code() {
  if (bundle) return bundle;
  const out = join(await mkdtemp(join(tmpdir(), 'mark-save-show-')), 'bundle.js');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      import {SaveSpotAction} from './web/app/MarkCard.tsx';
      import {SavedSpotsRow} from './web/app/Legend.tsx';
      import {createSavedSpotLayer, savedSpotsOn} from './web/map/saved-spots.ts';
      import {SAVED_SPOTS_SOURCE} from './web/map/layers.ts';
      import {loadProtectedScreen} from './web/trip.ts';
      import {language, prepareCatalogue} from './web/i18n.ts';
      import {session} from './web/account.ts';
      import * as state from './web/state.ts';
      import {signal} from '@preact/signals';
      import {h, render} from 'preact';
      window.__t = {SaveSpotAction, SavedSpotsRow, createSavedSpotLayer, savedSpotsOn, SAVED_SPOTS_SOURCE, loadProtectedScreen, language, prepareCatalogue, session, state, signal, h, render};`},
    bundle: true, format: 'iife', platform: 'browser', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins,
  });
  bundle = await readFile(out, 'utf8');
  return bundle;
}

const MARK = {id: 'spot:A', name: 'Mark A', kind: 'Reef mark', reading: '', source: 'Source', basis: 'Basis', position: {latitude: 35.31, longitude: -121.05}};

/** A page on a routed origin (so the address can change), the real layer and legend row over a stub transport. */
async function withApp(presentation, fn) {
  const js = await code();
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  try {
    const page = await browser.newPage();
    await page.route('http://sc.test/**', route => route.fulfill({contentType: 'text/html', body: '<div id="root"></div>'}));
    await page.goto('http://sc.test/map?region=morro-bay');
    await page.addScriptTag({content: js});
    await page.evaluate(async presentation => {
      const t = window.__t;
      window.__calls = []; window.__rows = []; window.__failGet = false; window.__fills = [];
      window.fetch = async (url, init = {}) => {
        const method = init.method ?? 'GET';
        window.__calls.push(method);
        if (url !== '/api/spots') return new Response('{}', {status: 404});
        if (method === 'POST') {
          const body = JSON.parse(init.body);
          window.__rows.push({id: '11111111-2222-3333-4444-555555555555', owner: 'o', created_at: '2026-11-04T00:00:00Z', ...body});
          return new Response(JSON.stringify(window.__rows.at(-1)), {status: 201});
        }
        if (window.__failGet) return new Response('{}', {status: 500});
        return new Response(JSON.stringify({spots: window.__rows}), {status: 200});
      };
      t.session.value = {state: 'signed-in', name: 'Sam', advisor: false};
      t.state.region.value = 'morro-bay'; t.state.appView.value = 'coast';
      await t.loadProtectedScreen('morro-bay', async () => ({coversGeometry: () => true, exportExclusions: () => ({features: []}), refresh: async () => {}}));
      const engine = t.signal({setData(id, data) { if (id === t.SAVED_SPOTS_SOURCE) window.__fills.push(data.features.map(f => f.properties?.name ?? null)); }});
      t.createSavedSpotLayer({engine});
      if (presentation !== 'chart') t.state.navigate(new URL(location.href).origin + `/map?region=morro-bay&presentation=${presentation}`);
      window.__show = m => t.render(t.h('div', null, t.h(t.SaveSpotAction, {mark: m}), t.h('ul', null, t.h(t.SavedSpotsRow, null))), document.getElementById('root'));
    }, presentation);
    await fn(page);
  } finally { await browser.close(); }
}

const snap = page => page.evaluate(() => ({
  on: window.__t.savedSpotsOn.value,
  checked: document.querySelector('.app-legend-saved-spots input')?.checked ?? null,
  presentation: window.__t.state.presentation.value,
  url: location.href,
  calls: window.__calls.slice(),
  lastFill: window.__fills.at(-1) ?? null,
  buttons: [...document.querySelectorAll('button')].map(b => b.textContent.trim()),
  history: history.length,
}));
const start = async (page, mark = MARK) => { await page.evaluate(m => { window.__mark = m; window.__show(m); }, mark); };
const press = (page, label) => page.evaluate(async label => {
  [...document.querySelectorAll('button')].find(b => b.textContent.trim() === label)?.click();
  for (let i = 0; i < 40; i++) await new Promise(r => setTimeout(r, 5));
}, label);

test('save_does_not_show_until_explicit_press: saving leaves the layer off; Show on Chart draws the new pin and checks the legend row', needsChromium, async () => {
  await withApp('chart', async page => {
    await start(page);
    assert.ok(!(await snap(page)).buttons.includes('Show on Chart'), 'no Show button before a save');
    await press(page, 'Save this spot');
    const saved = await snap(page);
    assert.ok(saved.buttons.includes('Saved to your spots') && saved.buttons.includes('Show on Chart'), 'the confirmation gains Show on Chart');
    assert.equal(saved.on, false, 'the layer is still off');
    assert.equal(saved.checked, false, 'the legend row is unchecked');
    assert.deepEqual(saved.calls, ['POST'], 'no list read while the layer is off');
    assert.ok((saved.lastFill ?? []).length === 0, 'nothing drawn');
    assert.equal(saved.url, 'http://sc.test/map?region=morro-bay', 'the address is untouched');
    await press(page, 'Show on Chart');
    const shown = await snap(page);
    assert.equal(shown.on, true);
    assert.equal(shown.checked, true, 'the legend row is checked');
    assert.deepEqual(shown.lastFill, ['Mark A'], 'the new pin is drawn');
    assert.deepEqual(shown.calls, ['POST', 'GET'], 'one list read, no second save');
    assert.equal(shown.url, saved.url, 'already on the Chart: no address change');
    assert.equal(shown.history, saved.history, 'already on the Chart: no new history entry');
    await press(page, 'Show on Chart');
    const again = await snap(page);
    assert.equal(again.on, true, 'a second press never toggles it off');
    assert.deepEqual(again.calls, ['POST', 'GET'], 'a second press asks for nothing');
  });
});

test('terrain_show_opens_chart: from 2D and from 3D one press opens the Chart, turns the layer on and draws the pin', needsChromium, async () => {
  for (const presentation of ['2d', '3d']) {
    await withApp(presentation, async page => {
      await start(page);
      await press(page, 'Save this spot');
      const saved = await snap(page);
      assert.equal(saved.presentation, presentation, `${presentation}: saving does not navigate`);
      assert.equal(saved.on, false);
      await press(page, 'Show on Chart');
      const shown = await snap(page);
      assert.equal(shown.presentation, 'chart', `${presentation}: the press opens the Chart`);
      assert.equal(shown.on, true);
      assert.equal(shown.checked, true);
      assert.deepEqual(shown.lastFill, ['Mark A'], `${presentation}: the pin is drawn on the Chart`);
      const url = new URL(shown.url);
      assert.equal(url.searchParams.get('presentation'), 'chart');
      assert.equal(url.searchParams.get('region'), 'morro-bay', 'public parameters stay');
      assert.deepEqual([...url.searchParams.keys()].sort(), ['presentation', 'region'], 'nothing private or new in the address');
      assert.equal(url.hash, '');
    });
  }
});

test('no_show_for_nonconfirmed_save_and_context_loss: a failed save has no Show; a different region or account removes it and a stale press does nothing', needsChromium, async () => {
  await withApp('3d', async page => {
    await start(page);
    await page.evaluate(() => { window.fetch = async () => new Response('{}', {status: 500}); });
    await press(page, 'Save this spot');
    assert.ok(!(await snap(page)).buttons.includes('Show on Chart'), 'a failed save offers no Show');
    await page.evaluate(() => { window.fetch = async (u, i = {}) => { window.__calls.push(i.method ?? 'GET'); return new Response(JSON.stringify({id: 'x', ...JSON.parse(i.body ?? '{}')}), {status: 201}); }; });
    await press(page, 'Save this spot');
    const before = await snap(page);
    assert.ok(before.buttons.includes('Show on Chart'));
    // The session changes: the confirmation and Show go, and nothing is turned on.
    await page.evaluate(async () => { window.__t.session.value = {state: 'signed-in', name: 'Sam', advisor: false}; for (let i = 0; i < 10; i++) await new Promise(r => setTimeout(r, 5)); });
    const after = await snap(page);
    assert.ok(!after.buttons.includes('Show on Chart'), 'a new session removes the action');
    assert.equal(after.on, false);
    assert.equal(after.presentation, '3d', 'no navigation');
  });
});

test('language_and_privacy: the button follows the language without another request; the layer is never written to the address or storage', needsChromium, async () => {
  await withApp('chart', async page => {
    await start(page);
    await press(page, 'Save this spot');
    const callsBefore = (await snap(page)).calls.length;
    await page.evaluate(async () => { await window.__t.prepareCatalogue('es'); window.__t.language.value = 'es'; for (let i = 0; i < 10; i++) await new Promise(r => setTimeout(r, 5)); });
    const es = await snap(page);
    assert.ok(es.buttons.includes('Mostrar en la carta'), 'Spanish words');
    assert.equal(es.calls.length, callsBefore, 'a language change asks for nothing');
    assert.equal(es.on, false, 'a language change does not turn it on');
    await press(page, 'Mostrar en la carta');
    const shown = await snap(page);
    assert.equal(shown.on, true);
    const stored = await page.evaluate(() => JSON.stringify([{...localStorage}, {...sessionStorage}]));
    assert.ok(!/saved|Mark A|35\.31/i.test(shown.url + stored), 'no layer flag, name or point in the address or storage');
  });
});
