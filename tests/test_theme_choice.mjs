import assert from 'node:assert/strict';
import test from 'node:test';
import {bootTheme} from '../web/theme-boot.ts';

const KEY = 'skippercast-theme-v1';
let navigation = 0;
function device(t, {light, stored = null, blocked = false}) {
  const scheme = Object.assign(new EventTarget(), {matches: light});
  const dataset = {};
  const before = Object.fromEntries(['localStorage', 'matchMedia', 'document'].map(key => [key, Object.getOwnPropertyDescriptor(globalThis, key)]));
  const globals = {
    localStorage: {
      getItem(key) { assert.equal(key, KEY); if (blocked) throw Error('blocked'); return stored; },
      setItem(key, value) { assert.equal(key, KEY); if (blocked) throw Error('blocked'); stored = value; },
    },
    matchMedia(query) { assert.equal(query, '(prefers-color-scheme: light)'); return scheme; },
    document: {documentElement: {dataset}},
  };
  for (const [key, value] of Object.entries(globals)) Object.defineProperty(globalThis, key, {configurable: true, value});
  t.after(() => {
    for (const [key, descriptor] of Object.entries(before)) {
      if (descriptor) Object.defineProperty(globalThis, key, descriptor); else delete globalThis[key];
    }
  });
  return {dataset, load: () => import(`../web/theme-choice.ts?navigation=${++navigation}`),
    change(matches) { scheme.matches = matches; scheme.dispatchEvent(Object.assign(new Event('change'), {matches})); }};
}

test('Auto uses the OS at boot and follows changes while open', async t => {
  const {dataset, load, change} = device(t, {light: true});
  bootTheme();
  assert.equal(dataset.theme, 'light');
  const {themeChoice} = await load();
  assert.equal(themeChoice.value, 'auto');
  change(false);
  assert.equal(Object.hasOwn(dataset, 'theme'), false);
  change(true);
  assert.equal(dataset.theme, 'light');
});

test('both overrides ignore OS changes and survive a new document boot and app load', async t => {
  const {dataset, load, change} = device(t, {light: false});
  const app = await load();
  app.setThemeChoice('light');
  assert.equal(dataset.theme, 'light');
  delete dataset.theme;
  bootTheme();
  assert.equal(dataset.theme, 'light');
  const reloaded = await load();
  assert.equal(reloaded.themeChoice.value, 'light');
  change(true);
  reloaded.setThemeChoice('dark');
  assert.equal(Object.hasOwn(dataset, 'theme'), false);
  change(false);
  change(true);
  assert.equal(Object.hasOwn(dataset, 'theme'), false);
  bootTheme();
  assert.equal(Object.hasOwn(dataset, 'theme'), false);
  const again = await load();
  assert.equal(again.themeChoice.value, 'dark');
  again.setThemeChoice('auto');
  assert.equal(dataset.theme, 'light');
});

test('junk and blocked storage fall back to Auto without preventing a page-only override', async t => {
  await t.test('junk', async t => {
    const {dataset, load} = device(t, {light: true, stored: '{junk'});
    bootTheme();
    assert.equal(dataset.theme, 'light');
    assert.equal((await load()).themeChoice.value, 'auto');
  });
  await t.test('blocked', async t => {
    const {dataset, load} = device(t, {light: false, blocked: true});
    const app = await load();
    assert.equal(app.themeChoice.value, 'auto');
    app.setThemeChoice('light');
    assert.equal(dataset.theme, 'light');
  });
});
