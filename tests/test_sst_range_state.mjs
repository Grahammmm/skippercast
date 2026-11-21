import assert from 'node:assert/strict';
import test from 'node:test';
import {shareLink} from '../web/share-link.ts';
import {configureStore, sstRange, sstRangeParam, syncFromURL, withParams} from '../web/state.ts';

const origin = 'https://s.test';
const address = `${origin}/map?view=35%2C-121%2C10&layers=water-temp`;
const share = href => shareLink({href, origin, ports: null, region: 'morro-bay', savedId: null,
  profile: 'boat', now: new Date('2026-11-07T12:00:00Z'), tz: 'UTC'}).url;
const analysis = {mode: 'analysis'};
const rawRange = value => `${address}&sstRange=${encodeURIComponent(value)}`;
configureStore({v2: true, storage: null});

test('valid ranges survive writing, sharing and reopening', () => {
  // Catch loss of the view mode, truncation of half steps and off-by-one bounds.
  for (const [range, wire] of [
    [{mode: 'view'}, 'view'],
    [{mode: 'custom', min: 57, max: 59}, '57-59'],
    [{mode: 'custom', min: 57.5, max: 58}, '57.5-58'],
    [{mode: 'custom', min: 57, max: 57.5}, '57-57.5'],
    [{mode: 'custom', min: 57.5, max: 58.5}, '57.5-58.5'],
    [{mode: 'custom', min: 28, max: 100}, '28-100'],
  ]) {
    const href = withParams(address, {sstRange: sstRangeParam(range)});
    assert.equal(href, rawRange(wire));
    const link = share(href);
    assert.deepEqual(new URL(link).searchParams.getAll('sstRange'), [wire]);
    syncFromURL(address);
    syncFromURL(link);
    assert.deepEqual(sstRange.value, range);
  }
  // A hand-edited URL uses the same grammar; sharing writes canonical numbers.
  const padded = rawRange('057.5-059');
  syncFromURL(padded);
  assert.deepEqual(sstRange.value, {mode: 'custom', min: 57.5, max: 59});
  assert.equal(new URL(share(padded)).searchParams.get('sstRange'), '57.5-59');
});

test('malformed, ambiguous and invalid ranges reset the signal and stay out of shared links', () => {
  // Catch permissive numeric conversion, ignored suffixes, missing validation or first-value wins.
  const invalid = ['', 'analysis', 'VIEW', 'view ', 'garbage', '57', '57-', '-59', '57--59', '57-59-60',
    '59-57', '57.5-57.5', '27.5-59', '57-100.5', 'NaN-59', '57-Infinity',
    '57.25-59', '57-59.1', '57.500000000000001-59', '57.0-59', '57-59.50', '.5-59',
    '5.7e1-59', '0x39-59', '+57-59', '57 -59', '57–59', '57-59\n', '57-59\0', '57-59%'];
  const legacy = share(address);
  for (const href of [...invalid.map(rawRange), `${rawRange('view')}&sstRange=view`, `${rawRange('view')}&sstRange=57-59`]) {
    syncFromURL(rawRange('view'));
    syncFromURL(href);
    assert.deepEqual(sstRange.value, analysis, href);
    assert.equal(share(href), legacy, href);
  }
  assert.equal(withParams(rawRange('view'), {sstRange: '57.25-59'}), address);
});

test('analysis reset removes the parameter and leaves the legacy share URL byte-identical', () => {
  // Catch a sticky range on navigation, or an explicit default written into old links.
  syncFromURL(rawRange('57-59'));
  const reset = withParams(rawRange('57-59'), {sstRange: sstRangeParam(analysis)});
  assert.equal(reset, address);
  syncFromURL(reset);
  assert.deepEqual(sstRange.value, analysis);
  assert.equal(share(reset), `${origin}/map?region=morro-bay&profile=boat&day=2026-11-07&view=35%2C-121%2C10&layers=water-temp`);
});
