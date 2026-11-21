import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {planGpxImport} from '../web/gpx-import-plan.ts';
import {screenGpxCandidates} from '../web/gpx-import-screen.ts';
import {MAX_GPX_BYTES, readGpxWaypoints} from '../web/gpx-waypoints.ts';

const xml = readFileSync(new URL('./fixtures/gpx/marks-150.gpx', import.meta.url), 'utf8');

// Independent of the reader: the 15-by-10 lattice traverses alternate rows in opposite directions.
const expectedWaypoints = Array.from({length: 150}, (_, i) => {
  const row = Math.floor(i / 10);
  const col = row % 2 ? 9 - i % 10 : i % 10;
  const name = `M${String(i + 1).padStart(3, '0')}`;
  return {
    name,
    lat: (3520 + 2 * row) / 100,
    lon: (-12120 + 2 * col) / 100,
    note: (i + 1) % 15 === 0 ? `Synthetic note for ${name}` : null,
  };
});

const inside = new Set([
  'M042', 'M043', 'M044', 'M045', 'M046', 'M047', 'M048',
  'M049', 'M050', 'M051', 'M052', 'M053', 'M054', 'M055',
]);
const near = new Set(['M038', 'M039', 'M040', 'M041', 'M056', 'M057', 'M058', 'M059']);
const now = Date.UTC(2026, 0, 1);
const hour = 3_600_000;
const key = (lat, lon) => `${lat},${lon}`;
const nameByPosition = new Map(expectedWaypoints.map(w => [key(w.lat, w.lon), w.name]));
const screen = {
  checkedAt: now - hour,
  verdict({latitude, longitude}) {
    // The real screen API only receives coordinates. These are fictional verdicts, not mapped boundaries.
    const name = nameByPosition.get(key(latitude, longitude));
    if (inside.has(name)) return {inside: true};
    if (near.has(name)) return {inside: false, screened: true};
    return {inside: false};
  },
  refused(v) { return v.inside === true || v.screened === true; },
};
const expectedClear = expectedWaypoints.filter(w => !inside.has(w.name) && !near.has(w.name));
const expectedRefused = expectedWaypoints.filter(w => inside.has(w.name) || near.has(w.name))
  .map(waypoint => ({waypoint, reason: inside.has(waypoint.name) ? 'inside' : 'near'}));

// Keep each scenario independent, while passing the real outputs between stages.
function readFixture() {
  const result = readGpxWaypoints(xml);
  assert.equal(result.ok, true);
  return result;
}

test('C1: the fixture is a compact synthetic GPX 1.1 lattice with one track segment', () => {
  // The decoded objects cannot detect loss of coordinate precision, the warning, or track nesting.
  assert.ok(Buffer.byteLength(xml) < 64 * 1024);
  assert.match(xml, /^<\?xml[^?]*\?>\s*<!--[^>]*Synthetic[^>]*not real marks[^>]*-->\s*<gpx version="1\.1" creator="[^"]+" xmlns="http:\/\/www\.topografix\.com\/GPX\/1\/1">/u);
  const tags = [...xml.matchAll(/<wpt\b[^>]*>/gu)].map(([tag]) => tag);
  assert.deepEqual(tags, expectedWaypoints.map(w => `<wpt lat="${w.lat.toFixed(5)}" lon="${w.lon.toFixed(5)}">`));
  assert.equal(new Set(tags).size, 150);
  assert.equal((xml.match(/<desc\b/gu) ?? []).length, 10);
  assert.deepEqual(xml.match(/<\/?(?:trk|trkseg)\b[^>]*>/gu), ['<trk>', '<trkseg>', '</trkseg>', '</trk>']);
  const segment = xml.match(/<trk>\s*<trkseg>([\s\S]*?)<\/trkseg>\s*<\/trk>/u);
  assert.equal((segment?.[1].match(/<trkpt\b/gu) ?? []).length, 12);
  assert.equal((xml.match(/<trkpt\b/gu) ?? []).length, 12);
});

test('C2: the reader keeps every mark and note, not the track points', () => {
  // An accidental import cap, sort, or promotion of track points changes the whole result.
  const result = readFixture();
  assert.deepEqual(result, {ok: true, waypoints: expectedWaypoints, rejected: [], ignoredTrackPoints: 12});
  assert.deepEqual({
    read: result.waypoints.length,
    notes: result.waypoints.filter(w => w.note !== null).length,
    rejected: result.rejected.length,
    ignoredTrackPoints: result.ignoredTrackPoints,
  }, {read: 150, notes: 10, rejected: 0, ignoredTrackPoints: 12});
  assert.deepEqual([result.waypoints[0], result.waypoints[74], result.waypoints[149]], [
    {name: 'M001', lat: 35.2, lon: -121.2, note: null},
    {name: 'M075', lat: 35.34, lon: -121.1, note: 'Synthetic note for M075'},
    {name: 'M150', lat: 35.48, lon: -121.02, note: 'Synthetic note for M150'},
  ]);
});

test('C3: fresh screening keeps clear marks in file order and reports both refusal reasons', () => {
  // Treating screened-but-outside points as clear, or grouping refusals by reason, loses the required split or order.
  const result = screenGpxCandidates(readFixture().waypoints, screen, now);
  assert.deepEqual(result, {ok: true, clear: expectedClear, refused: expectedRefused});
  assert.deepEqual({
    clear: result.clear.length,
    refused: result.refused.length,
    inside: result.refused.filter(w => w.reason === 'inside').length,
    near: result.refused.filter(w => w.reason === 'near').length,
  }, {clear: 128, refused: 22, inside: 14, near: 8});
});

test('C3: a 37-hour-old screen refuses the entire file', () => {
  // A stale screen must not return even a partial clear list for a large batch.
  assert.deepEqual(screenGpxCandidates(readFixture().waypoints, {...screen, checkedAt: now - 37 * hour}, now),
    {ok: false, error: 'screen-stale'});
});

test('C4: planning the screened file separates three rounded duplicates in file order', () => {
  // Extra precision rules out exact-coordinate matching. Existing spot order differs from file order.
  const existing = [
    {lat: 35.480001, lon: -121.020001}, // M150
    {lat: 35.200001, lon: -121.200001}, // M001
    {lat: 35.340001, lon: -121.100001}, // M075
  ];
  const duplicateNames = new Set(['M001', 'M075', 'M150']);
  const screened = screenGpxCandidates(readFixture().waypoints, screen, now);
  assert.equal(screened.ok, true);
  const plan = planGpxImport(existing, screened.clear);
  assert.deepEqual(plan, {
    save: expectedClear.filter(w => !duplicateNames.has(w.name)),
    duplicates: expectedClear.filter(w => duplicateNames.has(w.name)),
    invalid: [],
  });
  assert.deepEqual([plan.save.length, plan.duplicates.length, plan.invalid.length], [125, 3, 0]);
});

test('C4: the same GPX padded one byte over the cap is refused', () => {
  // Trailing XML whitespace must count toward the size limit, not be trimmed first.
  const oversized = xml + ' '.repeat(MAX_GPX_BYTES - Buffer.byteLength(xml) + 1);
  assert.deepEqual(readGpxWaypoints(oversized), {
    ok: false, error: {code: 'file-too-large', message: 'The GPX text is larger than the 1 MiB limit.'},
  });
});
