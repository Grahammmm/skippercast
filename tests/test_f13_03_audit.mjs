// SCA-546 / F13-03: synthetic inputs at the Chart's real ranking boundary.
// Default (including CI): node --test tests/test_f13_03_audit.mjs
// Read-only contract replay: node tests/test_f13_03_audit.mjs --baseline
// The opt-in replay is red until SCA-203 distinguishes unavailable from clear.
import assert from 'node:assert/strict';
import test from 'node:test';
import {nextShoreChange} from '../web/brief/shore.ts';
import {prepareCatalogue} from '../web/i18n.ts';
import {copyText} from '../web/mark-copy.ts';
import {shownRuns} from '../web/map/shore.ts';

await prepareCatalogue('es'); // Loads the local catalogue; do not measure English fallback.
const baseline = process.argv.includes('--baseline');
const hour = 3_600_000;
const boundary = Date.parse('2026-01-01T03:00:00Z');
const iso = ms => new Date(ms).toISOString();
// Coverage comes from the region/area, not from the presence of the feed or a
// notice row. Use a covered area ID from the county binding, and one outside it.
const covered = {region: 'morro-bay', areaId: 'central'};
const unsupported = {region: 'fixture-outside-county', areaId: 'fixture-outside-area'};
const county = (fetchedAt, outcome = 'ok') => ({id: 'slo-beach-water-quality', fetchedAt: iso(fetchedAt), outcome});
const beach = status => ({areaId: covered.areaId, name: 'Fixture Beach', status, url: 'https://example.invalid/beach'});
const closure = county(boundary - 3 * hour);
const report = ({areaId}, source, waterQuality = []) => ({
  alerts: [], sources: [{id: 'nws-alerts', outcome: 'ok', fetchedAt: iso(boundary - hour)}, ...(source ? [source] : [])],
  nearshore: [{areaId, availability: 'available', freshness: 'current', fetchedAt: iso(boundary - hour), issuedAt: iso(boundary - hour)}],
  waterQuality,
});
const lastClosed = report(covered, closure, [beach('Closed')]);

function observe(t, area, data, now) {
  const run = {geometry: {type: 'MultiLineString', coordinates: []}, properties: {
    ...area, name: 'Fixture Run', reviewExpiresAt: iso(boundary + hour), access: [],
  }};
  const [shown] = shownRuns({regionId: area.region, features: [run]}, {status: 'ready', boundaries: []}, data, now);
  assert.ok(shown, 'the run is visible independently of county confirmation');
  const {label, priority, reasons} = shown.status;
  const spanish = shown.copy ? copyText(shown.copy.reasons, 'es') : '';
  if (baseline) t.diagnostic(JSON.stringify({label, priority, reasons, spanish}));
  return {...shown.status, spanish};
}

const notice = 'Beach-health notice: Fixture Beach';

test('covered: a fresh closure is confirmed just before its three-hour boundary', t => {
  assert.equal(nextShoreChange(lastClosed, boundary - 1), boundary, 'the county check is the next change');
  const {label, priority, reasons, spanish} = observe(t, covered, lastClosed, boundary - 1);
  assert.deepEqual({label, priority, reasons}, {label: 'Hold', priority: 0, reasons: [notice]});
  assert.match(spanish, /aviso.*Fixture Beach/i, 'the confirmed notice reaches the Spanish catalogue');
});

test('covered: a fresh clean result can clear the preceding hold', t => {
  const clean = report(covered, county(boundary), [beach('Beach Open')]);
  const {label, priority} = observe(t, covered, clean, boundary);
  assert.deepEqual({label, priority}, {label: 'Current', priority: 3});
});

test('unsupported: no county feed applies; do not hold for a county check', t => {
  const {label, priority} = observe(t, unsupported, report(unsupported, null), boundary);
  assert.deepEqual({label, priority}, {label: 'Current', priority: 3});
});

// Expected for a covered run: no confirmation of the old closure, but a hold
// with a county-check unavailable reason (in both languages), not a reopening.
// A failed poll emits an error source and no rows; it follows the same prior
// confirmed closure as the expiry case but is not a new clean result.
if (baseline) for (const [scenario, data] of [
  ['the same closed reading expires exactly at three hours', lastClosed],
  ['the next county poll fails and returns no rows', report(covered, county(boundary, 'error'))],
]) {
  test(`covered / unavailable: ${scenario}`, t => {
    const {label, priority, reasons, spanish} = observe(t, covered, data, boundary);
    assert.ok(!reasons.includes(notice), 'do not present the old closure as confirmed');
    assert.deepEqual({label, priority}, {label: 'Hold', priority: 0}, 'loss of confirmation must not promote the run');
    assert.match(reasons.join(' '), /county|beach.health|water quality/i, 'identify the check holding the run');
    assert.match(spanish, /condado|playa|calidad del agua/i, 'identify the check in Spanish too');
  });
}
