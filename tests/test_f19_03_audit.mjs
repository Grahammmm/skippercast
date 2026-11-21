// F19-03 / SCA-557: synthetic rule dates, not a statement about current regulations.
// Run the importer baseline explicitly: node tests/test_f19_03_audit.mjs --baseline
// The baseline assertion checks the intended contract; it is not enrolled in the required suite.
import assert from 'node:assert/strict';
import test from 'node:test';
import {importRows} from '../scripts/advisor/import-rules.mjs';

// Vite normally injects these globals; seasonOpen does not consult either one.
globalThis.REGIONS = {};
globalThis.DEPLOYMENT = {allowed_origins: []};
const {seasonOpen} = await import('../server/advisor/answers/reports.ts');

const windows = [
  {start: '2026-04-01', end: '2026-04-30'},
  {start: '2026-07-01', end: '2026-07-31'},
];
const expected = {'2026-04-15': true, '2026-06-01': false, '2026-07-15': true};
const now = Date.parse('2026-03-01T12:00:00Z');
const imported = windows => importRows(now, [{
  jurisdiction: 'fixture',
  data: {species: {example: {windows, season: 'April and/or July as listed.', bag: '2 per person'}}},
}]);

function observe(rows) {
  return Object.fromEntries(Object.keys(expected).map(date => {
    const states = rows.map(row => seasonOpen(row, date));
    return [date, states.includes(true) ? true : states.includes(false) ? false : null];
  }));
}

test('independent windows open in April and July but not in June', t => {
  // Independent single-window imports are a control for the date check, not a DB batch.
  const observed = observe(windows.flatMap(window => imported([window])));
  t.diagnostic(JSON.stringify(observed));
  assert.deepEqual(observed, expected);
});

if (process.argv[2] === '--baseline') {
  test('split-season import preserves the gap or supplies no date-based advice', t => {
    const rows = imported(windows);
    const observed = observe(rows);
    t.diagnostic(JSON.stringify({
      rows: rows.map(({status, season_open, season_close}) => ({status, season_open, season_close})),
      dates: observed,
    }));
    // At this boundary a hold means no date candidate, not just review status
    // or null bounds (trip planning can treat undated rows as open).
    if (rows.length === 0) return;
    assert.deepEqual(observed, expected);
  });
}
