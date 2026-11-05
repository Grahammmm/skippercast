// SC2037-04: print this brief. The button calls window.print once, the print stylesheet hides the map
// stage, rail, legend, dock, command bar and dialogs, and the print block carries the printed-at time
// (region zone), the do-not-update line and, after it, the C1 footer.
import assert from 'node:assert/strict';
import test from 'node:test';
import {readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'print-')), 'print.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {PrintBrief, BriefFooter, printedText, printedAt, beforePrint, afterPrint} from './web/brief/Brief.tsx';
      export {regionInfo} from './web/app/region-info.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
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
