// Confidence badges and freshness pills (P4-04): states come only from data
// the target already carries, never upgrade a claim, and the limitation text
// moved from the spot sheet survives word for word in web/disclaimers.ts.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {ageText, depthBadge, depthText, fishBadge, freshnessPill, spotBadges, terrainBadge} from '../web/confidence.ts';
import {FISH_UNVERIFIED, RESEARCH_ONLY_LOCATION} from '../web/disclaimers.ts';
import {buoyReading} from '../dist/live-conditions.js';

const read = path => readFileSync(new URL(`../${path}`, import.meta.url), 'utf8');
const atlas = path => JSON.parse(read(path)).targets;

test('every historical Morro Bay target is estimated depth with the research-only text open', () => {
  const targets = atlas('dist/data/atlas.json');
  assert.ok(targets.length > 100);
  for (const t of targets) {
    assert.equal(t.research_only, true);
    const badge = depthBadge(t, t.vertical_datum);
    assert.equal(badge.state, 'estimated', t.id);
    // The caveat's lead is the answer line's "Research-only" marker; the why is its text, open.
    assert.deepEqual(badge.why, {text: RESEARCH_ONLY_LOCATION.text});
    assert.equal(badge.open, true);
    assert.equal(depthText(t, badge), `~${t.center_depth_ft} ft (estimated)`);
  }
});

test('only depth-qualified targets screened on a named datum with stated uncertainty show qualified depth', () => {
  const qualified = atlas('dist/regions/southern-california/atlas.json');
  assert.ok(qualified.length > 0);
  for (const t of qualified) {
    const badge = depthBadge(t);
    assert.equal(badge.state, 'qualified', t.id);
    assert.notEqual(badge.open, true);
    assert.match(badge.why.text, /^Measured-depth screen on MLLW: /);
    const u = t.qualification.maximum_product_uncertainty_m;
    assert.ok(badge.why.text.includes(`uncertainty up to ${u} m (${(u * 3.28084).toFixed(1)} ft)`), badge.why.text);
    assert.match(badge.why.text, /verify on your sounder\.$/);
    assert.doesNotMatch(badge.why.text, /verified/i);
    assert.equal(depthText(t, badge), `${t.center_depth_ft} ft`);
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
    {...t, qualification: {...t.qualification, maximum_product_uncertainty_m: null}},
    {...t, qualification: {...t.qualification, maximum_product_uncertainty_m: undefined}},
    {...t, qualification: {...t.qualification, maximum_product_uncertainty_m: -1}},
  ]) assert.notEqual(depthBadge(weaker).state, 'qualified', JSON.stringify({q: weaker.depth_qualified, d: weaker.vertical_datum}));
  assert.equal(depthBadge({...t, research_only: true}).why.text, RESEARCH_ONLY_LOCATION.text);
  assert.equal(depthBadge({...t, center_depth_ft: null}).state, 'unknown');
  assert.equal(depthText({...t, center_depth_ft: null}), null);
  assert.equal(depthText({...t, depth_qualified: false}), `~${t.center_depth_ft} ft (estimated)`);
});

test('no badge says Verified', async () => {
  const {BADGE_WORD} = await import('../web/confidence.ts');
  assert.deepEqual(Object.values(BADGE_WORD), ['Qualified', 'Estimated', 'Unknown']);
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

const iso = epoch => new Date(epoch).toISOString();
/** A one-station feed as live-conditions.js reads it, generated `feedAge` ms before `now`. */
function observation(readingEpoch, now, {feedAge = 5 * 60000, status = 'ok'} = {}) {
  const feed = {schema_version: 1, generated_at: iso(now - feedAge), sources: {diablo: {status, data: {
    units: {WVHT: 'm'}, observations: Number.isFinite(readingEpoch) ? [{time: iso(readingEpoch), WVHT: 1}] : []}}}};
  const r = buoyReading(feed, 'diablo', now);
  return {station: '46215', epoch: r.waveTime, feedEpoch: r.feedTime, sourceStatus: r.sourceStatus};
}

test('the freshness pill judges the stored reading with freshness() at render time', () => {
  const now = Date.parse('2026-09-29T18:00:00Z');
  const pill = (epoch, options) => freshnessPill(observation(epoch, now, options), now);
  assert.deepEqual(pill(now - 4 * 60000), {state: 'fresh', label: 'Buoy 4 min ago'});
  assert.deepEqual(pill(now - 125 * 60000), {state: 'stale', label: 'Buoy stale 2 h'});
  assert.deepEqual(pill(now - 3 * 86400000), {state: 'stale', label: 'Buoy stale 3 d'});
  assert.deepEqual(pill(NaN), {state: 'unavailable', label: 'Buoy unavailable'});
  assert.deepEqual(pill(now - 4 * 60000, {status: 'error'}), {state: 'unavailable', label: 'Buoy update unavailable'});
  assert.deepEqual(pill(now - 4 * 60000, {feedAge: 100 * 60000}), {state: 'unavailable', label: 'Buoy update unavailable'});
  assert.equal(pill(now + 30 * 60000).state, 'unavailable');
  assert.deepEqual(freshnessPill(null, now), {state: 'unavailable', label: 'Buoy unavailable'});
  assert.equal(ageText(59 * 60000), '59 min');
  assert.equal(ageText(47 * 3600000), '47 h');
});

test('a pill left on screen ages: the same observation turns stale and the feed times out', () => {
  const loaded = Date.parse('2026-09-29T18:00:00Z');
  const o = observation(loaded - 20 * 60000, loaded);
  // The observation keeps times and state, never a label.
  assert.deepEqual(Object.keys(o).sort(), ['epoch', 'feedEpoch', 'sourceStatus', 'station']);
  assert.deepEqual(freshnessPill(o, loaded), {state: 'fresh', label: 'Buoy 20 min ago'});
  assert.deepEqual(freshnessPill(o, loaded + 60000), {state: 'fresh', label: 'Buoy 21 min ago'});
  // Feed generated 5 min before load: 86 minutes on it is no longer current.
  assert.deepEqual(freshnessPill(o, loaded + 86 * 60000), {state: 'unavailable', label: 'Buoy update unavailable'});
  // Past two hours old the reading itself is stale.
  assert.deepEqual(freshnessPill(o, loaded + 101 * 60000), {state: 'stale', label: 'Buoy stale 2 h'});
});

test('the pill ticks every 60 s and shows only the spot\'s own buoy', () => {
  const pill = read('web/components/FreshnessPill.tsx');
  assert.match(pill, /FRESHNESS_TICK_MS = 60_000/);
  assert.match(pill, /setInterval\(\(\) => setNow\(Date\.now\(\)\), FRESHNESS_TICK_MS\)/);
  assert.match(pill, /clearInterval\(timer\)/);
  const row = read('web/components/SpotConfidence.tsx');
  assert.match(row, /const observation = buoy \? latest\[buoy\] \?\? null : null;/);
  const weather = read('dist/weather-ui.js');
  assert.doesNotMatch(weather, /buoyReadingStatus/);
  assert.match(weather, /nearshoreBuoy\(p\) \{\n\s+return localContext\(nearestPoint\(p\)\)\.stations\?\.nearshore_buoy \|\| null;/);
  assert.match(read('dist/app.js'), /buoy:weather\?\.nearshoreBuoy\(t\)\?\?null/);
});

test('every path that replaces the spot sheet without a spot clears spotConfidence', () => {
  const app = read('dist/app.js');
  const writes = [...app.matchAll(/\$\("detail"\)\.innerHTML\s*=/g)];
  assert.ok(writes.length >= 3, `found ${writes.length} writes to #detail`);
  for (const {index} of writes) {
    // The function body up to this write.
    const start = app.lastIndexOf('\nfunction ', index);
    const body = app.slice(start, app.indexOf('\n}\n', index));
    const before = app.slice(Math.max(start, index - 200), index);
    const setsSpot = /spotConfidence\.value=\{id:t\.id,/.test(body);
    assert.ok(setsSpot || /spotConfidence\.value = null;\s*$/.test(before),
      `#detail replaced without clearing spotConfidence near: ${app.slice(index - 80, index + 40)}`);
  }
  // The research-only answer line: marker and estimated depth come from the shared helpers.
  assert.match(app, /<span class="research-marker">\$\{RESEARCH_ONLY_MARKER\}<\/span>/);
  assert.match(app, /depth=depthText\(t,badges\[0\]\)/);
});
