import assert from 'node:assert/strict';
import test from 'node:test';
import {pastDayMode} from '../web/past-day-mode.ts';

const choices = [
  {kind: 'today'},
  {kind: 'past', offset: 1, day: '2026-04-01', weekday: 'Wed'},
  {kind: 'unshown', offset: 2, day: '2026-03-31', reason: 'not-observed'},
];
const notObserved = {day: 'none', date: '2026-03-31', hourPicker: false, reason: 'not-observed'};

// C1 catches extra or missing result fields; C2 catches reversed refusal precedence,
// re-enabled hours on past days, and chips shown without both history and connectivity.
for (const [o, ...expected] of [
  [{online: true, hasHistory: true},
    {day: 'today', hourPicker: true, chips: true},
    {day: 'past', date: '2026-04-01', hourPicker: false},
    notObserved],
  [{online: true, hasHistory: false},
    {day: 'today', hourPicker: true, chips: false},
    {day: 'none', date: '2026-04-01', hourPicker: false, reason: 'no-history'},
    notObserved],
  [{online: false, hasHistory: true},
    {day: 'today', hourPicker: true, chips: false},
    {day: 'none', date: '2026-04-01', hourPicker: false, reason: 'not-saved-offline'},
    notObserved],
  [{online: false, hasHistory: false},
    {day: 'today', hourPicker: true, chips: false},
    {day: 'none', date: '2026-04-01', hourPicker: false, reason: 'no-history'},
    notObserved],
]) {
  for (const [index, choice] of choices.entries()) {
    const contract = choice.kind === 'today' ? 'C1' : 'C2';
    test(`${contract}: ${choice.kind} with online=${o.online}, hasHistory=${o.hasHistory}`, () => {
      assert.deepEqual(pastDayMode(Object.freeze({...choice}), Object.freeze({...o})), expected[index]);
    });
  }
}
