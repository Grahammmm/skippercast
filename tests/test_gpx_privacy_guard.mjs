import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {posix} from 'node:path';
import {test} from 'node:test';

const paths = [
  'web/gpx-waypoints.ts',
  'web/gpx-import-plan.ts',
  'web/gpx-import-preview.ts',
  'web/gpx-import-screen.ts',
  'web/gpx-check.ts',
];
const forbiddenModules = new Set(['web/telemetry', 'server/analytics', 'web/private-map-log']);

// Check direct source spellings, including calls and imports split across lines.
// The runtime case covers side effects reached indirectly on the confirmed path.
const gap = String.raw`(?:\s|/\*[\s\S]*?\*/|//[^\r\n]*)*`;
const calls = [
  ['no console method calls', new RegExp(String.raw`\bconsole${gap}\??\.${gap}[$\w]+${gap}(?:\?\.${gap})?\(`, 'g')],
  ['no sendBeacon', /\bsendBeacon\b/g],
  ['no direct fetch calls', new RegExp(String.raw`(?<![\w$])fetch${gap}(?:\?\.${gap})?\(`, 'g')],
];
const imports = new RegExp(String.raw`\b(?:from${gap}|import${gap}(?:\(${gap})?)(['"\x60])([^'"\x60\r\n]+)\1`, 'g');

test('C4: the checked-out GPX sources must pass the guard unchanged', async t => {
  const sources = new Map();
  await t.test('C1: read the five named modules without discovery', () => {
    for (const file of paths) {
      assert.doesNotThrow(() => {
        sources.set(file, readFileSync(new URL(`../${file}`, import.meta.url), 'utf8'));
      }, `${file}:1: required GPX source must be readable`);
    }
  });
  await t.test('C2: reject logging, network calls and private-reporting imports', () => {
    const violations = [];
    for (const [file, source] of sources) {
      const report = (index, rule) => {
        const line = source.slice(0, index).split(/\r\n|\r|\n/).length;
        violations.push(`${file}:${line}: ${rule}`);
      };
      for (const [rule, pattern] of calls) {
        for (const match of source.matchAll(pattern)) report(match.index, rule);
      }
      for (const match of source.matchAll(imports)) {
        const specifier = match[2];
        const target = specifier.startsWith('.') ? posix.join(posix.dirname(file), specifier) : specifier;
        if (forbiddenModules.has(target.replace(/[?#].*$/, '').replace(/\.(?:[tj]s)$/, ''))) {
          report(match.index, `no import of ${target}`);
        }
      }
    }
    assert.deepEqual(violations, [], violations.join('\n'));
  });
});

test('C3: a confirmed import keeps its private note only at the owner save', async t => {
  const consoleCalls = [], networkCalls = [];
  for (const method of Object.keys(console).filter(key => typeof console[key] === 'function')) {
    t.mock.method(console, method, () => { consoleCalls.push(method); });
  }
  t.mock.method(globalThis, 'fetch', async () => {
    networkCalls.push('fetch');
    throw new Error('GPX privacy fixture is offline');
  });
  t.mock.getter(globalThis, 'navigator', () => ({
    sendBeacon() { networkCalls.push('sendBeacon'); return false; },
  }));

  const {exportSpots} = await import('../dist/account.js');
  const {placeRefused, screenPlace} = await import('../dist/geo-screen.js');
  const {saveSequentially} = await import('../web/gpx-import-plan.ts');
  const {gpxImportPreview} = await import('../web/gpx-import-preview.ts');
  const {screenGpxCandidates} = await import('../web/gpx-import-screen.ts');
  const {readGpxWaypoints} = await import('../web/gpx-waypoints.ts');

  const now = new Date('2025-06-15T12:00:00Z');
  const {note, ...publicWaypoint} = {
    name: 'Synthetic plotter mark', lat: 35.125, lon: -121.625, note: 'PRIVATE-GPX-NOTE-7D2A9C41',
  };
  const waypoint = {...publicWaypoint, note};
  const input = `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Synthetic chartplotter" xmlns="http://www.topografix.com/GPX/1/1">
  <wpt lat="35.125" lon="-121.625"><name>Synthetic plotter mark</name><desc>${note}</desc></wpt>
</gpx>`;
  const screen = {ready: () => true, pointAllowed: () => true};
  const region = {id: 'synthetic', mpa: {bounds: [-122, 35, -121, 36]}};

  const read = readGpxWaypoints(input);
  assert.deepEqual(read, {ok: true, waypoints: [waypoint], rejected: [], ignoredTrackPoints: 0});
  const screened = screenGpxCandidates(read.waypoints, {
    checkedAt: now.getTime(), verdict: place => screenPlace(screen, place), refused: placeRefused,
  }, now.getTime());
  assert.deepEqual(screened, {ok: true, clear: [waypoint], refused: []});
  const preview = gpxImportPreview(read, screened, []);
  assert.deepEqual(preview, {ok: true, save: [waypoint], counts: {
    read: 1, routePoints: 0, invalidPoints: 0, trackPoints: 0,
    refusedInside: 0, refusedNear: 0, refusedUnchecked: 0, duplicates: 0,
    invalid: 0, overCapacity: 0, save: 1,
  }});

  const saved = [], id = 'fixture-spot-1';
  const report = await saveSequentially(preview.save, async mark => { saved.push({...mark, id}); });
  assert.deepEqual(report, {saved: 1, failed: []});
  assert.deepEqual(saved, [{...waypoint, id}]);

  const {gpx, ...counts} = await exportSpots(saved, screen, region, now);
  assert.deepEqual(counts, {exported: 1, withheld: 0});
  assert.equal(gpx.includes(note), false, 'the private note marker must be absent from the entire GPX');
  // The exporter adds its own advisory description; compare only the public fields.
  const exported = readGpxWaypoints(gpx);
  assert.deepEqual({...exported, waypoints: exported.waypoints?.map(({name, lat, lon}) => ({name, lat, lon}))}, {
    ok: true, waypoints: [publicWaypoint], rejected: [], ignoredTrackPoints: 0,
  });
  assert.deepEqual(consoleCalls, [], 'no console calls during import or export');
  assert.deepEqual(networkCalls, [], 'no network calls during import or export');
});
