import assert from 'node:assert/strict';
import test from 'node:test';
import {createStage, shownPresentation, terrainBlocked, terrainCoverage, terrainFailed, UNAVAILABLE} from '../web/map/stage.ts';
import {configureStore, setParams, syncFromURL} from '../web/state.ts';

// The same signed-out URL/store and fake renderer boundary as test_map_stage.mjs.
const FIRST = 'morro-bay', SECOND = 'cambria-san-simeon', HABITAT = 'reef:synthetic';
const tick = () => new Promise(resolve => setTimeout(resolve, 0));
const coverage = key => ({key, sources: []});

function fakeTerrain({pending = false} = {}) {
  let settle;
  const ready = pending ? new Promise(resolve => { settle = resolve; }) : Promise.resolve(true);
  const fake = {mounts: 0, destroyed: 0, settle};
  fake.mount = (_host, options) => {
    fake.mounts++;
    fake.options = options;
    return {
      load: () => ready,
      destroy: () => { fake.destroyed++; },
      setRelief() {}, setHabitatVisible() {}, setLocation() {}, setPerspective() {}, setVisible() {}, selectHabitat() {},
    };
  };
  return fake;
}

function stage(t, module, c2 = {enabled: false, releases: {}}) {
  const href = `https://s.test/map?region=${FIRST}&presentation=3d&habitat=${HABITAT}`;
  t.mock.method(console, 'error', () => {});
  globalThis.location = {href};
  globalThis.history = {
    state: null,
    pushState(_state, _title, url) { location.href = url; },
    replaceState(_state, _title, url) { location.href = url; },
  };
  globalThis.dispatchEvent = () => true;
  configureStore({v2: true, storage: null});
  syncFromURL(href);
  terrainFailed.value = false;
  const mounted = createStage({
    host: {dataset: {}, shadowRoot: {replaceChildren() {}}},
    doc: {hidden: false, addEventListener() {}, removeEventListener() {}},
    load: async () => module,
    now: () => new Date('2026-10-05T20:17:00Z'),
    c2,
  });
  t.after(() => mounted.destroy());
  return mounted;
}

const param = name => new URL(location.href).searchParams.get(name);

test('the replacement terrain publishes only its own source key after a region switch', async t => {
  const first = fakeTerrain(), second = fakeTerrain();
  const release = `/data/coast-c2/${SECOND}/release-manifest.json`;
  let answerRelease;
  const requested = [];
  stage(t, {
    mountCoast: (...args) => (first.mounts ? second : first).mount(...args),
    loadC2: async () => ({mountRelease: (_host, url) => {
      requested.push(url);
      return new Promise(resolve => { answerRelease = resolve; });
    }}),
  }, {enabled: true, releases: {[SECOND]: release}});
  await tick();
  assert.equal(first.mounts, 1);
  assert.equal(terrainCoverage.value, null, 'no notification yet');
  const oldNotify = first.options.onSourceCoverage;
  oldNotify(coverage('first key'));
  assert.equal(terrainCoverage.value?.key, 'first key');
  oldNotify(coverage('updated first key'));
  assert.equal(terrainCoverage.value?.key, 'updated first key', 'same-region updates still work');

  setParams({region: SECOND});
  assert.equal(terrainCoverage.value, null, 'the old key clears immediately, before the replacement answers');
  await tick();
  assert.equal(first.destroyed, 1);
  assert.deepEqual(requested, [release], 'the listed C2 release still gets first refusal');
  assert.equal(second.mounts, 0);
  oldNotify(coverage('late first key'));
  assert.equal(terrainCoverage.value, null, 'the displaced handle cannot repopulate an empty key');

  answerRelease({refused: 'synthetic refusal'});
  await tick();
  assert.equal(second.mounts, 1, 'C2 refusal still mounts the legacy fallback');
  assert.equal(second.options.initial.visible, true);
  assert.equal(second.options.initial.habitat, HABITAT);
  assert.equal(param('habitat'), HABITAT);
  assert.equal(shownPresentation.value, '3d');
  assert.equal(terrainBlocked.value, null);
  assert.equal(terrainCoverage.value, null, 'the replacement key waits for its own notification');
  second.options.onSourceCoverage(coverage('second key'));
  oldNotify(coverage('even later first key'));
  assert.equal(terrainCoverage.value?.key, 'second key', 'the displaced handle cannot overwrite the replacement key');
});

test('an unlisted region clears the key without remounting legacy terrain', async t => {
  const fake = fakeTerrain();
  stage(t, {mountCoast: fake.mount});
  await tick();
  fake.options.onSourceCoverage(coverage('first key'));
  setParams({region: SECOND});
  assert.equal(terrainCoverage.value, null);
  fake.options.onSourceCoverage(coverage('wrong-region key'));
  assert.equal(terrainCoverage.value, null, 'a reused handle cannot claim coverage for another region');
  assert.equal(fake.mounts, 1);
  assert.equal(fake.destroyed, 0);
  assert.equal(shownPresentation.value, '3d');
  assert.equal(param('habitat'), HABITAT);
});

test('returning to Chart after a failed load clears coverage and ignores the failed handle', async t => {
  const fake = fakeTerrain({pending: true});
  stage(t, {mountCoast: fake.mount});
  await tick();
  const notify = fake.options.onSourceCoverage;
  notify(coverage('key before failure'));
  assert.equal(terrainCoverage.value?.key, 'key before failure');
  fake.settle(false);
  await tick();
  assert.equal(fake.destroyed, 1);
  assert.equal(shownPresentation.value, 'chart');
  assert.equal(terrainBlocked.value, UNAVAILABLE);
  assert.equal(param('presentation'), '3d', 'the link keeps the request');
  assert.equal(param('habitat'), HABITAT);
  assert.equal(terrainCoverage.value, null, 'failure clears the key even though the region did not change');
  notify(coverage('key after failure'));
  assert.equal(terrainCoverage.value, null);
});

test('destroying a healthy stage clears coverage and ignores the destroyed handle', async t => {
  const fake = fakeTerrain();
  const mounted = stage(t, {mountCoast: fake.mount});
  await tick();
  const notify = fake.options.onSourceCoverage;
  notify(coverage('key before destroy'));
  assert.equal(terrainCoverage.value?.key, 'key before destroy');
  mounted.destroy();
  assert.equal(fake.destroyed, 1);
  assert.equal(terrainCoverage.value, null);
  notify(coverage('key after destroy'));
  assert.equal(terrainCoverage.value, null);
});
