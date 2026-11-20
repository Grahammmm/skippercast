import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const {readiness} = await import('../scripts/report_rights_readiness.mjs');
const {coastFeeds} = await import('../server/coast-data.ts');

// Synthetic registers: no network, no provider data.
const IDS = ['nws-weather', 'ndbc-buoys', 'noaa-tides', 'landing-reports', 'noaa-blended-sst', 'cdfw-mpas'];
const row = (id, review_status = 'approved', commercial_use = 'allowed') => ({id, review_status, rights: {commercial_use}});
const register = (change = {}) => IDS.map(id => id in change ? change[id] : row(id)).filter(r => r !== null);
const fixtures = {
  confirmed: register(),
  restricted: register({'noaa-tides': row('noaa-tides', 'restricted', 'allowed')}),
  candidate: register({'landing-reports': row('landing-reports', 'candidate', 'unknown')}),
  missing: register({'cdfw-mpas': null}),
};

test('all six confirmed: honoured', () => {
  const {lines, honoured} = readiness(fixtures.confirmed);
  assert.equal(lines.length, 8);
  assert.equal(lines.filter(l => l.endsWith('-> confirmed')).length, 6);
  assert.equal(lines[6], 'report would be honoured');
  assert.equal(honoured, true);
});

test('one restricted row drops the report and is named', () => {
  const {lines, honoured} = readiness(fixtures.restricted);
  assert.ok(lines.includes('noaa-tides: restricted, allowed -> refused'));
  assert.ok(lines.includes('report would be dropped because noaa-tides: restricted/allowed'));
  assert.equal(lines.filter(l => l.endsWith('-> confirmed')).length, 5);
  assert.equal(honoured, false);
});

test('a candidate row needs owner confirmation but is not a refusal', () => {
  const {lines, honoured} = readiness(fixtures.candidate);
  assert.ok(lines.includes('landing-reports: candidate, unknown -> needs-owner-confirmation'));
  assert.ok(lines.includes('report would be honoured'));
  assert.equal(honoured, true);
});

test('a row missing from the register is refused and named', () => {
  const {lines, honoured} = readiness(fixtures.missing);
  assert.ok(lines.includes('cdfw-mpas: missing -> refused'));
  assert.ok(lines.includes('report would be dropped because cdfw-mpas: missing'));
  assert.equal(honoured, false);
});

test('output is at most 12 lines, ends with the PR link, and agrees with the Worker', () => {
  for (const [name, f] of Object.entries(fixtures)) {
    const {lines, honoured} = readiness(f);
    assert.ok(lines.length <= 12, name);
    assert.ok(lines.at(-1).includes('/pull/2223'), name);
    assert.equal(honoured, coastFeeds('report', f).has('report'), name);
  }
});

test('the checked-in catalog is honoured today', () => {
  const catalog = JSON.parse(readFileSync(new URL('../catalog/sources.json', import.meta.url), 'utf8'));
  assert.ok(readiness(catalog.sources).lines.includes('report would be honoured'));
});
