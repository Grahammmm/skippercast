// F18-09 / SCA-589: `node --test tests/test_f18_09_audit.mjs` qualifies the
// render-local reference. `node tests/test_f18_09_audit.mjs --baseline` applies
// the same contract to the unchanged overview and reports any duplicate work.
// Counts are actual buildDaily calls, not browser interaction timings.
import assert from 'node:assert/strict';
import {registerHooks} from 'node:module';
import test from 'node:test';

const dailyURL = new URL('../packages/coast/src/daily.ts', import.meta.url).href;
const probeURL = 'data:text/javascript,' + encodeURIComponent(`
  import {buildDaily as derive} from ${JSON.stringify(dailyURL)};
  export * from ${JSON.stringify(dailyURL)};
  let visit;
  export function observe(fn) { visit = fn; }
  export function buildDaily(...args) { return visit ? visit(derive, args) : derive(...args); }
`);
// Intercept only the daily module edge. The derivation, helpers and markup are real.
const hooks = registerHooks({resolve(specifier, context, next) {
  const result = next(specifier, context);
  if (result.url === dailyURL && context.parentURL !== probeURL) return {...result, url: probeURL};
  return result;
}});
const {briefing} = await import('../packages/coast/src/ui/briefing.ts').finally(() => hooks.deregister());
const {observe} = await import(probeURL);

const day = '2026-06-15';
const at = clock => `${day}T${clock}:00.000Z`;
function fixture() {
  const area = {id: 'fixture', name: 'Fixture coast', lat: 0, lon: 0, accessNote: 'Synthetic only'};
  const county = {id: 'fixture', areas: [area], timezone: 'UTC', tideStation: {name: 'Fixture tide station'}};
  const report = {
    countyId: county.id,
    forecasts: [{id: area.id, sourceId: 'forecast', hours: [11, 12, 13, 14].map((hour, i) => ({
      at: at(`${hour}:00`), windKnots: [5, 7, 8, 9][i], gustKnots: 10, windDirectionDeg: 270,
      waveFt: 2, wavePeriodS: 8, airTempF: 60, precipPct: 0, cloudCoverPct: null,
    }))}],
    sources: ['forecast', 'nws-alerts'].map(id => ({id, outcome: 'ok', issuedAt: at('11:00'), fetchedAt: at('11:30')})),
    // A real break in the curve: only the two 6-minute pairs may be joined.
    tides: [['12:00', 2.5], ['12:06', 2.6], ['12:36', 3], ['12:42', 3.1]]
      .map(([clock, heightFt]) => ({at: at(clock), heightFt})),
    tideEvents: [{type: 'H', at: at('12:42'), heightFt: 3.1}],
    observations: [], alerts: [],
  };
  return {report, county, areaId: area.id, mode: 'boat', date: day, at: at('12:00'), now: new Date(at('11:30'))};
}

function render(state, share) {
  let builds = 0, brief, inputs;
  observe((derive, args) => {
    if (share && builds) {
      // A brief may be handed to the other helpers only for identical render inputs.
      assert.equal(args.length, inputs.length);
      args.forEach((arg, i) => assert.equal(arg, inputs[i]));
      return brief;
    }
    builds++;
    inputs = args;
    return brief = derive(...args);
  });
  try {
    return {html: briefing(state), builds};
  } finally {
    observe();
  }
}

function assertTideAndGaps(html) {
  assert.match(html, /2\.5<small>ft<\/small><\/strong><small>Rising · MLLW/);
  const curve = html.match(/<path d="([^"]+)" style="stroke:var\(--coast-amber\)"/)?.[1];
  assert.deepEqual(curve?.match(/[ML]/g), ['M', 'L', 'M', 'L'], 'tide chart keeps the gap');
  assert.match(html, /No fresh local buoy/);
  assert.match(html, /Cloud —%/);
}

// Rebuilding in any of the four readers fails the work bound; retaining the
// brief across renders of this same object hides a new alert or stale sources.
// In required CI, compare all rendered bytes to the unshared renderer, without
// asserting its work count. Only the explicit baseline replay can be red.
const baseline = process.argv.includes('--baseline');
test(`F18-09: ${baseline ? 'unchanged overview' : 'render-local reference'} builds once and preserves outputs`, t => {
  const state = fixture(), counts = [];
  const check = observations => {
    const result = render(state, !baseline);
    if (!baseline) assert.equal(result.html, render(state, false).html, 'shared and unshared markup agree');
    assertTideAndGaps(result.html);
    for (const expected of observations) assert.match(result.html, expected);
    counts.push(result.builds);
  };

  check([/7<small>kt/, /5–9 kt wind/, /LOWER EXPOSURE<\/span><strong>Now–3 PM/]);
  state.report.alerts.push({event: 'Fixture marine warning', headline: 'Synthetic alert', effective: at('11:00'), expires: at('12:00')});
  check([/<h1>Fixture marine warning<\/h1>/, /No window qualified/]);
  state.now.setTime(Date.parse(at('12:30')));
  check([/<h1>A clearer picture of your coast\.<\/h1>/, /7–9 kt wind/, /LOWER EXPOSURE<\/span><strong>Now–3 PM/]);
  state.now.setTime(Date.parse(at('14:00')));
  check([/Fresh marine forecasts are unavailable/, /—<small>kt/, /No window qualified/]);

  t.diagnostic(`buildDaily calls (fresh, alert added, alert expired, sources stale): ${counts.join(', ')}`);
  assert.deepEqual(counts, [1, 1, 1, 1], 'one actual buildDaily call per overview render');
});
