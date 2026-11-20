import assert from 'node:assert/strict';
import test from 'node:test';
import {PREVIEW_LOADERS} from '../web/map/preview-layers.ts';

const sample = '2026-01-01T00:00:00Z';
const sampleMs = Date.parse(sample);
const minute = 60_000;
const collection = {type: 'FeatureCollection', features: []};
const fixtures = {
  sst: {data_time: sample, colours: ['#111', '#eee'], cells: collection, breaks: collection},
  chlorophyll: {sample_at: sample, bounds: [-1, -1, 1, 1], style: {legend: [[1, '#111'], [2, '#eee']]}},
};

function preview(id, limitJson, now) {
  const draws = [], states = [];
  const doc = JSON.stringify(fixtures[id]);
  const ctx = {
    engine: {setOverlay: (_id, overlay) => draws.push(overlay === null ? 'remove' : 'draw')},
    // Use actual JSON decoding, including overflow to Infinity, without a real transport.
    fetchFn: async () => new Response(`{"max_age_hours":${limitJson},${doc.slice(1)}`),
    now,
    palette: () => ({text: '#eee', bgDeep: '#111'}),
    url: path => `https://example.invalid${path}`,
    signal: new AbortController().signal,
    report: status => states.push(status.state),
  };
  return {ctx, draws, states};
}

for (const id of Object.keys(fixtures)) {
  for (const [label, limit, ageMinutes] of [
    ['overflowed number', '1e400', 6000],
    ['numeric string', '"48"', 1],
    ['boolean', 'true', 1],
    ['array', '[48]', 1],
    ['null', 'null', 1],
    ['zero', '0', 1],
    ['negative number', '-1', 1],
  ]) {
    test(`${id}: withholds previews with an invalid freshness limit (${label})`, async t => {
      t.mock.timers.enable({apis: ['setInterval']});
      const {ctx, draws, states} = preview(id, limit, () => new Date(sampleMs + ageMinutes * minute));
      const attach = await PREVIEW_LOADERS[id]();
      await assert.rejects(attach(ctx), /not a valid SST preview|chlorophyll file is not valid/);
      assert.deepEqual(draws, []);
      assert.deepEqual(states, []);
    });
  }

  test(`${id}: a finite positive limit preserves clock slack and expires while open`, async t => {
    t.mock.timers.enable({apis: ['setInterval']});
    let nowMs = sampleMs - 5 * minute;
    const {ctx, draws, states} = preview(id, '1.5', () => new Date(nowMs));
    const attach = await PREVIEW_LOADERS[id]();
    const handle = await attach(ctx);
    try {
      assert.deepEqual(draws, ['draw']);
      assert.deepEqual(states, ['ready']);
      nowMs = sampleMs + 90 * minute;
      t.mock.timers.tick(minute);
      assert.deepEqual(draws, ['draw'], 'still usable at the limit');
      nowMs += minute;
      t.mock.timers.tick(minute);
      assert.deepEqual(draws, ['draw', 'remove']);
      assert.deepEqual(states, ['ready', 'stale']);
    } finally {
      handle?.destroy();
    }
  });
}
