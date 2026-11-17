// RF1831-6: the chlorophyll preview withholds images whose geographic bounds are not one valid rectangle. Offline: fake engine, fake fetch.
import test from 'node:test';
import assert from 'node:assert/strict';

const {readChlorophyll, attach} = await import('../web/map/preview/chlorophyll.ts');

const NOW = new Date('2026-11-16T12:00:00Z');
const doc = bounds => ({bounds, sample_at: '2026-11-16T11:00:00Z', max_age_hours: 96, style: {legend: [[0.01, '#112233'], [100, '#ffee00']]}});
const BAD = {
  'west after east': [-120, 35, -121, 36], 'south above north': [-121, 36, -120, 35],
  'zero width': [-121, 35, -121, 36], 'zero height': [-121, 35, -120, 35],
  'west below -180': [-181, 35, -120, 36], 'east above 180': [-121, 35, 181, 36],
  'south below -90': [-121, -91, -120, 36], 'north above 90': [-121, 35, -120, 91],
  'NaN': [-121, NaN, -120, 36], 'Infinity': [-121, 35, Infinity, 36], 'wrong length': [-121, 35, -120],
};

test('chlorophyll_invalid_rectangles_are_rejected', () => {
  for (const [name, b] of Object.entries(BAD)) assert.throws(() => readChlorophyll(doc(b)), /chlorophyll file is not valid/, name);
  const edge = doc([-180, -90, 180, 90]);
  assert.ok(readChlorophyll(edge) === edge, 'the whole-world rectangle is still valid and returned unchanged');
});

function run(bounds) {
  const calls = [], reports = [], abort = new AbortController();
  const engine = {setOverlay: (id, overlay) => calls.push([id, overlay])};
  const fetchFn = async () => new Response(JSON.stringify(doc(bounds)), {status: 200});
  const ctx = {engine, fetchFn, now: () => NOW, palette: () => ({text: '#eee', bgDeep: '#111'}), url: p => new URL(p, 'https://x.test/app').href, signal: abort.signal, report: s => reports.push(s)};
  return {ctx, calls, reports};
}

test('chlorophyll_invalid_bounds_never_draw_or_report_ready', async () => {
  for (const [name, b] of Object.entries(BAD)) {
    const {ctx, calls, reports} = run(b);
    const handle = await attach(ctx).catch(err => err);
    if (handle && typeof handle.destroy === 'function') handle.destroy(); // old behaviour: stop the expiry timer so the run ends
    assert.ok(handle instanceof Error && /chlorophyll file is not valid/.test(handle.message), name);
    assert.equal(calls.length, 0, `${name}: no overlay installed`);
    assert.equal(reports.length, 0, `${name}: nothing reported ready`);
  }
});

test('chlorophyll_valid_rectangle_keeps_corners_and_ramp', async () => {
  const {ctx, calls, reports} = run([-121, 35, -120, 36]);
  const handle = await attach(ctx);
  try {
    assert.equal(calls.length, 1);
    const src = calls[0][1].sources['preview-chlorophyll'];
    assert.ok(JSON.stringify(src.coordinates) === JSON.stringify([[-121, 36], [-120, 36], [-120, 35], [-121, 35]]), 'corners');
    assert.ok(src.url.endsWith('chlorophyll.png'), 'image path');
    assert.equal(reports.at(-1).state, 'ready');
    assert.equal(reports.at(-1).ramp.low, '0.01 mg/m³');
    assert.equal(reports.at(-1).ramp.high, '100+');
  } finally { handle.destroy(); }
  assert.equal(calls.at(-1)[1], null, 'destroy removes the overlay');
});
