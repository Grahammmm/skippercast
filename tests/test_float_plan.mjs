// SC1407-14: the optional float plan in the offline notes. The fields exist only in the open dialog (web/planner.ts memory) and reach
// nothing but the English notes file: pure checks (web/float-plan.ts), the notes section (dist/trip-export.js) and the planner's lifetime.
import test from 'node:test';
import assert from 'node:assert/strict';
import {isDeepStrictEqual} from 'node:util';

const {createPlanner} = await import('../web/planner.ts');
const {draftKey, offlineNotes, floatPlanSection} = await import('../dist/trip-export.js');
const {emptyFloatPlan, seedFloatPlan, validateFloatPlan, boatLine} = await import('../web/float-plan.ts');
const {entranceFor} = await import('../packages/coast/src/bar-conditions.ts');

const NOW = new Date('2026-10-12T18:00:00Z');
const REGION = {id: 'test-coast', name: 'Test Coast', timezone: 'America/Los_Angeles', mpa: {bounds: [-10, -10, 10, 10]}, regulations_url: 'https://example.org/rules'};
const ZONE = REGION.timezone;
const SCREEN = {ready: () => true, pointAllowed: () => true, geometryAllowed: () => true, exportExclusions: () => ({features: [], checked_at: NOW.toISOString()})};
const MAP = {getSize: () => ({x: 512, y: 512}), getBounds: () => ({getWest: () => -1, getEast: () => 1, getNorth: () => 1, getSouth: () => -1, contains: () => true})};
const ring = (x, y, w = 0.002) => [[x, y], [x + w, y], [x + w, y + w], [x, y + w], [x, y]];
const ATLAS = {targets: [{id: 'old-1', name: 'Old 1', label: 'Old 1', latitude: 0.5, longitude: 0.5, habitat_grade: 'B', center_depth_ft: 80, neighborhood_depth_ft: [70, 90]}], areas: [], drifts: []};
function reefs() {
  const targets = [0, 1].map(i => ({id: `reef-${i}`, label: `Reef ${i}`, canonical_habitat: true, latitude: 0.01 * i, longitude: 0.01 * i, habitat_grade: 'A', habitat_score: 90 - i,
    neighborhood_depth_ft: [90, 120], resolution_m: 2, evidence_confidence: {percent: 90}, species_fit: {lingcod: 3, 'rockfish-reef': 3}, area_ids: [`area-${i}`],
    terrain_interpretation: 'Raised structure', source_url: 'https://example.org/s', evidence_status: 'Fish presence unverified.'}));
  const areas = targets.map((t, i) => ({id: `area-${i}`, target_ids: [t.id], geometry: {type: 'Polygon', coordinates: [ring(t.longitude, t.latitude)]}}));
  return {targets, areas, publication: {export_sha256: 'a'.repeat(64), status: 'ready', expires_at: '2099-12-31T00:00:00Z', region: 'test-coast'}, source_validation_date: '2026-10-01'};
}
function harness(extra = {}) {
  const store = new Map();
  const storage = {getItem: k => store.get(k) ?? null, setItem: (k, v) => { store.set(k, v); }};
  const planner = createPlanner({atlas: ATLAS, screen: SCREEN, region: REGION, map: MAP, getVisible: () => [], storage, now: () => NOW, landWater: async () => () => ({state: 'water'}),
    loadReefs: async () => reefs(), loadPorts: async () => ({ports: []}), emit: () => {}, nav: {open() {}, showMap() {}, conditions() {}}, ...extra});
  return {planner, store};
}
const notesOf = async p => (await p.exportFile('notes')).text();
const noClock = gpx => gpx.replace(/<time>[^<]*<\/time>/g, '');

const FULL = {boat: 'Sea <b>Wolf</b> · 24 ft', people: '3', departure: '07:00', backBy: '15:30', overdue: 'Call the harbor patrol & Sam\n"555-0100" {x}'};

test('float_notes_all_fields: the section, caveat, zone and escaping', () => {
  const check = validateFloatPlan(FULL, '2026-10-12', ZONE);
  assert.equal(check.ok, true);
  const html = floatPlanSection(check.record);
  assert.match(html, /^<section><h2>Float plan<\/h2>/);
  assert.ok(html.includes('<dt>Boat</dt><dd>Sea &lt;b&gt;Wolf&lt;/b&gt; · 24 ft</dd>'), html);
  assert.ok(html.includes('<dt>People aboard</dt><dd>3</dd>'));
  assert.ok(html.includes('<dt>Departure</dt><dd>2026-10-12 07:00 America/Los_Angeles (UTC-07:00)</dd>'));
  assert.ok(html.includes('<dt>Be back by</dt><dd>2026-10-12 15:30 America/Los_Angeles (UTC-07:00)</dd>'));
  assert.ok(html.includes('Call the harbor patrol &amp; Sam\n'), 'newlines stay plain text');
  assert.ok(!html.includes('<b>'));
  assert.ok(html.includes('Leave this float plan with someone ashore. SkipperCast does not send or file it. These times are the skipper&apos;s own') || html.includes("These times are the skipper's own"));
});

test('float_notes_no_fields: no section and the old bytes, in both notes paths', () => {
  const result = {created_at: 'c', boundary_checked_at: null, counts: {waypoints: 0, tracks: 0}, features: {selected: []}, exclusions: [], layers: {}, avoid_bounds: [0, 0, 0, 0]};
  const draft = {name: 'Plan', date: '2026-10-12'};
  const old = offlineNotes(result, REGION, draft, 'dd');
  for (const blank of [null, undefined, {}, {boat: '', overdue: ''}, validateFloatPlan(emptyFloatPlan(), '2026-10-12', ZONE).record])
    assert.ok(offlineNotes(result, REGION, draft, 'dd', blank) === old, 'identical bytes');
  assert.ok(!old.includes('Float plan'));
  assert.ok(validateFloatPlan({...emptyFloatPlan(), boat: '   ', overdue: '\n'}, '2026-10-12', ZONE).record === null, 'whitespace is absent');
  const withBoat = offlineNotes(result, REGION, draft, 'dd', {boat: 'Mary'});
  assert.ok(withBoat.startsWith(old.slice(0, -'</html>'.length)) && withBoat.includes('<dt>Boat</dt><dd>Mary</dd>') && !withBoat.includes('Departure'));
});

test('float_time_validation: plan date in the region zone, DST, order, limits', () => {
  const bad = (f, date = '2026-10-12') => { const c = validateFloatPlan({...emptyFloatPlan(), ...f}, date, ZONE); return c.ok ? 'ok' : c.errors; };
  const sole = (f, date, field) => bad(f, date)[field];
  assert.equal(sole({departure: '02:30'}, '2026-03-08', 'departure'), 'gap');
  assert.equal(sole({backBy: '01:30'}, '2026-11-01', 'backBy'), 'ambiguous');
  assert.equal(validateFloatPlan({...emptyFloatPlan(), departure: '03:30'}, '2026-03-08', ZONE).record.departure.offset, '-07:00');
  assert.equal(validateFloatPlan({...emptyFloatPlan(), departure: '08:00'}, '2026-11-01', ZONE).record.departure.offset, '-08:00');
  for (const t of ['24:00', '7:00', '07:60', 'noon']) assert.equal(sole({departure: t}, '2026-10-12', 'departure'), 'time', t);
  assert.equal(sole({departure: '07:00'}, '2026-02-30', 'departure'), 'date');
  assert.equal(validateFloatPlan({...emptyFloatPlan(), departure: '07:00'}, '2026-10-12', 'Not/AZone').ok, false);
  assert.equal(sole({departure: '09:00', backBy: '09:00'}, '2026-10-12', 'backBy'), 'order');
  assert.equal(sole({departure: '09:00', backBy: '08:00'}, '2026-10-12', 'backBy'), 'order');
  assert.equal(bad({backBy: '08:00'}), 'ok', 'one time alone is fine');
  for (const p of ['0', '-1', '1.5', '1e2', 'Infinity', '1000', 'x']) assert.equal(sole({people: p}, '2026-10-12', 'people'), 'people', p);
  for (const p of ['1', '999']) assert.equal(bad({people: p}), 'ok', p);
  assert.equal(bad({boat: 'a'.repeat(160), overdue: 'b'.repeat(1000)}), 'ok');
  assert.equal(sole({boat: 'a'.repeat(161)}, '2026-10-12', 'boat'), 'boat-long');
  assert.equal(sole({overdue: 'b'.repeat(1001)}, '2026-10-12', 'overdue'), 'overdue-long');
  assert.ok(!JSON.stringify(bad({boat: 'a'.repeat(161)})).includes('aaaa'), 'no typed text in a reason');
});

const HOUR = 3600000, START = Date.parse('2026-10-12T14:00:00Z');   // 07:00 PDT
const brief = (over = {}) => ({date: '2026-10-12', profile: 'boat', sunrise: null, sunset: null,
  bar: {entrance: entranceFor('morro-bay', 'morro-bay'), hours: ['No bar flag', 'No bar flag', 'No bar flag'].map((band, i) => ({at: new Date(START + i * HOUR).toISOString(), band,
    tide: {stage: 'flood', midEbb: false, fraction: 0.5}, swell: {heightFt: 1, periodS: 10, basis: 'offshore', longPeriodS: null}, windAgainst: false, reasons: []}))}, ...over});
const SHOWN = {id: 'test-coast', timezone: ZONE};
const seed = (over = {}) => seedFloatPlan({boat: {name: 'Mary', loa_ft: 24}, brief: brief(), shown: SHOWN, region: REGION, date: '2026-10-12', ...over});

test('float_prefill: be back by only from the brief for this day, region and a judged window; boat from the saved profile', () => {
  assert.equal(seed().fields.backBy, '10:00', 'the exclusive end of the entrance window, in the region zone');
  assert.equal(seed().fields.boat, 'Mary · 24 ft');
  assert.equal(seed().fields.departure, '', 'departure is the skipper\'s own');
  assert.equal(seed({date: '2026-10-13'}).fields.backBy, '', 'another date');
  assert.equal(seed({brief: brief({bar: null})}).fields.backBy, '', 'no estimate for the region');
  assert.equal(seed({brief: null}).fields.backBy, '');
  assert.equal(seed({shown: {id: 'other', timezone: ZONE}}).fields.backBy, '', 'wrong region');
  assert.equal(seed({brief: brief({profile: 'shore'})}).fields.backBy, '', 'not the Boat brief');
  const hazardous = brief(); hazardous.bar.hours.forEach(h => { h.band = 'Hazardous'; });
  assert.equal(seed({brief: hazardous}).fields.backBy, '', 'no window');
  const late = brief(); late.bar.hours = late.bar.hours.map((h, i) => ({...h, at: new Date(Date.parse('2026-10-13T06:00:00Z') + i * HOUR).toISOString()}));
  assert.equal(seed({brief: late}).fields.backBy, '', 'a window ending on another local date is not guessed');
  assert.equal(seed({boat: null}).fields.boat, '');
  assert.equal(boatLine({name: '', loa_ft: 30}), '30 ft');
  assert.equal(boatLine({name: 'Mary', loa_ft: NaN}), 'Mary');
});

test('float_lifetime_and_privacy: dialog-only, notes-only, absent from draft, storage, GPX and the file key', async () => {
  const {planner: p, store} = harness();
  p.add('old-1'); p.setResearch(true);
  const before = {draft: JSON.stringify(p.draft.value), stored: [...store.entries()].join('|'), gpx: noClock(await (await p.exportFile('gpx')).text())};
  assert.ok(!(await notesOf(p)).includes('Float plan'), 'closed dialog: no section');
  p.editFloatPlan({boat: 'ignored'});
  assert.equal(p.floatPlan.value.boat, '', 'edits before opening do nothing');
  p.setFloatPlanOpen(true, {fields: {...emptyFloatPlan(), boat: 'Mary'}, backAuto: true});
  p.setFloatPlanOpen(true, {fields: {...emptyFloatPlan(), boat: 'Other'}, backAuto: true});
  assert.equal(p.floatPlan.value.boat, 'Mary', 'a repeated open seeds once');
  p.editFloatPlan({people: '4', overdue: 'SENTINEL-OVERDUE-9f3'});
  const notes = await notesOf(p);
  assert.ok(notes.includes('<h2>Float plan</h2>') && notes.includes('SENTINEL-OVERDUE-9f3') && notes.includes('<dd>4</dd>'));
  assert.ok(isDeepStrictEqual(JSON.stringify(p.draft.value), before.draft), 'draft unchanged');
  assert.ok([...store.entries()].join('|') === before.stored && !JSON.stringify([...store.values()]).includes('SENTINEL'), 'nothing stored');
  assert.ok(!JSON.stringify(p.draft.value).includes('float'), 'no float key in the draft');
  const gpx = noClock(await (await p.exportFile('gpx')).text());
  assert.ok(gpx === before.gpx && !gpx.includes('SENTINEL') && !gpx.includes('Mary'), 'GPX bytes unchanged');
  p.setFloatPlanOpen(false);
  assert.deepEqual({...p.floatPlan.value}, emptyFloatPlan(), 'closing wipes the fields');
  p.setFloatPlanOpen(true, {fields: emptyFloatPlan(), backAuto: true});
  assert.ok(!(await notesOf(p)).includes('Float plan'), 'reopened empty: no section');
  p.dispose();
});

test('float_invalid_blocks_notes_only; a deliberate clear is not refilled', async () => {
  const {planner: p} = harness();
  p.add('old-1'); p.setResearch(true);
  p.setFloatPlanOpen(true, {fields: {...emptyFloatPlan(), backBy: '10:00'}, backAuto: true});
  p.reseedFloatBackBy('11:00');
  assert.equal(p.floatPlan.value.backBy, '11:00', 'an untouched automatic value follows a date change');
  p.editFloatPlan({backBy: ''});
  p.reseedFloatBackBy('11:00');
  assert.equal(p.floatPlan.value.backBy, '', 'a cleared box is not refilled');
  p.editFloatPlan({people: '0'});
  await assert.rejects(p.exportFile('notes'), /float plan has a problem/);
  assert.equal((await p.exportFile('gpx')).type, 'application/gpx+xml', 'GPX is not blocked');
  assert.equal(p.summary.value.ok, true);
  p.dispose();
});

test('float_stale_notes: closing, editing or changing the date while the publication loads drops the file', async () => {
  for (const change of [p => p.setFloatPlanOpen(false), p => p.editFloatPlan({boat: 'Changed'}), p => p.edit({date: '2026-10-14'})]) {
    let gate = null;
    const {planner: p} = harness({loadReefs: async () => { if (gate) await gate; return reefs(); }});
    await p.selectBest();
    p.setFloatPlanOpen(true, {fields: {...emptyFloatPlan(), boat: 'Mary'}, backAuto: true});
    let release; gate = new Promise(r => { release = r; });
    const pending = p.exportFile('notes');
    change(p); release();
    await assert.rejects(pending, /float plan changed/);
    p.dispose();
  }
});
