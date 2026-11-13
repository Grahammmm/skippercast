#!/usr/bin/env node
// SC2184-06: is the rules card blank? Runs the app's OWN rules logic (web/regs.ts `loadRegs` and
// `regulationState`) against the live site for the default region and says whether at least one of the
// region's species has a season status. A species reads "Check rules" (status `unknown`) when the registry
// did not load, is not reviewed, is outside its rule period or has a source check that is old or changed; if
// every species reads that, the rules card is blank for everyone. CI stayed green while all seven were blank.
//
// Exit 0: at least one species has a season status (open, closed, scheduled or restricted). Exit 3: every
// species reads "Check rules". Any other exit code (a crash, a missing install) counts as blank too: the
// workflow treats only exit 0 as healthy. A species that reads "Choose fishing location" has a season that
// needs a location, so it is not blank. This only reads status; it never edits a rule, gate or registry.
//
// Usage: node scripts/rules_status_probe.mjs [--base URL]   (default: FEEDS_PUBLIC_BASE, then the workers.dev host)
// Prints one line per species ("<species>: <status> (<reason id>)") and a final `rules-card-blank` or
// `rules-card-ok` line. Prints no response body, header or token.
import {pathToFileURL} from 'node:url';
import {loadRegs, regsData, regulationState, resetRegs} from '../web/regs.ts';

const DEFAULT_BASE = 'https://skippercast.g4651.workers.dev';
const TIMEOUT_MS = 15000;
export const BLANK_EXIT = 3;

/** True when a state reads "Check rules": unknown for want of rules, not for a season that needs a location. */
export const isBlank = state => state.status === 'unknown' && state.labelId === 'rules.label.unknown';

/** Per-species rule states and the verdict, from a fetch bound to the live site (or to a fixture). */
export async function probe(base, fetchFn = fetch, now = Date.now()) {
  const root = base.replace(/\/+$/, '') + '/';
  // loadRegs asks for site-relative paths ("regions/<id>/regulations-startup.json", "/api/daily?..."); resolve them on the site.
  const siteFetch = (url, init) => fetchFn(new URL(url, root).href, {...init, signal: AbortSignal.timeout(TIMEOUT_MS)});
  const getJSON = async path => {
    const r = await siteFetch(path, {cache: 'no-cache'});
    if (!r.ok) throw new Error(`HTTP ${r.status} for ${path}`);
    return r.json();
  };
  const index = await getJSON('regions/index.json');
  const id = index.default_region;
  if (typeof id !== 'string' || !id) throw new Error('regions/index.json names no default_region');
  const entry = Array.isArray(index.regions) ? index.regions.find(r => r?.id === id) : null;
  const region = await getJSON(typeof entry?.config === 'string' ? entry.config : `regions/${encodeURIComponent(id)}/region.json`);
  if (region.id !== id || !Array.isArray(region.species) || !region.species.length) throw new Error(`region.json for ${id} lists no species`);
  resetRegs();
  regsData.value = null;
  await loadRegs(region, siteFetch);
  const data = regsData.value?.region === region.id ? regsData.value.data : null;
  const species = region.species.map(name => {
    const state = regulationState(data, name, region, now);
    return {species: name, status: state.status, label: state.label, reason: state.reasonId ?? null, blank: isBlank(state)};
  });
  return {region: id, species, blank: species.every(s => s.blank)};
}

async function main(argv) {
  const at = argv.indexOf('--base');
  const base = at >= 0 && argv[at + 1] ? argv[at + 1] : process.env.FEEDS_PUBLIC_BASE || DEFAULT_BASE;
  try {
    const result = await probe(base);
    console.log(`region: ${result.region}`);
    for (const s of result.species) console.log(`${s.species}: ${s.status} (${s.reason ?? 'registry wording'})`);
    console.log(result.blank ? 'rules-card-blank' : 'rules-card-ok');
    return result.blank ? BLANK_EXIT : 0;
  } catch (e) {
    // Fail safe: not knowing is not healthy. Name the error class only.
    console.log(`probe crashed: ${e?.name ?? 'Error'}`);
    console.log('rules-card-blank');
    return 1;
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  process.exitCode = await main(process.argv.slice(2));
}
