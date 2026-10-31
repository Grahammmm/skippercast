// Report dates with an explicit year (server/advisor/intake/reports.ts
// parseDateWords). Only a date typed without a year ("12/30", "dec 30",
// "30 de dic") may be read as last year's across New Year. A date typed with
// a year (YYYY-MM-DD, M/D/YY, M/D/YYYY) is taken as typed, so a future one is
// null (outside the correction window) instead of being saved a year early.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const read = p => JSON.parse(readFileSync(new URL(p, import.meta.url)));
globalThis.REGIONS = {'morro-bay': read('../regions/morro-bay/region.json')};
globalThis.DEPLOYMENT = read('../deployments/production.json');
globalThis.SHELLS = {'/': '/index.0123456789.html'};
globalThis.BUILD_ID = 'build-test';
const {parseDateWords} = await import('../server/advisor/intake/reports.ts');

const JAN2 = '2026-01-02';
const check = (cases, today = JAN2) => {
  for (const [words, want] of Object.entries(cases)) assert.equal(parseDateWords(words, today), want, words);
};

test('an explicit future year is never rolled back to last year', () => {
  check({'12/30/2026': null, '12/30/26': null, '12-30-2026': null, '12-30-26': null});
});

test('an explicit past year inside the window is taken as typed', () => {
  check({'12/30/2025': '2025-12-30', '12/30/25': '2025-12-30', '12-30-2025': '2025-12-30', '1/2/2026': JAN2, '1/2/26': JAN2});
});

test('a date without a year still rolls back across New Year', () => {
  check({'12/30': '2025-12-30', 'dec 30': '2025-12-30', '30 de dic': '2025-12-30', 'on dec 30': '2025-12-30'});
});

test('ISO dates are unchanged: a future one is null, a recent past one kept', () => {
  check({'2026-12-30': null, '2025-12-30': '2025-12-30'});
});

test('the correction window is unchanged for explicit years', () => {
  // 13 days back is outside the default 7-day window; an explicit year a year back is far outside it.
  check({'12/20/2025': null, '12/30/2024': null, '12/30/24': null});
  assert.equal(parseDateWords('12/20/2025', JAN2, 14), '2025-12-20', 'a wider window still reads the typed year');
});

test('invalid dates stay null, with or without a year', () => {
  check({'2/30/2026': null, '2/30/26': null, '13/1/2026': null, '2/30': null, '12/32/2025': null});
});
