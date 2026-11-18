import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedCatalogue} from './helpers/esbuild-url.mjs';
const root = new URL('..', import.meta.url).pathname;
const out = join(await mkdtemp(join(tmpdir(), 'wake-lock-')), 'm.mjs');
await build({stdin: {resolveDir: root, loader: 'ts', contents: `
  export {createKeepAwake} from './web/wake-lock.ts';
  export {KeepAwake} from './web/app/KeepAwake.tsx';
  export {language} from './web/i18n.ts';
  export {render} from 'preact-render-to-string'; export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent',
  jsx: 'automatic', jsxImportSource: 'preact', plugins: [preparedCatalogue]});
const m = await import(pathToFileURL(out).href), key = 'skippercast-keep-awake-v1';
const tick = () => new Promise(resolve => setImmediate(resolve));
function fixture({saved, denied = false, supported = true, request} = {}) {
  const doc = new EventTarget(); doc.visibilityState = 'visible';
  const values = new Map(saved ? [[key, '1']] : []), calls = [], locks = [];
  const store = {getItem(k) { if (denied) throw Error(); return values.get(k); },
    setItem(k, v) { if (denied) throw Error(); values.set(k, v); }, removeItem(k) { if (denied) throw Error(); values.delete(k); }};
  const nav = supported ? {wakeLock: {request(type) { calls.push(type); if (request) return request();
    const lock = new EventTarget(); lock.releases = 0;
    lock.release = async () => { lock.releases++; lock.dispatchEvent(new Event('release')); }; locks.push(lock); return Promise.resolve(lock);
  }}} : {};
  const control = m.createKeepAwake({nav, doc, store});
  return {control, doc, values, calls, locks, visible(state) { doc.visibilityState = state; doc.dispatchEvent(new Event('visibilitychange')); }};
}
test('default off; on requests screen once, persists, and duplicate on/visible does not request', async () => {
  const f = fixture(); assert.equal(f.control.enabled.value, false); assert.equal(f.calls.length, 0);
  f.control.set(true); f.control.set(true); f.visible('visible'); await tick();
  assert.equal(f.calls.join(), 'screen'); assert.equal(f.values.get(key), '1');
  f.control.set(false); f.control.set(false); await tick();
  assert.equal(f.locks[0].releases, 1); assert.equal(f.values.has(key), false); assert.equal(f.calls.length, 1);
});
test('hidden releases; returning visible reacquires only while enabled; browser-expired lock can reacquire', async () => {
  const f = fixture(); f.control.set(true); await tick(); f.visible('hidden'); await tick();
  assert.equal(f.locks[0].releases, 1); f.visible('visible'); await tick(); assert.equal(f.calls.length, 2);
  await f.locks[1].release(); f.visible('visible'); await tick(); assert.equal(f.calls.length, 3);
  f.control.set(false); f.visible('hidden'); f.visible('visible'); await tick(); assert.equal(f.calls.length, 3);
});
test('rejection turns off, clears saved choice and renders a translated status', async () => {
  const f = fixture({request: () => Promise.reject(new DOMException('denied', 'NotAllowedError'))});
  f.control.set(true); await tick(); assert.equal(f.control.enabled.value, false);
  assert.equal(f.control.status.value, 'keepAwake.failed'); assert.equal(f.values.has(key), false);
  m.language.value = 'es'; const html = m.render(m.h(m.KeepAwake, {control: f.control})); m.language.value = 'en';
  assert.ok(html.includes('aria-pressed="false"') && html.includes('role="status"') && html.includes('No se pudo mantener'));
});
test('unsupported renders nothing; storage denied still works in session; prior explicit choice is remembered', async () => {
  const no = fixture({supported: false}); no.control.set(true); assert.equal(no.control.supported(), false);
  assert.equal(m.render(m.h(m.KeepAwake, {control: no.control})), ''); assert.equal(no.control.enabled.value, false);
  const f = fixture({denied: true}); f.control.set(true); await tick(); assert.equal(f.calls.length, 1);
  assert.ok(m.render(m.h(m.KeepAwake, {control: f.control})).includes('aria-pressed="true"'));
  const saved = fixture({saved: true}); await tick(); assert.equal(saved.calls.length, 1); assert.equal(saved.control.enabled.value, true);
  const hidden = fixture(); hidden.visible('hidden'); hidden.control.set(true); assert.equal(hidden.calls.length, 0);
});
test('cancelled or hidden pending acquisition releases stale result; stale rejection cannot disable a new request', async () => {
  let resolve, reject; const pending = [];
  const f = fixture({request: () => new Promise((yes, no) => { resolve = yes; reject = no; pending.push({resolve, reject}); })});
  f.control.set(true); f.control.set(false); f.control.set(true);
  pending[0].reject(Error('stale')); await tick(); assert.equal(f.control.enabled.value, true); assert.equal(f.control.status.value, '');
  let releases = 0; const lock = new EventTarget(); lock.release = async () => { releases++; };
  f.visible('hidden'); pending[1].resolve(lock); await tick(); assert.equal(releases, 1);
  f.visible('visible'); assert.equal(pending.length, 3); f.control.set(false); pending[2].resolve(lock); await tick();
  assert.equal(releases, 2); assert.equal(f.control.enabled.value, false);
});
