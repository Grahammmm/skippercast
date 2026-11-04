// SC1322-06 (SC-LAUNCH-4 follow-up e): the landing installs the cost-ceiling watch (web/degraded.ts) as
// /map does, shows /map's own saved-copies notice above its live verdict, and while degraded the verdict
// reads as from saved copies, not live. LandingApp is mounted on a small fake DOM (as
// tests/test_landing_port_retry.mjs) behind the page's real fetch wrapped by installDegradedWatch.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp, readFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const out = join(await mkdtemp(join(tmpdir(), 'landing-degraded-')), 'm.mjs');
await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
  export {LandingApp, LiveVerdict} from './web/landing/Landing.tsx';
  export {DegradedNotice} from './web/degraded-notice.tsx';
  export {degraded, installDegradedWatch} from './web/degraded.ts';
  export {render as html} from 'preact-render-to-string';
  export {h, render} from 'preact';`},
bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact'});
const {LandingApp, LiveVerdict, DegradedNotice, degraded, installDegradedWatch, html, h, render} = await import(pathToFileURL(out).href);

// A DOM just big enough for preact (as test_landing_port_retry.mjs).
class Node {
  constructor(type, name) { Object.assign(this, {nodeType: type, nodeName: name, childNodes: [], parentNode: null, on: {}, attrs: {}}); }
  get firstChild() { return this.childNodes[0] ?? null; }
  get nextSibling() { const i = this.parentNode?.childNodes.indexOf(this) ?? -1; return i < 0 ? null : this.parentNode.childNodes[i + 1] ?? null; }
  remove() { this.parentNode?.removeChild(this); }
  removeChild(c) { this.childNodes.splice(this.childNodes.indexOf(c), 1); c.parentNode = null; return c; }
  insertBefore(c, ref) { c.parentNode?.removeChild(c); const i = ref ? this.childNodes.indexOf(ref) : -1; this.childNodes.splice(i < 0 ? this.childNodes.length : i, 0, c); c.parentNode = this; return c; }
  appendChild(c) { return this.insertBefore(c, null); }
  setAttribute(k, v) { this.attrs[k] = String(v); } removeAttribute(k) { delete this.attrs[k]; }
  addEventListener(t, f) { this.on[t] = f; } removeEventListener(t) { delete this.on[t]; }
  focus() {}
}
class El extends Node { constructor(name) { super(1, name.toUpperCase()); this.style = {}; this.localName = name; } }
class Text extends Node { constructor(t) { super(3, '#text'); this.data = String(t); } }
globalThis.document = {createElement: n => new El(n), createElementNS: (_, n) => new El(n), createTextNode: t => new Text(t)};
const text = n => n.nodeType === 3 ? n.data : n.childNodes.map(text).join('');
const all = n => [n, ...n.childNodes.flatMap(all)];
const notices = root => all(root).filter(n => n.attrs?.['data-degraded'] === 'cost-ceiling' && n.localName === 'p');
const verdictOf = root => all(root).find(n => n.attrs?.class === 'landing-verdict');
const settle = () => new Promise(r => setTimeout(r, 60));

const V = {verdict: 'comfortable', word: 'Comfortable', sentence: 'Wind and sea inside the reference boat’s limits.', day: 'Tomorrow', date: '2026-10-09', place: 'Morro Bay & Avila', href: '/map?region=morro-bay&profile=boat&day=2026-10-09', boatName: 'reference 23 ft boat'};
/** The verdict as it rendered before SC1322-06 (the not-degraded snapshot). */
const LIVE_HTML = '<section class="landing-verdict" aria-live="polite" aria-label="Tomorrow’s brief" data-day="2026-10-09"><p class="landing-verdict-head">Tomorrow near Morro Bay &amp; Avila, reference 23 ft boat: <strong class="landing-verdict-word" data-verdict="comfortable">Comfortable</strong></p><p class="landing-verdict-limit">Wind and sea inside the reference boat’s limits.</p><a class="landing-verdict-link" href="/map?region=morro-bay&amp;profile=boat&amp;day=2026-10-09">Open the full brief</a></section>';
/** /map's notice, word for word as tests/test_app_shell.mjs asserts it on the masthead. */
const MAP_NOTICE = '<p class="app-limits-note app-degraded" role="status" data-degraded="cost-ceiling">Live data is paused for today to keep SkipperCast free; some readings are saved copies.</p>';
const NOT_LIVE = /saved copies|not live/i;

/** The page's fetch for a mounted landing: every read answers `reply()`; installDegradedWatch wraps it as main.tsx does. */
function page(reply) {
  const real = globalThis.fetch, asked = [];
  globalThis.fetch = async url => { asked.push(String(url)); return reply(); };
  installDegradedWatch();
  return {asked, restore: () => { globalThis.fetch = real; degraded.value = null; }};
}
const mount = () => { const root = new El('div'); render(h(LandingApp, {href: 'https://s.test/', navigate: () => {}, warm: async () => ({state: 'ready'}), verdict: async () => V}), root); return root; };
const costCeiling503 = () => new Response(JSON.stringify({degraded: true}), {status: 503, headers: {'X-SC-Degraded': 'cost-ceiling', 'Retry-After': '3600'}});

test('1: not degraded: the verdict renders exactly as before and the landing shows no notice', async () => {
  degraded.value = null;
  assert.equal(html(h(LiveVerdict, {v: V})), LIVE_HTML, 'the verdict snapshot is unchanged');
  assert.equal(html(h(LiveVerdict, {v: V, saved: false})), LIVE_HTML);
  assert.equal(html(h(DegradedNotice)), '', 'no notice while live');
  const string = html(h(LandingApp, {href: 'https://s.test/', navigate: () => {}, load: false}));
  assert.doesNotMatch(string, /data-degraded|saved copies/);
  const fetchPage = page(() => new Response('', {status: 404}));
  try {
    const root = mount();
    await settle();
    assert.ok(fetchPage.asked.length > 0, 'the landing read through the watched fetch');
    assert.equal(degraded.peek(), null, 'a plain 404 is not the cost ceiling');
    assert.equal(notices(root).length, 0, 'no notice');
    assert.ok(text(verdictOf(root)).startsWith('Tomorrow near Morro Bay & Avila'), 'the verdict as today');
    assert.doesNotMatch(text(root), NOT_LIVE);
    render(null, root);
  } finally { fetchPage.restore(); }
});

test('2: a 503 cost-ceiling reply seen by the watch: /map\'s notice above the verdict, which no longer reads as live', async () => {
  const fetchPage = page(costCeiling503);
  try {
    const root = mount();
    await settle();
    assert.deepEqual(degraded.peek(), {since: null}, 'the landing\'s own reads published the mark');
    const [notice] = notices(root);
    assert.ok(notice, 'the notice is on the landing');
    assert.equal(text(notice), 'Live data is paused for today to keep SkipperCast free; some readings are saved copies.');
    assert.equal(html(h(DegradedNotice)), MAP_NOTICE, 'the same element and words as /map');
    const verdict = verdictOf(root), kids = notice.parentNode.childNodes;
    assert.ok(verdict && kids.indexOf(notice) < kids.indexOf(verdict), 'the notice sits above the verdict');
    assert.equal(verdict.attrs['data-degraded'], 'cost-ceiling');
    assert.equal(verdict.attrs['aria-label'], 'Tomorrow’s brief, from saved copies');
    assert.ok(text(verdict).startsWith('From saved copies, not live: Tomorrow near Morro Bay & Avila'), text(verdict));
    assert.equal(text(verdict).match(/Comfortable/g)?.length, 1, 'the word itself is unchanged');
    render(null, root);
  } finally { fetchPage.restore(); }
});

test('2b: a 503 without the mark, or with another mark, is not the cost ceiling', async () => {
  for (const headers of [{}, {'X-SC-Degraded': 'maintenance'}, {'X-SC-Degraded': 'Cost-Ceiling'}]) {
    const fetchPage = page(() => new Response('', {status: 503, headers}));
    try {
      const root = mount();
      await settle();
      assert.equal(degraded.peek(), null, JSON.stringify(headers));
      assert.equal(notices(root).length, 0);
      assert.doesNotMatch(text(root), NOT_LIVE);
      render(null, root);
    } finally { fetchPage.restore(); }
  }
});

test('2c: the mark arriving after the verdict shows (a later read) still flips it to saved copies', async () => {
  let reply = () => new Response('', {status: 404});
  const fetchPage = page(() => reply());
  try {
    const root = mount();
    await settle();
    assert.equal(notices(root).length, 0);
    reply = costCeiling503;
    await globalThis.fetch('/feeds/data/regions/morro-bay/latest.json');
    await settle();
    assert.equal(notices(root).length, 1, 'the notice appears on screen');
    assert.match(text(verdictOf(root)), /^From saved copies, not live: /);
    render(null, root);
  } finally { fetchPage.restore(); }
});

test('3: recovery: when the watch clears, the notice goes and the verdict wording comes back', async () => {
  const fetchPage = page(costCeiling503);
  try {
    const root = mount();
    await settle();
    assert.equal(notices(root).length, 1);
    degraded.value = null;
    await settle();
    assert.equal(notices(root).length, 0, 'notice gone');
    const verdict = verdictOf(root);
    assert.equal(verdict.attrs['aria-label'], 'Tomorrow’s brief');
    assert.equal(verdict.attrs['data-degraded'], undefined);
    assert.ok(text(verdict).startsWith('Tomorrow near Morro Bay & Avila'), 'live wording back');
    assert.doesNotMatch(text(root), NOT_LIVE);
    render(null, root);
  } finally { fetchPage.restore(); }
});

test('4: installDegradedWatch twice in one page: one network call per read, the response untouched, one notice', async () => {
  let calls = 0;
  const response = costCeiling503();
  const scope = {fetch: async () => { calls++; return response; }};
  installDegradedWatch(scope);
  installDegradedWatch(scope);
  try {
    const got = await scope.fetch('/api/forecast');
    assert.equal(calls, 1, 'the page\'s fetch ran once');
    assert.equal(got, response, 'the same response object');
    assert.deepEqual(degraded.peek(), {since: null}, 'the same state as one install');
    assert.equal(html(h(DegradedNotice)), MAP_NOTICE, 'one notice, /map\'s words');
  } finally { degraded.value = null; }
  // The landing and /map are separate documents, each installing the watch once at the top of its entry.
  for (const [entry, page] of [['web/landing/main.tsx', 'dist/landing.html'], ['web/app/main.tsx', 'dist/app.html']]) {
    const code = await readFile(join(ROOT, entry), 'utf8');
    assert.equal(code.match(/^installDegradedWatch\(\);/gm)?.length, 1, `${entry}: one install`);
    assert.match(code, /^import \{installDegradedWatch\} from '\.\.\/degraded\.ts';$/m);
    const scripts = [...(await readFile(join(ROOT, page), 'utf8')).matchAll(/<script type="module" src="([^"]+)"/g)].map(m => m[1]);
    assert.deepEqual(scripts, [`../${entry}`], `${page} loads only its own entry`);
  }
});

test('the landing installs the watch before its first read, and its entry chunk carries the notice but not the map shell', async () => {
  const code = await readFile(join(ROOT, 'web/landing/main.tsx'), 'utf8');
  const install = code.search(/^installDegradedWatch\(\);/m);
  for (const first of [/^initTelemetry\(\);$/m, /^void savedPortTarget\(/m, /^mount\(/m]) assert.ok(install > 0 && install < code.search(first), `before ${first}`);
  const result = await build({entryPoints: [join(ROOT, 'web/landing/main.tsx')], bundle: true, splitting: true, format: 'esm', platform: 'browser', outdir: join(await mkdtemp(join(tmpdir(), 'landing-degraded-chunks-')), 'out'),
    write: false, metafile: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins, external: ['*.css']});
  const entry = Object.values(result.metafile.outputs).find(o => o.entryPoint?.endsWith('web/landing/main.tsx')), inputs = Object.keys(entry.inputs);
  for (const mod of ['web/degraded.ts', 'web/degraded-notice.tsx']) assert.ok(inputs.includes(mod), `${mod} is in the landing entry`);
  for (const mod of ['web/app/Masthead.tsx', 'web/app/App.tsx']) assert.ok(!inputs.includes(mod), `${mod} stays out of the landing`);
});
