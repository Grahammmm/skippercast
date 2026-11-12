// SC1137-06: the shared fallback, the basis popover's source link and the cost-ceiling notice read the chosen language.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {readFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {preparedCatalogue} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname;

async function load() {
  const dir = await mkdtemp(join(tmpdir(), 'shared-chrome-'));
  const out = join(dir, 'm.mjs');
  await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
    export {Guard, GuardFallback} from './web/ui/Guard.tsx';
    export {Popover} from './web/ui/Popover.tsx';
    export {DegradedNotice} from './web/degraded-notice.tsx';
    export {degraded, degradedText} from './web/degraded.ts';
    export {language} from './web/i18n.ts';
    export {render} from 'preact-render-to-string';
    export {h} from 'preact';`},
  bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: [preparedCatalogue]});
  return import(pathToFileURL(out).href);
}

const m = await load();

const withLang = (lang, fn) => { m.language.value = lang; try { return fn(); } finally { m.language.value = 'en'; } };
const guarded = () => m.render(m.h(m.GuardFallback, {name: 'x', onRetry() {}}));

test('the failed boundary reads the chosen language; English is unchanged', () => {
  assert.equal(withLang('en', guarded), '<div class="ui-guard" role="status" data-guard="x"><p>This part could not load. The rest of the page still works.</p><button type="button">Try again</button></div>');
  assert.equal(withLang('es', guarded), '<div class="ui-guard" role="status" data-guard="x"><p>Esta parte no se pudo cargar. El resto de la página sigue funcionando.</p><button type="button">Intentar de nuevo</button></div>');
});

test('popover default summary and source link follow the language; caller summary, empty summary, sources=false and custom URL are untouched', () => {
  const pop = props => m.render(m.h(m.Popover, props, 'Body'));
  assert.ok(withLang('en', () => pop({})).includes('>Source</summary>') && withLang('en', () => pop({})).includes('<a href="/sources">How it’s built</a>'));
  const es = withLang('es', () => pop({}));
  assert.ok(es.includes('>Fuente</summary>') && es.includes('<a href="/sources">Cómo se hizo</a>'));
  assert.ok(withLang('es', () => pop({summary: 'Swell basis', iconOnly: true})).includes('aria-label="Swell basis"'));
  assert.ok(withLang('es', () => pop({summary: ''})).includes('></summary>'));
  assert.ok(!withLang('es', () => pop({sources: false})).includes('ui-popover-sources'));
  assert.ok(withLang('es', () => pop({sources: '/x'})).includes('<a href="/x">Cómo se hizo</a>'));
});

test('degradedText: injected clock kept, English default, Spanish whole templates and chosen-locale time', () => {
  assert.equal(m.degradedText(null, () => assert.fail('no call'), 'es'), null);
  assert.equal(m.degradedText({since: null}), 'Live data is paused for today to keep SkipperCast free; some readings are saved copies.');
  assert.equal(m.degradedText({since: null}, undefined, 'es'), 'Los datos en vivo están pausados por hoy para mantener SkipperCast gratis; algunas lecturas son copias guardadas.');
  const calls = [];
  assert.equal(m.degradedText({since: '2026-10-05T20:00:00.000Z'}, iso => (calls.push(iso), 'TIME'), 'es'), 'Los datos en vivo están pausados por hoy para mantener SkipperCast gratis; algunas lecturas son copias guardadas de TIME.');
  assert.equal(calls.length, 1);
  const iso = '2026-10-05T20:00:00.000Z', opts = {weekday: 'short', hour: 'numeric', minute: '2-digit'};
  assert.ok(m.degradedText({since: iso}, undefined, 'es').endsWith(`de ${new Date(iso).toLocaleString('es', opts)}.`));
  assert.ok(m.degradedText({since: iso}, undefined, 'en').endsWith(`from ${new Date(iso).toLocaleString('en-US', opts)}.`));
});

test('the shared notice follows the language and stays absent while live', () => {
  try {
    m.degraded.value = null;
    assert.equal(m.render(m.h(m.DegradedNotice, null)), '');
    m.degraded.value = {since: null};
    assert.ok(withLang('en', () => m.render(m.h(m.DegradedNotice, null))).includes('some readings are saved copies.</p>'));
    const es = withLang('es', () => m.render(m.h(m.DegradedNotice, null)));
    assert.ok(es.includes('role="status"') && es.includes('data-degraded="cost-ceiling"') && es.includes('copias guardadas.'));
  } finally { m.degraded.value = null; }
});

test('the new ids have en and es values with matching placeholders', () => {
  const strings = JSON.parse(readFileSync(join(ROOT, 'catalog/app/strings.json'), 'utf8')).strings;
  const ids = Object.keys(strings).filter(id => id.startsWith('shared.'));
  assert.equal(ids.length, 6);
  for (const id of ids) {
    const ph = s => (s.match(/\{\w+\}/g) ?? []).sort().join();
    assert.ok(strings[id].en && strings[id].es && ph(strings[id].en) === ph(strings[id].es), id);
  }
});
