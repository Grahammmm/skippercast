import assert from 'node:assert/strict';
import test from 'node:test';
import {chartMounted, mapFirstIdle, mapMayLoad, markChartMounted} from '../web/map-ready.ts';
import {chartFailed, createChart} from '../web/map/chart.ts';
import {readPalette} from '../web/map/palette.ts';
import {camera, shownPresentation} from '../web/map/stage.ts';
import {presentation, region} from '../web/state.ts';

const turn = () => new Promise(resolve => setImmediate(resolve));
const palette = () => readPalette(key => /(?:opacity|width)$/.test(key) ? '1' : `token(${key})`);

function openChart(t) {
  const page = () => 'https://synthetic.test/map';
  const fetchFn = async () => ({ok: false, status: 404});
  t.mock.method(globalThis, 'fetch', fetchFn);
  t.mock.method(console, 'warn', () => {});
  const load = Promise.withResolvers();
  let loads = 0, engines = 0;
  const Control = class {};
  const lib = {
    Map: class {
      keyboard = this.touchZoomRotate = {disableRotation() {}};
      constructor() { engines++; }
      on() {} off() {} addControl() {} getLayer() {} getSource() {} jumpTo() {} remove() {}
    },
    NavigationControl: Control, ScaleControl: Control, AttributionControl: Control,
    setWorkerUrl() {}, addProtocol() {},
  };
  chartMounted.value = mapFirstIdle.value = chartFailed.value = mapMayLoad.value = false;
  presentation.value = '3d';
  camera.value = {latitude: 35, longitude: -121, zoom: 10};
  region.value = 'morro-bay';
  const chart = createChart({host: {dataset: {}}, load: () => { loads++; return load.promise; }, page, fetchFn, palette});
  t.after(() => chart.destroy());
  return {
    succeed: () => load.resolve({lib, Protocol: class {}}), fail: error => load.reject(error),
    state: () => ({loads, engines, mounted: chartMounted.value, idle: mapFirstIdle.value, failed: chartFailed.value}),
  };
}

// The admission point is successful engine mount, not construction of Chart or start of the library load.
test('C6: terrain-only and held Chart stay unmounted; completing the engine mount sets the signal before idle', async t => {
  const chart = openChart(t);
  const unmounted = {loads: 0, engines: 0, mounted: false, idle: false, failed: false};
  mapMayLoad.value = true;
  await turn();
  assert.equal(shownPresentation.value, '3d');
  assert.deepEqual(chart.state(), unmounted);
  mapMayLoad.value = false;
  presentation.value = 'chart';
  await turn();
  assert.deepEqual(chart.state(), unmounted);
  mapMayLoad.value = true;
  await turn();
  assert.deepEqual(chart.state(), {...unmounted, loads: 1});
  chart.succeed();
  await turn();
  assert.deepEqual(chart.state(), {...unmounted, loads: 1, engines: 1, mounted: true});
});

test('C1: mount failure releases first idle without marking Chart mounted', async t => {
  const chart = openChart(t), errors = [];
  t.mock.method(console, 'error', (event, error) => errors.push([event, error.name, error.message]));
  presentation.value = 'chart';
  mapMayLoad.value = true;
  chart.fail(new Error('no WebGL'));
  await turn();
  assert.deepEqual(chart.state(), {loads: 1, engines: 0, mounted: false, idle: true, failed: true});
  assert.deepEqual(errors, [['Chart unavailable', 'Error', 'no WebGL']]);
});

test('C1: marking Chart mounted repeatedly only transitions the signal once', t => {
  chartMounted.value = false;
  const values = [];
  t.after(chartMounted.subscribe(value => values.push(value)));
  assert.equal(markChartMounted(), undefined);
  assert.equal(markChartMounted(), undefined);
  assert.deepEqual(values, [false, true]);
  assert.equal(chartMounted.value, true);
});
