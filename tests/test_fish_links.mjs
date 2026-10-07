import test from 'node:test';
import assert from 'node:assert/strict';
import {FISH_REGIONS, canonicalHour, fishLink} from '../web/fish-links.ts';
import {configureStore, profile, species, hour, readURL, syncFromURL, withParams} from '../web/state.ts';

test('the actual Fish shore link keeps its place, date, target and selected UTC hour', () => {
  const input = 'https://skippercast.com/map?mode=shore&area=central&day=2026-10-06&species=surfperch&layer=opportunity&view=coast&place=morro&hour=2026-10-07T05%3A00%3A00.000Z#ocean-map';
  const u = fishLink(input);
  assert.equal(u.searchParams.get('region'), 'morro-bay');
  assert.equal(u.searchParams.get('profile'), 'shore');
  assert.equal(u.searchParams.get('target'), 'surfperch');
  assert.equal(u.searchParams.get('hour'), '2026-10-07T05:00Z');
  assert.equal(u.searchParams.get('layers'), 'seafloor');
  for (const key of ['place', 'day', 'area', 'view']) assert.equal(u.searchParams.get(key), new URL(input).searchParams.get(key));
  assert.equal(u.hash, '#ocean-map');
  assert.equal(fishLink(u.href).href, u.href, 'normalization is idempotent');
  assert.equal(input.includes('mode=shore'), true, 'input is not mutated');
});

test('explicit canonical values, including an empty choice, win over aliases', () => {
  const u = fishLink('https://s.test/map?region=southern-california&place=morro&profile=boat&mode=spear&target=&species=lingcod&layers=none&layer=currents');
  assert.equal(u.searchParams.get('region'), 'southern-california');
  assert.equal(u.searchParams.get('profile'), 'boat');
  assert.equal(u.searchParams.get('target'), '');
  assert.equal(u.searchParams.get('layers'), 'none');
  for (const key of ['mode', 'species', 'layer']) assert.equal(u.searchParams.has(key), false);
});

test('geography is explicit and an unknown place cannot inherit a SLO binding', () => {
  for (const [place, region] of Object.entries(FISH_REGIONS)) assert.equal(fishLink(`https://s.test/map?place=${place}`).searchParams.get('region'), region);
  assert.equal(fishLink('https://s.test/map?place=coast').searchParams.get('coast'), 'central');
  assert.equal(fishLink('https://s.test/map?mode=boat&area=north').searchParams.get('region'), 'cambria-san-simeon');
  assert.equal(fishLink('https://s.test/map?place=unknown&area=central').searchParams.get('region'), null);
  assert.equal(fishLink('https://s.test/map?coast=south&place=morro').searchParams.get('region'), null);
  const unknown = fishLink('https://s.test/map?mode=kayak&layer=unknown&species=custom-fish');
  assert.equal(unknown.searchParams.get('profile'), null);
  assert.equal(unknown.searchParams.get('layers'), null);
  assert.equal(unknown.searchParams.get('target'), 'custom-fish', 'never substitutes a known species');
});

test('whole-hour ISO forms agree; impossible dates, offsets and partial hours are rejected', () => {
  for (const value of ['2026-10-07T05:00Z', '2026-10-07T05:00:00Z', '2026-10-07T05:00:00.000Z']) assert.equal(canonicalHour(value), '2026-10-07T05:00Z');
  for (const value of [null, '', '2026-02-30T05:00Z', '2026-10-07T24:00Z', '2026-10-07T05:30Z', '2026-10-07T05:00:01Z', '2026-10-07T05:00:00.001Z', '2026-10-07T05:00+00:00']) assert.equal(canonicalHour(value), null, String(value));
});

test('inherited property names cannot become data packages or layers', () => {
  for (const key of ['constructor', 'toString', '__proto__', 'hasOwnProperty']) {
    const u = fishLink(`https://s.test/map?place=${key}&area=${key}&layer=${key}`);
    assert.equal(u.searchParams.get('region'), null, key);
    assert.equal(u.searchParams.get('layers'), null, key);
    assert.equal(u.searchParams.get('layer'), key, 'unknown alias is retained');
  }
});

test('shared store understands Fish only in v2; changing a choice does not resurrect its alias', () => {
  const input = 'https://s.test/map?mode=spear&species=cabezon-shallow-reef&place=cambria&hour=2026-10-07T05:00:00.000Z';
  configureStore({v2: false, storage: null});
  assert.equal(readURL(input).profile, null, 'legacy store behavior retained');
  configureStore({v2: true, storage: null});
  syncFromURL(input);
  assert.equal(profile.value, 'spear');
  assert.equal(species.value, 'cabezon-shallow-reef');
  assert.equal(hour.value, '2026-10-07T05:00Z');
  const changed = withParams(input, {profile: 'boat', target: null});
  assert.equal(readURL(changed).target, null);
  assert.equal(readURL(changed).profile, 'boat');
  for (const input of ['https://s.test/map?place=monterey&mode=boat', 'https://s.test/map?area=north&mode=boat']) for (const empty of [null, '']) {
    const cleared = withParams(input, {region: empty, coast: empty});
    assert.equal(readURL(cleared).region, null, 'clearing geography cannot resurrect a Fish alias');
    assert.equal(readURL(cleared).coast, null);
  }
  syncFromURL(input);
  assert.equal(profile.value, 'spear', 'Back/Forward can restore the original shared link');
  configureStore({v2: false, storage: null});
});
