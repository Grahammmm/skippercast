import assert from 'node:assert/strict';
import test from 'node:test';
import {signal} from '@preact/signals';
import {WAVE_MODEL} from '../web/map/forecast-grid.ts';
import {createSwell, REFRESH_MS, swellState} from '../web/map/swell.ts';
import {configureStore, syncFromURL} from '../web/state.ts';

const A = 'morro-bay', B = 'cambria-san-simeon';
const PAGE = 'https://swell.test/map';
const START = Date.parse('2026-01-01T00:00:00Z'), HOUR = 3_600_000, MINUTE = 60_000;
const VALID = START + HOUR;
const visit = region => syncFromURL(`${PAGE}?region=${region}&layers=swell&hour=${new Date(VALID).toISOString()}`);
const settle = () => new Promise(resolve => setImmediate(resolve));

function forecast(region, height, issued, retrieved) {
  const points = [['a', 10, 20], ['b', 10, 20.25], ['c', 10.25, 20], ['d', 10.25, 20.25]];
  const sample = {
    utc_offset_seconds: 0,
    hourly_units: {time: 'unixtime', swell_wave_height: 'ft', swell_wave_period: 's', swell_wave_direction: '°'},
    hourly: {time: [VALID / 1000], swell_wave_height: [height], swell_wave_period: [12], swell_wave_direction: [290]},
  };
  return Response.json({region_id: region, retrieved, requested_points: points, models: {[WAVE_MODEL.id]: {
    data: points.map(() => sample), meta: {last_run_initialisation_time: issued / 1000, data_end_time: VALID / 1000},
  }}});
}

for (const outcome of ['resolves', 'rejects']) {
  test(`F15-05: after A → B → A, the first A ${outcome} without replacing the second A`, async t => {
    t.mock.timers.enable({apis: ['setTimeout']});
    configureStore({v2: true, storage: null});
    visit(A);
    let clock = START;
    const advance = ms => { clock += ms; t.mock.timers.tick(ms); };
    const requests = [];
    const fetchFn = url => new Promise((resolve, reject) => {
      requests.push({region: new URL(url).searchParams.get('region'), resolve, reject});
    });
    const swell = createSwell({engine: signal(null), zone: () => 'UTC', page: () => PAGE, now: () => new Date(clock), fetchFn});
    t.after(() => swell.destroy());

    advance(5 * MINUTE);
    visit(B);
    advance(5 * MINUTE);
    visit(A);
    assert.deepEqual(requests.map(r => r.region), [A, B, A]);
    const [first, other, current] = requests;
    const issued = START - HOUR;
    current.resolve(forecast(A, 7, issued, START));
    await settle();
    const good = swellState.value;
    assert.deepEqual(good.drawn?.height, [7, 7], 'A2 draws the valid forecast');
    assert.equal(good.drawn.issuedAt, issued);
    assert.equal(good.drawn.validAt, VALID);
    assert.equal(good.reason, '');

    other.resolve(forecast(B, 9, issued, START));
    await settle();
    assert.deepEqual(swellState.value, good, 'a late B response is ignored');

    if (outcome === 'resolves') first.resolve(forecast(A, 3, START - 2 * HOUR, START - MINUTE));
    else first.reject(new Error('synthetic failed request'));
    await settle();
    assert.deepEqual(swellState.value, good, 'late A1 must not change A2’s forecast, timestamps or status');

    // The private request timestamp is observable through the next refresh deadline.
    advance(REFRESH_MS - 10 * MINUTE + 1_000);
    assert.equal(requests.length, 3, 'no refresh at the first visit’s deadline');
    advance(10 * MINUTE);
    assert.deepEqual(requests.map(r => r.region), [A, B, A, A], 'refresh at the current visit’s deadline');
    const refreshing = swellState.value;
    assert.equal(refreshing.drawn?.key, good.drawn.key);
    requests[3].reject(new Error('synthetic failed refresh'));
    await settle();
    assert.deepEqual(swellState.value, refreshing, 'an active failed refresh keeps A2’s still-fresh forecast');
  });
}
