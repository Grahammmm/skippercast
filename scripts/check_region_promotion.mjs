#!/usr/bin/env node
// Read-only SCB-17 technical preflight, not a promotion or beta release authorization.
import {readFile, readdir} from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import {loadRegs, regsData, regulationState, resetRegs} from '../web/regs.ts';
import {manifestState, manifestURL} from '../dist/seafloor-data.js';

const ROOT = new URL('../', import.meta.url);
const HEALTH = JSON.parse(await readFile(new URL('catalog/feed-health.json', ROOT), 'utf8'));
const HOUR = 3600000, MAX_BYTES = 16 * 1024 * 1024;
const ID = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const object = x => x !== null && typeof x === 'object' && !Array.isArray(x);
const stamp = s => typeof s === 'string' && /T.*(?:Z|[+-]\d{2}:\d{2})$/.test(s) ? Date.parse(s) : NaN;
const fresh = (s, now, hours) => Number.isFinite(stamp(s)) && now - stamp(s) >= -600000 && now - stamp(s) <= hours * HOUR;
const requireThat = (ok, code) => { if (!ok) throw new Error(code); };
const dateOnly = s => /^\d{4}-\d{2}-\d{2}$/.test(s ?? '') && Number.isFinite(Date.parse(s)) && new Date(s).toISOString().slice(0, 10) === s;

/** Same-origin GETs only; no credentials, redirects, retries or archives. Cache each response once per run. */
export function reader(base, fetchFn = fetch) {
  const root = new URL(base);
  requireThat(['https:', 'http:'].includes(root.protocol) && !root.username && !root.password && root.pathname === '/' && !root.search && !root.hash, 'base-must-be-an-origin');
  const cache = new Map();
  return path => {
    const url = new URL(path, root);
    requireThat(url.origin === root.origin && !url.username && !url.password, 'off-origin-path');
    if (!cache.has(url.href)) cache.set(url.href, (async () => {
      const response = await fetchFn(url.href, {method: 'GET', credentials: 'omit', redirect: 'error', cache: 'no-store', signal: AbortSignal.timeout(15000)});
      const chunks = [], stream = response.body?.getReader();
      let bytes = 0;
      if (stream) try {
        for (;;) {
          const part = await stream.read();
          if (part.done) break;
          bytes += part.value.byteLength;
          requireThat(bytes <= MAX_BYTES, 'response-too-large');
          chunks.push(part.value);
        }
      } finally { await stream.cancel().catch(() => {}); }
      const text = Buffer.concat(chunks).toString('utf8');
      return {status: response.status, text, json() { return JSON.parse(text); }};
    })());
    return cache.get(url.href);
  };
}

async function json(get, path) {
  const r = await get(path);
  requireThat(r.status === 200, `http-${r.status}`);
  return r.json();
}

/** Catalog degradation semantics, but missing required kinds also fail promotion. */
function feedCheck(feed, id, now, hours, requiredKinds, degradedHours) {
  requireThat(feed?.schema_version === 1 && feed.region_id === id, 'feed-identity');
  requireThat(fresh(feed.published_at || feed.completed_at || feed.generated_at, now, hours), 'feed-clock-stale-invalid-or-future');
  requireThat(object(feed.sources) && Object.keys(feed.sources).length > 0, 'feed-sources-missing');
  const sources = Object.values(feed.sources).filter(object);
  for (const kind of new Set([...requiredKinds, ...sources.map(s => s.kind).filter(k => HEALTH.critical_kinds.includes(k))])) {
    const rows = sources.filter(s => s.kind === kind);
    requireThat(rows.length > 0, `missing-${kind}-sources`);
    // A failed source's retained data may bridge an outage only inside the existing catalog limit.
    requireThat(rows.some(s => s.status === 'ok' || fresh(s.data?.sample_at || s.data?.issued_at || s.data_retrieved_at || s.last_success_at, now, degradedHours)), `degraded-${kind}-sources`);
  }
}

/** Runs sequentially: the app's rules loader has a shared region-keyed store. */
export async function checkRegion(id, sourceRegion, index, get, now = Date.now(), rulesThrough = null) {
  const checks = [];
  const check = async (name, fn) => {
    try { checks.push({name, pass: true, detail: await fn()}); }
    catch (e) { checks.push({name, pass: false, detail: e instanceof SyntaxError ? 'invalid-json' : e.message}); }
  };
  let region, daily;
  await check('package', async () => {
    requireThat(ID.test(id) && sourceRegion?.id === id, 'unknown-region');
    requireThat(['preview', 'active'].includes(sourceRegion.status), `region-${sourceRegion.status ?? 'status-missing'}`);
    requireThat(index?.schema_version === 1 && Array.isArray(index.regions), 'index-invalid');
    const entries = index.regions.filter(r => r?.id === id);
    requireThat(entries.length === 1, entries.length ? 'duplicate-index-region' : 'region-not-published');
    const entry = entries[0], path = `regions/${id}/region.json`;
    requireThat(entry.config === path && entry.status === sourceRegion.status, 'index-config-or-status-mismatch');
    region = await json(get, path);
    requireThat(region?.id === id && region.schema_version === 1 && region.status === entry.status, 'region-identity-or-status');
    requireThat(typeof region.timezone === 'string' && typeof region.jurisdiction_id === 'string' && Array.isArray(region.species) && region.species.length && region.species.every(s => ID.test(s)), 'region-rules-fields-missing');
    for (const [field, branch, file] of [['daily_feed', 'data', 'latest.json'], ['conditions_feed', 'conditions', 'latest.json'], ['intelligence_feed', 'conditions', 'intelligence.json']]) {
      requireThat(region[field] === `https://raw.githubusercontent.com/Grahammmm/skippercast/${branch}/regions/${id}/${file}`, `region-${field}-binding`);
    }
    new Intl.DateTimeFormat('en-CA', {timeZone: region.timezone});
    return region.status;
  });
  if (!checks[0].pass) return {region: id, pass: false, checks};
  await check('feeds', async () => {
    for (const [branch, file, hours, kinds, degraded] of [
      ['conditions', 'latest.json', HEALTH.regions.max_age_hours, ['observation'], HEALTH.regions.critical_degraded_hours],
      ['data', 'latest.json', HEALTH.feeds.data.max_age_hours, ['observation', 'prediction', 'advisory', 'forecast'], HEALTH.feeds.data.critical_degraded_hours],
      ['conditions', 'intelligence.json', HEALTH.regions.max_age_hours, ['forecast'], HEALTH.regions.critical_degraded_hours],
    ]) {
      const feed = await json(get, `/feeds/${branch}/regions/${id}/${file}`);
      if (branch === 'data') daily = feed;
      try { feedCheck(feed, id, now, hours, kinds, degraded); }
      catch (e) { throw new Error(`${branch}/${file}: ${e.message}`); }
    }
    return 'regional conditions, daily and intelligence fresh; critical sources checked';
  });
  await check('tides', async () => {
    // Fetch independently if an earlier feed failed: all useful failure reasons still print.
    daily ??= await json(get, `/feeds/data/regions/${id}/latest.json`);
    requireThat(daily.region_id === id, 'daily-region-mismatch');
    const station = region.stations?.tide, tide = daily.sources?.tides, data = tide?.data;
    requireThat(typeof station === 'string' && /^\d{7}$/.test(station), 'tide-station-missing');
    requireThat(tide?.status === 'ok' && data?.station === station, 'tide-unhealthy-or-station-mismatch');
    requireThat(fresh(tide.data_retrieved_at, now, HEALTH.feeds.data.max_age_hours), 'tide-retrieval-stale-invalid-or-future');
    requireThat(stamp(data.coverage_start) <= now && stamp(data.coverage_end) > now, 'tide-coverage-not-current');
    requireThat(data.datum === 'MLLW' && data.units === 'ft' && data.timezone === 'UTC', 'tide-units-datum-or-timezone');
    requireThat(Array.isArray(data.predictions) && data.predictions.some(p => stamp(p?.time) > now && Number.isFinite(p.height_ft) && ['H', 'L'].includes(p.type)), 'tide-predictions-missing');
    return `station ${station}; current coverage and future high/low prediction`;
  });
  await check('rules', async () => {
    resetRegs(); regsData.value = null;
    const appFetch = async path => {
      const r = await get(path);
      return new Response(r.text, {status: r.status});
    };
    await loadRegs(region, appFetch);
    const data = regsData.value?.region === id ? regsData.value.data : null;
    const binding = Array.isArray(data?.reviewed_regions) ? data.reviewed_regions.find(r => r?.id === id) : null;
    requireThat(data && data.jurisdiction_id === region.jurisdiction_id && binding && Array.isArray(region.fishing_bounds) && JSON.stringify(binding.fishing_bounds) === JSON.stringify(region.fishing_bounds) && data.timezone === region.timezone, 'rules-package-not-reviewed-for-region-footprint');
    const species = [...new Set(region.species.flatMap(s => s === 'reef' ? ['lingcod', 'rockfish'] : [s]))];
    const states = species.map(s => ({species: s, ...regulationState(data, s, region, now)}));
    const bad = states.filter(s => !['open', 'closed', 'restricted', 'scheduled'].includes(s.status) && !(s.status === 'unknown' && s.labelId === 'rules.label.chooseLocation'));
    requireThat(!bad.length, bad.map(s => `${s.species}:${s.reasonId ?? s.status}`).join(', '));
    requireThat(!rulesThrough || data.valid_through >= rulesThrough, `rules-expire-before-${rulesThrough}`);
    return states.map(s => `${s.species}:${s.labelId === 'rules.label.chooseLocation' ? 'location-needed' : s.status}`).join(', ') + `; valid through ${data.valid_through}`;
  });
  await check('habitat', async () => {
    const r = await get(manifestURL(id));
    if (r.status === 404) return 'GAP: no published seafloor habitat; app hides this layer (SC-D1=B)';
    requireThat(r.status === 200 || r.status === 503, `http-${r.status}`);
    const manifest = r.json();
    requireThat(manifest?.region === id, 'habitat-region-mismatch');
    const state = manifestState(manifest, id, now).state;
    requireThat(state === 'held' || (state === 'ready' && r.status === 200), `habitat-${state}`);
    return state === 'held' ? 'GAP: habitat held for screening; app withholds it (SC-D1=B)' : 'ready; current screening manifest (archive not downloaded)';
  });
  await check('smoke', async () => {
    const health = await json(get, '/api/health');
    requireThat(health?.service === 'SkipperCast' && /^[a-f0-9]{40}$/.test(health.revision ?? '') && health.revision_dirty === false, 'site-health-or-revision');
    const page = await get(`/map?region=${id}`);
    requireThat(page.status === 200 && /<html[\s>]/i.test(page.text) && /<script\b[^>]*\btype=["']module["']/i.test(page.text), 'map-shell-missing');
    const brief = await json(get, `/api/daily?region=${id}&part=brief`);
    requireThat(brief.schema_version === 1 && brief.region_id === id && brief.part === 'brief' && object(brief.sources) && !!brief.sources.tides && Array.isArray(brief.reports) && brief.catch_probability === null && brief.bite_score === null, 'regional-brief-invalid');
    requireThat(fresh(brief.generated_at, now, HEALTH.feeds.data.max_age_hours), 'regional-brief-stale');
    return `HTTP map shell and regional brief; live head ${health.revision} (not a browser test)`;
  });
  return {region: id, pass: checks.every(c => c.pass), checks};
}

export async function main(argv, {fetchFn = fetch, now = Date.now(), print = console.log} = {}) {
  const ids = []; let base = 'https://skippercast.com', rulesThrough = null, asJSON = false;
  try {
    for (let i = 0; i < argv.length; i++) {
      const arg = argv[i];
      if (arg === '--help') { print('Usage: node scripts/check_region_promotion.mjs [--base ORIGIN] [--rules-through YYYY-MM-DD] [--json] [REGION ...]\nNo regions: check every local region package, including drafts. Read-only technical preflight only; never authorizes promotion or beta GO.'); return 0; }
      if (arg === '--base') { base = argv[++i]; requireThat(!!base, 'missing-base'); }
      else if (arg === '--rules-through') { rulesThrough = argv[++i]; requireThat(dateOnly(rulesThrough), 'invalid-rules-through-date'); }
      else if (arg === '--json') asJSON = true;
      else { requireThat(ID.test(arg), 'invalid-region-or-option'); ids.push(arg); }
    }
    if (!ids.length) for (const entry of await readdir(new URL('regions/', ROOT), {withFileTypes: true})) {
      if (!entry.isDirectory()) continue;
      try { await readFile(new URL(`regions/${entry.name}/region.json`, ROOT)); ids.push(entry.name); }
      catch (e) { if (e.code !== 'ENOENT') throw e; }
    }
    requireThat(ids.length > 0, 'no-region-packages');
    const get = reader(base, fetchFn);
    let index; try { index = await json(get, '/regions/index.json'); } catch { index = null; }
    const results = [];
    for (const id of [...new Set(ids)].sort()) {
      let source;
      try { source = JSON.parse(await readFile(new URL(`regions/${id}/region.json`, ROOT), 'utf8')); } catch { source = null; }
      results.push(await checkRegion(id, source, index, get, now, rulesThrough));
    }
    const report = {checked_at: new Date(now).toISOString(), base, scope: 'technical preflight only; human/legal approval and beta GO still required', rules_through: rulesThrough, results};
    if (asJSON) print(JSON.stringify(report, null, 2));
    else {
      print(`${report.scope}; checked ${report.checked_at}`);
      for (const r of results) {
        print(`${r.pass ? 'PASS' : 'FAIL'} ${r.region}`);
        for (const c of r.checks) print(`  ${c.pass ? 'PASS' : 'FAIL'} ${c.name}: ${c.detail}`);
      }
    }
    return results.every(r => r.pass) ? 0 : 1;
  } catch (e) { print(`ERROR: ${e.name === 'TypeError' ? 'invalid-base-or-input' : e.message}`); return 2; }
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) process.exitCode = await main(process.argv.slice(2));
