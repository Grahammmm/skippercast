// SCA-203 / F13-03: synthetic inputs at the Chart's real ranking boundary.
import assert from 'node:assert/strict';
import test from 'node:test';
import {beachHealthCheck, nextShoreChange} from '../web/brief/shore.ts';
import {prepareCatalogue} from '../web/i18n.ts';
import {copyText} from '../web/mark-copy.ts';
import {shownRuns} from '../web/map/shore.ts';

await prepareCatalogue('es'); // Loads the local catalogue; do not measure English fallback.

const hour = 3_600_000;
const boundary = Date.parse('2026-01-01T03:00:00Z');
const iso = ms => new Date(ms).toISOString();
// Coverage comes from the region/area, not from the presence of the feed or a
// notice row. Use a covered area ID from the county binding, and one outside it.
const covered = {region: 'morro-bay', areaId: 'central'};

const county = (fetchedAt, outcome = 'ok') => ({id: 'slo-beach-water-quality', fetchedAt: iso(fetchedAt), outcome});
const beach = status => ({areaId: covered.areaId, name: 'Fixture Beach', status, url: 'https://example.invalid/beach'});
const closure = county(boundary - 3 * hour);
const report = ({areaId}, source, waterQuality = []) => ({
  alerts: [], sources: [{id: 'nws-alerts', outcome: 'ok', fetchedAt: iso(boundary - hour)}, ...(source ? [source] : [])],
  nearshore: [{areaId, availability: 'available', freshness: 'current', fetchedAt: iso(boundary - hour), issuedAt: iso(boundary - hour)}],
  waterQuality,
});
const lastClosed = report(covered, closure, [beach('Closed')]);

function observe(area, data, now) {
  const run = {geometry: {type: 'MultiLineString', coordinates: []}, properties: {
    ...area, name: 'Fixture Run', reviewExpiresAt: iso(boundary + hour), access: [],
  }};
  const [shown] = shownRuns({regionId: area.region, features: [run]}, {status: 'ready', boundaries: []}, data, now);
  assert.ok(shown, 'the run is visible independently of county confirmation');
  const spanish = shown.copy ? copyText(shown.copy.reasons, 'es') : '';
  return {...shown.status, spanish};
}

const notice = 'Beach-health notice: Fixture Beach';

test('covered: a fresh closure is confirmed just before its three-hour boundary', () => {
  assert.equal(nextShoreChange(lastClosed, boundary - 1), boundary, 'the county check is the next change');
  const {label, priority, reasons, spanish} = observe(covered, lastClosed, boundary - 1);
  assert.deepEqual({label, priority, reasons}, {label: 'Hold', priority: 0, reasons: [notice]});
  assert.match(spanish, /aviso.*Fixture Beach/i, 'the confirmed notice reaches the Spanish catalogue');
});

test('covered: a fresh clean result can clear the preceding hold', () => {
  const clean = report(covered, county(boundary), [beach('Beach Open')]);
  assert.equal(beachHealthCheck(clean, covered.region, covered.areaId, boundary).beachCheck, 'clear');
  const {label, priority} = observe(covered, clean, boundary);
  assert.deepEqual({label, priority}, {label: 'Current', priority: 3});
});

test('unsupported: the county binding is specific to both region and area', () => {
  for (const area of [{...covered, areaId: 'fixture-outside-area'}, {...covered, region: 'fixture-outside-county'}]) {
    // Even a notice with the same area ID from another region must not apply.
    const data = report(area, county(boundary), [beach('Closed')]);
    assert.equal(beachHealthCheck(data, area.region, area.areaId, boundary).beachCheck, 'unsupported');
    const {label, priority} = observe(area, data, boundary);
    assert.deepEqual({label, priority}, {label: 'Current', priority: 3});
  }
});

// Expected for a covered run: no confirmation of the old closure, but a hold
// with a county-check unavailable reason (in both languages), not a reopening.
// A failed poll emits an error source and no rows; it follows the same prior
// confirmed closure as the expiry case but is not a new clean result.
for (const [scenario, data] of [
  ['the same closed reading expires exactly at three hours', lastClosed],
  ['the next county poll fails and returns no rows', report(covered, county(boundary, 'error'))],
  ['the report has no county source', report(covered, null)],
  ['the report has no county readings array', {...report(covered, county(boundary)), waterQuality: undefined}],
  ['the county timestamp is too far in the future', report(covered, county(boundary + 5 * 60_000 + 1), [beach('Closed')])],
]) {
  test(`covered / unavailable: ${scenario}`, () => {
    const {label, priority, reasons, spanish} = observe(covered, data, boundary);
    assert.ok(!reasons.includes(notice), 'do not present the old closure as confirmed');
    assert.deepEqual({label, priority}, {label: 'Hold', priority: 0}, 'loss of confirmation must not promote the run');
    assert.match(reasons.join(' '), /county.*water-quality check unavailable/i);
    assert.match(spanish, /no está disponible.*calidad del agua.*condado/i);
    assert.doesNotMatch(spanish, /Fixture Beach/i, 'do not present the old closure as confirmed in Spanish');
  });
}
