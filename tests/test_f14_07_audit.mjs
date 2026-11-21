// F14-07: an offline-save marker must be a believable time before a report gets the saved allowance.
// Synthetic fixtures only; no network.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {CLOCK_SKEW_MS, OFFLINE_REPORT_LIMIT_MS, admitSnapshot} from '../web/coast-data.ts';

const report = JSON.parse(readFileSync(new URL('./fixtures/coast/report.json', import.meta.url), 'utf8'));
const GENERATED = Date.parse(report.generatedAt);
const HOUR = 3_600_000;
const FOUR_HOURS = GENERATED + 4 * HOUR;
const iso = ms => new Date(ms).toISOString();

test('negative control: future save date does not extend a four-hour-old report', () => {
  assert.equal(admitSnapshot('report', report, null, FOUR_HOURS), 'expired');
  assert.equal(admitSnapshot('report', report, iso(FOUR_HOURS + 24 * HOUR), FOUR_HOURS), 'invalid');
  assert.equal(admitSnapshot('report', report, iso(FOUR_HOURS + CLOCK_SKEW_MS + 1), FOUR_HOURS), 'invalid');
});

test('negative control: a malformed marker is refused, not treated as absent', () => {
  for (const bad of ['', 'not a time', 'yesterday', '2026-13-45']) {
    assert.equal(admitSnapshot('report', report, bad, GENERATED + HOUR), 'invalid', JSON.stringify(bad));
    assert.equal(admitSnapshot('report', report, bad, FOUR_HOURS), 'invalid', JSON.stringify(bad));
  }
});

test('positive control: a valid past save keeps the 24-hour backstop; absent marker keeps three hours', () => {
  const saved = iso(GENERATED + HOUR);
  const ok = admitSnapshot('report', report, saved, FOUR_HOURS);
  assert.equal(ok.savedAt, saved);
  assert.equal(ok.expiresAt, iso(GENERATED + OFFLINE_REPORT_LIMIT_MS));
  assert.equal(admitSnapshot('report', report, saved, GENERATED + OFFLINE_REPORT_LIMIT_MS), 'expired');
  assert.equal(admitSnapshot('report', report, null, GENERATED + HOUR).savedAt, null);
  // Save time within clock skew of now is still believable.
  assert.equal(typeof admitSnapshot('report', report, iso(FOUR_HOURS + CLOCK_SKEW_MS), FOUR_HOURS), 'object');
});
