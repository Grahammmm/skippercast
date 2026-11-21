import assert from 'node:assert/strict';
import test from 'node:test';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';

const root = new URL('..', import.meta.url).pathname;
const {outputFiles: [bundle]} = await build({
  stdin: {resolveDir: root, loader: 'ts', contents: `
    export {LayerRail} from './web/app/LayerRail.tsx';
    export {Legend} from './web/app/Legend.tsx';
    export * as registry from './web/map/layers.ts';
    export {toggled} from './web/app/rail.ts';
    export * as store from './web/state.ts';
    export {h} from 'preact';
    export {render} from 'preact-render-to-string';
    export {testState} from './web/map/kit-layers/kd490.ts';`},
  bundle: true, format: 'esm', platform: 'node', write: false, jsx: 'automatic', jsxImportSource: 'preact',
  plugins: [{name: 'kit-fixture', setup(b) {
    // A future module's state producer, not a replacement for the Legend or its adapter.
    b.onResolve({filter: /(?:^|\/)kd490\.ts$/}, () => ({path: 'kd490', namespace: 'kit-fixture'}));
    b.onLoad({filter: /.*/, namespace: 'kit-fixture'}, () => ({resolveDir: root, contents: `
      import {signal} from '@preact/signals';
      export const testState = signal({kind: 'no-data'});
      export default {id: 'kd490', get state() {return testState.value;}, autoEnable: false, overlay: () => null};`}));
  }}, ...rendererPlugins],
});
const m = await import(`data:text/javascript;base64,${Buffer.from(bundle.text).toString('base64')}`);
const page = 'https://s.test/map?region=morro-bay&presentation=chart';
const pick = ids => m.store.syncFromURL(`${page}&layers=${ids}`);
const row = id => m.render(m.h(m.Legend)).match(new RegExp(`<li[^>]+data-kit="${id}"[^>]*>.*?</li>`, 's'))?.[0] ?? '';

// A legend-only stub list leaves the actual rail absent, or the next rail toggle silently drops it.
test('all nine kit stubs are selectable, not preselected, and survive unrelated toggles', () => {
  pick('none');
  const rail = m.render(m.h(m.LayerRail));
  const ids = ['kd490', 'ssh', 'upwelling', 'subsurface-temp', 'salinity', 'sea-ice', 'pressure', 'precip-radar', 'visibility-fog'];
  for (const id of ids) {
    const e = m.registry.LAYERS.find(entry => entry.id === id);
    assert.ok(e, `${id} is in the registry`);
    assert.match(rail, new RegExp(`<li[^>]+data-on="false"><button[^>]*aria-pressed="false"[^>]*>[^]*?<span class="ui-rail-label">${e.label}</span>`));
    assert.equal(e.kit.overlay(), null);
    assert.ok(m.toggled([], id, true).includes(id));
  }
  assert.deepEqual(m.toggled(['water-temp', 'sea-ice'], 'swell', true), ['water-temp', 'sea-ice', 'swell']);
  assert.deepEqual(m.toggled(['swell', 'water-temp'], 'sea-ice', true), ['swell', 'water-temp', 'sea-ice']);
});

// The old no-data-or-drawn shortcut mislabels withheld/unknown and never renders dates, stale time or replacement.
test('the rendered legend uses live module metadata and the actual stack result', () => {
  pick('kd490');
  assert.match(row('kd490'), /no data yet/);
  const set = (state, stack = {status: 'drawn', reps: ['fill']}) => {
    m.testState.value = state;
    if (m.registry.chartStack) m.registry.chartStack.value = [{id: 'kd490', opacity: {}, ...stack}];
    return row('kd490');
  };
  const withheld = set({kind: 'withheld', reason: 'past the age limit', dataTime: '2026-11-16T09:10Z'});
  assert.match(withheld, /Withheld: past the age limit.*2026-11-16T09:10Z/);
  assert.doesNotMatch(withheld, /data-state="drawn"/);
  assert.match(set({kind: 'stale', dataTime: '2026-11-17T09:10Z'}), /last 2026-11-17T09:10Z/);
  assert.match(set({kind: 'dated', date: '2026-11-18'}), /Data date: 2026-11-18/);
  assert.match(set({kind: 'ready'}, {status: 'replaced', reps: [], replacedBy: 'waves-swell'}), /Replaced by Waves.*swell/i);
  assert.match(set({kind: 'ready'}), /data-state="drawn"/);
  assert.match(set({kind: 'unrecognized'}), /no data yet/);
  assert.match(set({kind: 'dated', date: ''}), /no data yet/);
});
