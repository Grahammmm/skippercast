import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {setImmediate as turn} from 'node:timers/promises';
import test from 'node:test';
import {habitatManifestURL, regionalSST, SST_LAYER_ID} from '../web/map/habitat-feed.ts';

const page = 'https://ocean.test/map', region = 'fixture', now = new Date('2026-01-05T00:00:00Z');
const manifestURL = habitatManifestURL(region, page), time = now.getTime() / 1000;
const fields = ['latitude', 'longitude', 'temperature_c', 'analysis_error_c'];
const resolution_degrees = [0.25, 0.25], bounds = [-16, -1, 0, 1];
const tiles = Array.from({length: 16}, (_, i) => {
  const bytes = Buffer.from(JSON.stringify({schema_version: 1, region_id: region, layer_id: SST_LAYER_ID,
    fields, resolution_degrees, bounds, frames: [{time, cells: [[0, -i - 0.25, i, 0.5], [0.25, -i - 0.25, i + 1, 0.5]]}]}));
  const sha256 = createHash('sha256').update(bytes).digest('hex');
  return {bytes, record: {bounds, bytes: bytes.length, sha256, path: `habitat-tiles/fixture-${i}-${sha256.slice(0, 16)}.json`}};
});
const manifest = {schema_version: 1, region_id: region,
  layers: {[SST_LAYER_ID]: {id: SST_LAYER_ID, kind: 'analysis', status: 'ok', max_age_hours: 6,
    fields, resolution_degrees, frames: [{time}], tiles: tiles.map(t => t.record)}},
  sources: {[SST_LAYER_ID]: {name: 'Synthetic analysis', data_retrieved_at: now.toISOString()}}};

function fixture(mode) {
  const hold = Promise.withResolvers();
  const stats = {started: [], completed: [], cancelled: [], active: 0, peak: 0, badPulls: 0};
  const fetchFn = async (url, {signal}) => {
    if (url === manifestURL) return Response.json(manifest);
    const i = tiles.findIndex(t => new URL(t.record.path, manifestURL).href === url);
    assert.notEqual(i, -1);
    stats.started.push(i);
    const bytes = tiles[i].bytes, middle = Math.floor(bytes.length / 2);
    const chunks = [bytes.subarray(0, middle), bytes.subarray(middle)];
    if (i === 0 && mode === 'long') chunks.push(Uint8Array.of(0));
    if (i === 0 && mode === 'short') chunks.pop();
    let reading = false;
    const finish = () => { if (reading) stats.active--; reading = false; };
    return new Response(new ReadableStream({
      async pull(controller) {
        if (!reading) stats.peak = Math.max(stats.peak, ++stats.active);
        reading = true;
        if (mode === 'cancel' || (i === 0 && mode === 'valid')) await hold.promise;
        signal.throwIfAborted();
        if (i === 0 && mode === 'long') stats.badPulls++;
        if (chunks.length) controller.enqueue(chunks.shift());
        else {
          finish();
          stats.completed.push(i);
          controller.close();
          if (i === 3 && mode === 'valid') hold.resolve();
        }
      },
      cancel() { finish(); stats.cancelled.push(i); },
    }, {highWaterMark: 0}));
  };
  return {stats, release: hold.resolve, read: signal => regionalSST(region, {fetchFn, page, now, signal})};
}

test('16 live tiles peak at four body reads and keep manifest sample order despite out-of-order completion', {timeout: 2000}, async () => {
  const {read, stats} = fixture('valid');
  const result = await read();
  assert.equal(result.state, 'ready');
  assert.equal(stats.peak, 4);
  assert.equal(stats.completed.length, 16);
  assert.ok(stats.completed.indexOf(3) < stats.completed.indexOf(0));
  assert.deepEqual(result.sst.points, tiles.flatMap((_, i) => [0, 0.25].map((lat, j) => ({
    lat, lon: -i - 0.25, tempF: (i + j) * 1.8 + 32, errorF: 0.9,
  }))));
});

for (const mode of ['long', 'short']) {
  test(`one ${mode} tile refuses the whole layer without returning partial samples`, async () => {
    const {read, stats} = fixture(mode);
    assert.deepEqual(await read(), {state: 'error'});
    if (mode === 'long') {
      assert.ok(stats.cancelled.includes(0), 'the overrun stream was cancelled');
      assert.equal(stats.badPulls, 3, 'no pull for EOF or further bytes after the first excess chunk');
    }
  });
}

test('cancelling with all four reads pending stops them and never starts queued fetches', {timeout: 2000}, async () => {
  const {read, stats, release} = fixture('cancel');
  const controller = new AbortController();
  const pending = read(controller.signal);
  const rejected = assert.rejects(pending, {name: 'AbortError'});
  await turn();
  const atAbort = stats.active;
  controller.abort();
  release();
  await rejected;
  assert.equal(atAbort, 4);
  assert.deepEqual(stats.started, [0, 1, 2, 3]);
  assert.equal(stats.active, 0);
});
