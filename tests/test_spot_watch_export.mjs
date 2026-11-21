import test from 'node:test';
import assert from 'node:assert/strict';
import {exportSpotWatches} from '../server/spot-watch-export.ts';

const owner = 'owner-a';
const watch = {owner, id: 'w', spot_id: 's'};
const event = {owner, id: 'e'};
const empty = {watches: [], spot_alert_events: []};
const watchExport = {
  id: 'w', spot_id: 's', layer: null, op: null, a: null, b: null, enabled: null,
  last_state: null, last_fired_at: null, last_sample_at: null, created_at: null,
};
const eventExport = {id: 'e', watch_id: null, message: null, status: null, created_at: null, delivered_at: null};

// Catch treating missing/invalid identity as an unscoped export, or coercing the owner.
test('C1: invalid owners give two empty lists', () => {
  for (const value of ['', null, undefined, 0, new String(owner)]) {
    assert.deepEqual(exportSpotWatches(value, [watch, {...watch, owner: value}], [event, {...event, owner: value}]), empty);
  }
});

// Catch spreading entire records or scoping only one of the lists.
test('C1: keeps exact-owner plain records and never exports extra keys', () => {
  const extras = {lat: 12, lon: 34, endpoint: 'private-device', internal: 'private-note', [Symbol('extra')]: true};
  const mixed = (row) => [
    {...row, owner: 'owner-b'}, {...row, owner: owner.toUpperCase()}, {...row, owner: undefined},
    {...row, owner: new String(owner)}, Object.assign([], row), Object.assign(() => {}, row),
    Object.assign(new Date(0), row), Object.create(row), null, 42,
    Object.assign(Object.create(null), row, extras),
  ];
  assert.deepEqual(exportSpotWatches(owner, mixed(watch), mixed(event)), {
    watches: [watchExport], spot_alert_events: [eventExport],
  });
});

// Catch emitting partial rows or casting a numeric identifier to text.
test('C2: both watch ids must be non-empty strings', () => {
  const invalid = [undefined, '', 1, null, {}];
  const watches = [
    {owner, spot_id: 's'}, {owner, id: 'w'},
    ...invalid.flatMap(value => [{...watch, id: value}, {...watch, spot_id: value}]),
  ];
  assert.deepEqual(exportSpotWatches(owner, watches, []), empty);
});

// Catch truthiness/coercion in place of exact flag decoding, or a default for missing flags.
test('C2: decodes only the four enabled spellings', () => {
  for (const [value, expected] of [[1, true], [true, true], [0, false], [false, false],
    ['1', null], ['0', null], [2, null], [undefined, null], [null, null], [{}, null]]) {
    assert.deepEqual(exportSpotWatches(owner, [{...watch, enabled: value}], []), {
      watches: [{...watchExport, enabled: expected}], spot_alert_events: [],
    });
  }
});

// Catch dropping valid zero/empty text or forwarding values that are not JSON-safe scalars.
test('C2: projects all watch fields with scalar-or-null values', () => {
  const valid = {
    ...watch, layer: 'water-temp', op: 'between', a: 0, b: 64.5, enabled: 1,
    last_state: 0, last_fired_at: null, last_sample_at: '', created_at: '2026-11-20',
  };
  const malformed = {
    ...watch, id: 'invalid-scalars', layer: {}, op: true, a: Infinity, b: NaN,
    last_state: [], last_fired_at: -Infinity, last_sample_at: 1n, created_at: Symbol('time'),
  };
  assert.deepEqual(exportSpotWatches(owner, [malformed, valid], []), {
    watches: [{
      id: 'w', spot_id: 's', layer: 'water-temp', op: 'between', a: 0, b: 64.5, enabled: true,
      last_state: 0, last_fired_at: null, last_sample_at: '', created_at: '2026-11-20',
    }, {...watchExport, id: 'invalid-scalars'}], spot_alert_events: [],
  });
});

// Catch leaking malformed fields or filtering events based on a watch join instead of event owner/id.
test('C3: projects event scalars and skips only invalid event ids among readable owned rows', () => {
  const events = [
    {owner, watch_id: 'w'}, ...['', null, 2, {}].map(id => ({...event, id})),
    {...event, id: 'valid', watch_id: 'not-in-export', message: 'Threshold crossed', status: 'sent', created_at: 42, delivered_at: ''},
    {...event, watch_id: {}, message: [], status: false, created_at: NaN, delivered_at: Infinity},
  ];
  assert.deepEqual(exportSpotWatches(owner, [], events), {
    watches: [], spot_alert_events: [
      {id: 'valid', watch_id: 'not-in-export', message: 'Threshold crossed', status: 'sent', created_at: 42, delivered_at: ''},
      eventExport,
    ],
  });
});

// Reverse ties and mix the null and dated entries so stable input order alone cannot pass.
test('C3: both lists sort by timestamp text, then id, with nulls last and no input mutation', () => {
  const times = [['z-null', null], ['z-tie', 2], ['first', '10'], ['A-tie', '2'], ['A-null', null], ['last-date', 'null']];
  const watches = Object.freeze(times.map(([id, created_at]) => Object.freeze({...watch, id, created_at})));
  const events = Object.freeze(times.map(([id, created_at]) => Object.freeze({...event, id, created_at})).reverse());
  const ordered = [['first', '10'], ['A-tie', '2'], ['z-tie', 2], ['last-date', 'null'], ['A-null', null], ['z-null', null]];
  assert.deepEqual(exportSpotWatches(owner, watches, events), {
    watches: ordered.map(([id, created_at]) => ({...watchExport, id, created_at})),
    spot_alert_events: ordered.map(([id, created_at]) => ({...eventExport, id, created_at})),
  });
});

// Catch a single unreadable row aborting the export, or turning a partial row into an exported one.
test('C3: skips throwing owner and field getters and continues with valid rows', () => {
  const fail = () => { throw new Error('unreadable'); };
  const badOwner = (row) => Object.defineProperty({...row, id: 'bad-owner'}, 'owner', {get: fail});
  const watches = [badOwner(watch), {...watch, id: 'bad-state', get last_state() { return fail(); }}, watch];
  const events = [badOwner(event), {...event, id: 'bad-message', get message() { return fail(); }}, event];
  assert.deepEqual(exportSpotWatches(owner, watches, events), {
    watches: [watchExport], spot_alert_events: [eventExport],
  });
});

// A failed collection read must not erase the other list, nor a later readable entry.
test('C3: unreadable collection and entry do not throw', () => {
  const {proxy, revoke} = Proxy.revocable([], {});
  revoke();
  const events = [event, {...event, id: 'e2'}];
  Object.defineProperty(events, 0, {get() { throw new Error('unreadable'); }});
  assert.deepEqual(exportSpotWatches(owner, proxy, events), {
    watches: [], spot_alert_events: [{...eventExport, id: 'e2'}],
  });
});

// Catch coercing a Symbol in the loop condition and aborting before events are projected.
test('C3: Symbol watch length leaves the full event export intact', () => {
  const watches = new Proxy([watch], {
    get: (target, key) => key === 'length' ? Symbol('length') : target[key],
  });
  assert.deepEqual(exportSpotWatches(owner, watches, [event, {...event, id: 'e2'}]), {
    watches: [], spot_alert_events: [eventExport, {...eventExport, id: 'e2'}],
  });
});

// Catch a guard applied only to watches, or a loop that accepts/coerces non-integer lengths.
test('C3: invalid event lengths leave the full watch export intact', () => {
  for (const length of [Symbol('length'), '1', 0.5, -1, NaN]) {
    const events = new Proxy([event], {
      get: (target, key) => key === 'length' ? length : target[key],
    });
    assert.deepEqual(exportSpotWatches(owner, [watch], events), {
      watches: [watchExport], spot_alert_events: [],
    });
  }
});

// Catch moving the length read outside the catch or re-reading an unreadable length.
test('C3: a throwing length getter is read once and only empties its own list', () => {
  let reads = 0;
  const watches = {get length() { reads++; throw new Error('unreadable'); }};
  assert.deepEqual(exportSpotWatches(owner, watches, [event]), {
    watches: [], spot_alert_events: [eventExport],
  });
  assert.equal(reads, 1);
});
