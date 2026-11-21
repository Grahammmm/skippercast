import test from 'node:test';
import assert from 'node:assert/strict';
import {MAX_OWNER_PAGE, mergeOwnerPages, allCheckOwners} from '../server/check-owner-pages.ts';

// An off-by-one limit would reject the queue's normal page size.
test('C1: accept a full 500-owner page', () => {
  assert.equal(MAX_OWNER_PAGE, 500);
  const page = Array.from({length: 500}, (_, i) => `owner-${String(i).padStart(3, '0')}`);
  assert.deepEqual(mergeOwnerPages(page, [], 500), {owners: page, next: 'owner-499'});
});

// Clamping or coercing the limit could make a partial page look complete.
test('C1: reject invalid limits', () => {
  for (const limit of [-1, 0, 1.5, 501, NaN, Infinity]) {
    assert.throws(() => mergeOwnerPages([], [], limit), RangeError, String(limit));
  }
});

// Silently sorting, deduplicating or truncating malformed pages can mask a bad cutoff.
test('C1: reject descending, duplicate or oversized pages from either source', () => {
  for (const page of [['b', 'a'], ['a', 'a'], ['a', 'b', 'c']]) {
    assert.throws(() => mergeOwnerPages(page, [], 2), RangeError);
    assert.throws(() => mergeOwnerPages([], page, 2), RangeError);
  }
});

// A locale sort or concatenation would not reproduce SQL's ASCII key order.
test('C2: merge two short interleaved pages and finish', () => {
  assert.deepEqual(mergeOwnerPages(['A', 'b'], ['Z', 'b', 'c'], 4), {
    owners: ['A', 'Z', 'b', 'c'], next: null,
  });
});

// A short page must neither limit the walk nor emit entries past the full page's tail.
test('C2: only the full page sets the bound when one source is short', () => {
  assert.deepEqual(mergeOwnerPages(['b', 'd', 'f'], ['a', 'z'], 3), {
    owners: ['a', 'b', 'd', 'f'], next: 'f',
  });
  assert.deepEqual(mergeOwnerPages(['a'], ['b', 'd', 'f'], 3), {
    owners: ['a', 'b', 'd', 'f'], next: 'f',
  });
});

// Advancing to the greater tail can jump over unseen owners in the other source.
test('C2: use the smaller full-page tail in either source order', () => {
  assert.deepEqual(mergeOwnerPages(['a', 'd'], ['b', 'f'], 2), {
    owners: ['a', 'b', 'd'], next: 'd',
  });
  assert.deepEqual(mergeOwnerPages(['b', 'f'], ['a', 'd'], 2), {
    owners: ['a', 'b', 'd'], next: 'd',
  });
});

// Equal tails still require another round, even when every entry overlaps.
test('C2: deduplicate identical full pages without dropping the cursor', () => {
  assert.deepEqual(mergeOwnerPages(['a', 'b'], ['a', 'b'], 2), {
    owners: ['a', 'b'], next: 'b',
  });
});

// All pairs cover early exhaustion, overlapping sources and interleaved tails.
// The unpaged oracle catches skipped or repeated owners anywhere in the walk.
for (const limit of [1, 2, 3]) {
  test(`C3: walk all pairs of four-owner subsets at limit ${limit}`, async () => {
    const universe = ['A', 'Z', 'a', 'z'];
    const subsets = Array.from({length: 16}, (_, mask) => (
      universe.filter((_, i) => mask & (1 << i))
    ));
    for (const trips of subsets) {
      for (const watches of subsets) {
        const pages = {trips, watches};
        const read = async (source, after, size) => pages[source].filter(owner => owner > after).slice(0, size);
        const expected = Array.from(new Set([...trips, ...watches])).sort();
        assert.deepEqual(await allCheckOwners(read, limit, 5), expected, JSON.stringify(pages));
      }
    }
  });
}

// The final short round counts too; both reads must use the shared exclusive cursor.
test('C3: read both sources per round and finish exactly at the round budget', async () => {
  const calls = [];
  const read = async (source, after, limit) => {
    calls.push([source, after, limit]);
    return source === 'trips' && after === '' ? ['a'] : [];
  };
  assert.deepEqual(await allCheckOwners(read, 1, 2), ['a']);
  assert.deepEqual(calls.sort(), [
    ['trips', '', 1], ['trips', 'a', 1], ['watches', '', 1], ['watches', 'a', 1],
  ]);
  calls.length = 0;
  await assert.rejects(allCheckOwners(read, 1, 1), RangeError);
  assert.deepEqual(calls.sort(), [['trips', '', 1], ['watches', '', 1]]);
});

// A reader returning a stale full page must fail before the round cap masks the stall.
test('C3: reject equal or backwards cursors', async () => {
  for (const stale of ['b', 'a']) {
    let tripReads = 0;
    const read = async (source, after) => {
      if (source === 'watches') return [];
      tripReads++;
      return [after === '' ? 'b' : stale];
    };
    await assert.rejects(allCheckOwners(read, 1, 3), RangeError);
    assert.equal(tripReads, 2);
  }
});

// Even an always-advancing reader cannot run beyond the default budget.
test('C3: cap the default walk at 10,000 rounds', async () => {
  let tripReads = 0;
  const read = async source => source === 'watches' ? [] : [String(++tripReads).padStart(5, '0')];
  await assert.rejects(allCheckOwners(read, 1), RangeError);
  assert.equal(tripReads, 10_000);
});

// Validation must not turn a reader's own failure into an empty page or wrap its error.
test('C3: propagate a rejected read unchanged from either source', async () => {
  const failure = new Error('reader refused');
  for (const rejected of ['trips', 'watches']) {
    const read = async source => {
      if (source === rejected) throw failure;
      return [];
    };
    await assert.rejects(allCheckOwners(read, 1), error => error === failure);
  }
});

// Reject a bad limit before passing it to a reader that may query storage.
test('C3: reject an invalid page limit without reading', async () => {
  let calls = 0;
  await assert.rejects(allCheckOwners(async () => { calls++; return []; }, 0), RangeError);
  assert.equal(calls, 0);
});
