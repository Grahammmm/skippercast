// Currents as animated streamlines (FE-15, docs/plans/front-end/design.md § 9):
// the streamline mathematics over packages/coast's surface field
// (web/map/flow.ts), the frame and source rules (web/map/currents.ts) and the
// Chart overlay's animation, over a fake map view, canvas and frame clock. The
// packets are synthetic: a regular 0.04° grid off Morro Bay with uniform flow.
import assert from 'node:assert/strict';
import test from 'node:test';
import {signal} from '@preact/signals';
import {DASH, MAX_PATHS, SEEDS, drawDashes, fastSpeed, flowPaths, frameField, screenVector, seedSpacing} from '../web/map/flow.ts';
import {CURRENTS_BASIS, createCurrents, currentMark, currentsState, currentsStatus, regionPlace} from '../web/map/currents.ts';
import {readPalette} from '../web/map/palette.ts';
import {UNSUPPORTED_CURRENT} from '../web/map/stage.ts';
import {appView, current, hour, presentation, region, UNSUPPORTED} from '../web/state.ts';

const NOW = new Date('2026-10-07T12:20:00Z'), AT = new Date('2026-10-07T12:00:00Z'), TZ = 'America/Los_Angeles';
const WEST = -121.0, NORTH = 35.5, STEP = 0.04, N = 8;
/** Cells on an N × N grid; `skip` removes cells (a gap) and `speed` sets eastward m/s per cell. */
function cells({skip = () => false, u = () => 0.3, v = () => 0.1} = {}) {
  const out = [];
  for (let j = 0; j < N; j++) for (let i = 0; i < N; i++) {
    if (skip(i, j)) continue;
    const lon = +(WEST + i * STEP).toFixed(6), lat = +(NORTH - j * STEP).toFixed(6), uMs = u(i, j), vMs = v(i, j);
    out.push({lat, lon, uMs, vMs, speedKnots: Math.hypot(uMs, vMs) * 1.943844492, towardDeg: (Math.atan2(uMs, vMs) * 180 / Math.PI + 360) % 360});
  }
  return out;
}
const wcofs = (frameCells = cells(), extra = {}) => ({
  id: 'wcofs', kind: 'forecast', label: 'NOAA WCOFS surface forecast', url: 'https://example.test/wcofs', fetchedAt: '2026-10-07T11:50:00Z',
  issuedAt: '2026-10-07T03:00:00Z', sampleAt: null, nativeResolutionKm: 4, sampleStride: 1, horizontalDatum: 'NAD83', surfaceOnly: true,
  attribution: 'NOAA', license: 'public-domain-us-gov', limitations: 'Surface only.',
  frames: [{validAt: '2026-10-07T09:00:00Z', cells: frameCells}, {validAt: '2026-10-07T12:00:00Z', cells: frameCells}, {validAt: '2026-10-07T15:00:00Z', cells: frameCells}],
  ...extra,
});
const packet = (...currents) => ({schemaVersion: 1, countyId: 'slo', generatedAt: '2026-10-07T11:55:00Z', currents, cloud: null, sources: []});
/** A screen 100 px per cell step, north up, the grid's north-west cell at (0, 0). */
const PX = 100;
const unproject = (x, y) => ({lon: WEST + x / PX * STEP, lat: NORTH - y / PX * STEP});
const project = (lon, lat) => ({x: (lon - WEST) / STEP * PX, y: (NORTH - lat) / STEP * PX});
const SIZE = (N - 1) * PX;

test('streamlines follow the field and stop at a gap: no point falls where the field has no support', () => {
  const hole = (i, j) => i === 3 && j === 3;
  const field = frameField(wcofs(), {validAt: AT.toISOString(), cells: cells({skip: hole})});
  assert.ok(field, 'a grid with one missing cell is still a field');
  assert.equal(field.sample(WEST + 3 * STEP, NORTH - 3 * STEP), null, 'the missing cell is a gap');
  const vector = screenVector(field, unproject);
  const paths = flowPaths(vector, SIZE, SIZE, Infinity);
  assert.ok(paths.length > 3, 'paths are drawn around the gap');
  for (const {points} of paths) {
    assert.ok(points.length > 5);
    for (const p of points) assert.ok(vector(p.x, p.y), `(${p.x.toFixed(1)}, ${p.y.toFixed(1)}) samples the field`);
    // Uniform flow toward ENE: each step moves east and north on screen.
    for (let k = 1; k < points.length; k++) { assert.ok(points[k].x > points[k - 1].x); assert.ok(points[k].y < points[k - 1].y); }
  }
  // Every cell around the gap is unsupported, so no point lies in the four quads that touch it.
  const inHole = p => p.x > 2 * PX && p.x < 4 * PX && p.y > 2 * PX && p.y < 4 * PX;
  assert.equal(paths.flatMap(p => p.points).filter(inHole).length, 0);
});

test('land ends a path, still water draws nothing, and a coarse or ragged grid is refused', () => {
  const field = frameField(wcofs(), {validAt: AT.toISOString(), cells: cells()});
  const land = (x) => x > 4 * PX;
  const paths = flowPaths(screenVector(field, unproject, land), SIZE, SIZE, Infinity);
  assert.ok(paths.length > 0);
  assert.ok(paths.every(p => p.points.every(q => !land(q.x))), 'no point on land');
  const still = frameField(wcofs(), {validAt: AT.toISOString(), cells: cells({u: () => 0.005, v: () => 0.005})});
  assert.deepEqual(flowPaths(screenVector(still, unproject), SIZE, SIZE, Infinity), []);
  const sparse = cells().filter((_, k) => k % 2 === 0).map(c => ({...c}));
  assert.equal(frameField(wcofs(), {validAt: AT.toISOString(), cells: sparse.map((c, k) => ({...c, lon: c.lon + (k % 3) * 0.013}))}), null);
  assert.equal(frameField(wcofs(), {validAt: AT.toISOString(), cells: []}), null);
});

test('seeds keep the 64 px spacing on a laptop and widen on a large screen: never more than MAX_PATHS streamlines', () => {
  const everywhere = () => ({x: 1, y: 0, speed: 0.5});
  assert.equal(seedSpacing(1280, 800), SEEDS.spacing);
  assert.equal(flowPaths(everywhere, 1280, 800, Infinity).length, 20 * 13, 'a laptop keeps a seed every 64 px');
  assert.equal(seedSpacing(390, 844), SEEDS.spacing);
  for (const [width, height] of [[1920, 1080], [2560, 1440], [3840, 2160], [7680, 4320], [5000, 300]]) {
    const n = flowPaths(everywhere, width, height, Infinity).length;
    assert.ok(n <= MAX_PATHS, `${width}×${height}: ${n} paths`);
    assert.ok(n >= MAX_PATHS * 0.75, `${width}×${height}: ${n} paths still cover the screen`);
    assert.ok(seedSpacing(width, height) > SEEDS.spacing, `${width}×${height} widens the spacing`);
  }
});

test('the fastest fifth of cells draws in --flow-fast; dashes move only with the clock', () => {
  const speeds = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0];
  assert.equal(fastSpeed({validAt: '', cells: speeds.map(speedKnots => ({speedKnots}))}), 0.8, 'the 80th percentile by nearest rank');
  const field = frameField(wcofs(), {validAt: AT.toISOString(), cells: cells({u: (i) => 0.1 + i * 0.1})});
  const paths = flowPaths(screenVector(field, unproject), SIZE, SIZE, 1.0);
  assert.ok(paths.some(p => p.fast) && paths.some(p => !p.fast));
  assert.ok(paths.every(p => p.fast === p.speed > 1.0));
  const strokes = [];
  const ctx = {beginPath() {}, moveTo() {}, lineTo() {}, setLineDash(d) { this.dash = d; }, stroke() { strokes.push([this.strokeStyle, this.lineDashOffset, this.dash]); }};
  const colours = {flow: 'token(flow)', fast: 'token(flow-fast)'};
  drawDashes(ctx, paths, colours, 0);
  const still = strokes.splice(0);
  drawDashes(ctx, paths, colours, 0);
  assert.deepEqual(strokes.splice(0), still, 'the same clock draws the same dashes');
  drawDashes(ctx, paths, colours, 1.5);
  assert.notDeepEqual(strokes.map(s => s[1]), still.map(s => s[1]), 'a later clock moves them');
  assert.deepEqual(new Set(still.map(s => s[0])), new Set([colours.flow, colours.fast]));
  assert.deepEqual(still[0][2], [...DASH]);
});

test('a chosen source draws only its own frame; off, unsupported and missing frames draw nothing and say why', () => {
  const ocean = packet(wcofs());
  const drawn = currentsStatus('wcofs', 'ready', ocean, AT, NOW, TZ);
  assert.equal(drawn.drawn.frame.validAt, '2026-10-07T12:00:00Z');
  assert.equal(drawn.note, 'forecast Wed 5 am');
  assert.equal(drawn.reason, '');
  assert.match(drawn.basis, /^NOAA WCOFS surface forecast, about 4 km, issued 9 h ago; arrows follow the toward-bearing and their motion is illustrative\.$/);

  assert.deepEqual(currentsStatus('off', 'ready', ocean, AT, NOW, TZ), {drawn: null, note: '', reason: '', basis: CURRENTS_BASIS});
  assert.equal(currentsStatus(UNSUPPORTED, 'ready', ocean, AT, NOW, TZ).reason, UNSUPPORTED_CURRENT);
  // Radar is chosen and the packet holds only the forecast: no substitute.
  const radar = currentsStatus('hfr-6', 'ready', ocean, AT, NOW, TZ);
  assert.equal(radar.drawn, null);
  assert.equal(radar.reason, 'Currents unavailable: no fresh Observed HF radar · 6 km frame for this hour.');
  for (const [status, note] of [['unbound', 'no packet for this region'], ['loading', 'loading'], ['error', 'unavailable'], ['invalid', 'unavailable'], ['expired', 'expired']]) {
    const s = currentsStatus('wcofs', status, status === 'loading' ? null : ocean, AT, NOW, TZ);
    assert.equal(s.drawn, null, status);
    assert.equal(s.note, note, status);
  }
  // A cycle issued more than 36 hours ago is no fresh frame; the rail keeps the last valid time.
  const old = currentsStatus('wcofs', 'ready', packet(wcofs(cells(), {issuedAt: '2026-10-05T21:00:00Z'})), AT, NOW, TZ);
  assert.equal(old.drawn, null);
  assert.equal(old.note, 'no fresh frame · last Wed 5 am');
  assert.equal(old.reason, 'Currents unavailable: no fresh NOAA WCOFS forecast frame for this hour; the last was valid Wed 5 am.');
  // Past the forecast's last frame: nothing, and the last frame named.
  assert.equal(currentsStatus('wcofs', 'ready', ocean, new Date('2026-10-08T12:00:00Z'), NOW, TZ).note, 'no fresh frame · last Wed 8 am');
  // Two products with the same id are ambiguous: a gap, never a pick.
  assert.equal(currentsStatus('wcofs', 'ready', packet(wcofs(), wcofs()), AT, NOW, TZ).drawn, null);
});

test('a frame the surface field refuses draws nothing, and the rail and legend say why rather than naming the frame', () => {
  const refused = 'Currents unavailable: the NOAA WCOFS forecast frame valid Wed 5 am is not a grid that can be drawn without bridging gaps (too sparse, too coarse, irregular or too large), and no other source is shown.';
  const ragged = cells().filter((_, k) => k % 2 === 0).map((c, k) => ({...c, lon: c.lon + (k % 3) * 0.013}));
  // Cells 0.04° apart against a 1 km native grid are too coarse to join.
  for (const [what, field] of [['ragged', wcofs(ragged)], ['coarse', wcofs(cells(), {nativeResolutionKm: 1})]]) {
    const s = currentsStatus('wcofs', 'ready', packet(field), AT, NOW, TZ);
    assert.equal(s.drawn, null, what);
    assert.equal(s.note, 'grid cannot be drawn · Wed 5 am', what);
    assert.equal(s.reason, refused, what);
    assert.equal(s.basis, CURRENTS_BASIS, what);
  }
  assert.ok(currentsStatus('wcofs', 'ready', packet(wcofs()), AT, NOW, TZ).drawn.surface, 'a regular grid carries its field');
});

test('a click reads the blended field with its time, source and basis; outside the field it reads nothing', () => {
  const drawn = currentsStatus('wcofs', 'ready', packet(wcofs()), AT, NOW, TZ).drawn;
  const field = frameField(drawn.field, drawn.frame);
  const mark = currentMark(drawn, field, {lon: WEST + 0.1, lat: NORTH - 0.1}, TZ, NOW);
  assert.equal(mark.name, 'Surface current');
  assert.equal(mark.reading, '0.61 kt toward 72° true');
  assert.equal(mark.kind, 'Forecast · valid Wed 5 am');
  assert.equal(mark.source, 'NOAA WCOFS surface forecast · issued 9 h ago');
  assert.match(mark.basis, /motion is illustrative\. Blended from adjacent wet cells; surface flow, not bottom current or boat drift\.$/);
  assert.equal(currentMark(drawn, field, {lon: WEST - 0.5, lat: NORTH}, TZ, NOW), null);
});

test('the region place binds by its centre and reviewed local areas', () => {
  const place = regionPlace({id: 'morro-bay', center: [35.34, -120.965], localAreas: [{id: 'estero-bay', bounds: [-121.05, 35.32, -120.78, 35.47]}]}, 'boat', 'lingcod');
  assert.deepEqual({...place, at: null}, {regionId: 'morro-bay', point: {latitude: 35.34, longitude: -120.965}, localAreas: [{id: 'estero-bay', bounds: [-121.05, 35.32, -120.78, 35.47]}], profile: 'boat', target: 'lingcod', at: null});
  assert.equal(regionPlace(null, 'boat', ''), null);
});

/** A fake map view, document, canvas and frame clock for the Chart overlay. */
function harness({reduced = false, ocean = packet(wcofs()), land = [], now = () => NOW, onHide, options = {}} = {}) {
  const listeners = {}, docListeners = {}, motionListeners = {}, canvases = [], requests = [], cancels = [];
  let next = 1;
  const context = () => ({
    calls: 0, setTransform() {}, clearRect() { this.cleared = (this.cleared ?? 0) + 1; }, beginPath() {}, moveTo() {}, lineTo() {}, stroke() { this.calls++; },
    arc() {}, fill() {}, setLineDash() {}, getImageData: (_x, _y, w, h) => ({data: new Uint8ClampedArray(w * h * 4)}),
  });
  const doc = {
    hidden: false,
    addEventListener: (type, fn) => { (docListeners[type] ??= []).push(fn); },
    removeEventListener: (type, fn) => { docListeners[type] = (docListeners[type] ?? []).filter(f => f !== fn); },
    createElement: () => { const ctx = context(); const c = {width: 0, height: 0, dataset: {}, className: '', setAttribute() {}, removed: false, remove() { this.removed = true; }, getContext: () => ctx, ctx}; return c; },
  };
  const container = {append: c => canvases.push(c)};
  const view = {
    container: () => container, size: () => ({width: SIZE, height: SIZE}), project: (lon, lat) => project(lon, lat), unproject,
    busy: () => false, land: () => land,
    on: (type, fn) => { (listeners[type] ??= []).push(fn); return () => { listeners[type] = listeners[type].filter(f => f !== fn); }; },
  };
  const motion = {matches: reduced, addEventListener: (t, fn) => { motionListeners[t] = fn; }, removeEventListener: () => {}};
  const frames = {request: fn => { requests.push(fn); return next++; }, cancel: id => cancels.push(id)};
  const data = {coastOcean: signal({data: ocean}), coastStatus: signal({ocean: 'ready', report: 'idle', history: 'idle'}), setPlace() {}, load: async () => {}};
  const currents = createCurrents({view, palette: () => readPalette(name => `token(${name})`), zone: () => TZ, data, doc, motion, frames, now, onHide, ...options});
  const fire = type => { for (const fn of listeners[type] ?? []) fn(); };
  const visibility = hidden => { doc.hidden = hidden; for (const fn of docListeners.visibilitychange ?? []) fn(); };
  return {currents, canvases, requests, cancels, fire, visibility, data, listeners, dash: () => canvases[1], motionListeners, motion};
}

function choose(value) { presentation.value = 'chart'; appView.value = 'coast'; hour.value = '2026-10-07T12:00Z'; current.value = value; }

test('the overlay animates while shown, stops when the page is hidden and clears at once on off', t => {
  choose('wcofs');
  const h = harness();
  t.after(() => { h.currents.destroy(); current.value = 'off'; hour.value = null; });
  assert.equal(h.canvases.length, 2, 'a still canvas and a dash canvas');
  assert.ok(Number(h.dash().dataset.paths) > 0);
  assert.equal(h.dash().dataset.motion, 'animated');
  assert.equal(h.requests.length, 1);
  assert.equal(currentsState.value.note, 'forecast Wed 5 am');
  // Frames inside the 20 fps budget skip painting; the next one paints.
  const strokes = () => h.dash().ctx.calls;
  h.requests.shift()(1000);
  const painted = strokes();
  assert.ok(painted > 0);
  h.requests.shift()(1010);
  assert.equal(strokes(), painted, 'within 50 ms nothing repaints');
  h.requests.shift()(1050);
  assert.ok(strokes() > painted);

  h.visibility(true);
  assert.equal(h.dash().dataset.motion, 'paused');
  assert.ok(h.cancels.length > 0, 'the pending frame is cancelled');
  const pending = h.requests.length;
  h.visibility(false);
  assert.equal(h.dash().dataset.motion, 'animated');
  assert.equal(h.requests.length, pending + 1, 'visible again, one frame is requested');

  // A moving map hides the paths until it settles; then they are rebuilt.
  h.fire('movestart');
  assert.equal(h.dash().dataset.paths, '0');
  h.fire('idle');
  assert.ok(Number(h.dash().dataset.paths) > 0);

  current.value = 'off';
  assert.equal(h.dash().dataset.paths, '0', 'off clears in the same tick');
  assert.equal(h.dash().dataset.motion, 'paused');
  assert.deepEqual(h.listeners.idle, [], 'no map listener while nothing draws');
});

test('a source without a fresh frame draws nothing; reduced motion draws still arrows and lines', t => {
  choose('hfr-1');
  const h = harness();
  t.after(() => { h.currents.destroy(); current.value = 'off'; hour.value = null; });
  assert.equal(h.canvases.length, 0, 'nothing is drawn for radar the packet does not hold');
  assert.match(currentsState.value.reason, /^Currents unavailable: no fresh Observed HF radar · 1 km frame/);
  h.currents.destroy();

  choose('wcofs');
  const still = harness({reduced: true});
  t.after(() => still.currents.destroy());
  assert.equal(still.dash().dataset.motion, 'still');
  assert.equal(still.requests.length, 0, 'no animation frame under reduced motion');
  assert.ok(still.dash().ctx.calls > 0, 'the dashes are drawn once, standing still');
  assert.ok(still.canvases[0].ctx.calls > 0, 'paths and arrowheads on the still canvas');
  still.motion.matches = false; still.motionListeners.change();
  assert.equal(still.dash().dataset.motion, 'animated');
});

test('a host picks its own source and shown rule: the landing draws without ?current= or the Chart (FE-25)', t => {
  presentation.value = '3d'; appView.value = 'coast'; current.value = 'off'; hour.value = '2026-10-07T12:00Z';
  let pick = 'hfr-1';
  const h = harness({options: {source: () => pick, shown: () => true}});
  t.after(() => { h.currents.destroy(); presentation.value = 'chart'; hour.value = null; });
  assert.equal(h.canvases.length, 0, 'a source the packet does not hold draws nothing');
  pick = 'wcofs';
  h.visibility(false);   // any clock tick re-asks the host for its source
  assert.ok(Number(h.dash().dataset.paths) > 0, 'drawn while ?current= is off and the stage shows 3D');
  assert.equal(h.dash().dataset.motion, 'animated');
  assert.match(currentsState.value.basis, /^NOAA WCOFS surface forecast, about 4 km/);
});

test('a drawn frame reads on click and is withdrawn when the presentation leaves the Chart', t => {
  choose('wcofs');
  const h = harness();
  t.after(() => { h.currents.destroy(); current.value = 'off'; hour.value = null; presentation.value = 'chart'; region.value = null; });
  region.value = 'morro-bay';
  assert.equal(h.currents.reading({lon: WEST + 0.1, lat: NORTH - 0.1}).reading, '0.61 kt toward 72° true');
  presentation.value = '3d';
  assert.equal(h.dash().dataset.paths, '0');
  assert.equal(h.currents.reading({lon: WEST + 0.1, lat: NORTH - 0.1}), null);
});

test('a reading is withdrawn with its frame: at the frame\'s own deadline, on off, another source or another hour', t => {
  t.mock.timers.enable({apis: ['setTimeout']});
  const at = {lon: WEST + 0.1, lat: NORTH - 0.1};
  t.after(() => { current.value = 'off'; hour.value = null; });
  // The packet was fetched at 11:50Z, so its frames expire at 17:50Z; nothing touches the map or the dock.
  let clock = NOW.getTime();
  choose('wcofs');
  const hides = [];
  const h = harness({now: () => new Date(clock), onHide: () => hides.push(currentsState.value.note)});
  assert.ok(h.currents.reading(at));
  t.mock.timers.tick(60 * 60_000);
  assert.deepEqual(hides, [], 'the hourly re-judge keeps a frame still in date');
  clock = Date.parse('2026-10-07T17:51:00Z');
  t.mock.timers.tick(5 * 60 * 60_000);
  assert.equal(hides.length, 1, 'the card is cleared when the frame reaches expiresAt');
  assert.equal(h.currents.reading(at), null);
  assert.equal(h.dash().dataset.paths, '0');
  assert.match(currentsState.value.note, /^no fresh frame/);
  h.currents.destroy();

  for (const [what, change] of [['off', () => { current.value = 'off'; }], ['another source', () => { current.value = 'hfr-6'; }],
    ['another hour', () => { hour.value = '2026-10-07T15:00Z'; }]]) {
    clock = NOW.getTime();
    choose('wcofs');
    let hidden = 0;
    const each = harness({onHide: () => { hidden++; }});
    change();
    assert.equal(hidden, 1, what);
    each.currents.destroy();
  }
});
