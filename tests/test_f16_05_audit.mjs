// F16-05 / SCA-550: offline fixture, not a production fix. The normal Node
// suite uses the serialized reference. To apply the same append contract to
// the unmodified store: node tests/test_f16_05_audit.mjs --baseline
// On the affected baseline only that opt-in replay should fail (two races).
import assert from 'node:assert/strict';
import test from 'node:test';
import {LOG_KEY, readEntries, saveEntry} from '../web/private-map-log.ts';

const baseline = process.argv.includes('--baseline');
const row = (name, kind = 'blank') => ({
  kind, name, region: 'FixtureRegion', position: {latitude: 0, longitude: 0},
  positionBasis: 'Selected map position; not live GPS', recordedAt: '2000-01-01T00:00:00.000Z', conditions: null,
});
const arrivals = [row('TabA', 'catch'), row('TabB')];

function memoryLog(raw = null) {
  let writes = 0;
  return {
    // Each tab gets a distinct view of the same synthetic origin's bytes.
    view(onFirstRead) {
      return {
        getItem(key) {
          assert.equal(key, LOG_KEY);
          const snapshot = raw;
          const start = onFirstRead;
          onFirstRead = undefined;
          start?.();
          return snapshot;
        },
        setItem(key, value) {
          assert.equal(key, LOG_KEY);
          writes++;
          raw = value;
        },
      };
    },
    state: () => ({raw, writes}),
  };
}

function originSave() {
  if (baseline) return saveEntry;
  // Test-only per-origin queue. Scope covers the entire read/check/write,
  // not just setItem; both simulated tabs submit to it.
  let pending = Promise.resolve();
  return (entry, storage) => (pending = pending.then(() => saveEntry(entry, storage)));
}

async function overlap(seed, t) {
  const log = memoryLog(JSON.stringify(seed));
  const save = originSave();
  let second;
  const tabA = log.view(() => { second = Promise.resolve(save(arrivals[1], log.view())); });
  // B attempts its save after A snapshots the bytes and before A commits.
  // No timers or browser scheduling assumptions are needed for this interleaving.
  const first = await save(arrivals[0], tabA);
  assert.ok(second, 'tab B attempted its save during tab A’s read');
  const statuses = [first, await second];
  const rows = readEntries(log.view());
  t.diagnostic(JSON.stringify({statuses, rowCount: rows.length, appended: rows.slice(seed.length).map(r => r.name)}));
  return {statuses, rows};
}

// A stale read/replace can acknowledge both writes but drop one on reopen.
test('F16-05: both acknowledged rows survive overlapping tab saves', async t => {
  const {statuses, rows} = await overlap([], t);
  assert.deepEqual(statuses, ['saved', 'saved']);
  assert.deepEqual(rows.toSorted((a, b) => a.name.localeCompare(b.name)), arrivals);
});

// A capacity check on a stale snapshot can sell the final slot twice.
test('F16-05: exactly one tab receives the final slot at 499 rows', async t => {
  const seed = Array.from({length: 499}, (_, i) => row(`Seed${i}`));
  const {statuses, rows} = await overlap(seed, t);
  assert.deepEqual(statuses.toSorted(), ['full', 'saved']);
  assert.deepEqual(rows, [...seed, arrivals[statuses.indexOf('saved')]]);
});

test('F16-05: corrupt legacy bytes survive a failed migration', t => {
  const corrupt = '  [{"kind": "blank"},';
  const legacy = memoryLog(corrupt);
  const target = memoryLog();
  // No migration exists in the baseline: exercise its real append refusal.
  // In the reference, model decoding legacy bytes before committing a new store.
  function migrate() {
    try {
      target.view().setItem(LOG_KEY, JSON.stringify(readEntries(legacy.view())));
      return 'saved';
    } catch {
      return 'unavailable';
    }
  }
  const status = baseline ? saveEntry(arrivals[0], legacy.view()) : migrate();
  const before = legacy.state(), after = target.state();
  t.diagnostic(JSON.stringify({
    status, legacyUnchanged: before.raw === corrupt, legacyWrites: before.writes, targetWrites: after.writes,
  }));
  assert.equal(status, 'unavailable');
  assert.deepEqual(before, {raw: corrupt, writes: 0});
  assert.deepEqual(after, {raw: null, writes: 0});
});
