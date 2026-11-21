// SCA-530 / F13-02: opt-in, offline Chromium/PDF fixture (cached Chromium and pdftotext).
//   node tests/test_f13_02_audit.mjs --reference
//   node tests/test_f13_02_audit.mjs --baseline
// The same contract applies in both modes. The baseline is diagnostic, not a required CI check.
// This mounts the real log in a synthetic phone sheet, not the full app or a native print dialog.
import assert from 'node:assert/strict';
import {execFileSync} from 'node:child_process';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {styledRendererPlugins} from './helpers/esbuild-url.mjs';

const mode = process.argv[2];
if (mode !== undefined) {
  assert.ok(['--reference', '--baseline'].includes(mode), 'choose --reference or --baseline');
  const {build} = await import('esbuild');
  const {chromium} = await import('@playwright/test');
  const root = fileURLToPath(new URL('..', import.meta.url));
  const reference = mode === '--reference';
  const entries = [
    {kind: 'catch', name: 'FixtureLogAlpha', recordedAt: '2000-01-01T00:00:01.000Z', position: {latitude: 1, longitude: 2}},
    {kind: 'blank', name: 'FixtureLogBeta', recordedAt: '2000-01-01T00:00:02.000Z', position: {latitude: -3, longitude: 4}},
  ].map(row => ({...row, region: 'FixtureRegion', positionBasis: 'Selected map position; not live GPS', conditions: null}));
  const tokens = entries.flatMap(({name, recordedAt, position}) => [name, recordedAt, `${position.latitude.toFixed(5)}, ${position.longitude.toFixed(5)}`]);
  const bundle = (await build({
    stdin: {resolveDir: root, loader: 'tsx', contents: `
      ${reference ? '' : "import './web/brief/Brief.tsx';"}
      import {h, render} from 'preact';
      import {PrivateMapLog} from './web/app/PrivateMapLog.tsx';
      import {LOG_KEY} from './web/private-map-log.ts';
      Object.defineProperty(window, 'localStorage', {value: {
        getItem: key => key === LOG_KEY ? ${JSON.stringify(JSON.stringify(entries))} : null,
        setItem() { throw new Error('Read-only fixture'); },
      }});
      const mark = {name: 'FixturePhoneMark', position: {latitude: 0, longitude: 0}};
      render(h(PrivateMapLog, {mark, region: 'FixtureRegion', forecast: null, tz: 'UTC'}), document.querySelector('#log'));
    `},
    bundle: true, write: false, outdir: 'fixture', format: 'esm', splitting: true,
    jsx: 'automatic', jsxImportSource: 'preact', plugins: styledRendererPlugins,
    entryNames: 'entry',
  })).outputFiles;
  const script = bundle.find(file => file.path.endsWith('/entry.js')).text;
  const css = reference ? '@media print { #log { display: none !important; } }'
    : bundle.find(file => file.path.endsWith('/entry.css')).text;

  const state = page => page.locator('details').evaluateAll(nodes => nodes.map(node => node.open));
  const html = `<!doctype html><div class="app-mobile"><div class="app-sheet app-sheet-brief">
    <section class="app-mark"><h2>FixturePhoneMark</h2><div id="log"></div></section>
    <details class="app-details" data-print-brief><summary>Forecast</summary><p>FixtureForecast</p></details>
    <details data-print-brief open><summary>Basis</summary><p>FixtureBasis</p></details>
    <details><summary>Unrelated</summary><p>FixtureUnrelated</p></details>
  </div></div>`;

  test('phone brief excludes both synthetic log entries and restores disclosures', {timeout: 30_000}, async t => {
    const browser = await chromium.launch();
    t.after(() => browser.close());
    const context = await browser.newContext({offline: true, serviceWorkers: 'block', viewport: {width: 390, height: 844}});
    await context.route('**/*', route => route.abort());
    for (const open of [false, true]) {
      await t.test(`log initially ${open ? 'open' : 'closed'}`, async () => {
        const page = await context.newPage();
        try {
          await page.setContent(html);
          await page.addStyleTag({content: css});
          await page.addScriptTag({content: script, type: 'module'});
          await page.waitForFunction(() => document.querySelectorAll('[data-private-entry]').length === 2);
          const log = page.locator('#log details');
          await log.evaluate((node, value) => { node.open = value; }, true);
          const screenText = await log.innerText();
          for (const token of tokens) assert.ok(screenText.includes(token), `screen has ${token}`);
          await log.evaluate((node, value) => { node.open = value; }, open);

          if (reference) await page.evaluate(() => {
            let opened = [];
            window.addEventListener('beforeprint', () => {
              opened = [...document.querySelectorAll('details[data-print-brief]:not([open])')];
              opened.forEach(node => { node.open = true; });
            });
            window.addEventListener('afterprint', () => opened.splice(0).forEach(node => { node.open = false; }));
          });

          const prior = [open, false, true, false]; // private log, closed allowed, open allowed, unrelated
          assert.deepEqual(await state(page), prior);
          // Model cancellation at the browser event boundary; no OS print UI or spooler.
          await page.evaluate(() => window.dispatchEvent(new Event('beforeprint')));
          const during = await state(page);
          await page.evaluate(() => window.dispatchEvent(new Event('afterprint')));
          const cancelled = await state(page);

          const pdf = await page.pdf(); // Native Chromium print events and print CSS; bytes stay in memory.
          const text = execFileSync('pdftotext', ['-', '-'], {input: pdf, encoding: 'utf8'}).replace(/\s+/g, ' ');
          const observations = {
            during, cancelled, afterPdf: await state(page),
            missingBriefText: ['FixturePhoneMark', 'FixtureForecast', 'FixtureBasis'].filter(token => !text.includes(token)),
            privatePdfText: tokens.filter(token => text.includes(token)),
            unrelatedPdfText: text.includes('FixtureUnrelated'),
          };
          t.diagnostic(`${mode} ${open ? 'open' : 'closed'}: ${JSON.stringify(observations)}`);
          assert.deepEqual(observations, {
            during: [open, true, true, false], cancelled: prior, afterPdf: prior,
            missingBriefText: [], privatePdfText: [], unrelatedPdfText: false,
          });
        } finally {
          await page.close();
        }
      });
    }
  });
}
