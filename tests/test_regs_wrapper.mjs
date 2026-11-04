// The mark card's regulations line (FE-54, docs/plans/front-end/dev-plan.md; design § 6, § 9, § 12):
// web/regs.ts restates dist/regulations.js's state and "rules at a glance" row with the region passed
// in; these tests pin it to v1's output over frozen FE-61 registry and region inputs with
// fresh synthetic source checks, as tests/test_regulations.mjs builds it, plus synthetic edits for an
// opening time, a latitude band and a depth line), including #396's guard against inherited ids, and
// render the card's line. web/regs.ts runs by type stripping; the card is bundled with esbuild.
import assert from 'node:assert/strict';
import {readdirSync, readFileSync} from 'node:fs';
import {mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {pathToFileURL} from 'node:url';
import test from 'node:test';
import {build} from 'esbuild';
import {rendererPlugins} from './helpers/esbuild-url.mjs';
import {createHash} from 'node:crypto';
import {CDFW_OCEAN, freshnessLabel, loadRegs, officialURL, openingAt, regsData, regulationState, resetRegs, ruleProfile, ruleSummary, speciesPage, validRegulations, verifiedText} from '../web/regs.ts';
import {isDeepStrictEqual} from 'node:util';

const ROOT = new URL('..', import.meta.url).pathname;
// Both inputs affect the historical digests: species/order, rules, source ids/URLs,
// jurisdiction, timezone and authority hosts must not follow generated dist data.
const fixtureBytes = readFileSync(new URL('./fixtures/regulations/fe61-v1.json', import.meta.url));
const fixture = JSON.parse(fixtureBytes);
const MORRO = fixture.region;
const ORIGINAL = fixture.regulations;
test('the frozen v1 oracle inputs retain their reviewed identity', () => {
  assert.equal(createHash('sha256').update(fixtureBytes).digest('hex'),
    '5c170912135231fa42aab6918694e8947fa08dd2287ce3caf45a05d0e46ecda3');
  assert.equal(fixture.provenance.commit, 'db50a71da352c2b06c3e736067a1677be17328c7');
});
const NOW = Date.parse('2026-09-21T18:00:00Z');
const HOUR = 3600000;
function data(at = NOW) {
  const d = structuredClone(ORIGINAL);
  d.reviewed_at = new Date(at - HOUR).toISOString();
  d.rules_review_status = 'reviewed';
  for (const [id, source] of Object.entries(d.sources)) {
    source.approved_content_sha256 = 'a'.repeat(64);
    d.checks[id] = {url: source.url, normalization: source.normalization, status: 'unchanged', source_status: 'ok', content_sha256: 'a'.repeat(64), data_retrieved_at: new Date(at).toISOString()};
  }
  return d;
}
/** Synthetic windows v1 supports that the frozen registry does not use. */
function edited(at = NOW) {
  const d = data(at), band = d.species.salmon.source_ids[0];
  d.species.salmon.windows = [{start: '2026-09-21', end: '2026-09-30', start_at: '2026-09-21T05:00:00-07:00'}];
  d.species.halibut.windows = [{start: '2026-01-01', end: '2026-12-31', geography: {kind: 'latitude-band', south: 34.5, north: 36, source_id: band, note: 'Synthetic band.'}}];
  d.species.halibut.source_ids = [band, ...d.species.halibut.source_ids.filter(s => s !== band)];
  d.species.lingcod.windows = [{start: '2026-04-01', end: '2026-12-31', access: 'shoreward-50fm'}];
  d.species.bluefin.windows = [{start: '2026-01-01', end: '2026-12-31', restriction: 'Synthetic restriction text.'}];
  return d;
}
const IDS = [...Object.keys(ORIGINAL.species), 'reef'];
const INHERITED = ['constructor', 'toString', '__proto__', 'hasOwnProperty', '', 'unsupported-target'];
const fields = s => ({status: s.status, label: s.label, today: s.today, reason: s.reason, issues: s.issues});
// FE-61 deleted dist/regulations.js with the v1 shell. Its output over these cases is
// pinned by digest (state fields and row, in loop order), computed from v1 before the deletion.
// SP-RULES-STATUS departs from v1 on purpose in exactly 50 grid rows: an unknown state with fresh,
// reviewed checks (outside the rule period, or a latitude-band season with no location) no longer
// carries `verified`; that date moves to `checked`. Every state field is still v1's. v1's own grid
// digest was 2a00529fc1145ddaf4d3b74ee98130a4ccb7274b3f579e7301e7eba85a2d2a7b.
const V1_DIGEST = {grid: 'e48a0a7730896a7b4fae6a4000d565c264a0361778a397889ff72c7e2e4a5cdc', evidence: '9845ca291ad962d581d162241d51f0cd41dcf147405a061ea8fd05806235586b'};
const digest = rows => createHash('sha256').update(JSON.stringify(rows)).digest('hex');

test('state and row equal dist/regulations.js for every species, date and trip hour', () => {
  assert.ok(validRegulations(data(), MORRO), 'the frozen registry passes for Morro Bay');
  const dates = ['2026-09-21T18:00:00Z', '2026-09-21T11:00:00Z', '2026-09-21T13:00:00Z', '2026-10-01T06:59:00Z', '2026-10-01T07:00:00Z', '2026-11-07T08:00:00Z', '2027-01-01T08:00:00Z'];
  const rows = [];
  for (const build of [data, edited]) {
    for (const when of dates) {
      const at = Date.parse(when), d = build(at);
      for (const id of [...IDS, ...INHERITED]) {
        for (const [tripDate, tripInstant] of [[null, null], ['2026-09-21', null], ['2026-09-21', Date.parse('2026-09-21T11:30:00Z')], ['2026-09-21', Date.parse('2026-09-21T13:00:00Z')], ['2026-12-31', null]]) {
          const mine = regulationState(d, id, MORRO, at, tripDate, tripInstant);
          rows.push([fields(mine), ruleSummary(d, id, mine, MORRO)]);
        }
      }
    }
  }
  assert.equal(rows.length, 980);
  assert.equal(digest(rows), V1_DIGEST.grid);
});

test('stale, changed, unreviewed and out-of-period evidence withholds open exactly as v1 does', () => {
  const rows = [];
  for (const edit of [
    d => { d.checks['rules-salmon'].status = 'changed'; }, d => { delete d.checks['rules-groundfish']; }, d => { d.checks['rules-salmon'].source_status = 'retained'; },
    d => { d.sources['rules-salmon'].approved_content_sha256 = null; }, d => { d.checks['rules-salmon'].data_retrieved_at = '2026-09-19T00:00:00Z'; },
    d => { d.rules_review_status = 'pending'; }, d => { d.valid_through = '2026-09-20'; }, d => { d.schema_version = 2; },
  ]) {
    const d = data(); edit(d);
    for (const id of IDS) {
      const mine = regulationState(d, id, MORRO, NOW);
      rows.push([fields(mine), ruleSummary(d, id, mine, MORRO)]);
    }
  }
  assert.equal(digest(rows), V1_DIGEST.evidence);
});

test('#396: an inherited or unsupported target never borrows a record; the row links CDFW', () => {
  const d = data();
  for (const id of INHERITED) {
    assert.equal(ruleProfile(d, id, MORRO), null, id);
    const state = regulationState(d, id, MORRO, NOW), row = ruleSummary(d, id, state, MORRO);
    assert.equal(state.status, 'unknown', id);
    assert.deepEqual([row.bag, row.size, row.depth, row.verified, row.link], [[], [], null, null, CDFW_OCEAN], id);
  }
  const inherited = Object.create({borrowed: d.species.lingcod});
  Object.assign(inherited, d.species);
  assert.equal(regulationState({...d, species: inherited}, 'borrowed', MORRO, NOW).status, 'unknown');
});

test('every link is an official page: the region\'s authority hosts over https, else CDFW', () => {
  for (const [value, v1] of [['https://wildlife.ca.gov/x', 'https://wildlife.ca.gov/x'], ['http://wildlife.ca.gov/x', CDFW_OCEAN], ['https://user@wildlife.ca.gov/x', CDFW_OCEAN],
    ['https://example.com/x', CDFW_OCEAN], ['not a url', CDFW_OCEAN], ['https://www.ecfr.gov/y', 'https://www.ecfr.gov/y']])
    assert.equal(officialURL(value, MORRO), v1, value);
  const d = data();
  for (const id of IDS) assert.ok(MORRO.regulatory_authority_hosts.includes(new URL(ruleSummary(d, id, regulationState(d, id, MORRO, NOW), MORRO).link).hostname), id);
  assert.equal(ruleSummary(null, 'lingcod', regulationState(null, 'lingcod', MORRO, NOW), MORRO).link, CDFW_OCEAN, 'nothing loaded: CDFW\'s page');
});

test('loads the region\'s file, then the daily checks when as recent; another jurisdiction is refused', async () => {
  const committed = data(NOW - 48 * HOUR), daily = data(NOW);
  const answers = {'data/regulations.json': committed, '/api/daily?region=morro-bay&part=regulations': {schema_version: 1, part: 'regulations', region_id: 'morro-bay', generated_at: new Date(NOW).toISOString(), catch_probability: null, bite_score: null, regulations: daily}};
  const urls = [];
  const fetchFn = async url => { urls.push(url); return url in answers ? Response.json(answers[url]) : new Response('', {status: 404}); };
  regsData.value = null;
  await loadRegs(MORRO, fetchFn);
  assert.deepEqual(urls.slice(0, 3), ['regions/morro-bay/regulations-startup.json', '/api/daily?region=morro-bay&part=regulations', 'data/regulations.json'], 'startup copy and daily start together; absent copy falls back to the whole registry');
  assert.equal(regsData.value?.region, 'morro-bay');
  assert.equal(regsData.value.data.checks['rules-groundfish'].data_retrieved_at, daily.checks['rules-groundfish'].data_retrieved_at, 'the daily checks replace the committed ones');
  regsData.value = null;
  await loadRegs({...MORRO, id: 'other', jurisdiction_id: 'california-other'}, fetchFn);
  assert.equal(regsData.value, null, 'a registry naming another jurisdiction never shows');
});

test('the card\'s line shows v1\'s row: status, bag, size, check date and the official link', async () => {
  const out = join(await mkdtemp(join(tmpdir(), 'regs-')), 'card.mjs');
  await build({
    stdin: {resolveDir: ROOT, loader: 'ts', contents: `
      export {RulesLine} from './web/app/MarkCard.tsx';
      export {markData} from './web/map/marks.ts';
      export {regsData} from './web/regs.ts';
      export * as state from './web/state.ts';
      export {render} from 'preact-render-to-string';
      export {h} from 'preact';`},
    bundle: true, format: 'esm', platform: 'node', outfile: out, write: true, logLevel: 'silent', jsx: 'automatic', jsxImportSource: 'preact',
    plugins: rendererPlugins,
  });
  const m = await import(pathToFileURL(out).href);
  m.state.configureStore({v2: true, storage: null});
  m.state.syncFromURL('https://s.test/map?region=morro-bay&target=reef');
  const d = data(Date.now());
  m.markData.value = {region: {...MORRO, id: 'morro-bay'}, atlas: null, survey: null, geology: null};
  m.regsData.value = {region: 'morro-bay', data: d};
  const mark = {id: 'spot:x', name: 'x', kind: 'Reef mark', reading: '', source: '', basis: ''};
  const html = m.render(m.h(m.RulesLine, {mark}));
  const row = ruleSummary(d, 'reef', regulationState(d, 'reef', MORRO, Date.now()), MORRO);
  const text = html.replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&').replace(/\s+/g, ' ');
  for (const part of [row.label, ...row.bag, ...row.size, verifiedText(row), row.linkLabel]) assert.ok(text.includes(part), `${part} in ${text}`);
  assert.match(html, new RegExp(`<a href="${row.link.replace(/[.?]/g, '\\$&')}" target="_blank" rel="noopener"`), 'the official link');
  assert.match(html, /aria-label="Rules at a glance: Lingcod &amp; rockfish"/);
  assert.doesNotMatch(text, /\b(?:hotspot|chance|odds|probab\w*|bite|guarantee\w*|you should|we recommend)\b/i, 'no advice or promise');
  for (const id of ['mpa:x', 'coastline:x', 'ais:x']) assert.equal(m.render(m.h(m.RulesLine, {mark: {...mark, id}})), '', `${id}: no rules line`);
  assert.equal(m.render(m.h(m.RulesLine, {mark: {...mark, withheld: true}})), '', 'a withheld mark keeps its own words');
  m.state.syncFromURL('https://s.test/map?region=morro-bay&target=constructor');
  assert.match(m.render(m.h(m.RulesLine, {mark})), /Check rules.*Official CDFW rules/s, '#396 in the card');
});

// SC1938-06: the legality line reads the region's startup copy of the registry (regions/<id>/regulations-startup.json,
// src/skippercast/platform/startup_forms.py regs_startup) and the whole registry only when the copy cannot be used.
const COPY_URL = 'regions/morro-bay/regulations-startup.json', FULL_URL = 'data/regulations.json', DAILY_URL = '/api/daily?region=morro-bay&part=regulations';
const speciesOf = region => [...new Set(region.species.flatMap(id => id === 'reef' ? ['lingcod', 'rockfish'] : [id]))];
/** The registry cut as the platform build cuts a startup copy: the region's species, the sources and checks they cite, no area notices. */
function copyOf(full, region) {
  const wanted = new Set(speciesOf(region)), species = Object.fromEntries(Object.entries(full.species).filter(([id]) => wanted.has(id)));
  const cited = new Set(Object.values(species).flatMap(p => [...p.source_ids, p.primary_source_id].filter(Boolean)));
  const keep = table => Object.fromEntries(Object.entries(table).filter(([id]) => cited.has(id)));
  const {area_notices: _notices, ...rest} = full;
  return {...rest, species, sources: keep(full.sources), checks: keep(full.checks)};
}
const dailyPart = d => ({schema_version: 1, part: 'regulations', region_id: 'morro-bay', generated_at: new Date(NOW).toISOString(), catch_probability: null, bite_score: null, regulations: d});
function serve(answers) {
  const urls = [];
  const fetchFn = async url => {
    urls.push(url);
    const a = answers[url];
    if (a === 'throw') throw new TypeError('Failed to fetch');
    if (a === 'bad-json') return new Response('{not json', {status: 200});
    if (typeof a === 'number') return new Response('', {status: a});
    return a === undefined ? new Response('', {status: 404}) : Response.json(a);
  };
  return {urls, fetchFn, set: (url, a) => { answers[url] = a; }};
}
const fresh = () => { resetRegs(); regsData.value = null; };
const sameStates = (a, b, region, now = NOW) => IDS.every(id => isDeepStrictEqual(regulationState(a, id, region, now), regulationState(b, id, region, now)));

test('a valid startup copy is the only registry read: the whole registry is not fetched', async () => {
  fresh();
  const s = serve({[COPY_URL]: {...copyOf(data(), MORRO), revision: 'copy'}, [FULL_URL]: {...data(), revision: 'full'}});
  await loadRegs(MORRO, s.fetchFn);
  assert.deepEqual(s.urls, [COPY_URL, DAILY_URL], 'the copy, then the daily part; never data/regulations.json');
  assert.equal(regsData.value?.data.revision, 'copy');
  assert.ok(sameStates(regsData.value.data, data(), MORRO), 'every rule state is the whole registry\'s');
  await loadRegs(MORRO, s.fetchFn);
  assert.equal(s.urls.length, 2, 'read once');
});

test('a copy that is missing, unreadable, for another jurisdiction or not valid for the region falls back to the whole registry', async () => {
  const copy = copyOf(data(), MORRO), noSalmon = structuredClone(copy);
  delete noSalmon.species.salmon;
  const cases = {'404': 404, 'not JSON': 'bad-json', 'another jurisdiction': {...copy, jurisdiction_id: 'california-other'},
    'a species of the region missing': noSalmon, 'unsupported schema': {...copy, schema_version: 2}, 'an unreviewed registry': {...copy, valid_through: 'soon'}};
  for (const [name, answer] of Object.entries(cases)) {
    fresh();
    const s = serve({[COPY_URL]: answer, [FULL_URL]: {...data(), revision: 'full'}});
    await loadRegs(MORRO, s.fetchFn);
    assert.deepEqual(s.urls, [COPY_URL, DAILY_URL, FULL_URL], `${name}: copy and daily start together; the whole registry is the extra fallback request`);
    assert.equal(regsData.value?.data.revision, 'full', `${name}: the whole registry shows`);
  }
});

test('a daily part newer than the startup copy wins; an older one is refused', async () => {
  for (const [name, dailyAt, wins] of [['newer', NOW, true], ['older', NOW - 96 * HOUR, false]]) {
    fresh();
    const copyAt = NOW - 48 * HOUR, copy = copyOf(data(copyAt), MORRO);
    const s = serve({[COPY_URL]: copy, [DAILY_URL]: dailyPart(data(dailyAt))});
    await loadRegs(MORRO, s.fetchFn);
    assert.deepEqual(s.urls, [COPY_URL, DAILY_URL], name);
    assert.equal(regsData.value.data.reviewed_at, new Date((wins ? dailyAt : copyAt) - HOUR).toISOString(), `${name}: the ${wins ? 'daily' : 'copy'} registry shows`);
  }
});

test('a copy that fails in transit is not asked again when the whole registry loads; it is when nothing loads', async () => {
  for (const failure of [503, 429, 'throw']) {
    fresh();
    const s = serve({[COPY_URL]: failure, [FULL_URL]: data()});
    await loadRegs(MORRO, s.fetchFn);
    await loadRegs(MORRO, s.fetchFn);
    assert.deepEqual(s.urls, [COPY_URL, DAILY_URL, FULL_URL], `${failure}: whole registry loaded, read once`);
    assert.ok(regsData.value);
    fresh();
    const none = serve({[COPY_URL]: failure});
    await loadRegs(MORRO, none.fetchFn);
    await loadRegs(MORRO, none.fetchFn);
    assert.equal(none.urls.length, 6, `${failure}: nothing loaded, so the next card asks again`);
  }
});

const DIST = new URL('../dist/', import.meta.url);
const readDist = path => JSON.parse(readFileSync(new URL(path.replace(/^\//, ''), DIST), 'utf8'));
const committedRegions = readdirSync(new URL('regions/', DIST), {withFileTypes: true}).filter(e => e.isDirectory())
  .map(e => readDist(`regions/${e.name}/region.json`)).filter(r => r.jurisdiction_id && r.assets?.regulations);
const localDay = (tz, at) => new Intl.DateTimeFormat('en-CA', {timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date(at));
/** Three instants over one registry: now, the next opening (a minute before and after), and a date on which a species is closed. */
function instants(full, region) {
  const latest = Math.max(...Object.values(full.checks).map(c => Date.parse(c.data_retrieved_at)).filter(Number.isFinite)), now = latest + HOUR, tz = region.timezone;
  const openings = Object.values(full.species).flatMap(p => p.windows.map(w => w.start_at)).filter(Boolean).map(s => Date.parse(s)).sort((a, b) => a - b);
  const next = openings.find(t => t > now) ?? openings.at(-1) ?? now;
  const list = [{now, date: null, at: null}, ...[next - 60000, next + 60000].map(t => ({now: t, date: localDay(tz, next), at: t}))];
  for (let day = Date.parse(full.valid_from); day <= Date.parse(full.valid_through); day += 24 * HOUR) {
    const date = new Date(day).toISOString().slice(0, 10);
    if (IDS_OF(region).some(id => regulationState(full, id, region, now, date, null).status === 'closed')) { list.push({now, date, at: null}); break; }
  }
  return list;
}
const IDS_OF = region => [...new Set([...region.species, ...speciesOf(region)])];

test('every committed region: the startup copy gives the whole registry\'s states, rows, check dates, pages and openings at every instant', () => {
  assert.ok(committedRegions.length >= 10, 'the committed regions are read');
  const seen = new Set();
  for (const region of committedRegions) {
    const full = readDist(region.assets.regulations), copy = readDist(`regions/${region.id}/regulations-startup.json`);
    assert.ok(validRegulations(full, region) && validRegulations(copy, region), `${region.id}: both registries are valid for the region`);
    assert.equal(copy.jurisdiction_id, region.jurisdiction_id, region.id);
    assert.deepEqual(Object.keys(copy.species), Object.keys(full.species).filter(id => speciesOf(region).includes(id)), `${region.id}: the region's own species, in the registry's order`);
    assert.ok(Object.keys(copy.sources).every(id => id in full.sources) && Object.keys(copy.checks).every(id => id in full.checks), `${region.id}: nothing the registry does not hold`);
    const list = instants(full, region);
    assert.ok(list.length >= 3, `${region.id}: now, the next opening and a closed date`);
    for (const {now, date, at} of list) {
      for (const id of IDS_OF(region)) {
        const a = regulationState(full, id, region, now, date, at), b = regulationState(copy, id, region, now, date, at);
        const where = `${region.id} ${id} ${date ?? 'today'} ${new Date(now).toISOString()}`;
        assert.ok(isDeepStrictEqual(a, b), `${where}: state`);
        assert.ok(isDeepStrictEqual(ruleSummary(full, id, a, region), ruleSummary(copy, id, b, region)), `${where}: row`);
        assert.ok(isDeepStrictEqual(freshnessLabel(full, id, a, region, now), freshnessLabel(copy, id, b, region, now)), `${where}: check date`);
        assert.ok(isDeepStrictEqual(speciesPage(full, id, region), speciesPage(copy, id, region)), `${where}: species page`);
        assert.equal(openingAt(copy, id, region, localDay(region.timezone, now)), openingAt(full, id, region, localDay(region.timezone, now)), `${where}: opening`);
        seen.add(a.status);
      }
    }
  }
  assert.ok(seen.has('closed') && (seen.has('open') || seen.has('restricted')), `the instants cover real states, not only unknown: ${[...seen]}`);
});
