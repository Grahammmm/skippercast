import './helpers/spanish-ready.mjs';
import assert from 'node:assert/strict';
import test from 'node:test';
import {signal} from '@preact/signals';
import {railNoteCopies, railNotes} from '../web/map/layers.ts';
import {createStations, stationState} from '../web/map/stations.ts';
import {resolveStatusText} from '../web/map/status-copy.ts';
import {configureStore, syncFromURL} from '../web/state.ts';

// Zero selected pins after a successful load used to keep both surfaces on Loading.
const cases = [
  ['empty', {}, 0, 'No stations configured for this selection', 'No hay estaciones configuradas para esta selección'],
  ['missing-location', {tide: '9999999'}, 1,
    '0 station locations · latest readings with individual times; 9999999 · 9999999: location unavailable',
    '0 ubicaciones de estaciones · últimas lecturas con sus horas individuales; 9999999 · 9999999: ubicación no disponible'],
  ['error', null, 0, 'Station configuration unavailable', 'Configuración de estaciones no disponible'],
];

test('F15-15: station rail and legend distinguish pending, empty, missing location and error in both locales', async t => {
  configureStore({v2: true, storage: null});
  const assertNotes = (en, es) => {
    for (const [note, copy] of [[stationState.value.note, stationState.value.copy], [railNotes.value.stations, railNoteCopies.value.stations]]) {
      assert.equal(resolveStatusText(note, copy, 'en'), en);
      assert.equal(resolveStatusText(note, copy, 'es'), es);
    }
  };
  for (const [id, stations, count, en, es] of cases) {
    await t.test(id, async t => {
      syncFromURL(`https://example.test/map?region=${id}&layers=stations`);
      const response = Promise.withResolvers();
      const overlay = createStations({engine: signal(null), feed: () => null, zone: () => 'UTC', fetchFn: () => response.promise});
      t.after(() => overlay.destroy());
      assertNotes('Loading station configuration', 'Cargando la configuración de estaciones');
      response.resolve(stations === null ? {ok: false} : {ok: true, json: async () => ({id, stations})});
      await new Promise(resolve => setImmediate(resolve));
      assertNotes(en, es);
      assert.deepEqual(stationState.value.pins.map(p => p.location), Array(count).fill(null));
    });
  }
});
