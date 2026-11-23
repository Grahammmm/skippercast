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
  export {loadRegion} from './web/app/App.tsx';
  export {regionInfo} from './web/app/region-info.ts';
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

// SCB2222-14: the loaded package's own status decides the badge; the port is only a fallback.
// Contract: a deep-linked preview region that no port lists still says Preview (bug: it rendered unbadged).
const pkg = id => JSON.parse(readFileSync(new URL(`../dist/regions/${id}/region.json`, import.meta.url)));
const served = body => async () => new Response(JSON.stringify(body));
const noPort = 'big-sur-coast', active = 'morro-bay', listed = 'monterey-point-sur';
const surfaces = lang => { s.language.value = lang; return [s.Location, s.Mobile, s.WhereToLook].map(render); };
/** Real route: URL, ports directory for the id, then the real loadRegion reader and publication. */
const open = async (id, body, list = directory.ports) => {
  at(id); s.regionPorts.value = null;
  await s.loadRegionPorts(id, async () => list);
  return s.loadRegion(id, served(body));
};
const badged = async (id, body, list) => {
  const info = await open(id, body, list);
  assert.equal(info?.id, id, 'the package loaded');
  const out = [];
  for (const lang of ['en', 'es']) {
    const reason = s.t('shell.regionPreview.reason', lang), label = s.t('shell.regionPreview.label', lang);
    const [location, mobile, where] = surfaces(lang);
    const says = [location.includes(`class="app-region-preview-label">${label}`), mobile.includes(`class="app-region-preview-label">${label}`),
      location.includes(reason), mobile.includes(reason), where.includes(reason)];
    out.push(says.every(Boolean) ? true : says.some(Boolean) ? 'partial' : false);
  }
  return out.every(v => v === true) ? true : out.every(v => v === false) ? false : 'partial';
};

test('a portless preview package says Preview on every surface, en/es, whatever the directory says', async () => {
  assert.ok(!directory.ports.some(p => p.region === noPort), 'fixture: no port lists this preview region');
  assert.equal(pkg(noPort).status, 'preview');
  assert.equal(await badged(noPort, pkg(noPort)), true);
  // A failed or empty directory cannot take the badge away from a package that says preview.
  assert.equal(await badged(noPort, pkg(noPort), []), true);
  at(noPort); s.regionPorts.value = {region: noPort, state: 'failed', list: []};
  assert.equal(s.currentRegionPreview(), true);
});

test('a loaded active package is unbadged, even when the directory lists a preview port for it', async () => {
  const conflicting = directory.ports.map(p => p.region === active ? {...p, status: 'preview'} : p);
  assert.ok(conflicting.some(p => p.region === active && p.status === 'preview'), 'fixture: a conflicting preview port');
  assert.equal(pkg(active).status, 'active');
  assert.equal(await badged(active, pkg(active), conflicting), false);
  assert.equal(await badged(active, pkg(active)), false);
});

test('missing or unrecognized package status is ignored: only the matching ready port decides', async () => {
  for (const status of [undefined, 'bogus', 42, null, '', 'Preview']) {
    const noStatus = {...pkg(noPort), status}, listedNoStatus = {...pkg(listed), status};
    if (status === undefined) { delete noStatus.status; delete listedNoStatus.status; }
    assert.equal(await badged(noPort, noStatus), false, `portless, status ${JSON.stringify(status)}: no badge`);
    assert.equal(await badged(listed, listedNoStatus), true, `listed, status ${JSON.stringify(status)}: port fallback`);
    assert.equal(s.regionInfo.value.status, undefined, 'an unrecognized status is not kept');
  }
});

test('a previous region\'s package never badges a new id, delayed or not', async () => {
  assert.equal(await badged(noPort, pkg(noPort)), true);
  at(active);                                   // switch before anything for the new id has loaded
  assert.equal(s.currentRegionPreview(), false);
  assert.doesNotMatch(surfaces('en').join(''), /app-region-preview-label|app-region-preview-reason/);
  // The old region's read still pending when the link changes to the active region.
  at(noPort); s.regionPorts.value = null;
  const gate = Promise.withResolvers(), pending = s.loadRegion(noPort, () => gate.promise);
  at(active); await s.loadRegionPorts(active, async () => directory.ports);
  gate.resolve(new Response(JSON.stringify(pkg(noPort)))); assert.equal(await pending, null);
  assert.equal(s.regionInfo.value, null);
  assert.equal(s.currentRegionPreview(), false);
  assert.doesNotMatch(surfaces('es').join(''), /app-region-preview-label|app-region-preview-reason/);
  // The info signal holding a foreign region's package is not read for this id.
  s.regionInfo.value = {id: noPort, name: 'Foreign', center: [36, -121], timezone: 'America/Los_Angeles', status: 'preview'};
  at(listed); s.regionPorts.value = {region: listed, state: 'loading', list: []};
  assert.equal(s.isPreviewRegion(listed, s.regionPorts.value, s.regionInfo.value), false);
});
