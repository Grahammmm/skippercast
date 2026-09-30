// Confidence badges and freshness pills (P4-04): states come only from data
// the target already carries, never upgrade a claim, and the limitation text
// moved from the spot sheet survives word for word in web/disclaimers.ts.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {ageText, depthBadge, fishBadge, freshnessPill, spotBadges, terrainBadge} from '../web/confidence.ts';
import {FISH_UNVERIFIED, RESEARCH_ONLY_LOCATION} from '../web/disclaimers.ts';
import {freshness} from '../dist/live-conditions.js';

const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const atlas = path => JSON.parse(read(path)).targets;

test('every historical Morro Bay target is estimated depth with the research-only text', () => {
  const targets = atlas('dist/data/atlas.json');
  assert.ok(targets.length > 100);
  for (const t of targets) {
    assert.equal(t.research_only, true);
    const badge = depthBadge(t, t.vertical_datum);
    assert.equal(badge.state, 'estimated', t.id);
    assert.equal(badge.why, RESEARCH_ONLY_LOCATION);
  }
});

test('only depth-qualified targets screened on a named datum show verified depth', () => {
  const qualified = atlas('dist/regions/southern-california/atlas.json');
  assert.ok(qualified.length > 0);
  for (const t of qualified) {
    const badge = depthBadge(t);
    assert.equal(badge.state, 'verified', t.id);
    assert.equal(badge.why.text, t.qualification.note);
  }
  const t = qualified[0];
  // Remove any one supporting flag and the badge drops to estimated.
  for (const weaker of [
    {...t, depth_qualified: false},
    {...t, depth_qualified: undefined},
    {...t, qualification: {...t.qualification, full_geometry_screened: false}},
    {...t, qualification: null},
    {...t, vertical_datum: 'unverified source datum'},
    {...t, vertical_datum: 'not recorded'},
    {...t, vertical_datum: null},
    {...t, qualification: {...t.qualification, native_datum: 'NAVD88'}},
    {...t, research_only: true},
  ]) assert.notEqual(depthBadge(weaker).state, 'verified', JSON.stringify({q: weaker.depth_qualified, d: weaker.vertical_datum}));
  assert.equal(depthBadge({...t, research_only: true}).why, RESEARCH_ONLY_LOCATION);
  assert.equal(depthBadge({...t, center_depth_ft: null}).state, 'unknown');
});

test('terrain is always an estimate and fish presence is always unknown', () => {
  for (const t of [...atlas('dist/data/atlas.json'), ...atlas('dist/regions/southern-california/atlas.json')]) {
    const [depth, terrain, fish] = spotBadges(t);
    assert.deepEqual([depth.id, terrain.id, fish.id], ['depth', 'terrain', 'fish']);
    assert.equal(terrain.state, 'estimated');
    assert.equal(terrain.why.text, `Terrain interpretation confidence: ${t.confidence}.`);
    assert.equal(fish.state, 'unknown');
  }
  // Even a record that claimed verified catches stays unknown: no catch model exists.
  assert.equal(fishBadge().state, 'unknown');
  assert.equal(fishBadge().why, FISH_UNVERIFIED);
  assert.equal(terrainBadge({}).state, 'unknown');
});

test('the moved spot-sheet caveats keep their wording and leave app.js', () => {
  assert.equal(RESEARCH_ONLY_LOCATION.lead, 'Research-only location.');
  assert.equal(RESEARCH_ONLY_LOCATION.text, 'Source raster output vertical datum and product uncertainty are unverified. The displayed depths are not chart depths or a verified 200-foot fishing screen. Check your official chart and sounder.');
  assert.equal(FISH_UNVERIFIED.text, 'Fish presence is unverified; no verified charter AIS visits at this target.');
  const app = read('dist/app.js');
  assert.doesNotMatch(app, /Research-only location/);
  assert.doesNotMatch(app, /Fish presence is unverified/);
  assert.doesNotMatch(app, /class="evidence-note"><p><strong>Mapped habitat candidate/);
  assert.match(app, /spotBadges\(t,/);
});

test('the freshness pill words freshness() without changing its state', () => {
  const now = Date.parse('2026-09-29T18:00:00Z');
  const pill = (epoch, ok = true) => freshnessPill({epoch, ...freshness(epoch, now, ok), now});
  assert.deepEqual(pill(now - 4 * 60000), {state: 'fresh', label: 'Buoy 4 min ago'});
  assert.deepEqual(pill(now - 125 * 60000), {state: 'stale', label: 'Buoy stale 2 h'});
  assert.deepEqual(pill(now - 3 * 86400000), {state: 'stale', label: 'Buoy stale 3 d'});
  assert.deepEqual(pill(NaN), {state: 'unavailable', label: 'Buoy unavailable'});
  assert.deepEqual(pill(now - 4 * 60000, false), {state: 'unavailable', label: 'Buoy update unavailable'});
  assert.equal(pill(now + 30 * 60000).state, 'unavailable');
  assert.equal(ageText(59 * 60000), '59 min');
  assert.equal(ageText(47 * 3600000), '47 h');
});
