// SCA-587: a held optional request must not delay validated daily evidence.
// `node tests/test_f16_14_audit.mjs --baseline` replays the same observations
// against the unchanged view; this deliberately red mode is not a CI check.
import assert from 'node:assert/strict';
import test from 'node:test';
import {flush, load, response} from './fixtures/sp1605_reports_source_key/harness.mjs';

const baseline = process.argv.includes('--baseline');
const generated_at = '2026-10-08T18:00:00Z';
const now = Date.parse(generated_at);
const species = 'lingcod';
const daily = region => ({
  schema_version: 1, region_id: region, generated_at, sources: {}, health: {status: 'ok'},
  catch_probability: null, bite_score: null,
  reports: [{date: '2026-10-07', boat: `Fixture boat ${region}`, source_url: `https://reports.example/${region}`,
    catches: [{species, count: 2}]}],
});
const discussion = region => ({schema_version: 1, generated_at, health: {status: 'ok'}, candidates: [{
  region_id: region, review_status: 'candidate', published_at: generated_at,
  title: `Fixture discussion ${region}`, url: `https://forum.example/${region}`,
}]});

// Reference scheduling only: use the real feed validator and section renderers.
function reference(m) {
  let current;
  return {
    async open(region, fetcher) {
      const view = current = {evidence: null, discussions: null};
      const optional = fetcher(m.DISCUSSIONS_FEED).then(res => res.json());
      view.evidence = m.evidenceFrom(await (await fetcher(m.evidenceFeed(region))).json(), region, species, now);
      const intel = await optional;
      if (current === view) view.discussions = (await m.loadReports({region, species, now},
        async url => url === m.DISCUSSIONS_FEED ? response(intel) : response(daily(region)))).discussions;
    },
    html() {
      return m.render(m.h(m.EvidenceSection, {evidence: current.evidence})) + (current.discussions
        ? m.render(m.h(m.DiscussionsSection, {discussions: current.discussions}))
        : '<p role="status">Loading discussions</p>');
    },
  };
}

test(`SCA-587 ${baseline ? 'baseline' : 'reference'}: ready daily evidence and late-region isolation`, {timeout: 5000}, async t => {
  const m = await load();
  t.mock.timers.enable({apis: ['Date'], now});
  // Isolate the seasonal watch's implicit fetch as well as the two injected URLs.
  t.mock.method(globalThis, 'fetch', async () => new Response(null, {status: 503}));
  const view = baseline ? {
    open: (region, fetcher) => m.openReports(region, species, null, fetcher),
    html: () => m.render(m.h(m.Reports)),
  } : reference(m);

  function open(region) {
    m.region.value = region;
    m.species.value = species;
    const held = Promise.withResolvers(), read = Promise.withResolvers();
    let optionalRequested = false;
    const done = view.open(region, async url => {
      if (url === m.DISCUSSIONS_FEED) { optionalRequested = true; return held.promise; }
      assert.equal(url, m.evidenceFeed(region));
      return {ok: true, json: () => { read.resolve(); return daily(region); }};
    });
    return {done, release: () => held.resolve(response(discussion(region))), async beforeRelease() {
      await read.promise;
      await flush(); // drain the fulfilled daily promise, without releasing discussion or using a delay
      assert.ok(optionalRequested, 'discussion really is in flight');
      return view.html();
    }};
  }

  const a = open('region-a');
  const early = await a.beforeRelease();
  const b = open('region-b');
  await b.beforeRelease();
  b.release();
  await b.done;
  const beforeLate = view.html();
  assert.match(beforeLate, /Fixture boat region-b/);
  assert.match(beforeLate, /Fixture discussion region-b/);
  a.release();
  await a.done;
  assert.equal(view.html(), beforeLate, 'late region A must not replace the current signal or view');
  if (baseline) assert.equal(m.reportsData.peek()?.key, 'region-b:lingcod', 'stale data cannot overwrite the current key');
  assert.match(early, /href="https:\/\/reports\.example\/region-a"/, 'validated region A daily evidence must render before discussion settles');
  assert.match(early, /role="status">Loading discussions/, 'only the optional section is still loading');
  assert.doesNotMatch(early, /Fixture discussion|discussion search is unavailable/);
});
