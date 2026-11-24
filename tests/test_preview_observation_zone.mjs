import test from 'node:test';
import assert from 'node:assert/strict';
import {attach, SST_CELLS, SST_HALO, SST_LINES} from '../web/map/preview/sst.ts';

// Pinned Chart/preview SST fixture: same file shape, palette and view as test_preview_layers.mjs.
const PALETTE = {text: '#eeeeee', bgDeep: '#111111'};
const COLOURS = ['#2b5d9e', '#d33'];
const NOW = new Date('2026-11-17T12:00:00Z');

async function attachSst(data_time) {
  const doc = {data_time, max_age_hours: 48, colours: COLOURS,
    cells: {type: 'FeatureCollection', features: []}, breaks: {type: 'FeatureCollection', features: []}};
  const draws = [], reports = [];
  const handle = await attach({
    engine: {setOverlay: (id, overlay, before) => { if (overlay) draws.push({id, overlay, before}); },
      view: {container: () => ({appendChild() {}})}},
    fetchFn: async () => new Response(JSON.stringify(doc)), now: () => NOW, palette: () => PALETTE,
    url: p => new URL(p, 'https://x.test/app').href, signal: new AbortController().signal,
    report: status => reports.push(status),
  });
  handle?.destroy(); // Stop the real expiry timer even when main unexpectedly admits a fixture.
  assert.equal(reports.length, 1, data_time);
  return {attached: handle !== null, draws, report: reports[0]};
}

for (const zone of ['UTC', 'America/Los_Angeles']) {
  test(`SST withholds a stamp without a zone in ${zone}`, async t => {
    const previous = process.env.TZ;
    process.env.TZ = zone;
    t.after(() => { if (previous === undefined) delete process.env.TZ; else process.env.TZ = previous; });
    // Bare Date.parse reads this wall time as fresh in UTC but in the future in Los Angeles.
    for (const stamp of ['2026-11-17T11:00:00', '2026-11-17']) {
      const {attached, draws, report} = await attachSst(stamp);
      assert.equal(report.state, 'stale', stamp);
      assert.equal(attached, false, stamp);
      assert.deepEqual(draws, [], stamp);
      assert.equal(report.ramp, undefined, stamp);
    }
  });

  test(`SST zoned controls retain paint, legend and freshness bounds in ${zone}`, async t => {
    const previous = process.env.TZ;
    process.env.TZ = zone;
    t.after(() => { if (previous === undefined) delete process.env.TZ; else process.env.TZ = previous; });
    for (const stamp of ['2026-11-17T11:00:00Z', '2026-11-17 11:00:00 UTC', '2026-11-17T03:00:00-08:00', '2026-11-17T16:30:00+0530']) {
      const {attached, draws, report} = await attachSst(stamp);
      assert.equal(attached, true, stamp);
      assert.equal(report.state, 'ready', stamp);
      assert.equal(report.dataTime, stamp);
      assert.match(report.text, /2026-11-17 11:00 UTC \(1\.0 h old\)/);
      assert.deepEqual(report.ramp, {colours: COLOURS, low: '52 °F', high: '66 °F'});
      assert.equal(draws.length, 1, stamp);
      assert.equal(draws[0].id, SST_CELLS);
      assert.deepEqual(draws[0].before, ['swell', 'mpa-fill']);
      assert.deepEqual(draws[0].overlay.layers.map(({id, paint}) => [id, paint['line-color']]),
        [[SST_CELLS, undefined], [SST_HALO, PALETTE.text], [SST_LINES, PALETTE.bgDeep]]);
    }
    for (const [stamp, eligible] of [
      ['2026-11-17T12:05:00Z', true], ['2026-11-17T12:05:00.001Z', false],
      ['2026-11-15T12:00:00Z', true], ['2026-11-15T11:59:59.999Z', false],
    ]) {
      const {draws, report} = await attachSst(stamp);
      assert.equal(report.state, eligible ? 'ready' : 'stale', stamp);
      assert.equal(draws.length, Number(eligible), stamp);
    }
  });
}
