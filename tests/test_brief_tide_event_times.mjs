// RF1230-14: a regional tide event without a readable time is dropped, so the brief's tide list never throws.
import test from 'node:test';
import assert from 'node:assert/strict';
import montereyDaily from './fixtures/brief/monterey-daily.json' with {type: 'json'};
import montereyForecast from './fixtures/brief/monterey-forecast.json' with {type: 'json'};

const {regionalReport} = await import('../web/brief/model.ts');

const montereyPlace = {id: 'monterey', name: 'Monterey', lat: 36.62, lon: -121.9, timezone: 'America/Los_Angeles', port: 'Monterey'};
const eventsOf = daily => regionalReport(daily, montereyForecast, montereyPlace).report.tideEvents;
const withPredictions = edit => {
  const daily = structuredClone(montereyDaily);
  edit(daily.sources.tides.data);
  return daily;
};
const hour = new Intl.DateTimeFormat('en-US', {hour: 'numeric', timeZone: 'America/Los_Angeles'});
const readable = events => {
  for (const e of events) {
    assert.ok(Number.isFinite(Date.parse(e.at)), e.at);
    assert.doesNotThrow(() => hour.format(new Date(e.at)), e.at);
  }
};

// Golden taken from origin/main (be4cefab) for the unchanged fixture.
const GOLDEN = [
  ['2026-10-08T01:10:00Z', 4.9, 'H'], ['2026-10-08T07:22:00Z', 0.6, 'L'], ['2026-10-08T13:34:00Z', 4.9, 'H'],
  ['2026-10-08T19:46:00Z', 0.6, 'L'], ['2026-10-09T01:58:00Z', 4.9, 'H'], ['2026-10-09T08:10:00Z', 0.6, 'L'],
  ['2026-10-09T14:22:00Z', 4.9, 'H'], ['2026-10-09T20:34:00Z', 0.6, 'L'], ['2026-10-10T02:46:00Z', 4.9, 'H'],
  ['2026-10-10T08:58:00Z', 0.6, 'L'],
].map(([at, heightFt, type]) => ({at, heightFt, type}));

test('edge 1: the unchanged fixture maps exactly as on main', () => {
  const events = eventsOf(montereyDaily);
  assert.deepEqual(events, GOLDEN);
  readable(events);
});

test('edge 2: rows with a missing, null, unreadable or numeric time are dropped; the rest keep their order', () => {
  const daily = withPredictions(data => {
    delete data.predictions[1].time;
    data.predictions[3].time = null;
    data.predictions[5].time = 'soon';
    data.predictions[7].time = 12345;
  });
  const events = eventsOf(daily);
  assert.deepEqual(events, GOLDEN.filter((_, i) => ![1, 3, 5, 7].includes(i)));
  for (const at of ['undefined', 'null', 'soon', '12345']) assert.ok(!events.some(e => e.at === at), at);
  readable(events);
});

test('edge 2b: a list made only of unreadable times yields no events and no throw', () => {
  const daily = withPredictions(data => {
    data.predictions = [{height_ft: 1, type: 'H'}, {time: null, height_ft: 1, type: 'L'}, {time: '', height_ft: 1, type: 'H'}, {time: {}, height_ft: 1, type: 'L'}];
  });
  assert.deepEqual(eventsOf(daily), []);
});

test('edge 3: a readable time does not rescue a row the height/type rules already drop', () => {
  const daily = withPredictions(data => {
    data.predictions[0].height_ft = NaN;
    data.predictions[2].type = 'X';
    data.predictions[4].height_ft = '4.9';
  });
  const events = eventsOf(daily);
  assert.deepEqual(events, GOLDEN.filter((_, i) => ![0, 2, 4].includes(i)));
  readable(events);
});

test('edge 4: every kept event formats as an hour without throwing', () => {
  const daily = withPredictions(data => {
    data.predictions.push({time: 'not a date', height_ft: 3, type: 'H'}, {time: '2026-10-10T15:10:00Z', height_ft: 3.2, type: 'H'});
  });
  const events = eventsOf(daily);
  assert.equal(events.length, GOLDEN.length + 1);
  assert.deepEqual(events.at(-1), {at: '2026-10-10T15:10:00Z', heightFt: 3.2, type: 'H'});
  readable(events);
});

test('edge 5: missing or empty predictions give no events', () => {
  assert.deepEqual(eventsOf(withPredictions(data => { delete data.predictions; })), []);
  assert.deepEqual(eventsOf(withPredictions(data => { data.predictions = []; })), []);
});
