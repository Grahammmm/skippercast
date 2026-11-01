// SCJ-7: a 404 region.json says the region does not exist and links the port list; other failures keep Retry.
import assert from 'node:assert/strict';
import test from 'node:test';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const ROOT = new URL('..', import.meta.url).pathname, ORIGIN = 'https://s.test/map';
const NOT_EXIST = 'No ranked places: this region does not exist.';

let shell;
async function load() {
  if (shell) return shell;
  const out = join(await mkdtemp(join(tmpdir(), 'scj7-')), 'shell.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {createRegionReader, loadRegion, regionLoad, REGION_MISSING} from './web/app/App.tsx';
      export {Location} from './web/app/Masthead.tsx';
      export {currentRanking, WhereToLook} from './web/brief/WhereToLook.tsx';
      export {ranking} from './web/ranking.ts';
      export {CHECKING} from './web/map/habitat.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  shell = await import(pathToFileURL(out).href);
  return shell;
}
const memory = () => { const m = new Map(); return {getItem: k => m.get(k) ?? null, setItem: (k, v) => m.set(k, String(v))}; };
const status = code => async () => new Response('nope', {status: code});
const at = async id => {
  const s = await load(); s.state.configureStore({v2: true, storage: memory()}); s.state.syncFromURL(`${ORIGIN}?region=${id}`); return s;
};

test('the reader answers REGION_MISSING only for a 404; a 500 or a body with no name is null', async () => {
  const {createRegionReader, REGION_MISSING} = await load();
  assert.equal(await createRegionReader(status(404))('nowhere'), REGION_MISSING);
  assert.equal(await createRegionReader(status(500))('broken'), null);
  assert.equal(await createRegionReader(status(410))('gone'), null, 'only a 404 means the region does not exist');
  assert.equal(await createRegionReader(async () => new Response(JSON.stringify({map: {center: [1, 2]}})))('nameless'), null);
});

test('loadRegion: a 404 is missing; a 500 and a malformed body stay error', async () => {
  const {loadRegion, regionLoad} = await at('nowhere');
  assert.equal(await loadRegion('nowhere', status(404)), null);
  assert.deepEqual(regionLoad.peek(), {id: 'nowhere', state: 'missing'});
  await at('broken');
  assert.equal(await loadRegion('broken', status(500)), null);
  assert.deepEqual(regionLoad.peek(), {id: 'broken', state: 'error'});
  await at('garbled');
  assert.equal(await loadRegion('garbled', async () => new Response('{}')), null);
  assert.deepEqual(regionLoad.peek(), {id: 'garbled', state: 'error'});
});

test('a 404 answered after the address moved on publishes nothing for the new region', async () => {
  const {loadRegion, regionLoad, state} = await at('stale-a');
  const gate = Promise.withResolvers(), pending = loadRegion('stale-a', async () => gate.promise);
  await new Promise(resolve => setImmediate(resolve));
  state.syncFromURL(`${ORIGIN}?region=stale-b`);
  gate.resolve(new Response('nope', {status: 404}));
  assert.equal(await pending, null);
  assert.equal(regionLoad.peek(), null, 'the late 404 for stale-a is dropped');
});

test('Location for a missing region: the raw id, the sentence and a port-list link, with no dash or Retry', async () => {
  const {loadRegion, Location, render, h} = await at('nowhere');
  await loadRegion('nowhere', status(404));
  const html = render(h(Location, {}));
  assert.match(html, /data-region="nowhere">&quot;nowhere&quot;<\/span>/);
  assert.match(html, /<span role="status">There is no region called &quot;nowhere&quot;. <a href="\/">Choose a port<\/a><\/span>/);
  assert.doesNotMatch(html, /Retry region details| —/, 'no Retry and no dash for a region that does not exist');
  await (await at('broken')).loadRegion('broken', status(500));
  const error = render(h(Location, {}));
  assert.match(error, /Retry region details/, 'a server error keeps Retry');
  assert.doesNotMatch(error, /no region called|Choose a port/, 'a server error never says the region does not exist');
});

test('ranking says the region does not exist only when told so; otherwise the loading line', async () => {
  const {ranking, CHECKING} = await load();
  const base = {region: 'nowhere', profile: 'boat', target: 'lingcod', coast: 'lingcod', data: null, screen: CHECKING, terrain: {state: 'loading'}, now: Date.now()};
  const m = ranking({...base, missing: true});
  assert.equal(`${m.empty} ${m.picks.length}`, `${NOT_EXIST} 0`);
  assert.equal(ranking({...base, missing: false}).empty, 'Ranked places load with the map.');
  assert.equal(ranking(base).empty, 'Ranked places load with the map.');
});

test('Shore: a missing region says it does not exist, ahead of the Shore runs line; otherwise the Shore runs line stays', async () => {
  const {ranking, CHECKING} = await load();
  const base = {region: 'nowhere', profile: 'shore', target: 'surfperch', coast: 'surfperch', data: null, screen: CHECKING, terrain: {state: 'loading'}, now: Date.now()};
  const m = ranking({...base, missing: true});
  assert.equal(`${m.empty} ${m.picks.length}`, `${NOT_EXIST} 0`);
  assert.equal(ranking(base).empty, 'Shore runs and their review status show on the Chart.');
});

test('Where to look for Shore on a 404 region shows the not-exist sentence, not the Shore runs line', async () => {
  const {loadRegion, currentRanking, WhereToLook, state, render, h} = await at('nowhere');
  state.syncFromURL(`${ORIGIN}?region=nowhere&profile=shore`);
  assert.equal(state.profile.value, 'shore');
  await loadRegion('nowhere', status(404));
  assert.equal(currentRanking().empty, NOT_EXIST);
  const html = render(h(WhereToLook, {}));
  assert.match(html, /<p class="app-empty">No ranked places: this region does not exist\.<\/p>/);
  assert.doesNotMatch(html, /Shore runs and their review status/);
});

test('Where to look reads missing only for the current region, never from a stale entry for another id', async () => {
  const {loadRegion, regionLoad, currentRanking, state, Location, render, h} = await at('nowhere');
  await loadRegion('nowhere', status(404));
  assert.equal(currentRanking().empty, NOT_EXIST);
  state.syncFromURL(`${ORIGIN}?region=morro-bay`);
  regionLoad.value = {id: 'nowhere', state: 'missing'};
  assert.notEqual(currentRanking().empty, NOT_EXIST, 'a stale missing entry for another region does not leak');
  assert.doesNotMatch(render(h(Location, {})), /no region called|Choose a port/, 'nor into the masthead');
});
