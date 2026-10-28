import assert from 'node:assert/strict';
import test, {beforeEach, afterEach} from 'node:test';
import {installOffline} from './fixtures/sp1402_nearshore_product/offline.mjs';
import {NOW, AT, TZ, HOUR, iso, site, sites, source, CDIP, OTHER, report} from './fixtures/sp1402_nearshore_product/report.mjs';

const restoreImport = installOffline();
const {nearshoreRings, ringMark, ringSummary, ringRadius, ringHitLayer, ringLayer} = await import('../web/map/nearshore.ts');
restoreImport();
let restoreCase;
beforeEach(() => { restoreCase = installOffline(); });
afterEach(() => { restoreCase(); });
const rings = (r = report(), at = AT, now = NOW) => nearshoreRings(r, 'central', at, now);
const card = (r, id, tz = TZ) => ringMark(r, id, NOW, tz);
function attribution(mark, product, url) {
  assert.equal(mark.kind, `${product} model site`);
  assert.ok(mark.source.startsWith(`${product} · sample `), mark.source);
  assert.ok(mark.basis.includes(`${product} nearshore model sites from the bound coast report:`), mark.basis);
  assert.deepEqual(mark.provider, {href: url, label: `${product} model site`});
  assert.match(mark.basis, /Model output, not a buoy observation and not breakers at a beach\./);
}

// A4: exactly this pair is registered in baseline mode; identical bytes after fix.
test('primary regression', t => {
  const r = rings();
  let mark, observedException = null;
  try { mark = card(r, 'synthetic-b'); } catch (error) { observedException = {name: error.name, message: error.message}; }
  t.diagnostic(JSON.stringify({observedException, observedCard: mark ?? null, summary: ringSummary(r, NOW)}));
  assert.equal(observedException, null, 'complete module must produce the synthetic card');
  assert.equal(mark.kind, 'Synthetic Other model site', 'SP1402_A1_SECOND_KIND');
  attribution(mark, 'Synthetic Other', 'https://example.test/model-b');
  attribution(card(r, 'synthetic-a'), 'CDIP MOP', 'https://example.test/model-a');
  assert.equal(r.product, 'multiple nearshore models');
  assert.equal(ringSummary(r, NOW), '2 nearshore model sites · multiple nearshore models · issued 6 h ago · ring 4 px + 3 px per ft');
});

test('healthy control', () => {
  const r = rings(report(sites().map(s => ({...s, sourceId: 'cdip-mop'}))));
  assert.equal(r.product, 'CDIP MOP');
  assert.equal(ringSummary(r, NOW), '2 nearshore model sites · CDIP MOP · issued 6 h ago · ring 4 px + 3 px per ft');
  for (const s of r.rings.map(x => x.site)) attribution(card(r, s.id), 'CDIP MOP', s.url);
});

if (process.env.SP1402_TEST_SUITE !== 'baseline') {
  test('A1 attribution is per clicked site regardless of site and source ordering', () => {
    const forward = rings(), reversed = rings(report(sites().reverse(), [OTHER, CDIP]));
    for (const id of ['synthetic-a', 'synthetic-b']) assert.deepEqual(card(reversed, id), card(forward, id));
    assert.equal(reversed.product, 'multiple nearshore models');
    assert.deepEqual(reversed.rings.map(r => r.site.id), ['synthetic-b', 'synthetic-a']);
    assert.equal(ringSummary(reversed, NOW), ringSummary(forward, NOW));
  });

  test('A2 single and same-product CDIP preserve complete card and summary wording', () => {
    const r = rings(report([site()]));
    assert.equal(r.product, 'CDIP MOP');
    assert.equal(ringSummary(r, NOW), '1 nearshore model site · CDIP MOP · issued 6 h ago · ring 4 px + 3 px per ft');
    const mark = card(r, 'synthetic-a');
    assert.deepEqual([mark.id, mark.name, mark.kind, mark.reading],
      ['nearshore:synthetic-a|2026-10-09T20:00:00.000Z', 'Synthetic Alpha', 'CDIP MOP model site', '3.8 ft · 13.0 s · from WNW 290°']);
    assert.match(mark.source, /^CDIP MOP · sample Oct 9, 1:00\s?PM PDT · 1h model sampling · issued 6 h ago$/);
    assert.match(card(r, 'synthetic-a', 'UTC').source, /^CDIP MOP · sample Oct 9, 8:00\s?PM UTC · 1h model sampling · issued 6 h ago$/);
    assert.equal(mark.basis, 'Model issued 2026-10-09T12:00:00.000Z; retrieved 2026-10-09T17:00:00.000Z. CDIP MOP nearshore model sites from the bound coast report: modelled significant wave height at each site, the sample nearest the selected hour within 90 minutes, drawn while the model was issued under 48 hours ago and retrieved under 3 hours ago. Model output, not a buoy observation and not breakers at a beach. Ring radius 4 px plus 3 px per foot; 15 ft and above draw alike. The site is in 15 m of water (MSL).');
    assert.deepEqual(mark.provider, {href: 'https://example.test/model-a', label: 'CDIP MOP model site'});
    for (const id of ['unknown', null, undefined, 1]) assert.equal(ringMark(r, id, NOW, TZ), null);
    const sameName = rings(report(sites(), [CDIP, source('other-model', 'CDIP MOP · another synthetic status')]));
    assert.equal(sameName.product, 'CDIP MOP', 'distinct IDs with one product retain single-product summary');
  });

  test('A3 missing or unusable source labels fall back to the exact clicked source ID', () => {
    const exactId = 'other-model:synthetic/β';
    for (const label of [undefined, null, '', 0, '   ', ' · no product']) {
      const r = rings(report([site(), site({id: 'synthetic-b', sourceId: exactId})], [CDIP, source(exactId, label)]));
      attribution(card(r, 'synthetic-b'), exactId, 'https://example.test/model-a');
      attribution(card(r, 'synthetic-a'), 'CDIP MOP', 'https://example.test/model-a');
      assert.equal(r.product, 'multiple nearshore models');
    }
    const missing = rings(report(sites(), [CDIP]));
    attribution(card(missing, 'synthetic-b'), 'other-model', 'https://example.test/model-b');
    const noSources = rings({...report(), sources: undefined});
    attribution(card(noSources, 'synthetic-a'), 'cdip-mop', 'https://example.test/model-a');
    attribution(card(noSources, 'synthetic-b'), 'other-model', 'https://example.test/model-b');
  });

  test('A3 geometry scale hit area ordering and per-site run age are unchanged', () => {
    const input = sites(); input[1].issuedAt = iso(NOW - 2 * HOUR);
    const r = rings(report(input));
    assert.deepEqual(r.rings.map(x => x.site.id), ['synthetic-a', 'synthetic-b']);
    assert.deepEqual(r.collection.features.map(f => [f.properties.id, +f.properties.radius.toFixed(6), f.geometry.coordinates]),
      [['synthetic-a', 15.4, [-120.75, 35.25]], ['synthetic-b', 15.4, [-120.9, 35.4]]]);
    assert.equal(r.key, input.map(s => `${s.id}|${s.issuedAt}|${s.fetchedAt}|2026-10-09T20:00:00.000Z`).join(','));
    assert.deepEqual([0, 5, 15, 30, -1].map(ringRadius), [4, 19, 49, 49, 4]);
    assert.deepEqual(ringHitLayer({blue: 'synthetic-blue'}).paint,
      {'circle-radius': ['max', 22, ['get', 'radius']], 'circle-color': 'synthetic-blue', 'circle-opacity': 0});
    assert.equal(ringLayer({blue: 'synthetic-blue'}).paint['circle-stroke-color'], 'synthetic-blue');
    assert.match(card(r, 'synthetic-a').source, /issued 6 h ago$/);
    assert.match(card(r, 'synthetic-b').source, /issued 2 h ago$/);
    assert.match(ringSummary(r, NOW), /issued 2 h ago/);
    for (const s of input) assert.match(card(r, s.id).basis, /Model output, not a buoy observation and not breakers at a beach\./);
  });

  test('A3 freshness span sampling and binding admission remain intact', () => {
    const count = (patch, at = AT) => rings(report([site(patch)]), at)?.rings.length ?? 0;
    assert.equal(count({}), 1);
    for (const patch of [{issuedAt: iso(NOW - 48 * HOUR)}, {fetchedAt: iso(NOW - 3 * HOUR)},
      {freshness: 'stale'}, {availability: 'error'}, {areaId: 'south'}, {lat: NaN}, {lon: Infinity},
      {validThrough: '2026-10-09T19:00:00Z'}, {hours: [{at: AT.toISOString(), waveFt: null}]}]) assert.equal(count(patch), 0);
    assert.equal(count({issuedAt: iso(NOW - 48 * HOUR + 60_000)}), 1);
    assert.equal(count({fetchedAt: iso(NOW - 3 * HOUR + 60_000)}), 1);
    assert.equal(count({}, new Date('2026-10-10T13:00:00Z')), 0);
    const sparse = {hours: [{at: '2026-10-09T12:00:00Z', waveFt: 3}, {at: '2026-10-10T12:00:00Z', waveFt: 4}]};
    assert.equal(count(sparse), 0, 'inside span but no sample within 90 minutes');
    assert.equal(nearshoreRings(null, 'central', AT, NOW), null);
    assert.equal(nearshoreRings(report(), null, AT, NOW), null);
    const drawn = rings(report([site({sourceId: 'other-model', fetchedAt: iso(NOW - 3 * HOUR)}), site()]));
    assert.equal(drawn.product, 'CDIP MOP', 'undrawn sources do not affect summary');
  });
}
