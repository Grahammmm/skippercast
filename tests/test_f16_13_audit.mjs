// SCA-586 / F16-13: a prediction series wholly outside the requested window must not satisfy the offline tide save, while
// a sparse high/low-only series inside the window must still be saved (no six-minute cadence imposed). Offline synthetic
// fixture; no network, no real station data. Valid controls must satisfy the contract. The affected control is only
// *observed* (diagnostic): the test neither asserts the gap is desirable nor fails when it is fixed. A synthetic
// negative control proves the detector.
import test from 'node:test';
import assert from 'node:assert/strict';
import {saveTidePack, tidePackURLs} from '../web/tide-stations.ts';

const NOW = Date.parse('2026-10-08T17:00:00Z');
const R = {id: '9000001', name: 'Fixture reference', lat: 35.1, lng: -121, type: 'R'};
const S = {id: '9000002', name: 'Fixture subordinate', lat: 35.2, lng: -121, type: 'S'};
const enc = value => new TextEncoder().encode(JSON.stringify(value));
const signal = new AbortController().signal;

// Requested interval read back from the pack URL itself (NOAA begin_date/end_date, UTC dates).
function windowOf(url) {
  const q = new URL(url).searchParams, day = s => Date.parse(`${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}T00:00:00Z`);
  return {from: day(q.get('begin_date')), to: day(q.get('end_date')) + 86400000};
}
const hilo = (iso, type, v = '3.0') => ({t: iso.replace('T', ' ').slice(0, 16), v, type});
const six = iso => ({t: iso.replace('T', ' ').slice(0, 16), v: '1.2'});

function run(station, bodies) {
  const urls = tidePackURLs(station, NOW), puts = [];
  const fetcher = async url => new Response(bodies(urls)[url], {status: 200, headers: {'content-type': 'application/json'}});
  return saveTidePack(urls, async key => { puts.push(key); }, signal, fetcher).then(() => ({outcome: 'saved', puts, urls}), e => ({outcome: 'refused', puts, urls, message: String(e.message)}));
}
const directory = (station, urls) => ({[urls[0]]: enc({stations: [station]})});
const inWindow = {hiloEvents: [hilo('2026-10-08T18:00', 'H'), hilo('2026-10-08T23:30', 'L', '0.4')], points: [six('2026-10-08T17:00'), six('2026-10-08T17:06')]};
const outWindow = {hiloEvents: [hilo('2026-12-25T18:00', 'H'), hilo('2026-12-25T23:30', 'L', '0.4')], points: [six('2026-12-25T17:00'), six('2026-12-25T17:06')]};
const bodiesFor = (station, s) => urls => ({...directory(station, urls), [urls[1]]: enc({predictions: s.hiloEvents}), ...(urls[2] ? {[urls[2]]: enc({predictions: s.points})} : {})});

// Contract: refuse (and write nothing) when every row is outside the requested window; otherwise save.
const contract = (r, wholly) => wholly ? r.outcome === 'refused' && r.puts.length === 0 : r.outcome === 'saved' && r.puts.length === r.urls.length;

// Coverage class of a saved series against the requested window. Cadence-free: a high/low-only station is "full" when its
// events reach within one tidal half-day (8 h) of both window edges; no six-minute spacing is required.
const EDGE = 8 * 3600000;
function coverage(w, times) {
  const inside = times.filter(t => t >= w.from && t < w.to).sort((a, b) => a - b);
  if (!inside.length) return 'none';
  return inside[0] - w.from <= EDGE && w.to - inside.at(-1) <= EDGE ? 'full' : 'partial';
}
// A saved result must carry its coverage class, so partial coverage is labelled separately from full.
const labelled = (r, expected) => r.outcome === 'saved' && r.coverage === expected;
const hiloTimes = (w, step = 6.2 * 3600000) => { const out = []; for (let t = w.from + 3600000; t < w.to; t += step) out.push(t); return out; };

test('fixture window is the requested NOAA UTC interval', () => {
  const [, hiloURL] = tidePackURLs(R, NOW), w = windowOf(hiloURL);
  assert.ok(Date.parse('2026-10-08T18:00:00Z') >= w.from && Date.parse('2026-10-08T18:00:00Z') < w.to);
  assert.ok(Date.parse('2026-12-25T18:00:00Z') >= w.to, 'out-of-window rows really are outside the request');
});

test('valid controls satisfy the contract', async () => {
  const full = await run(R, bodiesFor(R, inWindow));
  assert.ok(contract(full, false), JSON.stringify(full));
  // high/low-only station: two events, no six-minute series, still saved
  const sparse = await run(S, bodiesFor(S, inWindow));
  assert.equal(tidePackURLs(S, NOW).length, 2);
  assert.ok(contract(sparse, false), JSON.stringify(sparse));
  // partial coverage: events cover only part of the window; not refused
  const partial = await run(S, bodiesFor(S, {hiloEvents: [hilo('2026-10-08T18:00', 'H')], points: []}));
  assert.ok(contract(partial, false), JSON.stringify(partial));
});

test('coverage classes: partial is separate from full, with no cadence imposed', () => {
  const w = windowOf(tidePackURLs(S, NOW)[1]);
  assert.equal(coverage(w, hiloTimes(w)), 'full', 'sparse high/low-only events spanning the window are full');
  assert.equal(coverage(w, [w.from + 3600000]), 'partial', 'one early event leaves the rest of the window uncovered');
  assert.equal(coverage(w, [Date.parse('2026-12-25T18:00:00Z')]), 'none');
  assert.equal(coverage(w, hiloTimes(w).slice(0, 2)), 'partial');
});

test('labelling checker detects an unlabelled partial save on synthetic results', () => {
  const urls = ['a', 'b'], base = {outcome: 'saved', puts: ['a', 'b'], urls};
  assert.equal(labelled({...base}, 'partial'), false, 'partial save with no label must be detected');
  assert.equal(labelled({...base, coverage: 'full'}, 'partial'), false, 'partial save labelled full must be detected');
  assert.equal(labelled({...base, coverage: 'partial'}, 'partial'), true);
  assert.equal(labelled({...base, coverage: 'full'}, 'full'), true);
});

test('checker detects the stated gap on synthetic results', () => {
  // independent negative control: fabricated results, no dependence on saveTidePack
  const urls = ['a', 'b'];
  assert.equal(contract({outcome: 'saved', puts: ['a', 'b'], urls}, true), false, 'saving a wholly out-of-window series must be detected');
  assert.equal(contract({outcome: 'refused', puts: ['a'], urls}, true), false, 'a partial write on refusal must be detected');
  assert.equal(contract({outcome: 'refused', puts: [], urls}, true), true);
  assert.equal(contract({outcome: 'refused', puts: [], urls}, false), false, 'refusing an in-window sparse series must be detected');
});

test('affected control: baseline observation only (passes before and after a fix)', async t => {
  // Expected after a fix: refused with nothing written (previous pack kept). Not asserted, so a correct fix needs no edit here.
  for (const station of [R, S]) {
    const r = await run(station, bodiesFor(station, outWindow));
    t.diagnostic(`${station.type} wholly out-of-window: outcome=${r.outcome} puts=${r.puts.length} contractHolds=${contract(r, true)}`);
  }
  const part = await run(S, bodiesFor(S, {hiloEvents: [hilo('2026-10-08T18:00', 'H')], points: []}));
  t.diagnostic(`partial coverage save: outcome=${part.outcome} labelledPartial=${labelled(part, 'partial')}`);
});
