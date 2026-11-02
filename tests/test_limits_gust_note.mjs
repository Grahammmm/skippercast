// RF2030-11: the Limits form says so, under the fields, when the highest-gust
// limit is below the wind limit (gusts then decide every window). The choice
// is still saved as typed.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const {gustBelowWind, defaultLimits} = await import('../packages/coast/src/limits.ts');
const ROOT = new URL('..', import.meta.url).pathname;
const NOTE = 'Your gust limit is below your wind limit, so gusts decide every window.';

let mod;
async function load() {
  if (mod) return mod;
  const out = join(await mkdtemp(join(tmpdir(), 'limits-gust-')), 'limits.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {LimitsForm} from './web/app/LimitsPanel.tsx';
      export {saveLimits, resetLimits, limitsFor} from './web/limits.ts';
      export {configureStore} from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  mod = await import(pathToFileURL(out).href);
  return mod;
}

/** The form rendered with the given saved limits for the profile; the limits are reset afterwards. */
async function formWith(profile, limits) {
  const {LimitsForm, render, h, configureStore, saveLimits, resetLimits} = await load();
  configureStore({storage: null});
  try {
    if (limits) saveLimits(profile, limits);
    return render(h(LimitsForm, {profile}));
  } finally { resetLimits(profile); }
}

test('defaults of every profile show no gust note', async () => {
  for (const profile of ['boat', 'shore', 'spear', 'kayak']) {
    const d = defaultLimits(profile);
    assert.ok(d.gust >= d.wind, `${profile} default gust is not below wind`);
    const html = await formWith(profile);
    assert.ok(!html.includes(NOTE), profile);
    assert.ok(!html.includes('-gust-note'), profile);
  }
});

test('boat wind 15 / gust 8 names the pair under the fields and the gust input points at it', async () => {
  const html = await formWith('boat', {wind: 15, gust: 8});
  assert.ok(html.includes(NOTE));
  const noteId = html.match(/<p class="app-limits-hint" role="note" id="([^"]+-gust-note)"/)?.[1];
  assert.ok(noteId, 'the note has an id');
  const gust = html.match(/<input id="[^"]+-gust"[^>]*>/)?.[0] ?? '';
  assert.ok(new RegExp(`aria-describedby="[^"]*-gust-hint ${noteId}"`).test(gust), 'gust input describedby lists the note');
  const wind = html.match(/<input id="[^"]+-wind"[^>]*>/)?.[0] ?? '';
  assert.ok(!wind.includes('gust-note'), 'the wind input does not');
  assert.ok(html.indexOf(NOTE) > html.indexOf('Highest seas'), 'the note follows the field list');
  assert.ok(html.indexOf(NOTE) < html.indexOf('Kept on this device only'), 'the note sits under the fields');
});

test('gust equal to wind (12/12) shows no note', async () => {
  const html = await formWith('boat', {wind: 12, gust: 12});
  assert.ok(!html.includes(NOTE));
  assert.ok(!/<input id="[^"]+-gust"[^>]*gust-note/.test(html));
});

test('gustBelowWind: strings parse, blank/non-numeric/NaN/Infinity compare nothing and never throw', () => {
  assert.equal(gustBelowWind({wind: '15', gust: '8'}), true);
  assert.equal(gustBelowWind({wind: 15, gust: 8}), true);
  assert.equal(gustBelowWind({wind: 12, gust: 12}), false);
  assert.equal(gustBelowWind({wind: 10, gust: 15}), false);
  for (const bad of ['', '  ', 'abc', null, undefined, NaN, Infinity, -Infinity, {}, []]) {
    assert.equal(gustBelowWind({wind: 15, gust: bad}), false, `gust ${String(bad)}`);
    assert.equal(gustBelowWind({wind: bad, gust: 8}), false, `wind ${String(bad)}`);
  }
});

test('saving 15/8 still stores exactly 15/8 (no value is changed for the user)', async () => {
  const {configureStore, saveLimits, resetLimits, limitsFor} = await load();
  configureStore({storage: null});
  try {
    const saved = saveLimits('boat', {wind: '15', gust: '8'});
    assert.equal(saved.wind, 15);
    assert.equal(saved.gust, 8);
    assert.equal(limitsFor('boat').wind, 15);
    assert.equal(limitsFor('boat').gust, 8);
  } finally { resetLimits('boat'); }
});

test('shore labels and the spear surge select are unaffected by a gust note', async () => {
  const shore = await formWith('shore', {wind: 12, gust: 8});
  assert.ok(shore.includes(NOTE));
  assert.match(shore, /Highest surf/);
  assert.ok(!shore.includes('Highest seas'));
  const spear = await formWith('spear', {wind: 10, gust: 7});
  assert.ok(spear.includes(NOTE));
  assert.match(spear, /Highest surge/);
  assert.ok(!spear.includes('>Heavy<'));
  assert.match(spear, /<select id="[^"]+-surge"[^>]*aria-describedby="[^"]+-surge-hint"/);
});
