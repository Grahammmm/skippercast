import assert from 'node:assert/strict';
import test from 'node:test';
import {rampGradient} from '../web/map/preview-layers.ts';
import {readSst} from '../web/map/preview/sst.ts';

// The pinned Chart preview fixture (e2e/v2-preview-layers.spec.ts), with a fixed analysis time.
const preview = {
  data_time: '2026-11-06T12:00:00Z', max_age_hours: 48, source_id: 'fixture',
  colours: ['#2b5d9e', '#43c08a', '#f29a2e', '#e2492f'],
  cells: {type: 'FeatureCollection', features: [{type: 'Feature', properties: {colour: '#43c08a', temperature_f: 58},
    geometry: {type: 'Polygon', coordinates: [[[-121.1, 35.2], [-120.9, 35.2], [-120.9, 35.4], [-121.1, 35.4], [-121.1, 35.2]]]}}]},
  breaks: {type: 'FeatureCollection', features: []},
};

test('the Chart SST fixture keeps its data and ordered legend colours', () => {
  const doc = readSst(structuredClone(preview));
  assert.deepEqual(doc, preview);
  assert.equal(rampGradient(doc.colours), 'linear-gradient(to right, #2b5d9e, #43c08a, #f29a2e, #e2492f)');
});

// Checking only Array.isArray lets valid cells draw even when the file cannot supply a usable legend.
for (const [name, colours] of [
  ['empty', []],
  ['single stop', ['#2b5d9e']],
  ['non-colour string among valid stops', ['#2b5d9e', 'not-a-colour', '#e2492f']],
  ['wrong hex length', ['#2b5d9e', '#12345']],
  ['non-string value', ['#2b5d9e', ['#e2492f']]],
]) {
  test(`SST refuses a palette with ${name} before the preview can draw`, () => {
    assert.throws(() => readSst({...preview, colours}), /not a valid SST preview/);
  });
}
