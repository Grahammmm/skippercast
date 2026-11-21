import test from 'node:test';
import assert from 'node:assert/strict';
import {MAX_OWNER_WATCHES, planWatchRun, WATCH_FEED_LAYERS} from '../server/spot-watch-run.ts';

const publication = 'fixture|2026-11-20T12:00:00Z';
const sst = 'sst-analysis';
const chl = 'chlorophyll-observation';
const early = '2026-11-19T12:00:00Z';
const late = '2026-11-20T12:00:00Z';
const watch = (id, layer = 'water-temp', createdAt = early, enabled = true) => ({id, layer, createdAt, enabled});
const input = {degraded: false, publication, layers: {[sst]: {status: 'ok'}}};

test('C1: pin the feed layer and field for each watch and the exact owner cap', () => {
  assert.deepEqual(WATCH_FEED_LAYERS, {
    'water-temp': {layer: 'sst-analysis', field: 'temperature_c'},
    chlorophyll: {layer: 'chlorophyll-observation', field: 'chlorophyll_mg_m3'},
    'sst-contrast': {layer: 'sst-analysis', field: 'temperature_gradient_c_per_km'},
  });
  assert.deepEqual(MAX_OWNER_WATCHES, 50);
});

test('C2: frozen caller inputs still produce a full plan, catching in-place sorting or annotation', () => {
  const layers = Object.freeze({[sst]: Object.freeze({status: 'ok'})});
  const watches = Object.freeze([Object.freeze(watch('later', 'water-temp', late)), Object.freeze(watch('earlier'))]);
  assert.deepEqual(planWatchRun(Object.freeze({...input, layers, watches})), {
    run: true, publication, evaluate: ['earlier', 'later'], unknown: [], deferred: [],
  });
});

// Cross the gates so reordering them can't be hidden by isolated skip cases.
for (const [marker, label, reasons] of [
  [publication, 'present', ['degraded', 'degraded', null, 'no-watches']],
  [null, 'null', ['degraded', 'degraded', 'no-publication', 'no-publication']],
  ['', 'empty', ['degraded', 'degraded', 'no-publication', 'no-publication']],
]) {
  const cases = [[true, true], [true, false], [false, true], [false, false]];
  for (const [i, [degraded, enabled]] of cases.entries()) {
    test(`C3: ${label} publication, degraded=${degraded}, enabled=${enabled}`, () => {
      const reason = reasons[i];
      assert.deepEqual(planWatchRun({...input, degraded, publication: marker, watches: [watch('a', 'water-temp', early, enabled)]}),
        reason === null ? {run: true, publication, evaluate: ['a'], unknown: [], deferred: []} : {run: false, reason});
    });
  }
}

test('C3: an empty watch list skips a valid publication', () => {
  assert.deepEqual(planWatchRun({...input, watches: []}), {run: false, reason: 'no-watches'});
});

test('C4: 51 enabled watches put the string-order tie loser at the cap into deferred', () => {
  const first = Array.from({length: 49}, (_, i) => `early-${String(i).padStart(2, '0')}`);
  const watches = [watch('a', 'unmapped', late), ...first.map(id => watch(id)).reverse(),
    watch('A', 'water-temp', late), watch('disabled', 'water-temp', early, false)];
  assert.deepEqual(planWatchRun({...input, watches}), {
    run: true, publication, evaluate: [...first, 'A'], unknown: [], deferred: ['a'],
  });
  // Later overflow stays in sorted order, even if it appeared first in the input.
  assert.deepEqual(planWatchRun({...input, watches: [watch('z', 'water-temp', late), ...watches]}), {
    run: true, publication, evaluate: [...first, 'A'], unknown: [], deferred: ['a', 'z'],
  });
});

test('C4: an unknown watch still consumes one of the 50 slots', () => {
  const ids = Array.from({length: 50}, (_, i) => `watch-${String(i).padStart(2, '0')}`);
  assert.deepEqual(planWatchRun({...input, watches: [...ids.map(id => watch(id, 'water-temp', late)), watch('first', 'unmapped')]}), {
    run: true, publication, evaluate: ids.slice(0, 49),
    unknown: [{id: 'first', reason: 'unknown-layer'}], deferred: ['watch-49'],
  });
});

test('C5: unsupported keys, absent feed layers and withheld layers stay distinct and sorted', () => {
  const layers = Object.assign(Object.create({[chl]: {status: 'ok'}}), {[sst]: {status: 'withheld'}});
  const watches = [watch('d', 'toString'), watch('b', 'chlorophyll'), watch('c', 'sst-contrast'), watch('a')];
  assert.deepEqual(planWatchRun({...input, layers, watches}), {
    run: true, publication, evaluate: [],
    unknown: [
      {id: 'a', reason: 'layer-withheld'},
      {id: 'b', reason: 'layer-missing'},
      {id: 'c', reason: 'layer-withheld'},
      {id: 'd', reason: 'unknown-layer'},
    ],
    deferred: [],
  });
});

for (const status of ['ok', 'retained']) {
  test(`C5: ${status} SST admits both SST watches but not an unrecognized chlorophyll status`, () => {
    const layers = {[sst]: {status}, [chl]: {status: 'future-status'}};
    const watches = [watch('contrast', 'sst-contrast', late), watch('chl', 'chlorophyll'), watch('temp')];
    assert.deepEqual(planWatchRun({...input, layers, watches}), {
      run: true, publication, evaluate: ['temp', 'contrast'],
      unknown: [{id: 'chl', reason: 'layer-withheld'}], deferred: [],
    });
  });
}

test('C5: chlorophyll reads its own feed even when neither SST watch can run', () => {
  const layers = {[chl]: {status: 'ok'}};
  const watches = [watch('temp'), watch('chl', 'chlorophyll'), watch('contrast', 'sst-contrast')];
  assert.deepEqual(planWatchRun({...input, layers, watches}), {
    run: true, publication, evaluate: ['chl'],
    unknown: [{id: 'contrast', reason: 'layer-missing'}, {id: 'temp', reason: 'layer-missing'}], deferred: [],
  });
});
