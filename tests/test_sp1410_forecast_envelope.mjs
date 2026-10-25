// SP1410-FORECAST-ENVELOPE (SP-14-v1): a malformed regional forecast container is
// unavailable, never an exception inside an advisor reply.
//
// The gate under test is intelligenceFeed in server/advisor/answers/feeds.ts. Every
// case runs the complete real modules (feeds.ts, conditions.ts, planning.ts and the
// get_conditions tool) through their public API with an injected offline feed reader
// over the card-owned synthetic fixtures in tests/fixtures/sp1410_forecast_envelope/.
// The offline boundary below is imported before any product module.
//
// SP1410_SUITE=baseline registers ONLY the A4 pair ("primary regression" and
// "healthy control"), so the pre-change baseline can never hide a skip behind a
// name filter. Any other value (or none) registers every A1-A4 test.
import {offlineAttempts, offlineIntact, restoreOnline} from './fixtures/sp1410_forecast_envelope/offline.mjs';
import test, {after, afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const json = rel => JSON.parse(readFileSync(new URL(rel, import.meta.url), 'utf8'));
const FIXTURES = './fixtures/sp1410_forecast_envelope/';
const fixture = name => json(FIXTURES + name);

globalThis.REGIONS = {'morro-bay': json('../regions/morro-bay/region.json'), 'southern-california': json('../regions/southern-california/region.json')};
globalThis.DEPLOYMENT = json('../deployments/production.json');
const GLOBALS = {REGIONS: globalThis.REGIONS, DEPLOYMENT: globalThis.DEPLOYMENT};

const {intelligenceFeed, dailyFeed, feedReader} = await import('../server/advisor/answers/feeds.ts');
const {windowConditions} = await import('../server/advisor/answers/conditions.ts');
const {getConditions} = await import('../server/advisor/tools/get_conditions.ts');
const {advisorSettings} = await import('../server/advisor/settings.ts');
const {readFeed} = await import('../server/feeds.ts');

const REGION = globalThis.REGIONS['morro-bay'];
const OTHER_REGION = globalThis.REGIONS['southern-california'];
const POINT = 'central';                                   // catalog/home-ports.json: morro-bay -> central
const DATE = '2026-09-28';
const NOW = Date.parse('2026-09-28T13:00:00Z');            // 06:00 in Morro Bay, the fixtures' day
const CASES = fixture('contract.json').cases;
const BASELINE = process.env.SP1410_SUITE === 'baseline';

const clone = value => structuredClone(value);
/** A fresh copy of complete.json with one value set at `path` (an empty path replaces the whole feed). */
function applyCase(c, base = fixture('complete.json')) {
  if (!c.path.length) return clone(c.value);
  let node = base;
  for (const key of c.path.slice(0, -1)) node = node[key];
  node[c.path.at(-1)] = clone(c.value);
  return base;
}
/** An offline reader: the region's intelligence URL gives `intel`, its daily URL gives `daily`; anything else rejects. */
function readerFor(intel, daily = fixture('daily.json')) {
  const calls = [];
  const read = async url => {
    calls.push(url);
    if (url === REGION.intelligence_feed || url === OTHER_REGION.intelligence_feed) return intel;
    if (url === REGION.daily_feed || url === OTHER_REGION.daily_feed) return daily;
    throw new Error(`no synthetic feed for ${url}`);
  };
  read.calls = calls;
  return read;
}
const ctx = read => ({env: {}, db: null, contact: null, message: {id: 'sp1410'}, language: 'en', settings: advisorSettings({}), now: NOW, deps: {feeds: read}});
const conditionsFor = async (intel, daily) => (await getConditions.run({port: 'morro-bay', date: 'today'}, ctx(readerFor(intel, daily)))).result;
const UNAVAILABLE_FIELDS = ['wind_kt', 'wind_from', 'gusts_kt', 'seas_ft', 'sea_period_s', 'swell_ft', 'swell_period_s', 'swell_from', 'models_agree'];
function deepFreeze(value) {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) { Object.freeze(value); for (const v of Object.values(value)) deepFreeze(v); }
  return value;
}

afterEach(() => {
  // No case may leave the offline boundary or the region globals changed for the next one.
  assert.ok(offlineIntact(), 'the offline sentinels are still installed');
  for (const [key, value] of Object.entries(GLOBALS)) if (globalThis[key] !== value) globalThis[key] = value;
});
after(() => restoreOnline());

// ---- A4: the pair registered alone in baseline mode -------------------------------------------

test('primary regression', async t => {
  const c = CASES[0];
  assert.equal(c.id, 'gfs-time-string', 'contract.json keeps the first corrected A1 case first');
  const admitted = await intelligenceFeed(REGION, readerFor(applyCase(c)));
  // Observe what the unchanged consumer does with whatever the gate returned, before the semantic assertion.
  let observed = null;
  try { windowConditions(admitted, REGION, POINT, DATE); } catch (error) { observed = `${error?.name}: ${error?.message}`; }
  t.diagnostic(`SP1410_OBSERVED gate=${admitted === null ? 'null' : 'admitted'} windowConditions=${observed ?? 'no exception'}`);
  assert.equal(admitted === null ? null : 'admitted', null, 'SP1410_PRIMARY_SHAPE_REJECTION: a correct-region feed whose gfs_global hourly.time is a string must be unavailable (null)');
  assert.equal(observed, null, 'the unavailable forecast reaches windowConditions without an exception');
});

test('healthy control', async () => {
  const feed = fixture('minimal.json');
  const admitted = await intelligenceFeed(REGION, readerFor(feed));
  assert.equal(admitted, feed, 'a matching-region forecast with an empty GFS time array is admitted as it is');
  const day = windowConditions(admitted, REGION, POINT, DATE);
  assert.equal(day.available, false);
  const out = await conditionsFor(fixture('minimal.json'));
  assert.equal(out.days[0].available, false, 'get_conditions gives the ordinary unavailable day');
  assert.deepEqual(out.days[0], day);
});

if (!BASELINE) {
  // ---- A1: malformed containers are unavailable ------------------------------------------------

  test('A1 every malformed forecast container in an otherwise correct-region feed is unavailable (null)', async () => {
    assert.ok(CASES.length >= 21, 'the frozen case table is complete');
    for (const c of CASES) {
      const feed = applyCase(c);
      assert.equal(feed.region_id, 'morro-bay', `${c.id}: the region stays correct`);
      const admitted = await intelligenceFeed(REGION, readerFor(feed));
      assert.equal(admitted === null ? null : 'admitted', null, `${c.id}: malformed container is unavailable`);
    }
  });

  test('A1 get_conditions answers a malformed feed with an unavailable forecast and keeps the daily advisories', async () => {
    for (const c of CASES) {
      const out = await conditionsFor(applyCase(c));
      assert.equal(out.error, undefined, `${c.id}: no error result`);
      assert.deepEqual(out.dates, [DATE], c.id);
      const day = out.days[0];
      assert.deepEqual([day.available, day.reason], [false, 'regional forecast unavailable'], `${c.id}: unavailable forecast`);
      for (const k of UNAVAILABLE_FIELDS) assert.equal(day[k], null, `${c.id}: ${k}`);
      assert.equal(out.forecast_issued, null, `${c.id}: no issue time from a refused feed`);
      // The daily feed is independent: its advisories survive the refused forecast.
      assert.equal(out.advisories_checked, true, c.id);
      assert.deepEqual(out.advisories.map(a => [a.event, a.zone]), [['Small Craft Advisory', 'PZZ645']], c.id);
      assert.equal(out.lead_with_advisory, true, c.id);
      assert.match(out.advisory_line, /^SMALL CRAFT ADVISORY/, c.id);
    }
  });

  test('A1 provider-error GFS records with keyed-object data and a malformed time are unavailable through windowConditions and get_conditions', async () => {
    // windowConditions indexes gfs_global.data[point].hourly.time without consulting error,
    // so an error record's keyed-object data is a consumed container too (review round 1).
    const keyed = CASES.filter(c => c.id.startsWith('error-record-gfs-keyed-data-'));
    assert.deepEqual(keyed.map(c => c.id), ['error-record-gfs-keyed-data-time-string', 'error-record-gfs-keyed-data-time-object']);
    for (const c of keyed) {
      const feed = applyCase(c);
      assert.ok(feed.forecast.models.gfs_global.error && !Array.isArray(feed.forecast.models.gfs_global.data), `${c.id}: error record with non-array data`);
      const admitted = await intelligenceFeed(REGION, readerFor(feed));
      assert.equal(admitted, null, `${c.id}: refused`);
      let day;
      assert.doesNotThrow(() => { day = windowConditions(admitted, REGION, POINT, DATE); }, `${c.id}: windowConditions does not throw`);
      assert.deepEqual([day.available, day.reason], [false, 'regional forecast unavailable'], `${c.id}: unavailable`);
      const out = await conditionsFor(applyCase(c));
      assert.equal(out.error, undefined, `${c.id}: no error result`);
      assert.deepEqual(out.days[0], day, `${c.id}: get_conditions gives the same unavailable day`);
      assert.deepEqual(out.advisories.map(a => [a.event, a.zone]), [['Small Craft Advisory', 'PZZ645']], `${c.id}: daily advisories survive`);
      assert.equal(out.lead_with_advisory, true, c.id);
    }
  });

  // ---- A2: producer-shaped and missing-data feeds keep their outcome ----------------------------

  test('A2 the card-owned producer-shaped feed is admitted unchanged and gives the same conditions', async () => {
    const feed = fixture('complete.json');
    assert.equal(await intelligenceFeed(REGION, readerFor(feed)), feed);
    const direct = windowConditions(fixture('complete.json'), REGION, POINT, DATE);
    assert.equal(direct.available, true);
    assert.deepEqual([direct.wind_kt, direct.gusts_kt, direct.seas_ft, direct.swell_ft, direct.wind_from], [[10, 12], 15, [4, 4], [3, 3], 'WNW']);
    const out = await conditionsFor(fixture('complete.json'));
    assert.deepEqual(out.days[0], direct, 'get_conditions gives the conditions the unchanged reader computes');
    assert.equal(out.forecast_issued, feed.completed_at);
    assert.equal(out.advisories[0].event, 'Small Craft Advisory');
  });

  test('A2 the committed producer fixture tests/fixtures/feeds/intelligence.json is admitted and gives the same conditions', async () => {
    const feed = json('./fixtures/feeds/intelligence.json');
    assert.equal(await intelligenceFeed(REGION, readerFor(feed)), feed);
    const evening = {start: 17, end: 19};
    const direct = windowConditions(json('./fixtures/feeds/intelligence.json'), REGION, POINT, DATE, evening);
    assert.deepEqual([direct.available, direct.wind_kt, direct.seas_ft, direct.wind_from, direct.swell_from], [true, [15, 19], [7, 7], 'NW', 'S']);
    const out = (await getConditions.run({port: 'morro-bay', date: DATE, start_hour: 17, end_hour: 19}, ctx(readerFor(feed)))).result;
    assert.deepEqual(out.days[0], direct);
  });

  test('A2 valid empty arrays, absent models, null points, absent containers and provider-error records keep the missing-data outcome', async () => {
    const P = ['forecast', 'models'];
    const without = (path, base = fixture('complete.json')) => { let n = base; for (const k of path.slice(0, -1)) n = n[k]; delete n[path.at(-1)]; return base; };
    const variants = [
      ['gfs empty time array', applyCase({path: [...P, 'gfs_global', 'data', 1, 'hourly', 'time'], value: []}), false],
      ['every model with an empty data array', (() => { const f = fixture('complete.json'); for (const m of Object.values(f.forecast.models)) m.data = []; return f; })(), false],
      ['empty models object', applyCase({path: P, value: {}}), false],
      ['absent ECMWF models', without([...P, 'ecmwf_wam'], without([...P, 'ecmwf_ifs025'])), true],
      ['absent wave models', without([...P, 'ecmwf_wam'], without([...P, 'ncep_gfswave016'])), true],
      ['null points', applyCase({path: [...P, 'gfs_global', 'data'], value: [null, null]}), false],
      ['null forecast point for central only', applyCase({path: [...P, 'gfs_global', 'data', 1], value: null}), false],
      ['absent data on gfs', without([...P, 'gfs_global', 'data']), false],
      ['absent hourly', without([...P, 'gfs_global', 'data', 1, 'hourly']), false],
      ['absent time', without([...P, 'gfs_global', 'data', 1, 'hourly', 'time']), false],
      ['absent forecast block (snapshots predating it)', without(['forecast']), false],
      ['absent models container', without([...P]), false],
      ['explicit provider-error ECMWF record', applyCase({path: [...P, 'ecmwf_ifs025'], value: {data: [], meta: null, error: 'synthetic HTTP 503'}}), true],
      ['explicit provider-error wave record without data', applyCase({path: [...P, 'ncep_gfswave016'], value: {meta: null, error: 'synthetic timeout'}}), true],
      ['explicit provider-error GFS record', applyCase({path: [...P, 'gfs_global'], value: {data: [], meta: null, error: 'synthetic HTTP 500'}}), false],
      ['provider-error GFS record with non-array data', applyCase({path: [...P, 'gfs_global'], value: {data: null, meta: null, error: 'synthetic HTTP 500'}}), false],
      ['provider-error GFS record with string data', applyCase({path: [...P, 'gfs_global'], value: {data: 'synthetic', meta: null, error: 'synthetic HTTP 500'}}), false],
      ['provider-error GFS record with keyed-object data and an empty time array', applyCase({path: [...P, 'gfs_global'], value: {data: {1: {hourly: {time: []}}}, meta: null, error: 'synthetic timeout'}}), false],
      ['provider-error GFS record with keyed-object data and a null point', applyCase({path: [...P, 'gfs_global'], value: {data: {1: null}, meta: null, error: 'synthetic timeout'}}), false],
      ['provider-error ECMWF record keeping well-formed earlier points', (() => { const f = fixture('complete.json'); f.forecast.models.ecmwf_ifs025.error = 'synthetic stale'; return f; })(), true],
    ];
    for (const [label, feed, available] of variants) {
      const before = JSON.stringify(feed);
      assert.equal(await intelligenceFeed(REGION, readerFor(feed)), feed, `${label}: admitted`);
      const direct = windowConditions(JSON.parse(before), REGION, POINT, DATE);
      assert.equal(direct.available, available, `${label}: the unchanged reader's outcome`);
      const out = await conditionsFor(JSON.parse(before));
      assert.deepEqual(out.days[0], direct, `${label}: get_conditions keeps that outcome`);
      assert.equal(out.forecast_issued, feed.completed_at, `${label}: the admitted feed's issue time`);
    }
  });

  // ---- A3: boundaries that stay as they were ----------------------------------------------------

  test('A3 reader rejection, null and non-object input and a wrong or missing region stay null', async () => {
    const rejecting = async () => { throw new Error('synthetic reader rejection'); };
    assert.equal(await intelligenceFeed(REGION, rejecting), null, 'reader rejection');
    for (const value of [null, undefined, 'morro-bay', 7, [], [fixture('complete.json')]]) {
      assert.equal(await intelligenceFeed(REGION, readerFor(value)), null, `input ${JSON.stringify(value)}`);
    }
    assert.equal(await intelligenceFeed(OTHER_REGION, readerFor(fixture('complete.json'))), null, 'a morro-bay feed read for another region');
    assert.equal(await intelligenceFeed(REGION, readerFor({...fixture('complete.json'), region_id: 'southern-california'})), null, 'wrong region_id');
    const missing = fixture('complete.json'); delete missing.region_id;
    assert.equal(await intelligenceFeed(REGION, readerFor(missing)), null, 'missing region_id (no legacy exception for the intelligence feed)');
    const out = (await getConditions.run({port: 'morro-bay', date: 'today'}, ctx(rejecting))).result;
    assert.deepEqual([out.advisories_checked, out.days[0].available], [false, false], 'a rejecting reader stays unavailable');
  });

  test('A3 the gate never mutates a feed and admits optional unrelated fields', async () => {
    for (const feed of [fixture('complete.json'), fixture('minimal.json'), ...CASES.map(c => applyCase(c))]) {
      const before = JSON.stringify(feed);
      deepFreeze(feed);
      await intelligenceFeed(REGION, readerFor(feed));   // a write to a frozen feed would throw (module code is strict)
      assert.equal(JSON.stringify(feed), before);
    }
    const extra = fixture('complete.json');
    extra.extra_top = [1, 'two'];
    extra.forecast.currents = 'not read here';
    extra.forecast.coverage = ['also', 'not', 'read'];
    extra.forecast.models.future_model = 'unrecognized models are not this gate\'s concern';
    extra.forecast.models.ecmwf_ifs025.notes = ['optional'];
    extra.forecast.models.gfs_global.data[1].future_field = 'optional';
    extra.forecast.models.gfs_global.data[1].hourly.visibility = 'not consumed';
    extra.forecast.models.gfs_global.meta = 'meta is not a consumed container';
    assert.equal(await intelligenceFeed(REGION, readerFor(extra)), extra, 'optional unrelated fields are admitted');
  });

  test('A3 sample values and units stay owned by readHour', async () => {
    const feed = fixture('complete.json');
    const gfs = feed.forecast.models.gfs_global.data[1];
    gfs.hourly_units.wind_speed_10m = 'm/s';                   // a unit the reader refuses
    gfs.hourly.wind_gusts_10m = ['fast', null, {}];           // values the reader refuses
    gfs.hourly.time = [gfs.hourly.time[0], 'later', null];    // odd entries inside a real array
    feed.forecast.models.ecmwf_wam.data[1].hourly_units = 'units';
    const before = JSON.stringify(feed);
    assert.equal(await intelligenceFeed(REGION, readerFor(feed)), feed, 'values and units are not this gate\'s policy');
    const direct = windowConditions(JSON.parse(before), REGION, POINT, DATE);
    assert.equal(direct.available, true);
    assert.deepEqual((await conditionsFor(JSON.parse(before))).days[0], direct);
  });

  test('A3 dailyFeed and reader routing are unchanged', async () => {
    const daily = fixture('daily.json');
    assert.equal(await dailyFeed(REGION, readerFor(null, daily)), daily, 'the card-owned daily feed passes validFeed');
    const legacy = fixture('daily.json'); delete legacy.region_id;
    assert.equal(await dailyFeed(REGION, readerFor(null, legacy)), legacy, 'morro-bay keeps its legacy no-region_id daily feed');
    assert.equal(await dailyFeed(REGION, readerFor(null, {...fixture('daily.json'), region_id: 'elsewhere'})), null);
    const invalid = fixture('daily.json'); delete invalid.health;
    assert.equal(await dailyFeed(REGION, readerFor(null, invalid)), null);
    assert.equal(feedReader(undefined), readFeed);
    assert.equal(feedReader(null), readFeed);
    assert.equal(feedReader({}), readFeed);
    const injected = readerFor(null);
    assert.equal(feedReader({feeds: injected}), injected);
    const read = readerFor(fixture('complete.json'));
    await intelligenceFeed(REGION, read);
    assert.deepEqual(read.calls, [REGION.intelligence_feed], 'the gate reads only the region\'s intelligence feed, once');
  });

  test('offline boundary: no network, model or storage access in any case', () => {
    assert.ok(offlineIntact());
    assert.deepEqual(offlineAttempts(), []);
  });
}
