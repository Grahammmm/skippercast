import assert from 'node:assert/strict';
import test from 'node:test';
import {gpxImportOutcome} from '../web/gpx-import-outcome.ts';
import {saveSequentially} from '../web/gpx-import-plan.ts';
import {gpxImportPreview} from '../web/gpx-import-preview.ts';

const waypoint = (name, lat) => ({name, lat, lon: 7, note: null});
const selection = [waypoint('First', 1), waypoint('Second', 2), waypoint('Third', 3)];
const preview = {
  ok: true,
  save: selection,
  counts: {
    read: 53, routePoints: 11, trackPoints: 12, invalidPoints: 16,
    refusedInside: 1, refusedNear: 2, refusedUnchecked: 4,
    duplicates: 5, invalid: 8, overCapacity: 30, save: 3,
  },
};
const skipped = {duplicates: 5, refused: 7, invalid: 24, overCapacity: 30};

test('C1: all selected waypoints saved, with only the four skipped buckets', () => {
  // Dropping a refusal or invalid component, folding in route/track counts, or leaking coordinates changes the result.
  assert.deepEqual(gpxImportOutcome(preview, {saved: 3, failed: []}), {
    ok: true, saved: 3, failed: 0, skipped, failedNames: [],
  });
});

test('C2: a preview error takes precedence over an inapplicable report', () => {
  // Looking for preview counts before forwarding the error would throw.
  assert.deepEqual(gpxImportOutcome({ok: false, error: 'screen-stale'}, {saved: 1, failed: []}), {
    ok: false, error: 'screen-stale',
  });
});

test('C2: a null report counts no attempts even when the preview selected waypoints', () => {
  // Treating null as an empty report to reconcile would incorrectly return a mismatch.
  assert.deepEqual(gpxImportOutcome(preview, null), {
    ok: true, saved: 0, failed: 0, skipped, failedNames: [],
  });
});

test('C2: failure names follow report order, not waypoint indices or alphabetical order', () => {
  // A lookup by index, sort, or exposure of failure details instead of names changes the result.
  const report = {saved: 1, failed: [
    {index: 2, name: 'Zulu', error: 'temporary error'},
    {index: 0, name: 'Alpha', error: 'unavailable'},
  ]};
  assert.deepEqual(gpxImportOutcome(preview, report), {
    ok: true, saved: 1, failed: 2, skipped, failedNames: ['Zulu', 'Alpha'],
  });
});

for (const [label, saved] of [['too few', 1], ['too many', 3]]) {
  test(`C3: ${label} accounted-for saves returns report-mismatch without throwing`, () => {
    // A one-sided bound or a check of saved alone would accept at least one inconsistent report.
    const report = {saved, failed: [{index: 1, name: 'Second', error: 'unavailable'}]};
    assert.deepEqual(gpxImportOutcome(preview, report), {ok: false, error: 'report-mismatch'});
  });
}

test('C4: the real preview and saver join after one injected rejection', async () => {
  // Joining against the read total instead of the filtered save count would reject this valid report.
  const duplicate = waypoint('Duplicate', 1);
  const refused = waypoint('Refused', 4);
  const clear = [...selection, duplicate];
  const prepared = gpxImportPreview(
    {ok: true, waypoints: [...clear, refused], rejected: [], ignoredTrackPoints: 0},
    {ok: true, clear, refused: [{waypoint: refused, reason: 'near'}]},
    [],
  );
  assert.equal(prepared.ok, true);
  const report = await saveSequentially(prepared.save, async ({name}) => {
    if (name === 'Second') throw new Error('save failed');
  });
  assert.deepEqual(gpxImportOutcome(prepared, report), {
    ok: true,
    saved: 2,
    failed: 1,
    skipped: {duplicates: 1, refused: 1, invalid: 0, overCapacity: 0},
    failedNames: ['Second'],
  });
});
