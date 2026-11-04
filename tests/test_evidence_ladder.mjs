// The evidence ladder (docs/evidence-ladder.md): rungs come only from their own evidence, every claim carries
// rung + count + caveat, and a report polygon never becomes a point.
import test from 'node:test';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {readFileSync} from 'node:fs';
import {RUNGS, CAVEATS, reportClaim, aisClaim, isClaim} from '../server/fleet/evidence-ladder.ts';
import {advisorDatabase, sqliteUnavailable} from './_advisor_d1.mjs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.BUILD_ID = 'build-test';

const {publicClaims} = await import('../server/fleet/display.ts');
const {RUNG_LABELS, claimLine} = await import('../web/fleet.ts');

const POLY = {type: 'Polygon', coordinates: [[[-121, 35], [-120.9, 35], [-120.9, 35.1], [-121, 35]]]};
const POINT_KEYS = /"(lat|lon|lng|latitude|longitude|centroid|point|hotspot|heat|position)"|"type":"Point"/i;
const wire = c => JSON.parse(JSON.stringify(c));

test('one report is named-report; several from one source are still one voice', () => {
  assert.equal(reportClaim([{source: 'A'}]).rung, 'named-report');
  const same = reportClaim([{source: 'Syndicate'}, {source: ' syndicate '}, {source: 'SYNDICATE'}]);
  assert.equal(same.rung, 'named-report');
  assert.equal(same.count, 1);
});

test('two independent reports are repeated-report with that count', () => {
  const c = reportClaim([{source: 'A'}, {source: 'B'}, {source: 'A'}]);
  assert.equal(c.rung, 'repeated-report');
  assert.equal(c.count, 2);
});

test('zero evidence makes no claim; an unnamed report is no evidence', () => {
  assert.equal(reportClaim([]), null);
  assert.equal(reportClaim([{source: ''}, {source: '  '}, {}]), null);
  assert.equal(aisClaim([], true), null);
});

test('an AIS linger just under the threshold is no claim, at it is one', () => {
  assert.equal(aisClaim([{dwellMin: 14.99, thresholdMin: 15}], true), null);
  const c = aisClaim([{dwellMin: 15, thresholdMin: 15}, {dwellMin: 40, thresholdMin: 15}, {dwellMin: 5, thresholdMin: 15}], false);
  assert.equal(c.rung, 'ais-linger');
  assert.equal(c.count, 2);
  assert.equal(aisClaim([{dwellMin: NaN, thresholdMin: 15}, {dwellMin: 99, thresholdMin: NaN}], true), null);
});

test('only a confirmed identity reaches the verified rung; anything else stays lower', () => {
  const l = [{dwellMin: 30, thresholdMin: 15}];
  assert.equal(aisClaim(l, true).rung, 'ais-linger-verified');
  assert.equal(aisClaim(l, false).rung, 'ais-linger');
  assert.equal(aisClaim(l, 'yes').rung, 'ais-linger');
  assert.equal(aisClaim(l, undefined).rung, 'ais-linger');
});

test('every rung has a caveat on every claim; AIS names its weakness', () => {
  for (const r of RUNGS) assert.ok(CAVEATS[r].length > 40, r);
  const claims = [reportClaim([{source: 'A'}]), reportClaim([{source: 'A'}, {source: 'B'}]),
    aisClaim([{dwellMin: 20, thresholdMin: 15}], false), aisClaim([{dwellMin: 20, thresholdMin: 15}], true)];
  assert.deepEqual(claims.map(c => c.rung), [...RUNGS]);
  for (const c of claims) {
    assert.ok(isClaim(c));
    assert.ok(c.count >= 1 && c.caveat === CAVEATS[c.rung]);
    assert.ok(RUNG_LABELS[c.rung], 'web label for ' + c.rung);
    assert.match(claimLine(c), /evidence/);
  }
  assert.match(CAVEATS['ais-linger-verified'], /apparent fishing effort/i);
  assert.match(CAVEATS['ais-linger-verified'], /small vessels/);
});

test('a rung cannot be set by hand', () => {
  const c = reportClaim([{source: 'A'}]);
  assert.throws(() => { 'use strict'; c.rung = 'ais-linger-verified'; }, TypeError);
  assert.equal(isClaim({rung: 'ais-linger-verified', count: 1, caveat: CAVEATS['ais-linger-verified'], areas: []}), false);
  assert.equal(claimLine({rung: 'made-up', count: 1, caveat: 'x'}), null);
  assert.equal(claimLine({rung: 'named-report', count: 0, caveat: 'x'}), null);
});

test('a report polygon stays a polygon: no point, centroid or coordinate-shaped value on the wire', () => {
  const c = reportClaim([{source: 'A', area: POLY}, {source: 'B', area: {type: 'Point', coordinates: [-121, 35]}}, {source: 'C', area: {lat: 35, lon: -121}}]);
  const out = wire(c);
  assert.deepEqual(Object.keys(out).sort(), ['areas', 'caveat', 'count', 'rung']);
  assert.equal(out.areas.length, 1);
  assert.equal(out.areas[0].type, 'Polygon');
  assert.deepEqual(out.areas[0].coordinates, POLY.coordinates);
  assert.doesNotMatch(JSON.stringify(out), POINT_KEYS);
  const viaPublic = JSON.stringify(publicClaims([c]));
  assert.doesNotMatch(viaPublic, POINT_KEYS);
  assert.equal(JSON.parse(viaPublic)[0].areas[0].type, 'Polygon');
  // The caller's polygon is copied, not shared.
  POLY.coordinates[0][0][0] = -1;
  assert.equal(out.areas[0].coordinates[0][0][0], -121);
  POLY.coordinates[0][0][0] = -121;
});

test('a report without an area, or with only a point, carries no geometry at all', () => {
  for (const area of [undefined, null, {type: 'Point', coordinates: [1, 2]}, {type: 'Polygon'}, 'POINT(1 2)']) {
    const out = wire(reportClaim([{source: 'A', area}]));
    assert.deepEqual(out.areas, []);
    assert.doesNotMatch(JSON.stringify(out), POINT_KEYS);
  }
  assert.deepEqual(wire(aisClaim([{dwellMin: 30, thresholdMin: 15}], true)).areas, []);
});

test('publicClaims drops AIS rungs and keeps only the four fields', () => {
  const claims = [reportClaim([{source: 'A'}]), aisClaim([{dwellMin: 30, thresholdMin: 15}], true)];
  const shown = publicClaims(claims);
  assert.deepEqual(shown.map(c => c.rung), ['named-report']);
  assert.deepEqual(publicClaims([claims[1]]), []);
});

// ---- activityClaims against the real migrations ------------------------------------------
const sha = s => createHash('sha256').update(s, 'utf8').digest('hex').slice(0, 32);
const skip = sqliteUnavailable ?? false;
const NOW = '2026-10-05T12:00:00.000Z', REGION = 'CA', VESSEL = sha('CA:ev-boat'), MMSI = '999000201';

async function seeded({docs = 'doc-1', mmsi = MMSI, tripMmsi = MMSI, dwell = [40], reports = []} = {}) {
  const {sql, db} = advisorDatabase();
  sql.prepare(`INSERT INTO fleet_vessels(id,region,slug,name,name_norm,mmsi,uscg_doc,first_seen_at,last_seen_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)`)
    .run(VESSEL, REGION, 'ev-boat', 'Ev Boat', 'EVBOAT', mmsi, docs, NOW, NOW, NOW, NOW);
  const tripId = sha('trip');
  sql.prepare(`INSERT INTO fleet_trips(id,region,vessel_id,mmsi,departed_at,local_date,season,status,source,rights,classifier_version,computed_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)`)
    .run(tripId, REGION, VESSEL, tripMmsi, '2026-10-01T08:00:00.000Z', '2026-10-01', '2026', 'closed', 'aisstream', 'internal-only', 'c1', NOW);
  sql.prepare(`INSERT INTO fleet_segments(id,trip_id,seq,kind,started_at,ended_at) VALUES(?,?,?,?,?,?)`).run(sha('seg'), tripId, 0, 'drift-anchor', NOW, NOW);
  dwell.forEach((d, i) => sql.prepare(`INSERT INTO fleet_events(id,trip_id,segment_id,vessel_id,region,kind,lat,lon,started_at,ended_at,dwell_min,season,basis,source,rights,classifier_version) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`)
    .run(sha('ev' + i), tripId, sha('seg'), VESSEL, REGION, 'drift-anchor', 35.3, -120.9, NOW + i, NOW, d, '2026', 'inferred-from-movement', 'aisstream', 'internal-only', 'c1'));
  reports.forEach(([kind, ref, source]) => {
    if (source) sql.prepare(`INSERT INTO advisor_reports(id,boat_id,region,port,report_date,counts_json,source,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)`)
      .run(ref, 'boat-' + ref, REGION, 'p', '2026-10-01', '{}', source, 'published', NOW, NOW);
    sql.prepare(`INSERT INTO fleet_trip_reports(trip_id,report_kind,report_ref,match,confidence,created_at) VALUES(?,?,?,?,?,?)`).run(tripId, kind, ref, 'boat-date', 0.9, NOW);
  });
  return {sql, db};
}
const TH = {'drift-anchor': 15};

test('activityClaims: every claim has rung, count, caveat, and the wire holds no coordinate', {skip}, async () => {
  const {activityClaims} = await import('../server/fleet/activity.ts');
  const {sql, db} = await seeded({reports: [['advisor', 'r1', 'feed-x'], ['advisor', 'r2', 'feed-x'], ['landing', 'l1', null]]});
  try {
    const claims = await activityClaims(db, REGION, VESSEL, TH);
    assert.deepEqual(claims.map(c => c.rung), ['repeated-report', 'ais-linger-verified']);
    for (const c of claims) assert.ok(isClaim(c) && c.count >= 1 && c.caveat);
    assert.equal(claims[0].count, 2); // feed-x counted once, plus the landing feed
    const text = JSON.stringify(claims);
    assert.doesNotMatch(text, POINT_KEYS);
    assert.doesNotMatch(text, /35\.3|-120\.9/);
  } finally { sql.close(); }
});

test('activityClaims: syndicated reports stay named-report; unconfirmed identity stays ais-linger', {skip}, async () => {
  const {activityClaims} = await import('../server/fleet/activity.ts');
  for (const [opts, rungs] of [
    [{reports: [['advisor', 'r1', 'feed-x'], ['advisor', 'r2', 'feed-x']], docs: null}, ['named-report', 'ais-linger']],
    [{tripMmsi: '999000999'}, ['ais-linger']],
    [{dwell: [14]}, []],
    [{dwell: [14, 15], reports: [['advisor', 'r1', 'feed-y']]}, ['named-report', 'ais-linger-verified']],
  ]) {
    const {sql, db} = await seeded(opts);
    try { assert.deepEqual((await activityClaims(db, REGION, VESSEL, TH)).map(c => c.rung), rungs, JSON.stringify(opts)); } finally { sql.close(); }
  }
});

test('activityClaims: no evidence is no claims, and an unthresholded event kind is ignored', {skip}, async () => {
  const {activityClaims} = await import('../server/fleet/activity.ts');
  const {sql, db} = await seeded({dwell: []});
  try { assert.deepEqual(await activityClaims(db, REGION, VESSEL, TH), []); } finally { sql.close(); }
  const second = await seeded({dwell: [99]});
  try { assert.deepEqual(await activityClaims(second.db, REGION, VESSEL, {}), []); } finally { second.sql.close(); }
});
