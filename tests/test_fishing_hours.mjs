import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fishingHours} from '../web/brief/fishing-hours.ts';
import {planRun} from '../web/brief/run.ts';
import {openingAt, regulationState} from '../web/regs.ts';
import {configureStore, STORAGE_KEYS} from '../web/state.ts';
import {parseWanted, saveWanted, loadWanted, wantedHours, followStoredLimits} from '../web/limits.ts';
const window = {start: '2026-10-12T07:00:00-07:00', end: '2026-10-12T12:00:00-07:00', reasons: []};
const brief = {windows: [window], alerts: [], tiles: [], missing: []};
const run = planRun(brief, {name: 'Synthetic reef', nm: 7.4}, 20, new Date('2026-10-12T05:00:00-07:00'));
const rule = {status: 'open', opensAt: null, label: 'Open', reason: 'Local rules apply.'};
const options = {wantedMin: 240, sunrise: '2026-10-12T06:52:00-07:00', sunset: '2026-10-12T17:21:00-07:00', rule};
const calc = (over = {}, r = run) => fishingHours(r, {...options, ...over});
test('wanted hours compare with transit remainder, conservatively rounded', () => {
  assert.deepEqual(calc(), {kind: 'enough', availableMin: 250, wantedMin: 240, spareMin: 10});
  assert.deepEqual(calc({wantedMin: 300}), {kind: 'short', availableMin: 250, wantedMin: 300, shortMin: 50, endedBy: 'conditions'});
  assert.equal(calc({wantedMin: null}).kind, 'no-wanted');
  assert.equal(calc({}, {...run, turnBack: '2026-10-12T18:34:59Z'}).availableMin, 245);
  assert.equal(calc({}, {...run, kind: 'no-time'}).kind, 'none');
});
test('daylight limiter is the last full hour, not an invented sunset edge', () => {
  const short = {wantedMin: 600};
  assert.equal(calc({...short, sunset: '2026-10-12T12:59:00-07:00'}).kind, 'beyond-daylight');
  assert.equal(calc({wantedMin: 300, sunset: '2026-10-12T12:59:00-07:00'}).endedBy, 'daylight');
  assert.equal(calc({wantedMin: 300, sunset: '2026-10-12T13:00:00-07:00'}).endedBy, 'conditions');
  assert.equal(calc({wantedMin: 300}, {...run, window: {...window, end: '2026-10-12T16:00:00-07:00'}}).endedBy, 'conditions');
  assert.equal(calc({wantedMin: 720}).kind, 'beyond-daylight');
  assert.equal(calc({sunrise: null, wantedMin: 720}).kind, 'short');
  assert.equal(calc({sunset: null, wantedMin: 720}).kind, 'short');
});
test('opening clips arrival only when later; none when opening consumes the window', () => {
  const opensAt = Date.parse('2026-10-12T08:00:01-07:00');
  const clipped = calc({rule: {...rule, opensAt}});
  assert.equal(clipped.availableMin, 210);
  assert.equal(clipped.endedBy, 'opening');
  assert.equal(calc({wantedMin: 300, rule: {...rule, opensAt: Date.parse(run.arrive)}}).endedBy, 'conditions');
  assert.equal(calc({rule: {...rule, opensAt: Date.parse(run.turnBack)}}).kind, 'none');
});
test('closed/excluded override missing wanted and daylight; unknown never yields enough', () => {
  for (const status of ['closed', 'excluded']) assert.deepEqual(calc({wantedMin: null, rule: {...rule, status}}), {kind: 'closed', label: rule.label, reason: rule.reason});
  const result = calc({rule: {...rule, status: 'unknown'}});
  assert.equal(result.kind, 'short'); assert.equal(result.rulesUnconfirmed, true); assert.equal(result.shortMin, 0);
  assert.equal(calc({rule: {...rule, status: 'unknown', opensAt: Date.parse(run.turnBack)}}).rulesUnconfirmed, true);
  for (const status of ['restricted', 'scheduled']) assert.equal(calc({rule: {...rule, status}}).kind, 'enough');
});
test('DST durations use epoch instants, including the repeated and missing hours', () => {
  for (const [arrive, turnBack, minutes] of [
    ['2026-11-01T01:30:00-07:00', '2026-11-01T02:30:00-08:00', 120],
    ['2027-03-14T01:30:00-08:00', '2027-03-14T03:30:00-07:00', 60],
  ]) assert.equal(calc({wantedMin: 60, sunrise: null, sunset: null}, {...run, arrive, turnBack}).availableMin, minutes);
});
const fixture = JSON.parse(readFileSync(new URL('./fixtures/regulations/fe61-v1.json', import.meta.url)));
function registry() {
  const d = structuredClone(fixture.regulations), now = Date.parse('2026-10-12T12:00:00Z');
  d.reviewed_at = new Date(now).toISOString(); d.rules_review_status = 'reviewed';
  for (const [id, s] of Object.entries(d.sources)) {
    s.approved_content_sha256 = 'a'.repeat(64);
    d.checks[id] = {url: s.url, normalization: s.normalization, status: 'unchanged', source_status: 'ok', content_sha256: s.approved_content_sha256, data_retrieved_at: d.reviewed_at};
  }
  for (const [id, hour] of [['lingcod', '06'], ['rockfish', '07']]) d.species[id].windows = [{start: '2026-10-12', end: '2026-10-31', start_at: `2026-10-12T${hour}:00:00-07:00`}];
  return d;
}
test('registry reader guards malformed input, opening date, inherited keys and reef later opening/worse member', () => {
  const d = registry(), r = fixture.region;
  assert.equal(openingAt(d, 'lingcod', r, '2026-10-12'), Date.parse('2026-10-12T06:00:00-07:00'));
  assert.equal(openingAt(d, 'reef', r, '2026-10-12'), Date.parse('2026-10-12T07:00:00-07:00'));
  assert.equal(openingAt(d, 'reef', r, '2026-10-13'), null);
  for (const id of ['constructor', '__proto__', 'missing']) assert.equal(openingAt(d, id, r, '2026-10-12'), null);
  assert.equal(openingAt(null, 'reef', r, '2026-10-12'), null);
  const broken = structuredClone(d); broken.species.rockfish.windows[0].start_at = 'bad';
  assert.equal(openingAt(broken, 'reef', r, '2026-10-12'), null);
  d.species.rockfish.windows = [];
  assert.equal(regulationState(d, 'reef', r, Date.parse(d.reviewed_at), '2026-10-12', null).status, 'closed');
});
test('hours storage has no default, bounds invalid values, reloads across tabs and survives blocked storage', () => {
  const data = new Map();
  configureStore({storage: {getItem: k => data.get(k) ?? null, setItem: (k,v) => data.set(k,v)}});
  assert.equal(loadWanted(), null);
  for (const value of [0, .5, 12.5, 'abc', '', '4,5', NaN]) { assert.equal(parseWanted(value), null); assert.equal(saveWanted(value), null); assert.equal(loadWanted(), null); }
  assert.equal(saveWanted(4), 4); assert.equal(JSON.parse(data.get(STORAGE_KEYS.wanted)).hours, 4);
  let handler, removed = false;
  const stop = followStoredLimits({addEventListener: (_, fn) => handler = fn, removeEventListener: (_, fn) => { removed = fn === handler; }});
  data.set(STORAGE_KEYS.wanted, '{"hours":5}'); handler({key: STORAGE_KEYS.wanted}); assert.equal(wantedHours.peek(), 5);
  data.clear(); handler({key: null}); assert.equal(wantedHours.peek(), null); stop(); assert.ok(removed);
  data.set(STORAGE_KEYS.wanted, 'invalid'); assert.equal(loadWanted(), null);
  configureStore({storage: {getItem() {throw Error('blocked');}, setItem() {throw Error('blocked');}}});
  assert.equal(saveWanted(4), 4); assert.equal(wantedHours.peek(), 4);
  configureStore({storage: null}); wantedHours.value = null;
});
