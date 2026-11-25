import assert from 'node:assert/strict';
import {readFileSync, readdirSync} from 'node:fs';
import test from 'node:test';
import {COVERAGE_LAYERS, coverageNeedsRecheck, coverageRegionURL, coverageStatusId, lifecycleId, snapshot} from '../web/region-coverage.ts';
import evidence from '../catalog/app/region-coverage.json' with {type: 'json'};
import catalogue from '../catalog/app/strings.json' with {type: 'json'};

const root = new URL('../', import.meta.url);
const read = path => JSON.parse(readFileSync(new URL(path, root), 'utf8'));

test('coverage directory covers every region package and preserves its lifecycle and name', () => {
  const packages = readdirSync(new URL('regions/', root)).filter(id => {
    try { read(`regions/${id}/region.json`); return true; } catch { return false; }
  });
  assert.deepEqual(evidence.columns, ['id', 'name', 'lifecycle', 'habitat', 'basemap']);
  assert.ok(evidence.regions.every(row => row.length === evidence.columns.length));
  assert.deepEqual(snapshot.regions.map(r => r.id).sort(), packages.sort());
  assert.equal(new Set(snapshot.regions.map(r => r.id)).size, packages.length);
  for (const row of snapshot.regions) {
    const source = read(`regions/${row.id}/region.json`);
    assert.equal(row.lifecycle, source.status, row.id);
    assert.equal(row.name, source.name, row.id);
    for (const id of [lifecycleId(row), ...COVERAGE_LAYERS.map(layer => coverageStatusId(row, layer))]) {
      assert.ok(catalogue.strings[id]?.en, id);
      assert.ok(catalogue.strings[id]?.es, id);
    }
  }
});

test('reviewed audit exceptions remain gaps, not full or current coverage', () => {
  const byId = id => snapshot.regions.find(r => r.id === id);
  assert.equal(snapshot.audit_csv_sha256, '9f0d93f09623446438a33715144e0c827379d704e39d9050e46ffa025e2cddc3');
  assert.equal(byId('trinidad-klamath').basemap, 'overview');
  assert.equal(byId('santa-cruz-monterey-bay').habitat, 'held');
  const partial = ['big-sur-coast', 'cambria-san-simeon', 'monterey-point-sur', 'morro-bay', 'point-arguello-conception', 'south-big-sur-san-simeon'];
  for (const row of snapshot.regions) {
    assert.equal(row.habitat, partial.includes(row.id) ? 'partial' : row.id === 'santa-cruz-monterey-bay' ? 'held' : 'none');
    assert.equal(row.rules, row.lifecycle === 'draft' ? 'unreviewed' : 'review-needed');
    assert.equal(row.conditions, row.lifecycle === 'draft' ? 'unpublished' : 'partial');
    assert.equal(row.tides, row.lifecycle === 'draft' ? 'unpublished' : 'predictions');
    assert.equal(row.relief, 'unconfirmed');
  }
});

test('old, future and invalid dates demand recheck without changing layer states', () => {
  const checked = Date.parse(snapshot.checked_at), week = 7 * 24 * 60 * 60 * 1000;
  for (const [time, expected] of [[checked, false], [checked + week, false], [checked + week + 1, true], [checked - 1, true], [NaN, true]])
    assert.equal(coverageNeedsRecheck(time), expected);
  assert.equal(coverageNeedsRecheck(checked, 'bad-date'), true);
});

// Contract: an audit timestamp whose calendar date does not exist needs a recheck. Date.parse rolls
// 2026-02-30 into 2026-03-02, so a malformed stamp would look fresh and silence the reminder.
test('a timestamp whose calendar date does not exist demands recheck instead of rolling over', () => {
  const now = Date.parse('2026-03-03T12:00:00Z');
  // Control: the real date the impossible one rolls into stays fresh (catches an over-eager "always recheck").
  assert.equal(coverageNeedsRecheck(now, '2026-03-02T12:00:00Z'), false);
  // Catches the original bug: February 30 rolled into March 2 and looked recent.
  assert.equal(coverageNeedsRecheck(now, '2026-02-30T12:00:00Z'), true);
  // Catches a fix that only special-cases February: other short months roll over too (Apr 31 -> May 1).
  assert.equal(coverageNeedsRecheck(Date.parse('2026-05-02T12:00:00Z'), '2026-04-31T12:00:00Z'), true);
  // Catches a fix that treats every February as 28 days: leap day exists in 2028, not in 2026.
  assert.equal(coverageNeedsRecheck(Date.parse('2028-03-03T12:00:00Z'), '2028-02-29T12:00:00Z'), false);
  assert.equal(coverageNeedsRecheck(now, '2026-02-29T12:00:00Z'), true);
  // Catches a fix that only validates the "Z" form: an explicit offset must be checked the same way.
  assert.equal(coverageNeedsRecheck(now, '2026-02-30T12:00:00+00:00'), true);
  // Catches a regression that lets month 13 / hour 25 through if the parser ever becomes lenient.
  assert.equal(coverageNeedsRecheck(now, '2026-13-02T12:00:00Z'), true);
  assert.equal(coverageNeedsRecheck(now, '2026-03-02T25:00:00Z'), true);
  // Unchanged rules at the same clock: seven-day edge, just past it, and a future audit time.
  assert.equal(coverageNeedsRecheck(now, '2026-02-24T12:00:00Z'), false);
  assert.equal(coverageNeedsRecheck(now, '2026-02-24T11:59:59Z'), true);
  assert.equal(coverageNeedsRecheck(now, '2026-03-03T12:00:01Z'), true);
});

test('region navigation refuses drafts and unknown ids, clears old place selections and keeps language/profile', () => {
  const href = 'https://skippercast.com/?region=morro-bay&port=morro-bay&place=old&area=old&target=old&species=lingcod&spot=old&habitat=old&focus=old&coast=central&view=10/35/-121&profile=kayak&lang=es#old';
  for (const row of snapshot.regions) {
    const target = coverageRegionURL(href, row.id);
    if (row.lifecycle === 'draft') { assert.equal(target, null); continue; }
    const url = new URL(target);
    assert.equal(url.pathname, '/map');
    assert.equal(url.searchParams.get('region'), row.id);
    for (const key of ['port', 'place', 'area', 'target', 'spot', 'habitat', 'focus', 'coast', 'view']) assert.equal(url.searchParams.has(key), false, key);
    assert.equal(url.searchParams.get('lang'), 'es');
    assert.equal(url.searchParams.get('profile'), 'kayak');
    assert.equal(url.hash, '');
  }
  assert.equal(coverageRegionURL(href, 'unknown'), null);
  assert.equal(new URL(coverageRegionURL('https://skippercast.com/map?view=conditions', 'trinidad-klamath')).searchParams.get('view'), 'conditions');
});
