// SC1407-09: English pages never request the Spanish table; a Spanish page renders Spanish from its first translated
// render; a switch loads the table once and the latest choice wins; a failed load stays English, says so once and can
// be retried; the generated tables are exactly the catalogue's. The production readers run unmodified: the only stand-in
// is the network, the one dynamic import in web/i18n-catalogue.ts, which a test plugin routes to a recorder.
import assert from 'node:assert/strict';
import test from 'node:test';
import util from 'node:util';
import {execFileSync} from 'node:child_process';
import {mkdtemp, mkdir, readFile, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugin, rendererPlugins} from './helpers/esbuild-url.mjs';
import {generate, COMMAND} from '../scripts/build_landing_strings.mjs';

const ROOT = new URL('..', import.meta.url).pathname;
const CATALOGUE = JSON.parse(await readFile(join(ROOT, 'catalog/app/strings.json'), 'utf8')).strings;
const SPANISH = JSON.parse(await readFile(join(ROOT, 'web/strings.es.generated.json'), 'utf8'));
const REQUEST = "import('./strings.es.generated.json', {with: {type: 'json'}})";

// The network stand-in: every Spanish request calls globalThis.__spanishRequest, which the test answers.
const recorder = {name: 'spanish-request-recorder', setup: b => {
  b.onLoad({filter: /[\\/]web[\\/]i18n-catalogue\.ts$/}, async args => {
    const code = await readFile(args.path, 'utf8');
    assert.equal(code.split(REQUEST).length, 2, 'the catalogue module has exactly one literal Spanish import');
    return {contents: code.replace(REQUEST, 'globalThis.__spanishRequest()'), loader: 'ts'};
  });
}};

let bundleURL, copies = 0;
/** A fresh page: its own module instances (no table, no failure), answering Spanish requests with `answer()`. */
async function page(answer = () => Promise.resolve({default: SPANISH})) {
  if (!bundleURL) {
    const out = join(await mkdtemp(join(tmpdir(), 'i18n-catalogue-')), 'm.mjs');
    await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {initReadyLanguage, chooseReadyLanguage, catalogueFailed, catalogueLoading, language, t, STRINGS, LANGUAGE_KEY} from './web/i18n.ts';
      export {t as landingT, STRINGS as LANDING} from './web/landing/i18n.ts';
      export {spanishReady} from './web/i18n-catalogue.ts';
      export {LanguageChoice} from './web/app/LanguageChoice.tsx';
      export {LandingHead} from './web/landing/Landing.tsx';
      export {render} from 'preact-render-to-string';
      export {h, options} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: [rendererPlugin, recorder]});
    bundleURL = pathToFileURL(out).href;
  }
  const requests = [];
  globalThis.__spanishRequest = () => { requests.push(1); return answer(requests.length); };
  const m = await import(`${bundleURL}?page=${++copies}`);
  return {m, requests};
}

const deferred = () => { let resolve, reject; const promise = new Promise((y, n) => { resolve = y; reject = n; }); return {promise, resolve, reject}; };
const tick = () => new Promise(r => setTimeout(r, 0));
const memory = (init = {}) => { const map = new Map(Object.entries(init)), writes = []; return {getItem: k => map.get(k) ?? null, setItem: (k, v) => { writes.push([k, v]); map.set(k, String(v)); }, writes}; };
const env = (over = {}) => ({search: '', storage: memory(), languages: ['en-US'], doc: {documentElement: {lang: ''}}, ...over});

/** Render LanguageChoice, returning its HTML and its two buttons' real click handlers. */
function choice(m) {
  const buttons = {}, old = m.options.vnode;
  m.options.vnode = vnode => { if (vnode.type === 'button' && vnode.props?.lang) buttons[vnode.props.lang] = vnode.props.onClick; old?.(vnode); };
  try { return {html: m.render(m.h(m.LanguageChoice, {})), buttons}; } finally { m.options.vnode = old; }
}
/** Click a rendered button the way the browser would; returns whether it kept focus. */
function click(handler) { let focused = false; handler({currentTarget: {focus: () => { focused = true; }}}); return focused; }
const statusText = html => [...html.matchAll(/<span role="status">([^<]*)<\/span>/g)].map(x => x[1]);
const withStorage = async (storage, run) => { const old = globalThis.localStorage; globalThis.localStorage = storage; try { return await run(); } finally { globalThis.localStorage = old; } };

// ---- english_cold_graph_and_requests_exclude_spanish ----

test('english_cold_graph_and_requests_exclude_spanish: neither entry loads the Spanish table or the bilingual catalogue at first paint; it is a separate dynamic chunk', async () => {
  const result = await build({entryPoints: [join(ROOT, 'web/app/main.tsx'), join(ROOT, 'web/landing/main.tsx')], bundle: true, splitting: true, format: 'esm', platform: 'browser', minify: true,
    outdir: join(await mkdtemp(join(tmpdir(), 'i18n-graph-')), 'out'), write: false, metafile: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins, external: ['*.css']});
  const outputs = result.metafile.outputs;
  const closure = (entry, dynamic) => { const seen = new Set(), walk = p => { if (seen.has(p)) return; seen.add(p); for (const i of outputs[p]?.imports ?? []) if (i.kind === 'import-statement' || (dynamic && i.kind === 'dynamic-import')) walk(i.path); }; walk(entry); return [...seen].flatMap(p => Object.keys(outputs[p]?.inputs ?? {})); };
  for (const name of ['web/app/main.tsx', 'web/landing/main.tsx']) {
    const entry = Object.keys(outputs).find(p => outputs[p].entryPoint === name);
    const first = closure(entry, false);
    assert.ok(first.includes(name === 'web/app/main.tsx' ? 'web/strings.en.generated.json' : 'web/landing/strings.generated.json'), `${name}: the English table ships at first paint`);
    assert.ok(!first.includes('web/strings.es.generated.json'), `${name}: no Spanish table at first paint`);
    assert.ok(!first.includes('catalog/app/strings.json'), `${name}: no bilingual catalogue at first paint`);
    assert.ok(closure(entry, true).includes('web/strings.es.generated.json'), `${name}: Spanish stays reachable on demand`);
  }
});

test('english_cold_graph_and_requests_exclude_spanish: an English page (browser, stored or linked English) never requests Spanish, and renders English', async () => {
  for (const over of [{}, {storage: memory({'skippercast-language-v1': 'en'}), languages: ['es-MX']}, {search: '?lang=en', languages: ['es']}, {storage: null, languages: undefined}]) {
    const {m, requests} = await page(() => { throw Error('an English page asked for Spanish'); });
    const e = env(over);
    assert.equal(await m.initReadyLanguage(e), 'en');
    assert.equal(e.doc.documentElement.lang, 'en');
    const {html} = choice(m);
    assert.match(html, /<h2[^>]*>Language<\/h2>/);
    assert.deepEqual(statusText(html), [''], 'no failure notice');
    assert.doesNotMatch(m.render(m.h(m.LandingHead, {href: 'https://s.test/'})), /role="status"/);
    assert.equal(m.t('menu.language', 'es'), 'Language', 'without the table, Spanish reads English, never an id or a blank');
    await tick();
    assert.equal(requests.length, 0, `${JSON.stringify(over)}: no Spanish request`);
  }
});

// ---- spanish_known_before_first_translated_render ----

test('spanish_known_before_first_translated_render: a linked, stored or browser Spanish waits for its table, then every id reads its catalogue text', async () => {
  const cases = [{search: '?lang=es'}, {storage: memory({'skippercast-language-v1': 'es'})}, {languages: ['es-MX', 'en']},
    {storage: {getItem() { throw Error('blocked'); }, setItem() { throw Error('blocked'); }}, languages: ['es']}, {search: '?lang=es', storage: memory({'skippercast-language-v1': 'en'})}];
  for (const over of cases) {
    const gate = deferred();
    const {m, requests} = await page(() => gate.promise);
    const e = env(over);
    let settled = false;
    const ready = m.initReadyLanguage(e).then(lang => { settled = true; return lang; });
    await tick();
    assert.equal(settled, false, `${JSON.stringify(over)}: the first render waits for the table`);
    assert.equal(m.spanishReady(), false);
    gate.resolve({default: SPANISH});
    assert.equal(await ready, 'es');
    assert.equal(e.doc.documentElement.lang, 'es');
    assert.equal(m.language.peek(), 'es');
    assert.equal(requests.length, 1, 'one request');
    assert.match(choice(m).html, /<h2[^>]*>Idioma<\/h2>/);
    assert.match(m.render(m.h(m.LandingHead, {href: 'https://s.test/'})), /aria-label="[^"]+"/);
    assert.equal(m.landingT('landing.aria.site', 'es'), CATALOGUE['landing.aria.site'].es);
  }
  // Every id resolves, in both tables, to the catalogue's exact text with the same placeholders.
  const {m} = await page();
  await m.initReadyLanguage(env({search: '?lang=es'}));
  const ids = Object.keys(CATALOGUE);
  assert.ok(util.isDeepStrictEqual(Object.keys(m.STRINGS), ids), 'the app reader has every catalogue id, in order');
  for (const id of ids) {
    assert.equal(m.t(id, 'en'), CATALOGUE[id].en, `${id} en`);
    assert.equal(m.t(id, 'es'), CATALOGUE[id].es, `${id} es`);
  }
  for (const id of Object.keys(m.LANDING)) {
    assert.equal(m.landingT(id, 'en'), CATALOGUE[id].en, `landing ${id} en`);
    assert.equal(m.landingT(id, 'es'), CATALOGUE[id].es, `landing ${id} es`);
  }
});

// ---- spanish_switch_single_flight_and_latest_choice_wins ----

test('spanish_switch_single_flight_and_latest_choice_wins: two clicks share one request; Spanish applies once ready; a later English choice wins; a later Spanish reuses the table', async () => {
  const storage = memory();
  await withStorage(storage, async () => {
    const gate = deferred();
    const {m, requests} = await page(() => gate.promise);
    await m.initReadyLanguage(env());
    const {buttons} = choice(m);
    assert.equal(click(buttons.es), true, 'the activated button keeps focus');
    click(buttons.es);
    await tick();
    assert.equal(requests.length, 1, 'two pending Spanish choices share one request');
    assert.equal(m.language.peek(), 'en', 'English stays until the table arrives');
    assert.equal(m.catalogueLoading.peek(), true);
    assert.deepEqual(storage.writes, [], 'nothing stored before Spanish is ready');
    gate.resolve({default: SPANISH});
    await tick(); await tick();
    assert.equal(m.language.peek(), 'es');
    assert.equal(m.catalogueLoading.peek(), false);
    assert.match(choice(m).html, /<h2[^>]*>Idioma<\/h2>/, 'the menu re-renders in Spanish');
    assert.deepEqual(storage.writes.at(-1), ['skippercast-language-v1', 'es']);
    click(choice(m).buttons.en);
    assert.equal(m.language.peek(), 'en', 'English applies at once');
    click(choice(m).buttons.es);
    assert.equal(m.language.peek(), 'en', 'still a promise tick away');
    await tick();
    assert.equal(m.language.peek(), 'es', 'a later Spanish reuses the table');
    assert.equal(requests.length, 1, 'no second request');
  });
  for (const outcome of ['success', 'failure']) {
    await withStorage(memory(), async () => {
      const gate = deferred();
      const {m} = await page(() => gate.promise);
      await m.initReadyLanguage(env());
      click(choice(m).buttons.es);
      click(choice(m).buttons.en);
      if (outcome === 'success') gate.resolve({default: SPANISH}); else gate.reject(Error('offline'));
      await tick(); await tick();
      assert.equal(m.language.peek(), 'en', `${outcome}: the newer English choice wins`);
      assert.equal(m.catalogueFailed.peek(), false, `${outcome}: a stale request raises nothing`);
      assert.equal(m.catalogueLoading.peek(), false);
      assert.equal(globalThis.localStorage.writes.at(-1)[1], 'en');
    });
  }
});

// ---- spanish_load_failure_is_english_once_and_retryable ----

const FAILURES = {
  rejected: () => Promise.reject(Error('chunk failed')),
  malformed: () => Promise.resolve({default: ['not', 'a', 'table']}),
  partial: () => { const {'menu.language': _gone, ...rest} = SPANISH; return Promise.resolve({default: rest}); },
  blank: () => Promise.resolve({default: {...SPANISH, 'landing.aria.site': ''}}),
};

test('spanish_load_failure_is_english_once_and_retryable: at startup a failed, malformed or partial table keeps English, says so once, and a retry loads Spanish', async () => {
  let unhandled = 0;
  const count = () => { unhandled++; };
  process.on('unhandledRejection', count);
  try {
    for (const [name, fail] of Object.entries(FAILURES)) {
      const stored = memory({'skippercast-language-v1': 'es'});
      await withStorage(stored, async () => {
        const {m, requests} = await page(n => n === 1 ? fail() : Promise.resolve({default: SPANISH}));
        const e = env({storage: stored});
        assert.equal(await m.initReadyLanguage(e), 'en', `${name}: English in effect`);
        assert.equal(m.language.peek(), 'en');
        assert.equal(e.doc.documentElement.lang, 'en', `${name}: the document says English`);
        assert.equal(m.spanishReady(), false, `${name}: no partial Spanish installed`);
        assert.equal(m.t('menu.language', 'es'), 'Language', `${name}: Spanish lookups read English`);
        assert.equal(stored.getItem('skippercast-language-v1'), 'es', `${name}: the stored request is kept for a reload or retry`);
        const {html, buttons} = choice(m);
        assert.deepEqual(statusText(html), [CATALOGUE['language.loadFailed'].en], `${name}: one notice beside the choice`);
        assert.match(html, /<h2[^>]*>Language<\/h2>/);
        const head = m.render(m.h(m.LandingHead, {href: 'https://s.test/?region=morro-bay#tide'}));
        assert.equal(head.split(CATALOGUE['language.loadFailed'].en).length, 2, `${name}: the landing says it once`);
        assert.match(head, /<a href="\/\?region=morro-bay&amp;lang=es#tide" lang="es">Try Español again<\/a>/, `${name}: the retry reloads this address with lang=es`);
        click(buttons.es);
        await tick(); await tick();
        assert.equal(requests.length, 2, `${name}: an explicit retry asks again, once`);
        assert.equal(m.language.peek(), 'es', `${name}: the retry loads Spanish`);
        assert.equal(m.catalogueFailed.peek(), false);
        assert.deepEqual(statusText(choice(m).html), [''], `${name}: the notice clears`);
      });
    }
    await tick();
    assert.equal(unhandled, 0, 'no unhandled rejection');
  } finally { process.off('unhandledRejection', count); }
});

test('spanish_load_failure_is_english_once_and_retryable: a failed switch keeps English and its button, says so once however often it fails, and never retries on its own', async () => {
  await withStorage(memory(), async () => {
    const {m, requests} = await page(() => Promise.reject(Error('offline')));
    await m.initReadyLanguage(env());
    for (const attempt of [1, 2]) {
      click(choice(m).buttons.es);
      await tick(); await tick();
      assert.equal(m.language.peek(), 'en');
      assert.equal(m.catalogueFailed.peek(), true);
      const {html} = choice(m);
      assert.deepEqual(statusText(html), [CATALOGUE['language.loadFailed'].en], `attempt ${attempt}: one notice`);
      assert.match(html, /aria-pressed="true"[^>]*>English<|lang="en"[^>]*aria-pressed="true"/, 'English stays pressed');
      assert.equal(requests.length, attempt, 'one request per explicit choice');
    }
    await tick();
    assert.equal(requests.length, 2, 'no automatic retry');
    assert.deepEqual(globalThis.localStorage.writes, [], 'a failed Spanish is not stored');
    click(choice(m).buttons.en);
    assert.equal(m.language.peek(), 'en', 'English still works');
  });
});

// ---- generated_tables_exact_and_stale_check_refuses ----

test('generated_tables_exact_and_stale_check_refuses: the three tables are the catalogue, --check refuses a stale or missing table, and the catalogue must be complete', async () => {
  execFileSync(process.execPath, ['scripts/build_landing_strings.mjs', '--check'], {cwd: ROOT});
  const en = JSON.parse(await readFile(join(ROOT, 'web/strings.en.generated.json'), 'utf8'));
  const landing = JSON.parse(await readFile(join(ROOT, 'web/landing/strings.generated.json'), 'utf8'));
  assert.ok(util.isDeepStrictEqual(Object.keys(en), Object.keys(CATALOGUE)) && util.isDeepStrictEqual(Object.keys(SPANISH), Object.keys(CATALOGUE)), 'every id, in catalogue order');
  for (const [id, entry] of Object.entries(CATALOGUE)) {
    assert.ok(util.isDeepStrictEqual(en[id], {en: entry.en}), `${id}: English only`);
    assert.equal(SPANISH[id], entry.es, id);
  }
  for (const [id, entry] of Object.entries(landing)) assert.ok(util.isDeepStrictEqual(entry, {en: CATALOGUE[id].en}), `${id}: the landing slice is English only`);
  for (const id of ['language.loadFailed', 'language.retrySpanish']) assert.ok(Object.hasOwn(landing, id), `${id}: in the landing's first paint`);

  const root = await mkdtemp(join(tmpdir(), 'strings-gen-')), base = pathToFileURL(root + '/');
  await mkdir(join(root, 'catalog/app'), {recursive: true}); await mkdir(join(root, 'web/landing'), {recursive: true});
  const source = strings => writeFile(join(root, 'catalog/app/strings.json'), JSON.stringify({strings}));
  await source({'x.one': {en: 'One {n}', es: 'Uno {n}'}, 'landing.hero.title': {en: 'Hi', es: 'Hola'}});
  assert.throws(() => generate({check: true, root: base}), error => error.message.includes(COMMAND) && error.message.includes('web/strings.es.generated.json'), 'missing tables are stale');
  assert.equal(generate({root: base}).length, 3);
  assert.deepEqual(generate({check: true, root: base}), [], 'fresh tables pass');
  assert.equal(await readFile(join(root, 'web/strings.es.generated.json'), 'utf8'), '{"x.one":"Uno {n}","landing.hero.title":"Hola"}\n');
  assert.equal(await readFile(join(root, 'web/landing/strings.generated.json'), 'utf8'), '{"landing.hero.title":{"en":"Hi"}}\n');
  await source({'x.one': {en: 'One {n}', es: 'Uno más {n}'}, 'landing.hero.title': {en: 'Hi', es: 'Hola'}});
  assert.throws(() => generate({check: true, root: base}), /Stale web\/strings\.es\.generated\.json: run node scripts\/build_landing_strings\.mjs/, 'a changed source refuses');
  assert.equal(await readFile(join(root, 'web/strings.es.generated.json'), 'utf8'), '{"x.one":"Uno {n}","landing.hero.title":"Hola"}\n', '--check writes nothing');
  generate({root: base});
  await writeFile(join(root, 'web/strings.en.generated.json'), '{}\n');
  assert.throws(() => generate({check: true, root: base}), /Stale web\/strings\.en\.generated\.json/, 'stale generated bytes refuse');
  for (const [name, entry] of [['missing Spanish', {en: 'Two'}], ['blank Spanish', {en: 'Two', es: ''}], ['missing English', {es: 'Dos'}]]) {
    await source({'x.two': entry});
    assert.throws(() => generate({root: base}), /x\.two: no (?:English|Spanish) string/, name);
  }
});

// ---- RF1651-7: one latest-request order across initReadyLanguage and chooseReadyLanguage ----

test('english_init_supersedes_pending_spanish_choice: a later English init wins over an older pending Spanish choice, on success and on failure', async () => {
  for (const outcome of ['success', 'failure']) {
    for (const failedBefore of [false, true]) {
      const storage = memory();
      await withStorage(storage, async () => {
        const gate = deferred();
        const {m, requests} = await page(() => gate.promise);
        const e = env({storage});
        await m.initReadyLanguage(e);
        if (failedBefore) m.catalogueFailed.value = true;
        const old = m.chooseReadyLanguage('es', e);
        await tick();
        assert.equal(m.catalogueLoading.peek(), true);
        assert.equal(await m.initReadyLanguage(e), 'en', 'the newer init resolves English');
        assert.equal(m.catalogueLoading.peek(), false, 'English init settles the older loading indicator');
        if (outcome === 'success') gate.resolve({default: SPANISH}); else gate.reject(Error('offline'));
        assert.equal(await old, 'en', `${outcome}: the settled old choice resolves the effective language`);
        assert.equal(m.language.peek(), 'en');
        assert.equal(e.doc.documentElement.lang, 'en');
        assert.equal(m.catalogueLoading.peek(), false);
        assert.equal(m.catalogueFailed.peek(), failedBefore, `${outcome}: the failure flag is neither raised nor cleared by the stale request`);
        assert.ok(!storage.writes.some(w => w[1] === 'es'), 'no Spanish preference written');
        assert.equal(requests.length, 1, 'no duplicate import');
      });
    }
  }
});

test('superseded_spanish_initializer_returns_effective_language: an initial Spanish load overtaken by an English choice resolves English and owns no flags', async () => {
  for (const outcome of ['success', 'failure']) {
    await withStorage(memory(), async () => {
      const gate = deferred();
      const {m} = await page(() => gate.promise);
      const e = env({search: '?lang=es'});
      const init = m.initReadyLanguage(e);
      await tick();
      assert.equal(await m.chooseReadyLanguage('en', e), 'en');
      if (outcome === 'success') gate.resolve({default: SPANISH}); else gate.reject(Error('offline'));
      assert.equal(await init, 'en', `${outcome}: the stale initializer returns the effective language`);
      assert.equal(m.language.peek(), 'en');
      assert.equal(e.doc.documentElement.lang, 'en');
      assert.equal(m.catalogueFailed.peek(), false, `${outcome}: stale work raises no failure`);
      assert.equal(m.catalogueLoading.peek(), false);
    });
  }
});

test('newest_spanish_request_owns_flags: a stale Spanish settlement does not clear or raise the newer request\'s state; a retry after failure succeeds', async () => {
  await withStorage(memory(), async () => {
    const gates = [deferred(), deferred()];
    const {m, requests} = await page(n => gates[n - 1].promise);
    const e = env();
    await m.initReadyLanguage(e);
    const first = m.chooseReadyLanguage('es', e);
    const second = m.chooseReadyLanguage('es', e);
    await tick();
    assert.equal(requests.length, 1, 'one shared import');
    gates[0].reject(Error('offline'));
    assert.equal(await first, 'en');
    assert.equal(await second, 'en');
    assert.equal(m.catalogueFailed.peek(), true, 'the newest request owns the failure');
    assert.equal(m.catalogueLoading.peek(), false);
    const retry = m.chooseReadyLanguage('es', e);
    await tick();
    assert.equal(requests.length, 2, 'one new request on retry');
    gates[1].resolve({default: SPANISH});
    assert.equal(await retry, 'es');
    assert.equal(m.catalogueFailed.peek(), false, 'success clears the failure');
    assert.equal(m.language.peek(), 'es');
  });
});
