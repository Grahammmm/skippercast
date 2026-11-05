// RF1920-13: the first-use boat form's three numeric inputs take decimal measurements.
// Real BoatEntry bundled with esbuild and mounted in headless Chromium, so native
// constraint validation (step mismatch) and click-to-submit are the browser's own.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {build} from 'esbuild';
import {chromium} from '@playwright/test';

const ROOT = new URL('..', import.meta.url).pathname;
let bundle;
async function load() {
  if (bundle) return bundle;
  const out = join(await mkdtemp(join(tmpdir(), 'boat-numeric-')), 'bundle.js');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      import {BoatEntry} from './web/app/FirstRun.tsx';
      import {h, render} from 'preact';
      import {saveFirstUse} from './web/boat-entry.ts';
      import {configureStore} from './web/state.ts';
      import {savedLimits} from './web/limits.ts';
      window.__t = {BoatEntry, h, render, saveFirstUse, configureStore, savedLimits};`},
    bundle: true, format: 'iife', platform: 'browser', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
  });
  bundle = await readFile(out, 'utf8');
  return bundle;
}

// Run fn(page) on a page with the real BoatEntry mounted over a fresh in-memory storage.
async function withForm(fn) {
  const code = await load();
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  try {
    const context = await browser.newContext();
    try {
      const page = await context.newPage();
      await page.setContent('<div id="root"></div>');
      await page.addScriptTag({content: code});
      await page.evaluate(() => {
        const t = window.__t;
        const map = new Map();
        const storage = {getItem: k => (map.has(k) ? map.get(k) : null), setItem: (k, v) => { map.set(k, String(v)); }};
        window.__storage = storage; window.__map = map; window.__done = [];
        window.__submits = 0;
        t.configureStore({storage});
        t.savedLimits.value = {};
        t.render(t.h(t.BoatEntry, {storage, onDone: n => window.__done.push(n)}), document.getElementById('root'));
        document.querySelector('form').addEventListener('submit', () => { window.__submits++; });
      });
      await fn(page);
    } finally { await context.close(); }
  } finally { await browser.close(); }
}

const fill = async (page, typed) => { for (const [name, value] of Object.entries(typed)) await page.locator(`[name="${name}"]`).fill(value); };
const save = page => page.getByRole('button', {name: 'Save boat', exact: true}).click();
const state = page => page.evaluate(() => ({
  valid: document.querySelector('form').checkValidity(),
  submits: window.__submits,
  done: window.__done,
  boat: window.__map.get('skippercast-boat-v1') ?? null,
  limits: window.__map.get('skippercast-limits-v1') ?? null,
  mismatch: [...document.querySelectorAll('input')].map(i => i.validity.stepMismatch),
}));

test('boat_entry_inputs_declare_step_any_decimal_number', async () => {
  await withForm(async page => {
    const inputs = await page.evaluate(() => [...document.querySelectorAll('form input')].map(i => ({name: i.name, type: i.type, step: i.getAttribute('step'), mode: i.inputMode, required: i.required, min: i.getAttribute('min'), max: i.getAttribute('max')})));
    assert.deepEqual(inputs.map(i => i.name), ['lengthFt', 'wind', 'seas']);
    for (const i of inputs) assert.deepEqual([i.type, i.step, i.mode, i.required, i.min, i.max], ['number', 'any', 'decimal', false, null, null], i.name);
  });
});

test('boat_entry_fractional_seas_submits_natively', async () => {
  await withForm(async page => {
    await fill(page, {lengthFt: '19', wind: '12', seas: '2.5'});
    await save(page);
    const s = await state(page);
    assert.equal(s.valid, true);
    assert.deepEqual(s.mismatch, [false, false, false]);
    assert.equal(s.submits, 1);
    assert.deepEqual(s.done, [[]]);
    assert.equal(JSON.parse(s.limits).boat.seas, 2.5);
  });
});

test('boat_entry_fractional_length_submits_natively', async () => {
  await withForm(async page => {
    await fill(page, {lengthFt: '19.5'});
    await save(page);
    const s = await state(page);
    assert.equal(s.valid, true);
    assert.equal(s.submits, 1);
    assert.equal(JSON.parse(s.boat).boat.loa_ft, 19.5);
  });
  await withForm(async page => {
    await fill(page, {lengthFt: '19.5', wind: '12', seas: '2.5'});
    await save(page);
    const s = await state(page);
    assert.equal(s.submits, 1);
    assert.deepEqual(s.done, [[]]);
    assert.equal(JSON.parse(s.boat).boat.loa_ft, 19.5);
    assert.equal(JSON.parse(s.limits).boat.seas, 2.5);
  });
});

test('boat_entry_integer_and_blank_are_unchanged', async () => {
  await withForm(async page => {
    await fill(page, {lengthFt: '19', wind: '12', seas: '3'});
    await save(page);
    const s = await state(page);
    assert.equal(s.submits, 1);
    assert.equal(JSON.parse(s.boat).boat.loa_ft, 19);
  });
  await withForm(async page => {
    await save(page);
    const s = await state(page);
    assert.equal(s.submits, 1);
    assert.equal(s.boat, null);
    assert.equal(s.limits, null);
    assert.deepEqual(s.done, [[]]);
  });
  await withForm(async page => {
    await fill(page, {lengthFt: '19.5', seas: '2.5'});
    await page.getByRole('button', {name: 'Not now', exact: true}).click();
    const s = await state(page);
    assert.equal(s.submits, 0);
    assert.equal(s.boat, null);
    assert.equal(s.limits, null);
    assert.deepEqual(s.done, [[]]);
  });
});

test('boat_entry_validation_still_delegates_to_existing_policy', async () => {
  // Malformed native number input (real keystrokes) stays invalid and never submits.
  await withForm(async page => {
    await page.locator('[name="seas"]').click();
    await page.keyboard.type('1e');
    await save(page);
    const s = await state(page);
    assert.equal(s.valid, false);
    assert.equal(s.submits, 0);
    assert.equal(s.limits, null);
  });
  // Numeric but out-of-domain values reach the existing policy: length writes nothing, a wind limit is clamped with a notice.
  await withForm(async page => {
    await fill(page, {lengthFt: '200', wind: '999'});
    await save(page);
    const s = await state(page);
    assert.equal(s.submits, 1);
    assert.equal(s.boat, null);
    assert.equal(s.done.length, 1);
    assert.equal(s.done[0].length, 1);
    assert.match(s.done[0][0], /^Wind limit saved as \d+(\.\d+)? kt\.$/);
  });
  // A throwing store still reports the failure notice through the same submit path.
  const code = await load();
  const browser = await chromium.launch({headless: true, args: ['--no-sandbox']});
  try {
    const page = await browser.newPage();
    await page.setContent('<div id="root"></div>');
    await page.addScriptTag({content: code});
    await page.evaluate(() => {
      const t = window.__t;
      const broken = {getItem() { throw new Error('denied'); }, setItem() { throw new Error('QuotaExceededError'); }};
      window.__done = [];
      t.render(t.h(t.BoatEntry, {storage: broken, onDone: n => window.__done.push(n)}), document.getElementById('root'));
    });
    await fill(page, {lengthFt: '19.5'});
    await save(page);
    const done = await page.evaluate(() => window.__done);
    assert.equal(done.length, 1);
    assert.equal(done[0].length, 1);
  } finally { await browser.close(); }
});
