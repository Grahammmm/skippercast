// Generate the readers' tables from the one shared catalogue, catalog/app/strings.json (SC1407-09):
// web/strings.en.generated.json (every id, English only) ships with the app; web/strings.es.generated.json
// (every id, its Spanish) loads only when the page language is Spanish (web/i18n-catalogue.ts); and
// web/landing/strings.generated.json is the landing's first-paint slice, English only. Author only the
// catalogue; `--check` fails on any stale table and writes nothing. scripts/client-build.mjs runs this first.
import {readFileSync, writeFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';

const ROOT = new URL('../', import.meta.url);
export const COMMAND = 'node scripts/build_landing_strings.mjs';
export const OUTPUTS = {en: 'web/strings.en.generated.json', es: 'web/strings.es.generated.json', landing: 'web/landing/strings.generated.json', status: 'dist/status-strings.generated.json'};
const LANDING_IDS = ['brief.planning', 'brief.terms', 'brief.disclaimer', 'tile.wind', 'tile.swell', 'tile.water', 'tile.tide', 'language.loadFailed', 'language.retrySpanish', 'shared.degraded.saved', 'shared.degraded.savedAt', 'shared.popover.basis', 'shared.popover.sources'];

/** The landing's first-paint ids (the deferred live verdict uses the app reader). */
export const landingId = id =>
  (id.startsWith('landing.') && !id.startsWith('landing.basis.') && !id.startsWith('landing.reading.') && id !== 'landing.place.from') ||
  id.startsWith('where.profile.') || LANDING_IDS.includes(id);

const compact = value => JSON.stringify(value) + '\n';

// Keep each id's escaped key and value on a single line so unrelated edits merge.
function mergeLayout(table) {
  const lines = Object.entries(table).map(([id, value]) => `${JSON.stringify(id)}:${JSON.stringify(value)}`);
  return lines.length ? `{\n${lines.join(',\n')}\n}\n` : '{}\n';
}

/** {path: text} of the four tables in catalogue order; compact by default. Throws on a missing translation. */
export function projections(catalog, serialize = compact) {
  const map = catalog?.strings, isMap = value => value !== null && typeof value === 'object' && !Array.isArray(value);
  if (!isMap(catalog) || !isMap(map) || Object.keys(map).length === 0) throw Error('The catalogue strings map must be a non-empty object of ids');
  const en = {}, es = {}, landing = {}, status = {};
  for (const [id, entry] of Object.entries(map)) {
    if (typeof entry?.en !== 'string' || entry.en === '') throw Error(`${id}: no English string in the catalogue`);
    if (typeof entry.es !== 'string' || entry.es === '') throw Error(`${id}: no Spanish string in the catalogue`);
    en[id] = {en: entry.en};
    if (/^(status|coverage|skill)\./.test(id)) status[id] = {en: entry.en};
    es[id] = entry.es;
    if (landingId(id)) landing[id] = {en: entry.en};
  }
  return {[OUTPUTS.en]: serialize(en), [OUTPUTS.es]: serialize(es), [OUTPUTS.landing]: serialize(landing), [OUTPUTS.status]: serialize(status)};
}

/** Write the stale tables under `root` (with `check`, write nothing and throw naming them); returns the stale paths. */
export function generate({check = false, root = ROOT} = {}) {
  const catalog = JSON.parse(readFileSync(new URL('catalog/app/strings.json', root), 'utf8'));
  const stale = [];
  for (const [path, text] of Object.entries(projections(catalog, mergeLayout))) {
    const target = new URL(path, root);
    let current = null;
    try { current = readFileSync(target, 'utf8'); } catch { /* missing: stale */ }
    if (current === text) continue;
    stale.push(path);
    if (!check) writeFileSync(fileURLToPath(target), text);
  }
  if (check && stale.length) throw Error(`Stale ${stale.join(', ')}: run ${COMMAND}`);
  return stale;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) generate({check: process.argv.includes('--check')});
