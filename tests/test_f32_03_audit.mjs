import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { runInNewContext } from 'node:vm';
import { fresh, sample, validate } from '../web/map/wind-layer.js';

// Exercise the private page's actual handlers without loading a browser, renderer or private feed.
const html = readFileSync(new URL('../research/scripts/map_style/wind-test.html', import.meta.url), 'utf8');
const script = html.match(/<script type="module">([\s\S]*?)<\/script>/)[1]
  .replace(/^import .*;$/gm, '');
const grid = {
  schema_version: 1, source_id: 'noaa-gfs', units: 'm/s', width: 2, height: 2,
  west: 0, north: 0, resolution_degrees: .25, max_age_hours: 18,
  run_time: '2026-01-01T00:00:00Z', data_time: '2026-01-01T06:00:00Z',
  u: [[3, 3], [3, 3]], v: [[4, 4], [4, 4]],
};
const atLimit = Date.parse('2026-01-01T18:00:00Z');

async function preview(now = atLimit) {
  const mapEvents = new Map();
  const elements = new Map(['toggle', 'status', 'sample', 'time', 'wind', 'zoom']
    .map(id => [id, { textContent: '' }]));
  const canvas = elements.get('wind');
  canvas.hidden = true;
  const toggle = elements.get('toggle');
  toggle.addEventListener = (_event, handler) => { toggle.change = handler; };
  let tick, calls = 0;
  runInNewContext(script, {
    maplibregl: {
      setWorkerUrl() {}, addProtocol() {},
      Map: class {
        on(event, handler) { mapEvents.set(event, handler); }
        getZoom() { return 10; }
      },
    },
    window: { pmtiles: { Protocol: class {} } },
    location: new URL('http://localhost/'), URL, URLSearchParams,
    document: { getElementById: id => elements.get(id) },
    Date: { now: () => now, parse: Date.parse },
    fetch: async () => ({ ok: true, json: async () => grid }),
    setInterval: handler => { tick = handler; },
    validate, fresh: g => fresh(g, now),
    sample: (...args) => { calls++; return sample(...args); },
    particles: () => ({ setVisible(value) { canvas.hidden = !value; } }),
  });
  await mapEvents.get('load')();
  return {
    click: () => mapEvents.get('click')({ lngLat: { lng: .125, lat: -.125 } }),
    expire: () => { now = atLimit + 1; },
    tick, toggle, canvas,
    get calls() { return calls; },
    get readout() { return elements.get('sample').textContent; },
  };
}

test('fresh visible preview shows the real 3-4-5 vector as 9.7 knots', async () => {
  const p = await preview();
  assert.equal(p.canvas.hidden, false);
  p.click();
  assert.equal(p.readout, `9.7 kt · east 3.00, north 4.00 m/s · ${grid.data_time}`);
});

test('an already stale grid is not sampled even with a click inside its crop', async () => {
  const p = await preview(atLimit + 1);
  assert.equal(p.canvas.hidden, true);
  assert.equal(p.toggle.disabled, true);
  p.click();
  assert.equal(p.calls, 0);
  assert.equal(p.readout, '');
});

test('expiry blocks clicks before the next tick and clears a prior readout without a click', async () => {
  const p = await preview();
  p.click();
  p.expire();
  p.click();
  assert.equal(p.calls, 1, 'a click between freshness ticks must not resample');
  assert.equal(p.readout, '');

  const q = await preview();
  q.click();
  assert.match(q.readout, /^9\.7 kt/);
  q.expire();
  q.tick();
  assert.equal(q.canvas.hidden, true);
  assert.equal(q.toggle.disabled, true);
  assert.equal(q.readout, '');
});

test('toggle-off clears a fresh result and blocks sampling until toggled back on', async () => {
  const p = await preview();
  p.click();
  p.toggle.checked = false;
  p.toggle.change();
  assert.equal(p.canvas.hidden, true);
  assert.equal(p.readout, '');
  p.click();
  assert.equal(p.calls, 1);
  assert.equal(p.readout, '');
  p.toggle.checked = true;
  p.toggle.change();
  p.click();
  assert.match(p.readout, /^9\.7 kt/);
});
