import assert from 'node:assert/strict';
import {globSync, readFileSync} from 'node:fs';
import test from 'node:test';
import {fileURLToPath} from 'node:url';
import {resolveRelief, selectReliefArchives} from '../web/map/relief-data.ts';

const morro = 'morro-bay';
const draft = 'channel-islands-north';
const sha = digit => digit.repeat(64);
const source = (id = 'fixture-survey', label = 'measured') => ({
  id, label, rights_class: 'public', rights: {public_display: 'allowed'},
  attribution: 'Synthetic survey', survey_dates: ['2024-01-02', '2024-01-03'],
  release_date: '2025-02-01', vertical_datum: 'NAVD88',
});
const band = (resolution_m, min_depth_m, max_depth_m, support_class = 3, source_id = 'fixture-survey') =>
  ({source_id, min_depth_m, max_depth_m, resolution_m, support_class});
// Same row shape as the builder: overlapping source counts are not additive.
const zoom = (resolution_m, {limit_m = 91.44, support_class, id = 'fixture-survey'} = {}) => ({
  tiles: 2, limit_m, support_class, sources: resolution_m ? [{id, resolution_m, tiles: 2}] : [],
});
function pointer(region = morro, bounds = [-122, 34, -120, 36]) {
  return {
    region, sha256: sha('a'), bytes: 4096, digest_root_sha256: sha('b'),
    release_sha256: sha('c'), envelope_sha256: sha('d'), private: false,
    minzoom: 13, maxzoom: 14, bounds, sources: [source()],
    detail_summary: {mask: 'transparent-nodata', depth_bands: [band(2, 0, 20), band(2, 20, 91.44)]},
    native_support_by_zoom: {13: zoom(), 14: zoom(2, {support_class: 3})},
  };
}

function ready(p, observed) {
  const result = resolveRelief(p.region, p, observed);
  assert.equal(result.status, 'ready', JSON.stringify(result));
  return result.archive;
}
const unavailable = reason => ({status: 'unavailable', reason});

const regionsRoot = new URL('../regions/', import.meta.url);
const regions = globSync('*/region.json', {cwd: fileURLToPath(regionsRoot)}).sort().map(path =>
  JSON.parse(readFileSync(new URL(path, regionsRoot), 'utf8')).id);

test(`all ${regions.length} region definitions resolve their own binding, including drafts, with no Morro fallback`, () => {
  assert.ok(new Set(regions).size >= 22);
  const pointers = new Map(regions.map(id => [id, pointer(id)]));
  for (const id of regions) {
    assert.equal(ready(pointers.get(id)).object_key, `tiles/relief/${id}/${sha('a')}.pmtiles`);
    if (id !== morro) assert.deepEqual(resolveRelief(id, pointers.get(morro)), unavailable('wrong-region'), id);
  }
  const selected = selectReliefArchives([draft, 'unlisted'], new Map([[morro, pointer()]]));
  assert.deepEqual(selected.archives, []);
  assert.deepEqual([...selected.unavailable], [[draft, 'missing'], ['unlisted', 'missing']]);
});

test('one object for shared bytes; overlapping distinct archives and regional bounds are kept', () => {
  const other = 'santa-barbara-channel';
  const p = new Map([[morro, pointer()], [draft, pointer(draft, [-121, 34, -120, 35])],
    [other, {...pointer(other), sha256: sha('e')}]]);
  const selected = selectReliefArchives([morro, draft, other, morro], p);
  assert.deepEqual(selected.archives.map(group => group.bindings.map(({region, bounds}) => [region, bounds])), [
    [[morro, p.get(morro).bounds], [draft, p.get(draft).bounds]], [[other, p.get(other).bounds]],
  ]);
  assert.deepEqual([...selected.unavailable], []);
  p.get(draft).digest_root_sha256 = sha('f');
  const conflict = selectReliefArchives([morro, draft, other], p);
  assert.deepEqual(conflict.archives.map(group => group.archive.region), [other]);
  assert.deepEqual([...conflict.unavailable], [[morro, 'identity'], [draft, 'identity']]);
});

test('held, unreviewed, malformed identities and changed whole-object receipts are refused', () => {
  for (const [edit, reason] of [
    [{status: 'held', previous: pointer()}, 'unreviewed'], [{status: 'pending'}, 'unreviewed'],
    [{release_sha256: undefined}, 'unreviewed'], [{envelope_sha256: undefined}, 'unreviewed'],
    [{sha256: 'etag'}, 'identity'], [{bytes: 0}, 'identity'], [{digest_root_sha256: undefined}, 'identity'],
    [{bounds: [-120, 34, -122, 36]}, 'metadata'], [{detail_summary: {depth_bands: [band(2, 0, 20)]}}, 'metadata'],
  ]) assert.deepEqual(resolveRelief(morro, {...pointer(), ...edit}), unavailable(reason), JSON.stringify(edit));
  const p = pointer();
  const receipt = {sha256: p.sha256, bytes: p.bytes, digest_root_sha256: p.digest_root_sha256};
  const {sha256, bytes, digest_root_sha256} = ready(p, receipt);
  assert.deepEqual({sha256, bytes, digest_root_sha256}, receipt);
  const replacement = {...p, sha256: sha('f')};
  assert.deepEqual(resolveRelief(morro, replacement, receipt), unavailable('identity'));
  assert.deepEqual(resolveRelief(morro, p, {...receipt, bytes: 8192}), unavailable('identity'));
  assert.deepEqual(resolveRelief(morro, p, {...receipt, digest_root_sha256: sha('f')}), unavailable('identity'));
});

// Contract: DATA-LIVE-9 rights basis. Lineage names and unconfirmed terms are not refusals (G 2026-11-18);
// private rows, rows without explicit public-display rights and MBARI stay refused. Believable bugs: re-adding a
// name regex that refuses CSUMB/SFML again, or dropping the private/MBARI refusals along with it.
test('private, MBARI and sources lacking explicit public-display rights never select', () => {
  const clean = pointer();
  for (const p of [
    {...clean, private: true}, {...clean, private: undefined}, {...clean, sources: []},
    ...[
      {private: true},
      {id: 'mbari-survey'}, {attribution: 'Monterey Bay Aquarium Research Institute'}, {provider: 'MBARI'},
      {rights: {public_display: 'allowed', terms_url: 'https://www.mbari.org/data/'}},
      {rights: {public_display: 'excluded'}},
      {rights: {public_display: 'private'}}, {rights: {}}, {rights_class: 'excluded'},
    ].map(edit => ({...clean, sources: [...clean.sources, {...source('other-survey'), ...edit}]})),
  ]) {
    const selected = selectReliefArchives([morro], new Map([[morro, p]]));
    assert.deepEqual(selected.archives, []);
    assert.equal(selected.unavailable.get(morro), 'private');
  }
  const shared = selectReliefArchives([morro], new Map([[morro, clean], [draft, {...pointer(draft), private: true}]]));
  assert.deepEqual(shared.archives, []);
  assert.equal(shared.unavailable.get(morro), 'private', 'a public alias cannot admit the same held bytes');
});

test('CSUMB/SFML lineage, unresolved terms and withheld raw-file redistribution resolve ready under the G 2026-11-18 basis', () => {
  // One source whose row carries the edit, with bands and zoom rows bound to its id: only the rights fields vary.
  const withRow = edit => {
    const id = edit.id ?? 'fixture-survey', p = pointer();
    p.sources = [{...source(id), ...edit}];
    p.detail_summary.depth_bands = [band(2, 0, 20, 3, id), band(2, 20, 91.44, 3, id)];
    p.native_support_by_zoom = {13: zoom(), 14: zoom(2, {support_class: 3, id})};
    return p;
  };
  for (const edit of [
    {id: 'csumb-ventresca-cc2-blocka01'}, {id: 'fixture-sfml-survey'},
    {attribution: 'California State University, Monterey Bay Seafloor Mapping Lab'}, {provider: 'CSUMB SFML'},
    // Morro Bay's own USGS-CSUMB CSMP rows mention CSUMB.
    {provider: 'USGS', attribution: 'USGS and CSUMB, CSMP'},
    {rights: {public_display: 'allowed', license: 'unresolved'}},
    {rights: {public_display: 'allowed', terms_url: 'https://csumb.edu/undersea/sfml-data-library/'}},
    // Raw-file redistribution is a separate decision and stays off; it must not hide derived shading.
    {publication_allowed: false, review_status: 'restricted', rights: {public_display: 'allowed', redistribution_reviewed: false}},
    {review_status: 'candidate'},
  ]) {
    const archive = ready(withRow(edit));
    assert.equal(archive.sources[0].public_display, 'allowed', JSON.stringify(edit));
    // The relaxation changes rights only: depth-band tiering for this source is the usual integrity result.
    assert.deepEqual(archive.depth_bands.map(({tier}) => tier), ['estimated', '2m'], JSON.stringify(edit));
  }
  // Still integrity-checked: a CSUMB-lineage row cannot skip the identity or resolution checks.
  assert.deepEqual(resolveRelief(morro, {...withRow({id: 'csumb-x'}), sha256: 'etag'}), unavailable('identity'));
  assert.deepEqual(resolveRelief(morro, {...withRow({id: 'csumb-x'}), detail_summary: {mask: 'transparent-nodata', depth_bands: []}}), unavailable('unknown-resolution'));
});

test('depth bands and native zoom detail preserve evidence, clocks and no-data distinctions', () => {
  const p = pointer();
  p.maxzoom = 15;
  p.native_support_by_zoom[15] = {...zoom(2, {support_class: 3}), sources: [
    ...zoom(2).sources, ...zoom(5, {id: 'coarser-survey'}).sources,
  ]};
  p.native_support_by_zoom[16] = {tiles: 0, sources: [], limit_m: 20};
  p.sources.push(source('coarser-survey'));
  p.detail_summary.depth_bands.push(band(5, 20, 91.44, 3, 'coarser-survey'));
  const archive = ready(p);
  assert.deepEqual(archive.native_support_by_zoom[13], ['estimated']);
  assert.deepEqual(archive.native_support_by_zoom[15], ['2m', '5m', 'estimated']);
  assert.deepEqual(archive.native_support_by_zoom[16], ['none']);
  assert.deepEqual(archive.depth_bands.map(({tier}) => tier), ['estimated', '2m', '5m']);
  assert.equal(archive.mask, 'transparent-nodata');
  assert.equal(archive.sources[0].public_display, 'allowed');
  assert.equal(archive.sources[0].vertical_datum, 'NAVD88');
  assert.deepEqual(archive.sources[0].survey_dates, ['2024-01-02', '2024-01-03']);
  assert.equal(archive.sources[0].release_date, '2025-02-01');
  p.native_support_by_zoom[14].sources[0].resolution_m = null;
  assert.deepEqual(resolveRelief(morro, p), unavailable('unknown-resolution'));
});

test('1 m interpolated, compiled or uncertified data never earn a measured chip', () => {
  for (const [label, support_class, sourceEstimated] of [
    ['interpolated', 3, true], ['compiled', 3, true], ['measured', undefined, false],
  ]) {
    const p = pointer();
    p.sources = [source('fixture-survey', label)];
    p.detail_summary.depth_bands = [band(1, 0, 20, support_class ?? 2)];
    p.native_support_by_zoom[14] = zoom(1, {support_class});
    const archive = ready(p);
    assert.equal(archive.sources[0].estimated, sourceEstimated);
    assert.deepEqual(archive.native_support_by_zoom[14], ['estimated']);
    assert.equal(archive.depth_bands[0].tier, 'estimated');
  }
});

test('z16–17 require certified 1 m water pixels in the shallow band; z18 is never admitted', () => {
  const p = pointer();
  p.maxzoom = 17;
  p.detail_summary.depth_bands = [band(1, 0, 20)];
  p.native_support_by_zoom[14] = zoom(1, {support_class: 3});
  p.native_support_by_zoom[15] = zoom(1, {support_class: 3});
  p.native_support_by_zoom[16] = zoom(1, {limit_m: 20, support_class: 3});
  p.native_support_by_zoom[17] = zoom(1, {limit_m: 20, support_class: 3});
  const dedicated = ready(p);
  assert.deepEqual(dedicated.native_support_by_zoom[16], ['1m']);
  assert.deepEqual(dedicated.native_support_by_zoom[17], ['1m']);
  assert.equal(dedicated.depth_bands[0].tier, '1m');
  for (const edit of [
    f => { delete f.native_support_by_zoom[17].support_class; },
    f => { f.native_support_by_zoom[17].limit_m = 91.44; },
    f => { f.native_support_by_zoom[17].sources[0].resolution_m = 2; },
    f => { f.detail_summary.depth_bands[0].support_class = 2; },
    f => { f.sources[0].label = 'interpolated'; },
    f => { f.native_support_by_zoom[18] = zoom(1, {limit_m: 20, support_class: 3}); },
  ]) {
    const candidate = structuredClone(p);
    edit(candidate);
    assert.deepEqual(resolveRelief(morro, candidate), unavailable('unknown-resolution'));
  }
  assert.deepEqual(resolveRelief(morro, {...p, maxzoom: 18}), unavailable('metadata'));
});
