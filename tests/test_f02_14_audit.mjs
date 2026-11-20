// F02-14 / SCA-615: gallery selection must not serialize derivative metadata reads
// or fan out over the whole candidate window. Existing boat snapshots don't observe
// R2 concurrency. The default test qualifies the fixture, not a production fix.
// Read-only baseline probe (intentionally nonzero while the gap exists):
//   node tests/test_f02_14_audit.mjs --baseline
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import test from 'node:test';
import {setImmediate as nextTurn} from 'node:timers/promises';

const limit = 12; // Boat gallery contract: 12 results, at most 24 candidates.
const key = id => `advisor/derived/${id}/public.jpg`;
const where = 'm.boat_id=?';
const boat = 'audit-boat';

// Test-only valid control; production remains unchanged. Results are collected
// in input order, even when a newer candidate takes longer to resolve.
async function boundedControl(env, condition, binds, max) {
  const {results} = await env.DB.prepare(`SELECT m.* FROM advisor_media m JOIN advisor_boats b ON b.id=m.boat_id
    WHERE ${condition} AND m.kind='image' AND m.publish_state IN ('approved','posted') ORDER BY m.created_at DESC, m.id LIMIT ?`)
    .bind(...binds, 2 * max).all();
  const photos = [];
  for (let i = 0; i < results.length && photos.length < max; i += 4) {
    const batch = await Promise.all(results.slice(i, i + 4).map(async row => {
      if (!(row.mime === 'image/jpeg' && row.exif_stripped === 1) && !await env.ADVISOR_MEDIA.head(key(row.id))) return null;
      return {id: row.id, url: `/media/${row.id}.jpg`};
    }));
    photos.push(...batch.filter(Boolean));
  }
  return photos.slice(0, max);
}

async function observe(select, sparse) {
  const db = new DatabaseSync(':memory:');
  const idFor = rank => `audit-photo-${rank}`;
  const ready = rank => rank === 1 || rank === 3 || rank >= 24 || (!sparse && rank >= 5);
  const probes = [], completed = [];
  let active = 0, peak = 0;
  try {
    db.exec(`CREATE TABLE advisor_boats (id TEXT PRIMARY KEY);
      CREATE TABLE advisor_media (id TEXT, boat_id TEXT, mime TEXT, exif_stripped INTEGER,
        kind TEXT, publish_state TEXT, created_at INTEGER, credit TEXT, width INTEGER, height INTEGER);`);
    db.prepare('INSERT INTO advisor_boats VALUES (?)').run(boat);
    const add = db.prepare("INSERT INTO advisor_media VALUES (?, ?, ?, ?, 'image', 'approved', ?, NULL, NULL, NULL)");
    // Insert oldest first so a missing ORDER BY cannot satisfy the oracle.
    for (let rank = 25; rank >= 0; rank--) {
      add.run(idFor(rank), boat, rank === 2 ? 'image/jpeg' : 'image/png', rank === 2 ? 1 : 0, 100 - rank);
    }
    db.exec('PRAGMA query_only = ON');
    const env = {
      DB: {prepare: sql => ({bind: (...args) => ({async all() {
        return {results: db.prepare(sql).all(...args)};
      }})})},
      ADVISOR_MEDIA: {async head(objectKey) {
        probes.push(objectKey);
        peak = Math.max(peak, ++active);
        await nextTurn();
        // Force a ready, newer photo to complete after a ready, older photo
        // in the first batch, without any wall-clock threshold.
        if (objectKey === key(idFor(1))) await nextTurn();
        completed.push(objectKey);
        active--;
        const rank = Number(/^advisor\/derived\/audit-photo-(\d+)\/public\.jpg$/.exec(objectKey)?.[1] ?? NaN);
        return ready(rank) ? {key: objectKey} : null;
      }},
    };
    const photos = await select(env, where, [boat], limit);
    const expected = (sparse ? [1, 2, 3] : [1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13]).map(idFor);
    assert.deepEqual(photos.map(photo => photo.id), expected, 'newest first, omitting misses and respecting both limits');
    assert.deepEqual(photos.map(photo => photo.url), expected.map(id => `/media/${id}.jpg`));
    assert.equal(active, 0, 'all started reads have settled');
    assert.ok(!probes.includes(key(idFor(2))), 'no object probe for a stripped JPEG');
    const window = Array.from({length: 24}, (_, rank) => rank).filter(rank => rank !== 2).map(rank => key(idFor(rank)));
    assert.equal(new Set(probes).size, probes.length, 'no duplicate object probes');
    assert.ok(probes.every(probe => window.includes(probe)), 'no probe outside the newest 24 candidates');
    if (sparse) assert.deepEqual([...probes].sort(), window.sort(), 'scan only the available candidate window when results are sparse');
    return {peak, probes: probes.length, photos: photos.length, outOfOrder: completed.indexOf(key(idFor(3))) < completed.indexOf(key(idFor(1)))};
  } finally {
    db.close();
  }
}

async function check(select, log = () => {}) {
  const full = await observe(select, false);
  const sparse = await observe(select, true);
  log(JSON.stringify({full, sparse}));
  for (const result of [full, sparse]) {
    assert.ok(result.peak >= 2, `derivative HEAD requests must overlap; peak=${result.peak}`);
    assert.ok(result.peak <= 4, `derivative HEAD requests must stay bounded; peak=${result.peak}`);
  }
  return {full, sparse};
}

if (process.argv.includes('--baseline')) {
  // The real loader has no network path here: D1 and R2 are both fixture-local.
  // Fail closed if an unexpected transitive fetch is introduced.
  globalThis.REGIONS = {};
  globalThis.DEPLOYMENT = {allowed_origins: []};
  const fetch = globalThis.fetch;
  let fetches = 0;
  globalThis.fetch = async () => { fetches++; throw new Error('offline gallery fixture'); };
  try {
    const {publicPhotos} = await import('../server/advisor/pages/data.ts');
    await check(publicPhotos, console.log);
  } finally {
    globalThis.fetch = fetch;
    assert.equal(fetches, 0, 'no outbound fetch attempts');
  }
} else {
  test('F02-14 valid control: derivative HEADs overlap without changing the gallery contract', async t => {
    const {full, sparse} = await check(boundedControl, message => t.diagnostic(message));
    assert.ok(full.outOfOrder && sparse.outOfOrder, 'delayed storage exercised out-of-order completion');
  });
}
