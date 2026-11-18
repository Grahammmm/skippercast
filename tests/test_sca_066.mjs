import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {setImmediate as flush} from 'node:timers/promises';
import test from 'node:test';
import {PMTiles} from 'pmtiles';
import {createSeafloor, ROUGH_ZOOM, seafloorRough, seafloorState} from '../web/map/seafloor.ts';
import {camera} from '../web/map/stage.ts';
import {configureStore, syncFromURL} from '../web/state.ts';

const bytes = readFileSync(new URL('./fixtures/seafloor/chart.pmtiles', import.meta.url));
const archive = new PMTiles({getKey: () => 'fixture', getBytes: async (offset, length) => ({
  data: bytes.buffer.slice(bytes.byteOffset + offset, bytes.byteOffset + offset + length),
})});
const ledger = JSON.stringify({region: 'morro-bay', reaches: [
  {id: 'morro-bay-fx1', region: 'morro-bay', status: 'habitat-screened'},
]});
const valid = {latitude: 35.353, longitude: -120.948, zoom: 13};
const markId = 'fixture-candidate-a';
const cellPoint = {lon: -120.975, lat: 35.35};

for (const [name, unsupported, note] of [
  ['below minimum zoom', {...valid, zoom: 9}, /^Zoom in to see seafloor candidates/],
  ['outside coverage', {...valid, longitude: -123}, /^No published seafloor survey in this view/],
  ['over tile budget', {...valid, zoom: 10.5}, /^Zoom in to load seafloor candidates/],
]) {
  test(`SCA-066: held rough and detail reads cannot restore draws (${name})`, {timeout: 5000}, async t => {
    const west = await archive.getZxy(12, 671, 1617);
    const east = await archive.getZxy(12, 672, 1617);
    assert.ok(west && east);
    // Reuse the synthetic west tile's local habitat geometry as a rough outline
    // in its z10 parent. The rough renderer does not use coverage cells.
    const rough = Promise.withResolvers(), detail = Promise.withResolvers();
    const roughStarted = Promise.withResolvers(), detailStarted = Promise.withResolvers();
    configureStore({v2: true, storage: null});
    const page = 'https://fixture.test/map?region=morro-bay&profile=boat&layers=seafloor';
    syncFromURL(page);
    camera.value = valid;
    const writes = [];
    const layer = createSeafloor({
      engine: {setVisible() {}, setData(_source, data) { writes.push(data.features); }},
      open: () => ({
        getHeader: async () => ({minLon: -122, minLat: 34.5, maxLon: -120, maxLat: 36, maxZoom: 12}),
        async getZxy(z, x, y) {
          if (z === ROUGH_ZOOM) {
            roughStarted.resolve();
            await rough.promise;
            return x === 167 && y === 404 ? west : undefined;
          }
          detailStarted.resolve();
          await detail.promise;
          return y === 1617 ? (x === 671 ? west : x === 672 ? east : undefined) : undefined;
        },
      }),
      size: () => ({width: 1000, height: 700}), page: () => page, now: () => Date.UTC(2030, 0, 1),
      setTimer: () => 1, clearTimer() {},
      fetchFn: async url => {
        if (url === '/feeds/tiles/seafloor/manifest-morro-bay.json') return Response.json({
          schema_version: 1, region: 'morro-bay', status: 'ready', archive_sha256: 'a'.repeat(64),
          expires_at: '2099-01-01T00:00:00Z', ledger_sha256: createHash('sha256').update(ledger).digest('hex'),
          source_attribution: ['Fixture Survey Lab'], source_use_notice: 'Synthetic fixture only.',
          rough_first: {maxzoom: 11, detail_minzoom: 12},
        });
        assert.equal(url, '/feeds/tiles/seafloor/regions/morro-bay/ledger.json');
        return new Response(ledger);
      },
    });
    t.after(() => { layer.destroy(); rough.resolve(); detail.resolve(); });

    await roughStarted.promise;
    camera.value = unsupported;
    const clearNote = seafloorState.peek().note;
    assert.match(clearNote, note, 'the newer camera decision took the intended clear branch');
    const snapshot = () => ({note: seafloorState.peek().note, drawn: seafloorState.peek().drawn,
      rough: seafloorRough.peek(), mark: layer.mark(markId)?.id ?? null, cell: layer.cellAt(cellPoint)?.id ?? null,
      nonemptyWrites: writes.filter(features => features.length).length});
    const empty = {note: clearNote, drawn: 0, rough: false, mark: null, cell: null, nonemptyWrites: 0};
    assert.deepEqual(snapshot(), empty, 'the unsupported view starts empty');

    rough.resolve();
    await detailStarted.promise;
    await flush(); // All unblocked reads and decode continuations are in memory.
    const afterRough = snapshot();
    detail.resolve();
    await flush();
    assert.deepEqual({afterRough, afterDetail: snapshot()}, {afterRough: empty, afterDetail: empty});

    camera.value = {...valid};
    await flush();
    assert.ok(writes.at(-1)?.some(f => f.properties.id === markId));
    assert.match(seafloorState.peek().note, /2 candidates in view/);
    assert.equal(seafloorRough.peek(), false);
    assert.equal(layer.mark(markId)?.id, `seafloor:${markId}`);
    assert.equal(layer.cellAt(cellPoint)?.id, 'seafloor:cell:3310:fx:1');
  });
}
