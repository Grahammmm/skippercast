// SC-NEXT-03: offline browser events and real menu rendering/clicks.
import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp, rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedRendererPlugins} from './helpers/esbuild-url.mjs';
const dir = await mkdtemp(join(tmpdir(), 'install-app-'));
let m;
try {
  await build({stdin: {resolveDir: new URL('..', import.meta.url).pathname, loader: 'ts', contents: `
    export * from './web/install-app.ts'; export {InstallApp} from './web/app/InstallApp.tsx';
    export {language} from './web/i18n.ts'; export {render} from 'preact-render-to-string'; export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: join(dir, 'install.mjs'), jsx: 'automatic', jsxImportSource: 'preact', plugins: preparedRendererPlugins, logLevel: 'silent'});
  m = await import(pathToFileURL(join(dir, 'install.mjs')).href);
} finally { await rm(dir, {recursive: true, force: true}); }
const safari = 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1';
function browser(ua = 'Firefox/130.0', standalone = false, appleStandalone = false) {
  const win = new EventTarget();
  win.navigator = {userAgent: ua, standalone: appleStandalone}; win.matchMedia = () => ({matches: standalone});
  m.installable.value = null; m.language.value = 'en'; m.watchInstall(win);
  return win;
}
function offer(win, prompt = async () => ({outcome: 'accepted'})) {
  const event = new Event('beforeinstallprompt', {cancelable: true}); event.prompt = prompt;
  win.dispatchEvent(event); return event;
}
function html(win) { return m.render(m.h(m.InstallApp, {win})); }
function click(win) { return m.InstallApp({win}).props.children.props.onClick(); }
test('watchInstall defaults to the browser window', () => {
  const win = new EventTarget(); globalThis.window = win;
  try { m.watchInstall(); const event = offer(win); assert.equal(m.installable.value, event); }
  finally { delete globalThis.window; m.installable.value = null; }
});
test('install_event_kept: prevents the prompt and repeated watches do not duplicate listeners', () => {
  const win = browser(); m.watchInstall(win);
  const event = new Event('beforeinstallprompt'); let prevented = 0;
  event.preventDefault = () => prevented++; win.dispatchEvent(event);
  assert.equal(prevented, 1); assert.equal(m.installable.value, event);
  assert.match(html(win), /<li><button[^>]*>Install the app<\/button><\/li>/);
});
for (const outcome of ['accepted', 'dismissed', 'expired']) test(`install_prompt_clears: ${outcome} and duplicate click`, async () => {
  const win = browser(); let calls = 0, settle;
  offer(win, () => { calls++; return new Promise((resolve, reject) => { settle = () => outcome === 'expired' ? reject(Error('expired')) : resolve({outcome}); }); });
  const button = m.InstallApp({win}).props.children;
  const first = button.props.onClick(); await button.props.onClick();
  assert.equal(calls, 1); assert.equal(m.installable.value, null); assert.equal(html(win), '');
  settle(); await first; assert.equal(m.installable.value, null);
});
test('stale completion cannot erase a newer install event', async () => {
  const win = browser(); let finish;
  offer(win, () => new Promise(resolve => { finish = resolve; })); const pending = click(win);
  const newer = offer(win); finish({outcome: 'dismissed'}); await pending;
  assert.equal(m.installable.value, newer);
});
test('install_hidden_when_standalone: display mode and Apple flag override a kept event and iOS hint', () => {
  for (const flags of [[true, false], [false, true]]) {
    const win = browser(safari, ...flags); offer(win);
    assert.equal(m.isStandalone(win), true); assert.equal(html(win), '');
  }
});
test('install_ios_hint: Safari only, with translated words', () => {
  const win = browser(safari); assert.match(html(win), /Share.*Add to Home Screen/);
  m.language.value = 'es'; assert.match(html(win), /Compartir.*Añadir a pantalla de inicio/);
  for (const token of ['CriOS/130.0', 'FxiOS/130.0', 'EdgiOS/130.0', 'OPiOS/130.0']) {
    const other = browser(safari.replace('Version/18.0', token));
    assert.equal(m.isIosSafari(other.navigator.userAgent), false); assert.equal(html(other), '');
  }
});
test('install_appinstalled: a retained event is withdrawn', () => {
  const win = browser(); offer(win); win.dispatchEvent(new Event('appinstalled'));
  assert.equal(m.installable.value, null); assert.equal(html(win), '');
});
test('install_absent_by_default: no event on desktop Firefox', () => { assert.equal(html(browser()), ''); });
