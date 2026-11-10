// SC1922-04: status admission and the shared surfaces, using the committed directory.
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
const directory = JSON.parse(readFileSync(new URL('../dist/data/home-ports.json', import.meta.url)));
const out = join(await mkdtemp(join(tmpdir(), 'preview-')), 'shell.mjs');
await build({stdin: {resolveDir: ROOT, loader: 'ts', contents: `
  export {isPreviewRegion, currentRegionPreview} from './web/region-preview.ts';
  export {regionPorts, loadRegionPorts, loadPorts} from './web/ports.ts';
  export {Location} from './web/app/Masthead.tsx';
  export {Mobile} from './web/app/Mobile.tsx';
  export {WhereToLook} from './web/brief/WhereToLook.tsx';
  export * as state from './web/state.ts';
  export {language, prepareCatalogue, t} from './web/i18n.ts';
  export {render} from 'preact-render-to-string'; export {h} from 'preact';
`}, bundle: true, format: 'esm', platform: 'node', outfile: out, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact', plugins: rendererPlugins});
const s = await import(pathToFileURL(out).href);
await s.prepareCatalogue('es');
const at = id => s.state.syncFromURL(`https://s.test/map?region=${id}&profile=shore`);
const ready = (id, list = directory.ports) => ({region: id, state: 'ready', list});
const render = component => s.render(s.h(component, {}));

test('ready matching preview wins disagreement; foreign/loading/failed/empty/unknown never assert coverage', () => {
  const preview = directory.ports.find(p => p.region === 'monterey-point-sur');
  assert.equal(preview.status, 'preview');
  for (const list of [[preview], [preview, {...preview, status: 'active'}], [{...preview, status: 'active'}, preview]])
    assert.equal(s.isPreviewRegion(preview.region, ready(preview.region, list)), true);
  for (const [id, ports] of [[null, ready(preview.region)], ['', ready('')], [preview.region, null], [preview.region, {...ready(preview.region), state: 'loading'}], [preview.region, {...ready(preview.region), state: 'failed'}], [preview.region, ready('morro-bay')], [preview.region, ready(preview.region, [])], ['morro-bay', ready('morro-bay')], ['unknown', ready('unknown')]])
    assert.equal(s.isPreviewRegion(id, ports), false);
});

test('actual preview/active, en/es: Location and Mobile badge; same reason before Where heading in empty states', async () => {
  for (const id of ['monterey-point-sur', 'morro-bay']) {
    at(id); s.regionPorts.value = null;
    await s.loadRegionPorts(id, () => s.loadPorts(async () => new Response(JSON.stringify(directory))));
    for (const lang of ['en', 'es']) {
      s.language.value = lang;
      const reason = s.t('shell.regionPreview.reason', lang), label = s.t('shell.regionPreview.label', lang);
      const location = render(s.Location), mobile = render(s.Mobile), where = render(s.WhereToLook);
      for (const html of [location, mobile, where]) assert.equal(html.includes(reason), id === 'monterey-point-sur');
      if (id === 'monterey-point-sur') {
        assert.ok(location.includes(`class="app-region-preview-label">${label}`));
        assert.ok(mobile.includes(`class="app-region-preview-label">${label}`));
        assert.ok(where.indexOf(reason) < where.indexOf('<h2'));
      } else assert.doesNotMatch(location + mobile + where, /app-region-preview-label|app-region-preview-reason/);
    }
  }
});

test('late old response and immediate region switches cannot leak preview; duplicate consumers coalesce', async () => {
  at('monterey-point-sur'); s.regionPorts.value = null;
  let release, calls = 0;
  const pending = s.loadRegionPorts('monterey-point-sur', () => { calls++; return new Promise(r => { release = r; }); });
  await s.loadRegionPorts('monterey-point-sur', () => { calls++; return Promise.resolve(directory.ports); });
  assert.equal(calls, 1); assert.equal(s.currentRegionPreview(), false);
  at('morro-bay'); await s.loadRegionPorts('morro-bay', async () => directory.ports);
  release(directory.ports); await pending;
  assert.equal(s.currentRegionPreview(), false);
  at('monterey-point-sur'); assert.equal(s.currentRegionPreview(), false);
  await s.loadRegionPorts('monterey-point-sur', async () => directory.ports);
  assert.equal(s.currentRegionPreview(), true);
  at('unknown'); assert.equal(s.currentRegionPreview(), false);
});

test('failed real directory validation: 503, rejected, malformed, aborted, expired reads never say active or retry on render', async () => {
  // Each fresh bundle is needed because a successful directory is deliberately cached for the page.
  for (const failure of [async () => new Response('', {status: 503}), async () => { throw Error('offline'); }, async () => new Response('{}'), async () => { throw new DOMException('cancelled', 'AbortError'); }, async () => { throw new DOMException('expired', 'TimeoutError'); }]) {
    // loadPorts from the standalone source has an independent, initially empty cache.
    const {loadPorts} = await import(`../web/ports.ts?failure=${Math.random()}`);
    at('monterey-point-sur'); s.regionPorts.value = null; let calls = 0;
    await s.loadRegionPorts('monterey-point-sur', () => loadPorts(() => { calls++; return failure(); }));
    assert.equal(s.regionPorts.value.state, 'failed');
    for (const lang of ['en', 'es']) {
      s.language.value = lang;
      for (const component of [s.Location, s.Mobile, s.WhereToLook]) assert.doesNotMatch(render(component), /app-region-preview-label|app-region-preview-reason|>Active<|>Activo</);
    }
    assert.equal(calls, 1);
  }
});


test('preview adds only the disclosure to populated ranking; active/failed/unknown markup is identical', () => {
  at('monterey-point-sur');
  const pick = {id: 'synthetic', kind: 'spot', name: 'Synthetic reef', distance: '2 nm', depth: '40 ft', fit: 'Screened', reason: 'Synthetic evidence', nm: 2, at: {latitude: 36, longitude: -122}, screen: {status: 'allowed', reasons: []}};
  const ranking = {source: null, label: '', basis: '', empty: 'Synthetic empty state', picks: [pick]};
  for (const lang of ['en', 'es', 'en']) {
    s.language.value = lang;
    s.regionPorts.value = null;
    const baseline = s.render(s.h(s.WhereToLook, {ranking}));
    for (const state of [{...ready('monterey-point-sur'), state: 'failed'}, {...ready('monterey-point-sur'), list: directory.ports.map(p => ({...p, status: 'active'}))}]) {
      s.regionPorts.value = state;
      assert.ok(s.render(s.h(s.WhereToLook, {ranking})) === baseline, 'failed/active preserve every existing row and screening word');
    }
    s.regionPorts.value = ready('monterey-point-sur');
    const preview = s.render(s.h(s.WhereToLook, {ranking}));
    assert.ok(preview.replace(/<p class="app-region-preview-reason">[^<]*<\/p>/, '') === baseline, 'only coverage copy changes, not picks/order/reasons');
    assert.ok(preview.indexOf(s.t('shell.regionPreview.reason', lang)) < preview.indexOf('<h2'));
  }
});
