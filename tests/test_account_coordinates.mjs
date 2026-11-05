// SC2037-08: the account panel prints catch-log and saved-spot positions in the chosen coordinate format.
import test from 'node:test';
import assert from 'node:assert/strict';

const {logItemHTML, spotItemHTML, logBody, spotBody} = await import('../dist/account.js');
const {formatCoordinates} = await import('../dist/coordinates.js');

const KEY = 'skippercast-coordinates-v1';
const LAT = 35.123456, LON = -120.987654;
const ROW = {id: 'l1', started_at: '2026-11-01T14:00:00Z', outcome: 'blank', lat: LAT, lon: LON};
const SPOT = {id: 's1', name: 'Reef', lat: LAT, lon: LON};

function withStorage(storage, fn) {
  const had = Object.getOwnPropertyDescriptor(globalThis, 'localStorage');
  Object.defineProperty(globalThis, 'localStorage', {value: storage, configurable: true, writable: true});
  try { return fn(); } finally {
    if (had) Object.defineProperty(globalThis, 'localStorage', had); else delete globalThis.localStorage;
  }
}
const stored = value => ({getItem: key => (key === KEY ? value : null)});

for (const format of ['dd', 'ddm', 'dms']) {
  test(`stored ${format} prints both lists through formatCoordinates`, () => {
    const want = formatCoordinates(LAT, LON, format);
    withStorage(stored(format), () => {
      assert.ok(logItemHTML(ROW).includes(want), 'catch-log entry');
      assert.ok(spotItemHTML(SPOT).includes(want), 'saved spot');
    });
  });
}

test('a choice changed between draws applies at the next draw', () => {
  const store = {value: 'dd', getItem: () => store.value};
  withStorage(store, () => {
    assert.ok(spotItemHTML(SPOT).includes(formatCoordinates(LAT, LON, 'dd')));
    store.value = 'dms';
    assert.ok(spotItemHTML(SPOT).includes(formatCoordinates(LAT, LON, 'dms')));
    assert.ok(logItemHTML(ROW).includes(formatCoordinates(LAT, LON, 'dms')));
  });
});

test('an unreadable, missing or blocked stored value prints decimal degrees', () => {
  const want = formatCoordinates(LAT, LON, 'dd');
  const cases = [stored('xyz'), stored(null), {getItem() { throw new Error('blocked'); }}, undefined];
  for (const storage of cases) {
    withStorage(storage, () => {
      assert.ok(logItemHTML(ROW).includes(want));
      assert.ok(spotItemHTML(SPOT).includes(want));
    });
  }
});

test('the explicit format argument wins over storage', () => {
  withStorage(stored('dms'), () => {
    assert.ok(spotItemHTML(SPOT, null, 'ddm').includes(formatCoordinates(LAT, LON, 'ddm')));
    assert.ok(logItemHTML(ROW, [], 'ddm').includes(formatCoordinates(LAT, LON, 'ddm')));
  });
});

test('a catch-log row without a position shows no position bit', () => {
  withStorage(stored('ddm'), () => {
    for (const row of [{...ROW, lat: null}, {...ROW, lon: null}]) assert.ok(!logItemHTML(row).includes('°'));
  });
});

test('request bodies keep the stored decimal numbers whatever the format', () => {
  withStorage(stored('dms'), () => {
    assert.equal(spotBody({name: 'Reef', lat: String(LAT), lon: String(LON), note: ''}).lat, LAT);
    assert.equal(logBody({started: '2026-11-01T14:00', outcome: 'blank', lat: String(LAT), lon: String(LON)}).lon, LON);
  });
});
