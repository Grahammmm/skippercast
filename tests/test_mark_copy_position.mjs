// SC2252-09: "Copy position" on the mark card copies exactly the displayed position text, in the chosen format, and only for a
// mark the shared protected-area screen allows (web/saved-spots.ts `screenMarkPosition`, the save path's own rule, with no account).
// A refused or unchecked mark keeps its position line, with the screen's reason and no button; a withheld mark shows no position.
// Server-rendered checks run everywhere; the clipboard checks mount the real card in headless Chromium where it is installed.
// Synthetic marks and areas only; no app server, no network.
import assert from 'node:assert/strict';
import {existsSync, readFileSync} from 'node:fs';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import test from 'node:test';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {chromium} from '@playwright/test';
import {preparedRendererPlugins, rendererPlugins} from './helpers/esbuild-url.mjs';
import {initProtectedAreas} from '../dist/protected-areas.js';
import {setRegion} from '../dist/region.js';
import {formatCoordinates} from '../dist/coordinates.js';

const ROOT = new URL('..', import.meta.url).pathname;
setRegion(JSON.parse(readFileSync(new URL('../dist/regions/morro-bay/region.json', import.meta.url), 'utf8')));
const needsChromium = {skip: !existsSync(chromium.executablePath()) && 'chromium not installed'};

let ui;
async function components() {
  if (ui) return ui;
  const out = join(await mkdtemp(join(tmpdir(), 'mark-copy-')), 'card.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {MarkCard} from './web/app/MarkCard.tsx';
      export {protectedScreen} from './web/trip.ts';
      export {language} from './web/i18n.ts';
      export {session} from './web/account.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins,
  });
  ui = await import(pathToFileURL(out).href);
  return ui;
}

// The save tests' synthetic closure: a 0.01° square at (-121.0, 35.3) and eight far-away fillers, through the real initProtectedAreas.
const CX = -121.0, CY = 35.3, HALF = 0.005, M_LON = 111320 * Math.cos(CY * Math.PI / 180);
const square = (x, y, d) => ({type: 'Polygon', coordinates: [[[x - d, y - d], [x + d, y - d], [x + d, y + d], [x - d, y + d], [x - d, y - d]]]});
const area = (name, geometry) => ({type: 'Feature', properties: {NAME: name, FULLNAME: `${name} State Marine Reserve`, Type: 'SMR', CCR: 'Section 632(b)'}, geometry});
async function realScreen() {
  const saved = {fetch: globalThis.fetch, document: globalThis.document};
  globalThis.fetch = async () => ({ok: true, json: async () => ({type: 'FeatureCollection', checked_at: new Date().toISOString(),
    features: [area('Synthetic Reef', square(CX, CY, HALF)), ...Array.from({length: 8}, (_, i) => area(`Filler ${i}`, square(-121.8 + i * 0.01, 35.8, 0.001)))]})});
  globalThis.document = {getElementById: () => ({classList: {toggle() {}}, textContent: ''}), dispatchEvent() {}};
  try { return await initProtectedAreas(null, () => {}); } finally { Object.assign(globalThis, saved); }
}
const east = m => ({latitude: CY, longitude: CX + HALF + m / M_LON});
const mark = (at, over = {}) => ({id: 'spot:SC26-001', name: 'Synthetic mark', kind: 'Reef mark', reading: 'A reading', source: 'Source', basis: 'Basis', position: at, ...over});
const BUTTON = />Copy position<\/button>/;
const REASON = {
  notChecked: 'Protected areas not checked for this position: outside coverage or check unavailable.',
  inside: 'Inside a protected area.', margin: 'Within 70 m of a protected area.',
};

async function card(m, {screen, region = 'morro-bay', format = 'dd', lang = 'en'} = {}) {
  const {MarkCard, protectedScreen, language, state, render, h} = await components();
  state.region.value = region; state.coordinates.value = format; language.value = lang;
  protectedScreen.value = screen === undefined ? {state: 'idle'} : screen;
  try { return render(h(MarkCard, {mark: m})); } finally { protectedScreen.value = {state: 'idle'}; language.value = 'en'; state.coordinates.value = 'dd'; state.region.value = null; }
}
const line = at => `<p class="ui-mono">${formatCoordinates(at.latitude, at.longitude, 'dd')}</p>`;

test('copy_offered_for_a_screened_clear_mark_without_an_account: the button sits beside the unchanged position line', async () => {
  const {session} = await components();
  const loaded = {state: 'loaded', region: 'morro-bay', screen: await realScreen()};
  for (const s of [{state: 'signed-out'}, {state: 'signed-in', name: null}]) {
    session.value = s;
    try {
      const at = east(150), html = await card(mark(at), {screen: loaded});
      assert.ok(html.includes(`${line(at)}<div class="app-mark-copy"`), `${s.state}: right after the position line`);
      assert.match(html, BUTTON, `${s.state}: offered`);
      assert.ok(!/Copy position<\/button>[\s\S]*Copy position<\/button>/.test(html), 'once');
      for (const words of Object.values(REASON)) assert.ok(!html.includes(words), `${s.state}: no refusal`);
    } finally { session.value = {state: 'loading'}; }
  }
  assert.match(await card(mark(east(150)), {screen: loaded, lang: 'es'}), />Copiar posición<\/button>/);
});

test('refused_positions_have_reason_without_button: inside, the 70 m margin and an unchecked mark keep their line and say why', async () => {
  const screen = await realScreen(), loaded = {state: 'loaded', region: 'morro-bay', screen};
  const cases = [
    ['inside', {latitude: CY, longitude: CX}, {screen: loaded}, REASON.inside],
    ['on the boundary', {latitude: CY, longitude: CX + HALF}, {screen: loaded}, REASON.inside],
    ['30 m outside', east(30), {screen: loaded}, REASON.margin],
    ['60 m outside', east(60), {screen: loaded}, REASON.margin],
    ['screen not loaded', east(150), {}, REASON.notChecked],
    ['screen loading', east(150), {screen: {state: 'loading'}}, REASON.notChecked],
    ['screen failed', east(150), {screen: {state: 'failed'}}, REASON.notChecked],
    ['screen for another region', east(150), {screen: {state: 'loaded', region: 'other-region', screen}}, REASON.notChecked],
    ['no region', east(150), {screen: loaded, region: null}, REASON.notChecked],
    ['outside coverage', {latitude: 36.5, longitude: -120.0}, {screen: loaded}, REASON.notChecked],
  ];
  for (const [label, at, opts, words] of cases) {
    const html = await card(mark(at), opts);
    assert.doesNotMatch(html, BUTTON, `${label}: no button`);
    assert.ok(html.includes(line(at)), `${label}: the position shows as today`);
    assert.ok(html.includes(`<p class="app-mark-copy" role="status">${words}</p>`), `${label}: the screen's reason`);
  }
  assert.ok((await card(mark(east(30)), {screen: loaded, lang: 'es'})).includes('A 70 m o menos de un área protegida.'), 'Spanish names the 70 m boundary');
  assert.ok((await card(mark({latitude: CY, longitude: CX}), {screen: loaded, lang: 'es'})).includes('Dentro de un área protegida.'));
});

test('withheld_mark_shows_no_position_or_copy: as today, with no reason that could carry its point', async () => {
  const loaded = {state: 'loaded', region: 'morro-bay', screen: await realScreen()};
  const at = {latitude: 35.31234, longitude: -121.04321};
  const html = await card(mark(at, {withheld: true, reading: 'This mark is withheld.'}), {screen: loaded});
  assert.doesNotMatch(html, BUTTON);
  assert.doesNotMatch(html, /app-mark-copy/);
  assert.ok(!html.includes('35.31234') && !html.includes('121.04321') && !html.includes(formatCoordinates(at.latitude, at.longitude, 'dd')), 'no point anywhere');
});

// ---- Chromium: the real card mounted, a stubbed clipboard, a stubbed screen that covers or not. ----
let browserBundle;
async function browserCode() {
  if (browserBundle) return browserBundle;
  const out = join(await mkdtemp(join(tmpdir(), 'mark-copy-web-')), 'bundle.js');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      import {MarkCard} from './web/app/MarkCard.tsx';
      import {loadProtectedScreen} from './web/trip.ts';
      import {language, prepareCatalogue} from './web/i18n.ts';
      import {region, coordinates} from './web/state.ts';
      import {h, render} from 'preact';
      window.__t = {MarkCard, loadProtectedScreen, language, prepareCatalogue, region, coordinates, h, render};`},
    bundle: true, format: 'iife', platform: 'browser', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins,
  });
  browserBundle = await readFile(out, 'utf8');
  return browserBundle;
}

async function withCard(fn) {
  const code = await browserCode();
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  try {
    const page = await browser.newPage();
    await page.setContent('<div id="root"></div>');
    await page.addScriptTag({content: code});
    await page.evaluate(async () => {
      const t = window.__t;
      window.__writes = []; window.__mode = 'ok'; window.__covers = true; window.__fetches = 0; window.__held = [];
      const realFetch = window.fetch;
      window.fetch = (...a) => { window.__fetches++; return realFetch(...a); };
      const clipboard = {writeText: text => {
        window.__writes.push(text);
        if (window.__mode === 'throw') throw new Error('SECRET-CLIPBOARD-ERROR');
        if (window.__mode === 'deny') return Promise.reject(new DOMException('SECRET-CLIPBOARD-ERROR', 'NotAllowedError'));
        if (window.__mode === 'hold') return new Promise((resolve, reject) => { window.__held.push({resolve, reject}); });
        return Promise.resolve();
      }};
      Object.defineProperty(navigator, 'clipboard', {configurable: true, get: () => window.__mode === 'missing' ? undefined : clipboard});
      t.region.value = 'morro-bay';
      // The region's one shared screen, loaded through the real loader with a synthetic screen: no closures; covers the point or not.
      await t.loadProtectedScreen('morro-bay', async () => ({coversGeometry: () => window.__covers, exportExclusions: () => ({features: []}), refresh: async () => {}}));
      window.__show = m => t.render(t.h(t.MarkCard, {mark: m}), document.getElementById('root'));
    });
    await fn(page);
  } finally { await browser.close(); }
}
const A = {id: 'spot:A', name: 'Mark A', kind: 'Reef mark', reading: '', source: 'Source', basis: 'Basis', position: {latitude: -33.5, longitude: 151.25}};
const B = {...A, id: 'spot:B', name: 'Mark B', position: {latitude: 0, longitude: 0}};
const show = (page, m) => page.evaluate(m => { window.__show(m); }, m);
const shot = page => page.evaluate(() => ({
  writes: window.__writes, fetches: window.__fetches,
  line: document.querySelector('p.ui-mono')?.textContent ?? null,
  button: [...document.querySelectorAll('button')].some(b => b.textContent === 'Copy position'),
  status: document.querySelector('.app-mark-copy [role="status"], p.app-mark-copy')?.textContent ?? null,
  focused: document.activeElement?.textContent ?? null,
}));
const settle = page => page.evaluate(() => new Promise(r => setTimeout(r, 30)));
const copyButton = page => page.getByRole('button', {name: 'Copy position', exact: true});

test('copy_exactly_displayed_text: every coordinate format, one click one write, Copied after it resolves, nothing sent', needsChromium, async () => {
  await withCard(async page => {
    for (const format of ['dd', 'ddm', 'dms']) {
      await page.evaluate(f => { window.__t.coordinates.value = f; window.__writes.length = 0; }, format);
      await show(page, {...A, id: `spot:A-${format}`});
      await settle(page);
      let s = await shot(page);
      assert.equal(s.writes.length, 0, `${format}: nothing before the click`);
      assert.equal(s.status, '', `${format}: nothing said yet`);
      const before = s.fetches;
      await copyButton(page).click();
      await settle(page);
      s = await shot(page);
      assert.equal(s.writes.length, 1, `${format}: one write`);
      assert.equal(s.writes[0], s.line, `${format}: byte for byte the line shown`);
      assert.equal(s.line, formatCoordinates(A.position.latitude, A.position.longitude, format));
      assert.equal(s.status, 'Copied');
      assert.equal(s.fetches, before, `${format}: nothing sent`);
    }
    // Language changes the retained answer without another write.
    await page.evaluate(async () => { await window.__t.prepareCatalogue('es'); window.__t.language.value = 'es'; });   // SC1407-09: the Spanish table first, as the app does
    await settle(page);
    assert.equal((await shot(page)).status, 'Copiada');
    assert.equal((await shot(page)).writes.length, 1);
    await page.evaluate(() => { window.__t.language.value = 'en'; });
  });
});

test('clipboard_refused_or_missing_says_select_the_text: denied, thrown, missing; focus stays; a retry can succeed; keyboard works', needsChromium, async () => {
  await withCard(async page => {
    await show(page, A);
    await settle(page);
    for (const mode of ['deny', 'throw', 'missing']) {
      await page.evaluate(m => { window.__mode = m; }, mode);
      await copyButton(page).focus();
      await page.keyboard.press('Enter');
      await settle(page);
      const s = await shot(page);
      assert.equal(s.status, 'Could not copy; select the text instead', mode);
      assert.equal(s.focused, 'Copy position', `${mode}: focus stays on the action`);
      assert.ok(!JSON.stringify(s).includes('SECRET'), `${mode}: no error text echoed`);
    }
    assert.equal((await shot(page)).writes.length, 2, 'deny and throw tried the clipboard once each; missing had none to try');
    await page.evaluate(() => { window.__mode = 'ok'; });
    await page.keyboard.press('Space');
    await settle(page);
    assert.equal((await shot(page)).status, 'Copied', 'another explicit attempt works');
  });
});

test('late_copy_and_click_time_screen: a pending write is not repeated, a late answer for another mark says nothing, a screen gone at the click writes nothing', needsChromium, async () => {
  await withCard(async page => {
    await page.evaluate(() => { window.__mode = 'hold'; });
    await show(page, A);
    await settle(page);
    await copyButton(page).click();
    assert.equal(await copyButton(page).getAttribute('aria-disabled'), 'true', 'pending reads as unavailable');
    await copyButton(page).click({force: true});
    await settle(page);
    assert.equal((await shot(page)).writes.length, 1, 'pending: one write');
    // A→B→A while the write is pending: the late answer belongs to neither card.
    await show(page, B); await settle(page); await show(page, A); await settle(page);
    await page.evaluate(() => { window.__held[0].resolve(); });
    await settle(page);
    assert.equal((await shot(page)).status, '', 'the earlier A answer is not shown on the newer A');
    // The screen stops covering the point with no redraw: the click is refused, writes nothing, and the reason replaces the button.
    await page.evaluate(() => { window.__mode = 'ok'; window.__covers = false; window.__writes.length = 0; });
    await copyButton(page).click();
    await settle(page);
    const s = await shot(page);
    assert.equal(s.writes.length, 0);
    assert.equal(s.button, false);
    assert.equal(s.status, REASON.notChecked);
    assert.equal(s.line, formatCoordinates(A.position.latitude, A.position.longitude, 'dd'), 'the position still shows');
  });
});
