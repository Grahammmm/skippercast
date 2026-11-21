import test from 'node:test';
import assert from 'node:assert/strict';
import {ANALYSIS_LAYERS} from '../server/analysis-alerts.ts';
import {
  DATA_ALERT_LAYERS, readDataAlerts, toggleDataAlert, dataAlertsChanged, dataAlertsBody,
} from '../web/data-alerts-choice.ts';

const sst = 'sst-analysis';
const chl = 'chlorophyll-observation';
const unknown = 'future-layer';

test('C1: web layer IDs and order match the server allowlist', () => {
  assert.deepEqual(DATA_ALERT_LAYERS, ANALYSIS_LAYERS);
});

test('C1: reads full, partial and empty selections without retaining unknown or duplicate IDs', () => {
  for (const [layers, expected] of [
    [[sst, chl], [sst, chl]],
    [[sst, unknown, sst], [sst]],
    [[chl], [chl]],
    [[unknown], []],
    [[], []],
  ]) {
    assert.deepEqual(readDataAlerts({layers: Object.freeze(layers)}), new Set(expected));
  }
  assert.deepEqual(readDataAlerts(Object.assign(Object.create(null), {layers: [chl]})), new Set([chl]));
});

test('C1: rejects non-plain responses and missing or non-array own layers', () => {
  const arrayResponse = Object.assign([], {layers: [sst]});
  for (const [label, input] of [
    ['null', null],
    ['primitive', sst],
    ['array with layers', arrayResponse],
    ['custom prototype with own layers', Object.assign(Object.create({}), {layers: [sst]})],
    ['inherited layers', Object.create({layers: [sst]})],
    ['missing layers', {}],
    ['scalar layers', {layers: sst}],
  ]) {
    assert.deepEqual(readDataAlerts(input), null, label);
  }
});

test('C1: rejects malformed entries rather than returning an earlier valid layer', () => {
  assert.deepEqual(readDataAlerts({layers: [sst, 7]}), null);
  assert.deepEqual(readDataAlerts({layers: Array(1)}), null);
});

test('C1: a throwing layers or array-entry getter returns null', () => {
  const unreadable = () => { throw new Error('unreadable'); };
  const layers = Object.defineProperty([sst, chl], '1', {get: unreadable});
  assert.deepEqual(readDataAlerts({get layers() { return unreadable(); }}), null);
  assert.deepEqual(readDataAlerts({layers}), null);
});

test('C2: flips only the requested known layer and drops stale IDs without editing the input', () => {
  for (const [ids, layer, expected] of [
    [[chl, unknown], sst, [sst, chl]],
    [[sst, chl, unknown], sst, [chl]],
    [[sst, unknown], chl, [sst, chl]],
    [[sst, chl, unknown], chl, [sst]],
    [[chl, unknown], 'other-layer', [chl]],
  ]) {
    const on = new Set(ids);
    assert.deepEqual(toggleDataAlert(on, layer), new Set(expected), layer);
    assert.deepEqual(on, new Set(ids), layer);
  }
});

test('C2: toggling an unknown ID returns an independent copy even when no filtering is needed', () => {
  const on = new Set([sst]);
  const next = toggleDataAlert(on, unknown);
  assert.deepEqual(next, new Set([sst]));
  next.add(chl);
  assert.deepEqual(on, new Set([sst]));
});

test('C3: only known membership changes, not ID order or unknown IDs, mark the selection dirty', () => {
  for (const [before, after, expected] of [
    [[sst, chl, unknown], [chl, 'other-layer', sst], false],
    [[unknown], [sst, unknown], true],
    [[sst, chl, unknown], [sst, unknown], true],
    [[sst, unknown], [chl, unknown], true],
  ]) {
    const saved = new Set(before);
    const current = new Set(after);
    assert.deepEqual(dataAlertsChanged(saved, current), expected);
    assert.deepEqual(saved, new Set(before));
    assert.deepEqual(current, new Set(after));
  }
});

test('C3: the PUT body uses canonical layer order and leaves the current selection untouched', () => {
  for (const [ids, layers] of [
    [[chl, unknown, sst], [sst, chl]],
    [[unknown, chl], [chl]],
    [[unknown], []],
  ]) {
    const current = new Set(ids);
    assert.deepEqual(dataAlertsBody(current), {layers});
    assert.deepEqual([...current], ids);
  }
});
