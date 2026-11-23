// SC2037-04: print this brief. The button calls window.print once, the print stylesheet hides the map
// stage, rail, legend, dock, command bar and dialogs, and the print block carries the printed-at time
// (region zone), the do-not-update line and, after it, the C1 footer.
import assert from 'node:assert/strict';
import test from 'node:test';
import {existsSync, readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {chromium} from '@playwright/test';
import {preparedRendererPlugins, rendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'print-')), 'print.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {PrintBrief, BriefFooter, printedText, printedAt, beforePrint, afterPrint} from './web/brief/Brief.tsx';
      export {regionInfo} from './web/app/region-info.ts';
      export {language, setLanguage} from './web/i18n.ts';
      export {profile} from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: preparedRendererPlugins,
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}
const NOW = new Date('2026-11-01T08:30:00Z'); // 01:30 PDT, the hour before the zone falls back at 09:00Z
const walk = (v, f) => { if (v && typeof v === 'object') { f(v); [].concat(v.props?.children ?? []).forEach(c => walk(c, f)); } };

test('Print this brief calls window.print exactly once', async () => {
  const {PrintBrief, h} = await load();
  let calls = 0;
  globalThis.window = {print: () => { calls += 1; }};
  try {
    let onClick;
    walk(PrintBrief({now: NOW}), v => { if (v.props?.class === 'app-print-button') onClick = v.props.onClick; });
    assert.equal(typeof onClick, 'function');
    onClick();
    assert.equal(calls, 1);
  } finally { delete globalThis.window; }
  assert.ok(h);
});

test('the stylesheet hides each named region in print and keeps URLs out', () => {
  const css = readFileSync(join(ROOT, 'web/brief/brief-print.css'), 'utf8');
  const print = css.slice(css.indexOf('@media print'));
  assert.ok(print.startsWith('@media print'));
  const hidden = print.slice(0, print.indexOf('display: none !important'));
  for (const sel of ['.app-stage', '.app-rail', '.app-legend', '.app-dock', '.app-command', 'dialog', '[role="dialog"]']) assert.ok(hidden.includes(sel), `${sel} hidden in print`);
  assert.match(css, /\.app-print-only \{ display: none; \}/, 'print block is hidden on screen');
  assert.match(css, /a\[href\]::after[^}]*content: none/, 'no URL expansion after links');
  assert.match(css, /color: CanvasText/);
  assert.match(css, /break-inside: avoid/);
});

test('the print block shows printed-at in the region zone, the no-update line, then the C1 footer', async () => {
  const {PrintBrief, BriefFooter, printedText, printedAt, render, h, regionInfo} = await load();
  regionInfo.value = {id: 'morro-bay', name: 'Morro Bay', timezone: 'America/Los_Angeles'};
  // 08:30Z on 2026-11-01 is 01:30 PDT? No: DST ended 09:00Z, so 08:30Z is still PDT (01:30), not UTC 8:30.
  assert.match(printedText(NOW.getTime(), 'America/Los_Angeles'), /1:30\s?AM PDT/);
  // An hour later the clock fell back: same local hour, now PST.
  assert.match(printedText(NOW.getTime() + 3_600_000, 'America/Los_Angeles'), /1:30\s?AM PST/);
  assert.match(printedText(Date.parse('2026-03-08T11:00:00Z'), 'America/Los_Angeles'), /4:00\s?AM PDT/);
  printedAt.value = NOW.getTime();
  const html = render(h('div', null, h(PrintBrief, {now: NOW}), h(BriefFooter, {})));
  assert.match(html, /Printed [^<]*1:30\s?AM PDT/);
  assert.ok(html.includes('Printed briefs do not update; check conditions before you leave'));
  assert.ok(html.includes('Morro Bay'));
  assert.ok(html.includes('Planning aid · not a navigation chart.'));
  assert.ok(html.indexOf('Printed briefs do not update') < html.indexOf('Planning aid'), 'footer follows the print block');
  assert.ok(html.includes('Print this brief'));
  printedAt.value = null;
});

test('beforeprint stamps the time and opens the disclosures, afterprint restores them', async () => {
  const {beforePrint, afterPrint, printedAt} = await load();
  const d = {open: false}, seen = [];
  const doc = {querySelectorAll: sel => { seen.push(sel); return [d]; }};
  beforePrint(() => 1234, doc);
  assert.equal(printedAt.value, 1234);
  assert.equal(d.open, true);
  afterPrint();
  assert.equal(d.open, false);
  afterPrint(); // a second afterprint is harmless
  printedAt.value = null;
});

test('the new ids exist in the catalogue with es values', () => {
  const cat = JSON.parse(readFileSync(join(ROOT, 'catalog/app/strings.json'), 'utf8')).strings;
  for (const id of ['brief.print', 'brief.print.at', 'brief.print.stale']) {
    assert.ok(cat[id]?.en && cat[id]?.es, id);
  }
});

test('the desktop first-answer panel prints black on white with its screen-only button hidden', () => {
  const css = readFileSync(join(ROOT, 'web/brief/brief-print.css'), 'utf8');
  const print = css.slice(css.indexOf('@media print'));
  const hidden = print.slice(0, print.indexOf('display: none !important'));
  assert.ok(hidden.includes('.app-first-answer-more'), 'first-answer button hidden in print');
  assert.match(print, /\.app-first-answer, \.app-sheet, [^{]*\{[^}]*background: Canvas !important; color: CanvasText !important/, 'panel reset to Canvas/CanvasText');
  assert.match(print, /\.app-first-answer \*[^{]*\{[^}]*color: CanvasText !important; background: transparent !important/, 'children forced black on transparent');
});

test('print place line: English keeps the profile label, Spanish uses where.profile.<id>', async () => {
  const {PrintBrief, render, h, regionInfo, language, setLanguage, profile} = await load();
  regionInfo.value = {id: 'morro-bay', name: 'Morro Bay', timezone: 'America/Los_Angeles'};
  const place = lang => { setLanguage(lang, {storage: {getItem: () => null, setItem() {}}, doc: null}); return /app-print-place[^>]*>([^<]*)</.exec(render(h(PrintBrief, {now: NOW})))?.[1]; };
  try {
    const was = profile.value, seen = {};
    for (const [id, en, es] of [['boat', 'Boat', 'Barco'], ['shore', 'Shore', 'Orilla'], ['spear', 'Spear', 'Pesca submarina'], ['kayak', 'Kayak', 'Kayak']]) {
      profile.value = id;
      seen[id] = [place('en'), place('es'), place('en')];
      assert.equal(seen[id][0], `Morro Bay · ${en}`);
      assert.equal(seen[id][1], `Morro Bay · ${es}`);
      assert.equal(seen[id][2], seen[id][0], 'back to English restores the bytes');
    }
    profile.value = was;
  } finally { setLanguage('en', {storage: {getItem: () => null, setItem() {}}, doc: null}); regionInfo.value = null; }
  assert.equal(language.value, 'en');
});

// SCB2222-13: with the Plan or Reports page open on a desktop, Print / Save as PDF prints that page (R4 of
// docs/plans/print-and-save-as-pdf-coverage.md), not the brief under it. The real Desktop is rendered for each view; the page's rows are
// synthetic and long enough to run over several sheets. The browser checks load the real app.css and brief-print.css in headless Chromium.
const needsChromium = {skip: !existsSync(chromium.executablePath()) && 'chromium not installed'};
let desk;
async function loadDesktop() {
  if (desk) return desk;
  const out = join(await mkdtemp(join(tmpdir(), 'print-desktop-')), 'desktop.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {Desktop} from './web/app/Desktop.tsx';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins,
  });
  desk = await import(pathToFileURL(out).href);
  return desk;
}
async function desktopHtml(view) {
  const m = await loadDesktop();
  globalThis.location = {href: `https://s.test/map?region=morro-bay${view ? `&view=${view}` : ''}`};
  try {
    m.state.configureStore({v2: true, storage: null});
    m.state.syncFromURL(location.href);
    return m.render(m.h(m.Desktop, {now: NOW}));
  } finally { delete globalThis.location; }
}
// The real Desktop markup with a long synthetic body appended inside the open page: LAST-ROW is the final dated row.
const ROWS = 140;
const longRows = `<ul>${Array.from({length: ROWS}, (_, i) => `<li class="synthetic-row" id="${i === ROWS - 1 ? 'last-row' : `row-${i}`}">2026-11-${String(1 + (i % 28)).padStart(2, '0')} · synthetic dated row ${i} · source note</li>`).join('')}</ul>`;
const withRows = html => html.replace(/(<div class="app-page">)/, `$1<h1 id="page-heading">Synthetic heading</h1>${longRows}<div class="app-page-end"></div>`);

async function printed(html, fn) {
  const css = ['web/app/app.css', 'web/brief/brief-print.css'].map(f => readFileSync(join(ROOT, f), 'utf8')).join('\n');
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 800}});
    await page.setContent(`<!doctype html><html><head><style>${css}</style></head><body><div class="app">${html}</div></body></html>`);
    return await fn(page);
  } finally { await browser.close(); }
}
const pdfPages = async page => (await page.pdf({format: 'Letter'})).toString('latin1').match(/\/Type\s*\/Page(?![s\w])/g)?.length ?? 0;
const look = page => page.evaluate(() => {
  const shown = sel => { const e = document.querySelector(sel); return !!e && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().height > 0; };
  return {brief: shown('.app-brief'), stage: shown('.app-stage'), heading: shown('#page-heading'), last: shown('#last-row'),
    lastTop: document.querySelector('#last-row')?.getBoundingClientRect().top ?? null, page: document.querySelector('.app-page') && getComputedStyle(document.querySelector('.app-page')).position,
    overflow: document.querySelector('.app-page') && getComputedStyle(document.querySelector('.app-page')).overflowY};
});

test('Desktop marks the main wrapper only when Plan or Reports is open', async () => {
  for (const view of ['plan', 'reports']) assert.match(await desktopHtml(view), new RegExp(`<main class="app-main" data-overlay="${view}">`), view);
  for (const view of [null, 'fleet', 'history']) assert.match(await desktopHtml(view), /<main class="app-main">/, `${view ?? 'brief'} has no marker`);
});

for (const view of ['plan', 'reports']) {
  test(`desktop ${view} prints its heading and last row over several pages, not the brief`, needsChromium, async () => {
    await printed(withRows(await desktopHtml(view)), async page => {
      await page.emulateMedia({media: 'screen'});
      const screen = await look(page);
      assert.equal(screen.page, 'absolute', 'screen: the page is still the overlay');
      assert.equal(screen.overflow, 'auto', 'screen: it still scrolls inside itself');
      assert.ok(screen.brief && screen.stage, 'screen: the brief and stage stay under it');
      await page.emulateMedia({media: 'print'});
      const p = await look(page);
      assert.ok(!p.brief && !p.stage, 'print: neither the brief nor the stage');
      assert.ok(p.heading && p.last, 'print: the heading and the last dated row show');
      assert.equal(p.page, 'static');
      assert.ok(p.lastTop > 1056, `the last row lies beyond the first sheet (top ${p.lastTop})`);
      assert.ok(await pdfPages(page) > 1, 'the PDF runs over more than one page');
    });
  });
}

test('the ordinary desktop brief still prints the brief, and not Plan or Reports rows', needsChromium, async () => {
  await printed(await desktopHtml(null), async page => {
    await page.emulateMedia({media: 'print'});
    const p = await look(page);
    assert.ok(p.brief, 'the brief shows');
    assert.ok(!p.stage && !p.heading && !p.last, 'no stage and no overlay page');
    assert.equal(await pdfPages(page), 1);
  });
});
