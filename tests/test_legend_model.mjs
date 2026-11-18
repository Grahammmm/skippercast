// CI-ARTICLE-1: each test names the contract it protects and the believable bug that fails it.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import test from 'node:test';
import {NOT_FOR_NAVIGATION_ID, contourCopy, depthChips, shallowBand, surveyDetailChips} from '../web/map/legend-model.ts';

const bold = chips => chips.filter(c => c.bold).map(c => c.id);

// Contract: chips light only for classes drawn in view (MB-11 acceptance 1). Bug: all chips bold,
// or the 2 m chip dropped because 2 m "is not allowed" outside the shallow rule.
test('only 2 m and no survey in view: those two are bold, the rest grey, in fixed order', () => {
  const chips = surveyDetailChips(new Set(['2m', 'none']));
  assert.deepEqual(chips.map(c => c.id), ['1m-measured', '2m', '5m', '4-16m-compiled', 'estimated', 'none']);
  assert.deepEqual(bold(chips), ['2m', 'none']);
  assert.deepEqual(bold(surveyDetailChips(new Set())), [], 'an empty view lights nothing');
});

// Contract: MB-09's per-cell tier governs, never the nominal grid (a 1 m grid interpolated is "estimated").
// Bug: the legend keys off grid size and lights `1m-measured` for an interpolated 1 m surface.
test('an interpolated 1 m grid arrives as estimated and never lights 1m-measured', () => {
  const chips = surveyDetailChips(new Set(['estimated']));
  assert.deepEqual(bold(chips), ['estimated']);
  assert.equal(chips[0].bold, false);
});

// Contract: the 0-66 ft band is 1m-measured or estimated only (E2E-IMPL-BATCH MB-11 amendment).
// Bug: a measured 2 m survey in the shallows lights `2m`, implying 2 m detail in the spearfishing band.
test('2 m (or 5 m, or compiled) only in 0-66 ft makes estimated bold and its own chip grey', () => {
  for (const id of ['2m', '5m', '4-16m-compiled']) {
    const shallow = new Set([id]);
    assert.deepEqual(bold(surveyDetailChips(new Set([id]), shallow)), ['estimated'], id);
  }
  // Shallow-only classes count as in view even if the caller left them out of the full set.
  assert.deepEqual(bold(surveyDetailChips(new Set(), new Set(['2m']))), ['estimated']);
});

// Contract: the rule applies to the shallows only. Bug: 2 m is hidden everywhere once the rule exists.
test('2 m that also reaches deeper water keeps its chip; measured 1 m in the shallows stays 1m-measured', () => {
  assert.deepEqual(bold(surveyDetailChips(new Set(['2m', 'none']), new Set(['none']))), ['2m', 'none']);
  assert.deepEqual(bold(surveyDetailChips(new Set(['1m-measured', '2m']), new Set(['1m-measured']))), ['1m-measured', '2m']);
  assert.deepEqual(bold(surveyDetailChips(new Set(['1m-measured', '2m']), new Set(['1m-measured', '2m']))), ['1m-measured', 'estimated']);
});

// Contract: shallow and deeper presence are independent. Bug (review RETURN at 4abe17f): a class in both
// bands was kept out of the shallow set, so `2m` lit but `estimated` stayed grey for the shallow area.
test('2 m in both 0-66 ft and deeper water lights both 2m and estimated', () => {
  const both = new Set(['2m']);
  assert.deepEqual(bold(surveyDetailChips(new Set(['2m']), both, both)), ['2m', 'estimated']);
  assert.deepEqual(bold(surveyDetailChips(new Set(), both, both)), ['2m', 'estimated'], 'band sets count even if absent from the view set');
  // 5 m and compiled behave the same; a deeper-only class does not light estimated.
  assert.deepEqual(bold(surveyDetailChips(new Set(['5m']), new Set(['5m']), new Set(['5m']))), ['5m', 'estimated']);
  assert.deepEqual(bold(surveyDetailChips(new Set(['2m']), new Set(), new Set(['2m']))), ['2m']);
  // A 1 m measured class in both bands is one chip, not two.
  assert.deepEqual(bold(surveyDetailChips(new Set(['1m-measured']), new Set(['1m-measured']), new Set(['1m-measured']))), ['1m-measured']);
});

// Contract: only MB-22's decode keys light chips. Bug: a stray key ("1m", "unknown") or a prototype name lights something.
test('unknown classes light nothing', () => {
  assert.deepEqual(bold(surveyDetailChips(new Set(['1m', 'unknown', 'constructor', '']))), []);
  assert.deepEqual(bold(surveyDetailChips(new Set(), new Set(['1m', 'toString']))), []);
});

// Contract: v1 keeps today's ids byte for byte (MB-11 amendment); they must exist in the live catalogue.
// Bug: the v1 branch is renamed or gets the v2 ids, changing a live Morro legend.
test('v1 and an absent set return today\'s ids, all present in the catalogue', () => {
  const today = {label: 'layer.depth-contours.label', summary: 'legend.bs.depth', basis: 'layer.depth-contours.basis',
    legend: ['layer.depth-contours.legend0', 'layer.depth-contours.legend1'],
    plannerLabel: 'planner.layer.contours', plannerText: 'planner.layer.contours.text'};
  for (const set of ['v1', undefined]) {
    const {set: shown, notForNavigation, ...ids} = contourCopy(set);
    assert.equal(shown, 'v1');
    assert.deepEqual(ids, today);
    assert.equal(notForNavigation, 'legend.notForNav');
  }
  const catalogue = readFileSync(new URL('../catalog/app/strings.json', import.meta.url), 'utf8');
  for (const id of [...Object.values(today).flat(), NOT_FOR_NAVIGATION_ID]) {
    assert.ok(catalogue.includes(`"${id}":`), `${id} is in catalog/app/strings.json`);
  }
});

// Contract: ft-v2 shows v2 copy (basis, legend, planner), never the v1 "30 ft to 600 ft" ids.
// Bug: ft-v2 falls through to v1 and tells the user the lines run to 600 ft every 30 ft.
test('ft-v2 returns the v2 ids and none of the v1 basis, legend or planner ids', () => {
  const v1 = contourCopy('v1'), v2 = contourCopy('ft-v2');
  assert.equal(v2.set, 'ft-v2');
  assert.equal(v2.basis, 'layer.depth-contours.v2.basis');
  assert.deepEqual(v2.legend, ['layer.depth-contours.v2.legend0', 'layer.depth-contours.v2.legend1']);
  assert.equal(v2.plannerText, 'layer.depth-contours.v2.planner');
  for (const key of ['basis', 'plannerText']) assert.notEqual(v2[key], v1[key]);
  for (const i of [0, 1]) assert.notEqual(v2.legend[i], v1.legend[i]);
  assert.equal(v2.label, v1.label, 'the row keeps one name');
  assert.throws(() => contourCopy('ft-v3'), RangeError, 'an unknown set never shows possibly-wrong copy');
});

// Contract: NOT FOR NAVIGATION is always present. Bug: the v2 branch builds a fresh object and drops it.
test('the not-for-navigation id is on every copy', () => {
  assert.equal(NOT_FOR_NAVIGATION_ID, 'legend.notForNav');
  for (const set of ['v1', 'ft-v2', undefined]) assert.equal(contourCopy(set).notForNavigation, NOT_FOR_NAVIGATION_ID);
});

// Contract: G 11-18, no source names on the map; the model returns ids only. Bug: an id like
// `legend.surveyDetail.usgs` or a chip keyed by source leaks a provider into the legend.
test('no source name in any returned id', () => {
  const sources = /usgs|csumb|noaa|bluetopo|coned|cudem|ngdc|ncei|cdfw|nasa|ucsb|scripps|lidar/i;
  const ids = [NOT_FOR_NAVIGATION_ID];
  for (const set of ['v1', 'ft-v2', undefined]) {
    const c = contourCopy(set);
    ids.push(c.label, c.summary, c.basis, ...c.legend, c.plannerLabel, c.plannerText);
  }
  for (const c of surveyDetailChips(new Set(['1m-measured', '2m', '5m', '4-16m-compiled', 'estimated', 'none']))) ids.push(c.id, c.labelId);
  for (const id of ids) assert.doesNotMatch(id, sources, id);
});

// Contract: 11 ramp-B chips, 0 ... 300+ ft as numbers, tokens not colours; light adds the ring (§ 10.2).
// Bug: a hand-typed hex in the module (check_tokens lint) or a 10-chip ramp missing "300+".
test('depth chips: 11 in order with numeric feet, token names, light ring, resolved only from a palette', () => {
  const dark = depthChips('dark'), light = depthChips('light');
  assert.deepEqual(dark.map(c => c.feet), [0, 10, 20, 33, 50, 66, 100, 150, 200, 300, 300]);
  assert.deepEqual(dark.map(c => c.orMore), [...Array(10).fill(false), true]);
  assert.deepEqual(dark.map(c => c.token), Array.from({length: 11}, (_, i) => `depthB${i}`));
  assert.ok(dark.every(c => c.ring === false && c.color === undefined));
  assert.ok(light.every(c => c.ring === true));
  assert.deepEqual(light.map(c => c.token), dark.map(c => c.token), 'ramp B is identical in both themes');
  assert.equal(depthChips('dark', {depthB3: 'x'})[3].color, 'x');
  assert.deepEqual(shallowBand('light'), {token: 'depthB0', fromFeet: 0, toFeet: 66, ring: true});
  assert.equal(shallowBand('dark').ring, false);
});

// Contract: web/ holds no colour literals (scripts/check_tokens.mjs). Bug: a ramp hex pasted into the model.
test('the model source holds no colour literal', () => {
  const source = readFileSync(new URL('../web/map/legend-model.ts', import.meta.url), 'utf8');
  assert.doesNotMatch(source, /#[0-9a-fA-F]{3,8}\b|\b(?:rgb|rgba|hsl|hsla)\(/);
});
